from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from kaxi.identity.models import User
from kaxi.products.models import ProductSerial
from kaxi.sales.models import SalesOrder, SalesOrderLine
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.trade.models import (
    Package,
    PackageItem,
    Shipment,
    ShipmentMilestone,
    ShipmentOrder,
    TradeContract,
)


@dataclass(frozen=True)
class PackageItemInput:
    sales_order_line_id: int
    quantity: Decimal
    product_serial_id: int | None = None


def _emit(shipment: Shipment, event_type: str) -> None:
    append_outbox_event(
        company=shipment.company,
        aggregate_type="trade.shipment",
        aggregate_id=str(shipment.pk),
        aggregate_version=shipment.version_no,
        event_type=event_type,
        payload={"shipment_id": shipment.pk, "shipment_no": shipment.shipment_no},
    )


@transaction.atomic
def approve_contract(*, contract_id: int, actor: User) -> TradeContract:
    contract = TradeContract.objects.select_for_update().get(pk=contract_id)
    if contract.status != TradeContract.Status.DRAFT:
        raise ValidationError("只有草稿合同可以批准。")
    if contract.created_by_id == actor.pk:
        raise ValidationError("贸易合同创建人与批准人必须分离。")
    contract.status = TradeContract.Status.APPROVED
    contract.approved_by = actor
    contract.approved_at = timezone.now()
    contract.row_version += 1
    contract.save()
    append_outbox_event(
        company=contract.company,
        aggregate_type="trade.contract",
        aggregate_id=str(contract.pk),
        aggregate_version=contract.row_version,
        event_type="trade.contract.approved",
        payload={"contract_id": contract.pk, "contract_no": contract.contract_no},
    )
    return contract


@transaction.atomic
def add_order(*, shipment_id: int, sales_order_id: int) -> ShipmentOrder:
    shipment = Shipment.objects.select_for_update().get(pk=shipment_id)
    order = SalesOrder.objects.select_for_update().get(pk=sales_order_id)
    if shipment.status not in {Shipment.Status.PLANNED, Shipment.Status.ARRANGING}:
        raise ValidationError("当前出运状态不能增加订单。")
    if order.company_id != shipment.company_id or order.status in {
        SalesOrder.Status.DRAFT,
        SalesOrder.Status.CANCELLED,
    }:
        raise ValidationError("订单公司或状态不满足出运要求。")
    if not hasattr(order, "trade_detail"):
        raise ValidationError("订单缺少贸易资料。")
    link, _ = ShipmentOrder.objects.get_or_create(shipment=shipment, sales_order=order)
    return link


@transaction.atomic
def pack_items(*, package_id: int, items: list[PackageItemInput]) -> Package:
    package = Package.objects.select_for_update().select_related("shipment").get(pk=package_id)
    if package.status not in {Package.Status.DRAFT, Package.Status.PACKING}:
        raise ValidationError("只有草稿箱或装箱中箱可以增加明细。")
    shipment_order_ids = set(package.shipment.orders.values_list("sales_order_id", flat=True))
    for item_input in items:
        line = (
            SalesOrderLine.objects.select_for_update()
            .select_related("order", "sku")
            .get(pk=item_input.sales_order_line_id)
        )
        if line.order_id not in shipment_order_ids:
            raise ValidationError("订单行未加入当前出运批次。")
        already_packed = PackageItem.objects.filter(
            sales_order_line=line,
            package__shipment=package.shipment,
        ).aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        shippable = line.ordered_qty - line.cancelled_qty
        if item_input.quantity <= 0 or already_packed + item_input.quantity > shippable:
            raise ValidationError("装箱数量超过订单行可出运数量。")
        serial = None
        if item_input.product_serial_id:
            serial = ProductSerial.objects.select_for_update().get(pk=item_input.product_serial_id)
            if (
                serial.company_id != package.shipment.company_id
                or serial.sku_id != line.sku_id
                or serial.current_sales_order_id != line.order_id
                or serial.status not in {ProductSerial.Status.RESERVED, ProductSerial.Status.PICKED}
                or item_input.quantity != 1
            ):
                raise ValidationError("单件编号与订单、SKU、状态或数量不匹配。")
        PackageItem.objects.create(
            package=package,
            sales_order_line=line,
            sku=line.sku,
            product_serial=serial,
            quantity=item_input.quantity,
        )
    package.status = Package.Status.PACKING
    package.row_version += 1
    package.save(update_fields=["status", "row_version", "updated_at"])
    return package


@transaction.atomic
def submit_package(*, package_id: int) -> Package:
    package = Package.objects.select_for_update().get(pk=package_id)
    if package.status != Package.Status.PACKING or not package.items.exists():
        raise ValidationError("装箱中且有明细的箱才能提交复核。")
    if package.gross_weight <= 0 or package.net_weight <= 0 or package.volume <= 0:
        raise ValidationError("提交复核前必须填写重量和体积。")
    if package.gross_weight < package.net_weight:
        raise ValidationError("毛重不得小于净重。")
    package.status = Package.Status.REVIEW
    package.row_version += 1
    package.save(update_fields=["status", "row_version", "updated_at"])
    return package


@transaction.atomic
def review_package(*, package_id: int, actor: User, approved: bool, reason: str = "") -> Package:
    package = Package.objects.select_for_update().get(pk=package_id)
    if package.status != Package.Status.REVIEW:
        raise ValidationError("箱不在待复核状态。")
    if not approved:
        if not reason.strip():
            raise ValidationError("复核不通过必须填写原因。")
        package.status = Package.Status.PACKING
    else:
        package.status = Package.Status.SEALED
        package.sealed_at = timezone.now()
        package.reviewed_by = actor
    package.row_version += 1
    package.save()
    return package


@transaction.atomic
def open_package(*, package_id: int, reason: str) -> Package:
    if not reason.strip():
        raise ValidationError("开箱必须记录原因。")
    package = Package.objects.select_for_update().get(pk=package_id)
    if package.status != Package.Status.SEALED:
        raise ValidationError("只有已封箱且未交运的箱可以开箱。")
    package.status = Package.Status.PACKING
    package.sealed_at = None
    package.reviewed_by = None
    package.row_version += 1
    package.save()
    return package


TRANSITIONS = {
    "arrange": (Shipment.Status.PLANNED, Shipment.Status.ARRANGING),
    "confirm_transport": (Shipment.Status.ARRANGING, Shipment.Status.CONFIRMED),
    "start_packing": (Shipment.Status.CONFIRMED, Shipment.Status.PACKING),
    "documents_ready": (Shipment.Status.PACKING, Shipment.Status.DOCUMENTS),
    "ready_dispatch": (Shipment.Status.DOCUMENTS, Shipment.Status.DISPATCH_READY),
    "in_transit": (Shipment.Status.DISPATCHED, Shipment.Status.IN_TRANSIT),
    "arrive": (Shipment.Status.IN_TRANSIT, Shipment.Status.ARRIVED),
    "deliver": (Shipment.Status.ARRIVED, Shipment.Status.DELIVERED),
    "complete": (Shipment.Status.DELIVERED, Shipment.Status.COMPLETED),
}


@transaction.atomic
def transition_shipment(*, shipment_id: int, action: str, occurred_at=None) -> Shipment:  # type: ignore[no-untyped-def]
    shipment = Shipment.objects.select_for_update().prefetch_related("packages").get(pk=shipment_id)
    if action not in TRANSITIONS or shipment.status != TRANSITIONS[action][0]:
        raise ValidationError("出运状态转换无效。")
    target = TRANSITIONS[action][1]
    if action == "documents_ready" and (
        not shipment.packages.exists()
        or shipment.packages.exclude(status=Package.Status.SEALED).exists()
    ):
        raise ValidationError("全部箱复核封箱后才能进入单证阶段。")
    shipment.status = target
    if action == "arrive":
        shipment.actual_arrival_at = occurred_at or timezone.now()
    shipment.version_no += 1
    shipment.save()
    ShipmentMilestone.objects.create(
        shipment=shipment, milestone_type=target, occurred_at=occurred_at or timezone.now()
    )
    _emit(shipment, f"trade.shipment.{target}")
    return shipment


@transaction.atomic
def dispatch_shipment(*, shipment_id: int, actual_ship_at=None) -> Shipment:  # type: ignore[no-untyped-def]
    shipment = Shipment.objects.select_for_update().prefetch_related("packages").get(pk=shipment_id)
    if shipment.status != Shipment.Status.DISPATCH_READY:
        raise ValidationError("出运批次尚未达到可交运状态。")
    packages = list(shipment.packages.select_for_update())
    if not packages or any(package.status != Package.Status.SEALED for package in packages):
        raise ValidationError("存在未封箱包装。")
    shipment.package_count = len(packages)
    shipment.net_weight = sum((item.net_weight for item in packages), Decimal(0))
    shipment.gross_weight = sum((item.gross_weight for item in packages), Decimal(0))
    shipment.volume = sum((item.volume for item in packages), Decimal(0))
    shipment.actual_ship_at = actual_ship_at or timezone.now()
    shipment.status = Shipment.Status.DISPATCHED
    shipment.version_no += 1
    shipment.save()
    Package.objects.filter(pk__in=[item.pk for item in packages]).update(
        status=Package.Status.DISPATCHED
    )
    ShipmentMilestone.objects.create(
        shipment=shipment, milestone_type="dispatched", occurred_at=shipment.actual_ship_at
    )
    _emit(shipment, "trade.shipment.dispatched")
    return shipment


@transaction.atomic
def record_exception(*, shipment_id: int, exception_type: str, detail: str) -> Shipment:
    shipment = Shipment.objects.select_for_update().get(pk=shipment_id)
    if shipment.status == Shipment.Status.COMPLETED or not detail.strip():
        raise ValidationError("当前批次不能登记此异常。")
    shipment.status = Shipment.Status.EXCEPTION
    shipment.exception_type = exception_type
    shipment.exception_detail = detail
    shipment.version_no += 1
    shipment.save()
    _emit(shipment, "trade.shipment.exception")
    return shipment

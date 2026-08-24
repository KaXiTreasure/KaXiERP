from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance
from kaxi.inventory.services import adjust_on_hand
from kaxi.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseReturn,
    QualityInspection,
    QualityInspectionLine,
    RequestForQuotation,
    SupplierQuote,
)
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.warehouse.models import WarehouseLocation


@dataclass(frozen=True)
class ReceiptLineInput:
    purchase_order_line_id: int
    quantity: Decimal
    staging_location_id: int
    lot_no: str = ""


@dataclass(frozen=True)
class ReceiptResult:
    receipt_id: int
    order_id: int
    order_status: str
    repeated: bool


@dataclass(frozen=True)
class InspectionLineInput:
    receipt_line_id: int
    accepted_qty: Decimal
    rejected_qty: Decimal
    accepted_balance_id: int | None = None
    rejected_balance_id: int | None = None
    disposition: str = ""
    defect_code: str = ""
    remarks: str = ""


@dataclass(frozen=True)
class InspectionResult:
    inspection_id: int
    receipt_id: int
    result: str
    repeated: bool


@dataclass(frozen=True)
class PurchaseOrderTransitionResult:
    order_id: int
    status: str
    version_no: int


@transaction.atomic
def transition_purchase_order(
    *, order_id: int, expected_version: int, action: str
) -> PurchaseOrderTransitionResult:
    order = PurchaseOrder.objects.select_for_update().select_related("company").get(pk=order_id)
    if order.version_no != expected_version:
        raise ValueError("采购订单版本已变化，请刷新后重试")
    transitions = {
        "approve": (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.APPROVED),
        "issue": (PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.ISSUED),
    }
    if action == "cancel":
        if order.status not in {
            PurchaseOrder.Status.DRAFT,
            PurchaseOrder.Status.APPROVED,
            PurchaseOrder.Status.ISSUED,
        }:
            raise ValueError("当前采购订单状态不能取消")
        if order.lines.filter(received_qty__gt=0).exists():
            raise ValueError("已有收货记录的采购订单不能直接取消")
        target = PurchaseOrder.Status.CANCELLED
    else:
        transition = transitions.get(action)
        if transition is None or order.status != transition[0]:
            raise ValueError("采购订单状态不允许执行此操作")
        target = transition[1]
    order.status = target
    if action == "approve":
        order.approval_status = "approved"
    order.version_no += 1
    order.row_version += 1
    order.save(
        update_fields=["status", "approval_status", "version_no", "row_version", "updated_at"]
    )
    append_outbox_event(
        company=order.company,
        aggregate_type="purchase_order",
        aggregate_id=str(order.pk),
        aggregate_version=order.version_no,
        event_type=f"PURCHASE_ORDER_{action.upper()}",
        payload={"purchase_order_id": order.pk, "status": order.status},
    )
    return PurchaseOrderTransitionResult(order.pk, order.status, order.version_no)


def _validate_balance(
    balance: InventoryBalance,
    *,
    receipt_line: GoodsReceiptLine,
    rejected: bool,
) -> None:
    receipt = receipt_line.receipt
    if (
        balance.company_id != receipt.company_id
        or balance.warehouse_id != receipt.warehouse_id
        or balance.sku_id != receipt_line.sku_id
    ):
        raise ValueError("验收库存余额的公司、仓库或SKU与收货行不一致")
    if rejected and balance.location.location_type != WarehouseLocation.LocationType.EXCEPTION:
        raise ValueError("不合格品必须进入异常库位")
    if not rejected and balance.location.location_type == WarehouseLocation.LocationType.EXCEPTION:
        raise ValueError("合格品不能进入异常库位")


@transaction.atomic
def receive_purchase_order(
    *,
    order_id: int,
    receipt_no: str,
    received_at: datetime,
    received_by: User,
    lines: list[ReceiptLineInput],
    supplier_delivery_no: str = "",
) -> ReceiptResult:
    order = PurchaseOrder.objects.select_for_update().select_related("company").get(pk=order_id)
    existing = GoodsReceipt.objects.filter(company=order.company, receipt_no=receipt_no).first()
    if existing is not None:
        if existing.purchase_order_id != order.pk:
            raise ValueError("收货单号已被其他采购订单使用")
        return ReceiptResult(existing.pk, order.pk, order.status, True)
    if order.status not in {PurchaseOrder.Status.ISSUED, PurchaseOrder.Status.PARTIALLY_RECEIVED}:
        raise ValueError("只有已下达或部分收货的采购订单可以收货")
    if not lines:
        raise ValueError("收货单至少需要一个明细行")

    order_lines = {
        line.pk: line for line in PurchaseOrderLine.objects.select_for_update().filter(order=order)
    }
    input_ids = [item.purchase_order_line_id for item in lines]
    if len(input_ids) != len(set(input_ids)) or any(
        line_id not in order_lines for line_id in input_ids
    ):
        raise ValueError("收货明细包含重复或非本采购订单行")

    locations = {
        location.pk: location
        for location in WarehouseLocation.objects.select_related("warehouse").filter(
            pk__in={item.staging_location_id for item in lines}
        )
    }
    for item in lines:
        line = order_lines[item.purchase_order_line_id]
        location = locations.get(item.staging_location_id)
        if item.quantity <= 0:
            raise ValueError("收货数量必须大于零")
        if line.received_qty + item.quantity > line.ordered_qty:
            raise ValueError("累计收货数量不能超过采购数量")
        if (
            location is None
            or location.warehouse_id != order.warehouse_id
            or location.location_type
            not in {
                WarehouseLocation.LocationType.STAGING,
                WarehouseLocation.LocationType.INSPECTION,
            }
        ):
            raise ValueError("收货必须进入本采购仓的暂存或质检库位")

    receipt = GoodsReceipt.objects.create(
        company=order.company,
        receipt_no=receipt_no,
        purchase_order=order,
        supplier=order.supplier,
        warehouse=order.warehouse,
        received_at=received_at,
        received_by=received_by,
        status=GoodsReceipt.Status.INSPECTION,
        supplier_delivery_no=supplier_delivery_no,
    )
    for item in lines:
        line = order_lines[item.purchase_order_line_id]
        GoodsReceiptLine.objects.create(
            receipt=receipt,
            purchase_order_line=line,
            sku=line.sku,
            received_qty=item.quantity,
            pending_inspection_qty=item.quantity,
            lot_no=item.lot_no,
            staging_location_id=item.staging_location_id,
        )
        line.received_qty += item.quantity
        line.row_version += 1
        line.save(update_fields=["received_qty", "row_version", "updated_at"])

    all_received = all(line.received_qty == line.ordered_qty for line in order_lines.values())
    order.status = (
        PurchaseOrder.Status.RECEIVED if all_received else PurchaseOrder.Status.PARTIALLY_RECEIVED
    )
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    append_outbox_event(
        company=order.company,
        aggregate_type="goods_receipt",
        aggregate_id=str(receipt.pk),
        aggregate_version=receipt.row_version,
        event_type="PURCHASE_GOODS_RECEIVED",
        payload={"receipt_id": receipt.pk, "purchase_order_id": order.pk},
    )
    return ReceiptResult(receipt.pk, order.pk, order.status, False)


@transaction.atomic
def complete_purchase_inspection(
    *,
    receipt_id: int,
    inspection_no: str,
    inspector: User,
    completed_at: datetime,
    lines: list[InspectionLineInput],
) -> InspectionResult:
    receipt = (
        GoodsReceipt.objects.select_for_update()
        .select_related("company", "purchase_order")
        .get(pk=receipt_id)
    )
    existing = QualityInspection.objects.filter(
        company=receipt.company, inspection_no=inspection_no
    ).first()
    if existing is not None:
        if existing.receipt_id != receipt.pk:
            raise ValueError("质检单号已被其他收货单使用")
        return InspectionResult(existing.pk, receipt.pk, existing.result, True)
    if receipt.status != GoodsReceipt.Status.INSPECTION:
        raise ValueError("只有待验收收货单可以完成质检")

    receipt_lines = {
        line.pk: line
        for line in GoodsReceiptLine.objects.select_for_update()
        .select_related("receipt")
        .filter(receipt=receipt)
    }
    input_by_line = {item.receipt_line_id: item for item in lines}
    if set(input_by_line) != set(receipt_lines) or len(input_by_line) != len(lines):
        raise ValueError("必须一次提交收货单全部且不重复的质检明细")

    balance_ids = {
        balance_id
        for item in lines
        for balance_id in (item.accepted_balance_id, item.rejected_balance_id)
        if balance_id is not None
    }
    balances = {
        balance.pk: balance
        for balance in InventoryBalance.objects.select_related("location").filter(
            pk__in=balance_ids
        )
    }
    movements: list[tuple[int, Decimal, GoodsReceiptLine, bool]] = []
    for line_id, item in input_by_line.items():
        receipt_line = receipt_lines[line_id]
        if item.accepted_qty < 0 or item.rejected_qty < 0:
            raise ValueError("质检数量不能为负数")
        if item.accepted_qty + item.rejected_qty != receipt_line.pending_inspection_qty:
            raise ValueError("合格与不合格数量之和必须等于待验收数量")
        for quantity, balance_id, rejected in (
            (item.accepted_qty, item.accepted_balance_id, False),
            (item.rejected_qty, item.rejected_balance_id, True),
        ):
            if quantity == 0:
                continue
            balance = balances.get(balance_id or 0)
            if balance is None:
                raise ValueError("非零质检处置数量必须提供有效库存余额")
            _validate_balance(balance, receipt_line=receipt_line, rejected=rejected)
            movements.append((balance.pk, quantity, receipt_line, rejected))

    result = "pass" if all(item.rejected_qty == 0 for item in lines) else "partial"
    if all(item.accepted_qty == 0 for item in lines):
        result = "fail"
    inspection = QualityInspection.objects.create(
        company=receipt.company,
        inspection_no=inspection_no,
        receipt=receipt,
        warehouse=receipt.warehouse,
        inspector=inspector,
        started_at=completed_at,
        completed_at=completed_at,
        result=result,
        status=QualityInspection.Status.COMPLETED,
    )
    order_lines = {
        line.pk: line
        for line in PurchaseOrderLine.objects.select_for_update().filter(
            pk__in={line.purchase_order_line_id for line in receipt_lines.values()}
        )
    }
    for line_id, item in input_by_line.items():
        receipt_line = receipt_lines[line_id]
        QualityInspectionLine.objects.create(
            inspection=inspection,
            receipt_line=receipt_line,
            sku=receipt_line.sku,
            inspected_qty=receipt_line.pending_inspection_qty,
            accepted_qty=item.accepted_qty,
            rejected_qty=item.rejected_qty,
            pending_qty=0,
            disposition=item.disposition,
            defect_code=item.defect_code,
            remarks=item.remarks,
        )
        receipt_line.pending_inspection_qty = 0
        receipt_line.row_version += 1
        receipt_line.save(update_fields=["pending_inspection_qty", "row_version", "updated_at"])
        order_line = order_lines[receipt_line.purchase_order_line_id]
        order_line.accepted_qty += item.accepted_qty
        order_line.rejected_qty += item.rejected_qty
        order_line.row_version += 1
        order_line.save(update_fields=["accepted_qty", "rejected_qty", "row_version", "updated_at"])

    for balance_id, quantity, receipt_line, rejected in sorted(movements, key=lambda row: row[0]):
        movement_kind = "R" if rejected else "A"
        adjust_on_hand(
            balance_id=balance_id,
            quantity_delta=quantity,
            transaction_type="purchase_rejected" if rejected else "purchase_accepted",
            reference_type="quality_inspection",
            reference_id=inspection.pk,
            reference_no=inspection.inspection_no,
            idempotency_key=f"inspection:{inspection.pk}:{receipt_line.pk}:{movement_kind}",
            operator=inspector,
            occurred_at=completed_at,
        )

    receipt.status = GoodsReceipt.Status.COMPLETED
    receipt.row_version += 1
    receipt.save(update_fields=["status", "row_version", "updated_at"])
    append_outbox_event(
        company=receipt.company,
        aggregate_type="quality_inspection",
        aggregate_id=str(inspection.pk),
        aggregate_version=inspection.row_version,
        event_type="PURCHASE_INSPECTION_COMPLETED",
        payload={"inspection_id": inspection.pk, "receipt_id": receipt.pk, "result": result},
    )
    return InspectionResult(inspection.pk, receipt.pk, result, False)


@transaction.atomic
def submit_requisition(*, requisition_id: int) -> PurchaseRequisition:
    requisition = (
        PurchaseRequisition.objects.select_for_update()
        .prefetch_related("lines")
        .get(pk=requisition_id)
    )
    if requisition.status != PurchaseRequisition.Status.DRAFT or not requisition.lines.exists():
        raise ValidationError("只有包含明细的草稿采购需求可以提交。")
    requisition.status = PurchaseRequisition.Status.SUBMITTED
    requisition.version_no += 1
    requisition.row_version += 1
    requisition.save()
    return requisition


@transaction.atomic
def approve_requisition(*, requisition_id: int, actor: User, approved: bool) -> PurchaseRequisition:
    requisition = PurchaseRequisition.objects.select_for_update().get(pk=requisition_id)
    if requisition.status != PurchaseRequisition.Status.SUBMITTED:
        raise ValidationError("采购需求不在待审批状态。")
    if requisition.requested_by_id == actor.pk:
        raise ValidationError("采购需求申请人与审批人必须分离。")
    requisition.status = (
        PurchaseRequisition.Status.APPROVED if approved else PurchaseRequisition.Status.REJECTED
    )
    requisition.approved_by = actor
    requisition.approved_at = timezone.now()
    requisition.version_no += 1
    requisition.row_version += 1
    requisition.save()
    append_outbox_event(
        company=requisition.company,
        aggregate_type="purchase.requisition",
        aggregate_id=str(requisition.pk),
        aggregate_version=requisition.version_no,
        event_type=f"purchase.requisition.{requisition.status}",
        payload={"requisition_id": requisition.pk},
    )
    return requisition


@transaction.atomic
def issue_rfq(*, rfq_id: int) -> RequestForQuotation:
    rfq = (
        RequestForQuotation.objects.select_for_update().select_related("requisition").get(pk=rfq_id)
    )
    if rfq.status != RequestForQuotation.Status.DRAFT or not rfq.suppliers.exists():
        raise ValidationError("询价单必须处于草稿且至少邀请一个供应商。")
    if rfq.requisition.status != PurchaseRequisition.Status.APPROVED:
        raise ValidationError("采购需求尚未批准。")
    rfq.status = RequestForQuotation.Status.ISSUED
    rfq.row_version += 1
    rfq.save()
    PurchaseRequisition.objects.filter(pk=rfq.requisition_id).update(
        status=PurchaseRequisition.Status.SOURCING,
        version_no=rfq.requisition.version_no + 1,
    )
    return rfq


@transaction.atomic
def award_quote(*, rfq_id: int, quote_id: int, purchase_order_no: str) -> PurchaseOrder:
    rfq = (
        RequestForQuotation.objects.select_for_update()
        .select_related("requisition__warehouse", "company")
        .get(pk=rfq_id)
    )
    quote = (
        SupplierQuote.objects.select_for_update()
        .select_related("supplier", "currency")
        .get(pk=quote_id, rfq=rfq)
    )
    if rfq.status not in {RequestForQuotation.Status.ISSUED, RequestForQuotation.Status.EVALUATING}:
        raise ValidationError("询价单当前不能定标。")
    if not rfq.suppliers.filter(supplier=quote.supplier).exists():
        raise ValidationError("报价供应商未受邀。")
    quote_lines = list(quote.lines.select_related("requisition_line__sku"))
    required_ids = set(rfq.requisition.lines.values_list("id", flat=True))
    if {line.requisition_line_id for line in quote_lines} != required_ids:
        raise ValidationError("中标报价必须完整覆盖采购需求行。")
    subtotal = sum((line.quantity * line.unit_price for line in quote_lines), Decimal(0))
    tax_total = sum(
        (line.quantity * line.unit_price * line.tax_rate for line in quote_lines), Decimal(0)
    )
    order = PurchaseOrder.objects.create(
        company=rfq.company,
        purchase_order_no=purchase_order_no,
        supplier=quote.supplier,
        order_date=timezone.localdate(),
        currency=quote.currency,
        exchange_rate=quote.exchange_rate,
        warehouse=rfq.requisition.warehouse,
        expected_delivery_date=quote.delivery_date,
        subtotal=subtotal,
        tax_total=tax_total,
        total=subtotal + tax_total + quote.freight_amount,
        base_total=(subtotal + tax_total + quote.freight_amount) * quote.exchange_rate,
    )
    for index, quote_line in enumerate(quote_lines, start=1):
        line_total = quote_line.quantity * quote_line.unit_price
        PurchaseOrderLine.objects.create(
            order=order,
            line_no=index,
            sku=quote_line.requisition_line.sku,
            ordered_qty=quote_line.quantity,
            unit_price=quote_line.unit_price,
            tax_rate=quote_line.tax_rate,
            line_total=line_total,
            base_line_total=line_total * quote.exchange_rate,
            expected_delivery_date=quote.delivery_date,
        )
        req_line = quote_line.requisition_line
        req_line.ordered_qty = quote_line.quantity
        req_line.row_version += 1
        req_line.save(update_fields=["ordered_qty", "row_version", "updated_at"])
    rfq.status = RequestForQuotation.Status.AWARDED
    rfq.awarded_quote = quote
    rfq.row_version += 1
    rfq.save()
    req = rfq.requisition
    req.status = PurchaseRequisition.Status.ORDERED
    req.version_no += 1
    req.row_version += 1
    req.save()
    append_outbox_event(
        company=rfq.company,
        aggregate_type="purchase.rfq",
        aggregate_id=str(rfq.pk),
        aggregate_version=rfq.row_version,
        event_type="purchase.rfq.awarded",
        payload={"rfq_id": rfq.pk, "quote_id": quote.pk, "purchase_order_id": order.pk},
    )
    return order


@transaction.atomic
def approve_purchase_return(*, return_id: int, actor: User) -> PurchaseReturn:
    purchase_return = (
        PurchaseReturn.objects.select_for_update()
        .prefetch_related("lines__purchase_order_line", "lines__inventory_balance")
        .get(pk=return_id)
    )
    if purchase_return.status != PurchaseReturn.Status.DRAFT or not purchase_return.lines.exists():
        raise ValidationError("只有包含明细的草稿采购退货单可以批准。")
    if purchase_return.requested_by_id == actor.pk:
        raise ValidationError("采购退货申请人与审批人必须分离。")
    for line in purchase_return.lines.all():
        order_line = line.purchase_order_line
        balance = line.inventory_balance
        if (
            order_line.order_id != purchase_return.purchase_order_id
            or balance.company_id != purchase_return.company_id
            or balance.sku_id != order_line.sku_id
            or line.return_qty > order_line.accepted_qty - order_line.returned_qty
        ):
            raise ValidationError("采购退货行来源、库存或数量无效。")
    purchase_return.status = PurchaseReturn.Status.APPROVED
    purchase_return.approved_by = actor
    purchase_return.approved_at = timezone.now()
    purchase_return.version_no += 1
    purchase_return.row_version += 1
    purchase_return.save()
    return purchase_return


@transaction.atomic
def dispatch_purchase_return(
    *, return_id: int, actor: User, idempotency_key: str
) -> PurchaseReturn:
    purchase_return = (
        PurchaseReturn.objects.select_for_update()
        .prefetch_related("lines__purchase_order_line", "lines__inventory_balance")
        .get(pk=return_id)
    )
    if purchase_return.idempotency_key == idempotency_key:
        return purchase_return
    if purchase_return.status != PurchaseReturn.Status.APPROVED:
        raise ValidationError("采购退货尚未批准。")
    for line in purchase_return.lines.all():
        adjust_on_hand(
            balance_id=line.inventory_balance_id,
            quantity_delta=-line.return_qty,
            transaction_type="purchase_return",
            reference_type="purchase_return",
            reference_id=purchase_return.pk,
            reference_no=purchase_return.return_no,
            idempotency_key=f"{idempotency_key}:line:{line.pk}",
            operator=actor,
            occurred_at=timezone.now(),
        )
        line.dispatched_qty = line.return_qty
        line.row_version += 1
        line.save(update_fields=["dispatched_qty", "row_version", "updated_at"])
        order_line = line.purchase_order_line
        order_line.returned_qty += line.return_qty
        order_line.row_version += 1
        order_line.save(update_fields=["returned_qty", "row_version", "updated_at"])
    purchase_return.status = PurchaseReturn.Status.DISPATCHED
    purchase_return.dispatched_at = timezone.now()
    purchase_return.idempotency_key = idempotency_key
    purchase_return.version_no += 1
    purchase_return.row_version += 1
    purchase_return.save()
    append_outbox_event(
        company=purchase_return.company,
        aggregate_type="purchase.return",
        aggregate_id=str(purchase_return.pk),
        aggregate_version=purchase_return.version_no,
        event_type="purchase.return.dispatched",
        payload={"purchase_return_id": purchase_return.pk},
    )
    return purchase_return

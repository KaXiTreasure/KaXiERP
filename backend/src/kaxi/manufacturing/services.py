from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance
from kaxi.inventory.services import adjust_on_hand
from kaxi.manufacturing.models import (
    BillOfMaterial,
    BillOfMaterialItem,
    MaterialIssue,
    MaterialIssueLine,
    ProductionCompletion,
    ProductionConsumption,
    ProductionOrder,
)
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.warehouse.models import WarehouseLocation


@dataclass(frozen=True)
class ManufacturingResult:
    object_id: int
    status: str
    version_no: int
    repeated: bool = False


@dataclass(frozen=True)
class MaterialIssueInput:
    component_sku_id: int
    balance_id: int
    quantity: Decimal


@dataclass(frozen=True)
class CompletionConsumptionInput:
    component_sku_id: int
    actual_consumed_qty: Decimal


@transaction.atomic
def transition_bom(*, bom_id: int, action: str) -> ManufacturingResult:
    bom = BillOfMaterial.objects.select_for_update().select_related("company").get(pk=bom_id)
    if action == "approve" and bom.status == BillOfMaterial.Status.DRAFT:
        if not bom.approval_reference:
            raise ValueError("批准BOM必须提供审批引用")
        target = BillOfMaterial.Status.APPROVED
    elif action == "activate" and bom.status == BillOfMaterial.Status.APPROVED:
        items = list(BillOfMaterialItem.objects.filter(bom=bom))
        if not items:
            raise ValueError("BOM至少需要一个物料明细")
        if any(item.component_sku_id == bom.product_sku_id for item in items):
            raise ValueError("BOM成品不能直接作为自身组件")
        overlap = (
            BillOfMaterial.objects.select_for_update()
            .filter(
                product_sku=bom.product_sku,
                bom_type=bom.bom_type,
                status=BillOfMaterial.Status.ACTIVE,
            )
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=bom.valid_from))
        )
        if bom.valid_to is not None:
            overlap = overlap.filter(valid_from__lt=bom.valid_to)
        if overlap.exclude(pk=bom.pk).exists():
            raise ValueError("同一成品和BOM类型的启用有效期不能重叠")
        target = BillOfMaterial.Status.ACTIVE
    elif action == "obsolete" and bom.status in {
        BillOfMaterial.Status.APPROVED,
        BillOfMaterial.Status.ACTIVE,
    }:
        target = BillOfMaterial.Status.OBSOLETE
    else:
        raise ValueError("BOM状态不允许执行此操作")
    bom.status = target
    bom.row_version += 1
    bom.save(update_fields=["status", "row_version", "updated_at"])
    append_outbox_event(
        company=bom.company,
        aggregate_type="bill_of_material",
        aggregate_id=str(bom.pk),
        aggregate_version=bom.row_version,
        event_type=f"BOM_{action.upper()}",
        payload={"bom_id": bom.pk, "status": bom.status},
    )
    return ManufacturingResult(bom.pk, bom.status, bom.row_version)


@transaction.atomic
def transition_production_order(
    *, order_id: int, expected_version: int, action: str
) -> ManufacturingResult:
    order = (
        ProductionOrder.objects.select_for_update()
        .select_related("company", "bom")
        .get(pk=order_id)
    )
    if order.version_no != expected_version:
        raise ValueError("生产订单版本已变化，请刷新后重试")
    transitions = {
        "approve": (ProductionOrder.Status.DRAFT, ProductionOrder.Status.APPROVED),
        "release": (ProductionOrder.Status.APPROVED, ProductionOrder.Status.RELEASED),
        "close": (ProductionOrder.Status.COMPLETED, ProductionOrder.Status.CLOSED),
    }
    transition = transitions.get(action)
    if transition is None or order.status != transition[0]:
        raise ValueError("生产订单状态不允许执行此操作")
    if action == "approve" and order.bom.status != BillOfMaterial.Status.ACTIVE:
        raise ValueError("生产订单只能使用启用中的BOM版本")
    order.status = transition[1]
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    append_outbox_event(
        company=order.company,
        aggregate_type="production_order",
        aggregate_id=str(order.pk),
        aggregate_version=order.version_no,
        event_type=f"PRODUCTION_ORDER_{action.upper()}",
        payload={"production_order_id": order.pk, "status": order.status},
    )
    return ManufacturingResult(order.pk, order.status, order.version_no)


@transaction.atomic
def issue_production_materials(
    *,
    order_id: int,
    issue_no: str,
    idempotency_key: str,
    lines: list[MaterialIssueInput],
    operator: User,
    occurred_at: datetime,
) -> ManufacturingResult:
    order = (
        ProductionOrder.objects.select_for_update()
        .select_related("company", "bom", "warehouse")
        .get(pk=order_id)
    )
    existing = MaterialIssue.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.production_order_id != order.pk:
            raise ValueError("领料幂等键已被其他生产订单使用")
        return ManufacturingResult(existing.pk, existing.status, order.version_no, True)
    if order.status not in {
        ProductionOrder.Status.RELEASED,
        ProductionOrder.Status.WAITING_MATERIAL,
        ProductionOrder.Status.IN_PROGRESS,
        ProductionOrder.Status.PARTIALLY_COMPLETED,
    }:
        raise ValueError("当前生产订单状态不能领料")
    if not lines:
        raise ValueError("领料单至少需要一个明细行")
    if len({line.component_sku_id for line in lines}) != len(lines):
        raise ValueError("同一领料单组件SKU不能重复")
    bom_items = {
        item.component_sku_id: item for item in BillOfMaterialItem.objects.filter(bom=order.bom)
    }
    balances = {
        balance.pk: balance
        for balance in InventoryBalance.objects.select_related("warehouse").filter(
            pk__in={line.balance_id for line in lines}
        )
    }
    issue = MaterialIssue.objects.create(
        production_order=order,
        issue_no=issue_no,
        source_warehouse=order.warehouse,
        issued_at=occurred_at,
        issued_by=operator,
        idempotency_key=idempotency_key,
    )
    for line_no, item in enumerate(sorted(lines, key=lambda value: value.balance_id), start=1):
        bom_item = bom_items.get(item.component_sku_id)
        balance = balances.get(item.balance_id)
        if bom_item is None:
            raise ValueError("领料组件不在生产BOM中")
        if item.quantity <= 0:
            raise ValueError("实际领料数量必须大于零")
        if (
            balance is None
            or balance.company_id != order.company_id
            or balance.warehouse_id != order.warehouse_id
            or balance.sku_id != item.component_sku_id
        ):
            raise ValueError("领料库存余额与生产公司、仓库或组件SKU不一致")
        planned_qty = order.planned_qty / order.bom.output_qty * bom_item.standard_qty
        adjust_on_hand(
            balance_id=balance.pk,
            quantity_delta=-item.quantity,
            transaction_type="production_material_issue",
            reference_type="material_issue",
            reference_id=issue.pk,
            reference_no=issue.issue_no,
            idempotency_key=f"{idempotency_key}:line:{line_no}",
            operator=operator,
            occurred_at=occurred_at,
        )
        MaterialIssueLine.objects.create(
            issue=issue,
            line_no=line_no,
            component_sku_id=item.component_sku_id,
            source_balance=balance,
            planned_qty=planned_qty,
            actual_qty=item.quantity,
        )
        consumption, _ = ProductionConsumption.objects.select_for_update().get_or_create(
            production_order=order,
            component_sku_id=item.component_sku_id,
            defaults={"standard_qty": planned_qty},
        )
        consumption.issued_qty += item.quantity
        consumption.standard_qty = planned_qty
        consumption.row_version += 1
        consumption.save(update_fields=["issued_qty", "standard_qty", "row_version", "updated_at"])
    if order.actual_start is None:
        order.actual_start = occurred_at
    order.status = ProductionOrder.Status.IN_PROGRESS
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["actual_start", "status", "version_no", "row_version", "updated_at"])
    append_outbox_event(
        company=order.company,
        aggregate_type="material_issue",
        aggregate_id=str(issue.pk),
        aggregate_version=issue.row_version,
        event_type="PRODUCTION_MATERIALS_ISSUED",
        payload={"issue_id": issue.pk, "production_order_id": order.pk},
    )
    return ManufacturingResult(issue.pk, issue.status, order.version_no)


def _validate_output_balance(
    balance: InventoryBalance, *, order: ProductionOrder, rejected: bool
) -> None:
    if (
        balance.company_id != order.company_id
        or balance.warehouse_id != order.warehouse_id
        or balance.sku_id != order.product_sku_id
    ):
        raise ValueError("完工库存余额与生产公司、仓库或成品SKU不一致")
    if rejected and balance.location.location_type != WarehouseLocation.LocationType.EXCEPTION:
        raise ValueError("生产NG必须进入异常库位")
    if not rejected and balance.location.location_type == WarehouseLocation.LocationType.EXCEPTION:
        raise ValueError("生产合格品不能进入异常库位")


@transaction.atomic
def complete_production(
    *,
    order_id: int,
    completion_no: str,
    idempotency_key: str,
    accepted_qty: Decimal,
    rejected_qty: Decimal,
    accepted_balance_id: int | None,
    rejected_balance_id: int | None,
    consumptions: list[CompletionConsumptionInput],
    operator: User,
    occurred_at: datetime,
) -> ManufacturingResult:
    order = (
        ProductionOrder.objects.select_for_update()
        .select_related("company", "bom")
        .get(pk=order_id)
    )
    existing = ProductionCompletion.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.production_order_id != order.pk:
            raise ValueError("完工幂等键已被其他生产订单使用")
        return ManufacturingResult(existing.pk, order.status, order.version_no, True)
    if order.status not in {
        ProductionOrder.Status.IN_PROGRESS,
        ProductionOrder.Status.PARTIALLY_COMPLETED,
    }:
        raise ValueError("只有生产中或部分完工的订单可以报工")
    completed_qty = accepted_qty + rejected_qty
    if accepted_qty < 0 or rejected_qty < 0 or completed_qty <= 0:
        raise ValueError("完工数量必须大于零且不能为负数")
    if order.completed_qty + completed_qty > order.planned_qty:
        raise ValueError("累计完工数量不能超过计划数量")
    balance_ids = [value for value in (accepted_balance_id, rejected_balance_id) if value]
    balances = {
        balance.pk: balance
        for balance in InventoryBalance.objects.select_related("location").filter(
            pk__in=balance_ids
        )
    }
    accepted_balance = balances.get(accepted_balance_id or 0)
    rejected_balance = balances.get(rejected_balance_id or 0)
    if accepted_qty > 0:
        if accepted_balance is None:
            raise ValueError("合格数量大于零时必须提供合格库存余额")
        _validate_output_balance(accepted_balance, order=order, rejected=False)
    if rejected_qty > 0:
        if rejected_balance is None:
            raise ValueError("NG数量大于零时必须提供异常库存余额")
        _validate_output_balance(rejected_balance, order=order, rejected=True)
    consumption_records = {
        record.component_sku_id: record
        for record in ProductionConsumption.objects.select_for_update().filter(
            production_order=order
        )
    }
    required_components = set(
        BillOfMaterialItem.objects.filter(bom=order.bom).values_list("component_sku_id", flat=True)
    )
    if set(consumption_records) != required_components:
        raise ValueError("完工前必须完成BOM全部组件领料")
    if set(value.component_sku_id for value in consumptions) != set(consumption_records):
        raise ValueError("报工必须提交全部已领料组件的本次实际消耗")
    for value in consumptions:
        record = consumption_records[value.component_sku_id]
        if value.actual_consumed_qty < 0:
            raise ValueError("实际消耗不能为负数")
        if (
            record.actual_consumed_qty + value.actual_consumed_qty
            > record.issued_qty - record.returned_qty
        ):
            raise ValueError("累计实际消耗不能超过净领料数量")

    completion = ProductionCompletion.objects.create(
        production_order=order,
        completion_no=completion_no,
        accepted_qty=accepted_qty,
        rejected_qty=rejected_qty,
        accepted_balance=accepted_balance,
        rejected_balance=rejected_balance,
        completed_at=occurred_at,
        completed_by=operator,
        idempotency_key=idempotency_key,
    )
    for balance, quantity, rejected in (
        (accepted_balance, accepted_qty, False),
        (rejected_balance, rejected_qty, True),
    ):
        if balance is not None and quantity > 0:
            adjust_on_hand(
                balance_id=balance.pk,
                quantity_delta=quantity,
                transaction_type="production_rejected" if rejected else "production_completed",
                reference_type="production_completion",
                reference_id=completion.pk,
                reference_no=completion.completion_no,
                idempotency_key=f"{idempotency_key}:{'R' if rejected else 'A'}",
                operator=operator,
                occurred_at=occurred_at,
            )
    cumulative_output = order.completed_qty + completed_qty
    for value in consumptions:
        record = consumption_records[value.component_sku_id]
        bom_item = BillOfMaterialItem.objects.get(
            bom=order.bom, component_sku_id=value.component_sku_id
        )
        record.actual_consumed_qty += value.actual_consumed_qty
        record.standard_qty = cumulative_output / order.bom.output_qty * bom_item.standard_qty
        record.loss_qty = max(record.actual_consumed_qty - record.standard_qty, Decimal(0))
        record.loss_rate = (
            record.loss_qty / record.standard_qty if record.standard_qty > 0 else Decimal(0)
        )
        record.row_version += 1
        record.save(
            update_fields=[
                "actual_consumed_qty",
                "standard_qty",
                "loss_qty",
                "loss_rate",
                "row_version",
                "updated_at",
            ]
        )
    order.completed_qty = cumulative_output
    order.accepted_qty += accepted_qty
    order.rejected_qty += rejected_qty
    order.status = (
        ProductionOrder.Status.COMPLETED
        if cumulative_output == order.planned_qty
        else ProductionOrder.Status.PARTIALLY_COMPLETED
    )
    if order.status == ProductionOrder.Status.COMPLETED:
        order.actual_end = occurred_at
    order.version_no += 1
    order.row_version += 1
    order.save(
        update_fields=[
            "completed_qty",
            "accepted_qty",
            "rejected_qty",
            "status",
            "actual_end",
            "version_no",
            "row_version",
            "updated_at",
        ]
    )
    append_outbox_event(
        company=order.company,
        aggregate_type="production_completion",
        aggregate_id=str(completion.pk),
        aggregate_version=completion.row_version,
        event_type="PRODUCTION_COMPLETED",
        payload={
            "completion_id": completion.pk,
            "production_order_id": order.pk,
            "accepted_qty": str(accepted_qty),
            "rejected_qty": str(rejected_qty),
        },
    )
    return ManufacturingResult(completion.pk, order.status, order.version_no)

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance
from kaxi.inventory.services import adjust_on_hand
from kaxi.prepack.models import (
    PackagingPlan,
    PackagingPlanItem,
    PrepackBreakdown,
    PrepackBreakdownMaterial,
    PrepackExecution,
    PrepackMaterialUsage,
    PrepackOrder,
)
from kaxi.shared.outbox_service import append_outbox_event


@dataclass(frozen=True)
class PrepackResult:
    object_id: int
    status: str
    version_no: int
    repeated: bool = False


@dataclass(frozen=True)
class MaterialUsageInput:
    plan_item_id: int
    balance_id: int
    actual_used_qty: Decimal


@dataclass(frozen=True)
class BreakdownMaterialInput:
    plan_item_id: int
    return_balance_id: int
    returned_qty: Decimal


@transaction.atomic
def activate_packaging_plan(*, plan_id: int) -> PrepackResult:
    plan = PackagingPlan.objects.select_for_update().select_related("company").get(pk=plan_id)
    if plan.status != PackagingPlan.Status.DRAFT:
        raise ValueError("只有草稿包装方案可以启用")
    if not plan.approval_reference:
        raise ValueError("启用包装方案必须提供审批引用")
    if not plan.items.exists():
        raise ValueError("包装方案至少需要一个包装物料")
    conflict = PackagingPlan.objects.select_for_update().filter(
        product_sku=plan.product_sku,
        channel=plan.channel,
        trade_type=plan.trade_type,
        status=PackagingPlan.Status.ACTIVE,
    )
    if conflict.exclude(pk=plan.pk).exists():
        raise ValueError("同一适用范围只能有一个启用中的包装方案")
    plan.status = PackagingPlan.Status.ACTIVE
    plan.row_version += 1
    plan.save(update_fields=["status", "row_version", "updated_at"])
    append_outbox_event(
        company=plan.company,
        aggregate_type="packaging_plan",
        aggregate_id=str(plan.pk),
        aggregate_version=plan.row_version,
        event_type="PACKAGING_PLAN_ACTIVATED",
        payload={"packaging_plan_id": plan.pk},
    )
    return PrepackResult(plan.pk, plan.status, plan.row_version)


@transaction.atomic
def approve_prepack_order(*, order_id: int, expected_version: int) -> PrepackResult:
    order = (
        PrepackOrder.objects.select_for_update()
        .select_related("company", "packaging_plan")
        .get(pk=order_id)
    )
    if order.version_no != expected_version:
        raise ValueError("预包装单版本已变化，请刷新后重试")
    if order.status != PrepackOrder.Status.DRAFT:
        raise ValueError("只有草稿预包装单可以批准")
    if order.packaging_plan.status != PackagingPlan.Status.ACTIVE:
        raise ValueError("预包装单必须使用启用中的包装方案")
    order.status = PrepackOrder.Status.APPROVED
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    append_outbox_event(
        company=order.company,
        aggregate_type="prepack_order",
        aggregate_id=str(order.pk),
        aggregate_version=order.version_no,
        event_type="PREPACK_ORDER_APPROVED",
        payload={"prepack_order_id": order.pk},
    )
    return PrepackResult(order.pk, order.status, order.version_no)


def _validate_product_balances(
    *, order: PrepackOrder, source: InventoryBalance, target: InventoryBalance
) -> None:
    if (
        source.company_id != order.company_id
        or target.company_id != order.company_id
        or source.warehouse_id != order.warehouse_id
        or target.warehouse_id != order.warehouse_id
        or source.sku_id != order.product_sku_id
        or target.sku_id != order.product_sku_id
        or source.location_id != order.source_location_id
        or target.location_id != order.target_location_id
        or source.lot_id != target.lot_id
    ):
        raise ValueError("预包装产品库存余额与公司、仓库、SKU、批次或指定库位不一致")


@transaction.atomic
def execute_prepack(
    *,
    order_id: int,
    execution_no: str,
    quantity: Decimal,
    source_balance_id: int,
    target_balance_id: int,
    materials: list[MaterialUsageInput],
    idempotency_key: str,
    operator: User,
    occurred_at: datetime,
) -> PrepackResult:
    order = (
        PrepackOrder.objects.select_for_update()
        .select_related("company", "packaging_plan")
        .get(pk=order_id)
    )
    existing = PrepackExecution.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.order_id != order.pk:
            raise ValueError("预包装幂等键已被其他单据使用")
        return PrepackResult(existing.pk, order.status, order.version_no, True)
    if order.status not in {
        PrepackOrder.Status.APPROVED,
        PrepackOrder.Status.PACKAGING,
        PrepackOrder.Status.PARTIALLY_COMPLETED,
    }:
        raise ValueError("当前预包装单状态不能执行包装")
    if quantity <= 0 or order.completed_qty + quantity > order.planned_qty:
        raise ValueError("本次完成数量必须大于零且累计不能超过计划数量")
    balances = {
        balance.pk: balance
        for balance in InventoryBalance.objects.filter(
            pk__in={source_balance_id, target_balance_id, *(item.balance_id for item in materials)}
        )
    }
    source = balances.get(source_balance_id)
    target = balances.get(target_balance_id)
    if source is None or target is None:
        raise ValueError("产品来源或目标库存余额不存在")
    _validate_product_balances(order=order, source=source, target=target)
    plan_items = {
        item.pk: item for item in PackagingPlanItem.objects.filter(plan=order.packaging_plan)
    }
    if {item.plan_item_id for item in materials} != set(plan_items) or len(materials) != len(
        plan_items
    ):
        raise ValueError("执行预包装必须提交方案中的全部且不重复包装物料")
    for value in materials:
        item = plan_items[value.plan_item_id]
        balance = balances.get(value.balance_id)
        if value.actual_used_qty <= 0:
            raise ValueError("包装物料实际用量必须大于零")
        if (
            balance is None
            or balance.company_id != order.company_id
            or balance.warehouse_id != order.warehouse_id
            or balance.sku_id != item.material_sku_id
        ):
            raise ValueError("包装物料库存余额与公司、仓库或SKU不一致")

    execution = PrepackExecution.objects.create(
        order=order,
        execution_no=execution_no,
        quantity=quantity,
        source_balance=source,
        target_balance=target,
        executed_at=occurred_at,
        executed_by=operator,
        idempotency_key=idempotency_key,
    )
    adjust_on_hand(
        balance_id=source.pk,
        quantity_delta=-quantity,
        transaction_type="prepack_product_issue",
        reference_type="prepack_execution",
        reference_id=execution.pk,
        reference_no=execution.execution_no,
        idempotency_key=f"{idempotency_key}:product-source",
        operator=operator,
        occurred_at=occurred_at,
    )
    for value in sorted(materials, key=lambda item: item.balance_id):
        item = plan_items[value.plan_item_id]
        standard_qty = quantity * item.standard_qty
        adjust_on_hand(
            balance_id=value.balance_id,
            quantity_delta=-value.actual_used_qty,
            transaction_type="prepack_material_consume",
            reference_type="prepack_execution",
            reference_id=execution.pk,
            reference_no=execution.execution_no,
            idempotency_key=f"{idempotency_key}:material:{item.pk}",
            operator=operator,
            occurred_at=occurred_at,
        )
        PrepackMaterialUsage.objects.create(
            execution=execution,
            plan_item=item,
            material_balance_id=value.balance_id,
            standard_qty=standard_qty,
            actual_used_qty=value.actual_used_qty,
            loss_qty=max(value.actual_used_qty - standard_qty, Decimal(0)),
        )
    adjust_on_hand(
        balance_id=target.pk,
        quantity_delta=quantity,
        transaction_type="prepack_product_receipt",
        reference_type="prepack_execution",
        reference_id=execution.pk,
        reference_no=execution.execution_no,
        idempotency_key=f"{idempotency_key}:product-target",
        operator=operator,
        occurred_at=occurred_at,
    )
    order.completed_qty += quantity
    order.status = (
        PrepackOrder.Status.COMPLETED
        if order.completed_qty == order.planned_qty
        else PrepackOrder.Status.PARTIALLY_COMPLETED
    )
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["completed_qty", "status", "version_no", "row_version", "updated_at"])
    append_outbox_event(
        company=order.company,
        aggregate_type="prepack_execution",
        aggregate_id=str(execution.pk),
        aggregate_version=execution.row_version,
        event_type="PREPACK_COMPLETED",
        payload={"execution_id": execution.pk, "prepack_order_id": order.pk},
    )
    return PrepackResult(execution.pk, order.status, order.version_no)


@transaction.atomic
def breakdown_prepack(
    *,
    order_id: int,
    breakdown_no: str,
    quantity: Decimal,
    prepacked_balance_id: int,
    restored_product_balance_id: int,
    returned_materials: list[BreakdownMaterialInput],
    approval_reference: str,
    idempotency_key: str,
    operator: User,
    occurred_at: datetime,
) -> PrepackResult:
    order = (
        PrepackOrder.objects.select_for_update()
        .select_related("company", "packaging_plan")
        .get(pk=order_id)
    )
    existing = PrepackBreakdown.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.order_id != order.pk:
            raise ValueError("拆包幂等键已被其他单据使用")
        return PrepackResult(existing.pk, order.status, order.version_no, True)
    if not approval_reference:
        raise ValueError("拆包必须提供审批引用")
    if quantity <= 0 or order.broken_down_qty + quantity > order.completed_qty:
        raise ValueError("拆包数量必须大于零且不能超过可拆预包装数量")
    balance_ids = {
        prepacked_balance_id,
        restored_product_balance_id,
        *(item.return_balance_id for item in returned_materials),
    }
    balances = {
        balance.pk: balance for balance in InventoryBalance.objects.filter(pk__in=balance_ids)
    }
    prepacked = balances.get(prepacked_balance_id)
    restored = balances.get(restored_product_balance_id)
    if prepacked is None or restored is None:
        raise ValueError("拆包产品库存余额不存在")
    _validate_product_balances(order=order, source=restored, target=prepacked)
    plan_items = {
        item.pk: item for item in PackagingPlanItem.objects.filter(plan=order.packaging_plan)
    }
    if len({item.plan_item_id for item in returned_materials}) != len(returned_materials):
        raise ValueError("拆包退回物料不能重复")
    for value in returned_materials:
        item = plan_items.get(value.plan_item_id)
        balance = balances.get(value.return_balance_id)
        if item is None or not item.returnable_on_breakdown:
            raise ValueError("包装方案不允许退回该物料")
        if value.returned_qty <= 0:
            raise ValueError("退回物料数量必须大于零")
        if (
            balance is None
            or balance.company_id != order.company_id
            or balance.warehouse_id != order.warehouse_id
            or balance.sku_id != item.material_sku_id
        ):
            raise ValueError("退回物料库存余额与公司、仓库或SKU不一致")
        used = PrepackMaterialUsage.objects.filter(
            execution__order=order, plan_item=item
        ).aggregate(total=Sum("actual_used_qty"))["total"] or Decimal(0)
        returned = PrepackBreakdownMaterial.objects.filter(
            breakdown__order=order, plan_item=item
        ).aggregate(total=Sum("returned_qty"))["total"] or Decimal(0)
        if returned + value.returned_qty > used:
            raise ValueError("累计退回包装物料不能超过累计实际用量")

    breakdown = PrepackBreakdown.objects.create(
        order=order,
        breakdown_no=breakdown_no,
        quantity=quantity,
        prepacked_balance=prepacked,
        restored_product_balance=restored,
        approval_reference=approval_reference,
        occurred_at=occurred_at,
        operator=operator,
        idempotency_key=idempotency_key,
    )
    adjust_on_hand(
        balance_id=prepacked.pk,
        quantity_delta=-quantity,
        transaction_type="prepack_breakdown_issue",
        reference_type="prepack_breakdown",
        reference_id=breakdown.pk,
        reference_no=breakdown.breakdown_no,
        idempotency_key=f"{idempotency_key}:product-prepacked",
        operator=operator,
        occurred_at=occurred_at,
    )
    adjust_on_hand(
        balance_id=restored.pk,
        quantity_delta=quantity,
        transaction_type="prepack_breakdown_restore",
        reference_type="prepack_breakdown",
        reference_id=breakdown.pk,
        reference_no=breakdown.breakdown_no,
        idempotency_key=f"{idempotency_key}:product-restored",
        operator=operator,
        occurred_at=occurred_at,
    )
    for value in sorted(returned_materials, key=lambda item: item.return_balance_id):
        adjust_on_hand(
            balance_id=value.return_balance_id,
            quantity_delta=value.returned_qty,
            transaction_type="prepack_material_return",
            reference_type="prepack_breakdown",
            reference_id=breakdown.pk,
            reference_no=breakdown.breakdown_no,
            idempotency_key=f"{idempotency_key}:material:{value.plan_item_id}",
            operator=operator,
            occurred_at=occurred_at,
        )
        PrepackBreakdownMaterial.objects.create(
            breakdown=breakdown,
            plan_item_id=value.plan_item_id,
            return_balance_id=value.return_balance_id,
            returned_qty=value.returned_qty,
        )
    order.broken_down_qty += quantity
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["broken_down_qty", "version_no", "row_version", "updated_at"])
    append_outbox_event(
        company=order.company,
        aggregate_type="prepack_breakdown",
        aggregate_id=str(breakdown.pk),
        aggregate_version=breakdown.row_version,
        event_type="PREPACK_BROKEN_DOWN",
        payload={"breakdown_id": breakdown.pk, "prepack_order_id": order.pk},
    )
    return PrepackResult(breakdown.pk, order.status, order.version_no)

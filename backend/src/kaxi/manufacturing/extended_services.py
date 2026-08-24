from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance
from kaxi.inventory.services import adjust_on_hand
from kaxi.manufacturing.models import (
    BillOfMaterial,
    OperationReport,
    ProductionOrder,
    ProductionSuggestion,
    Routing,
    RoutingOperation,
    SubcontractOrder,
)
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.warehouse.models import Warehouse


@transaction.atomic
def activate_routing(*, routing_id: int, approval_reference: str) -> Routing:
    routing = Routing.objects.select_for_update().prefetch_related("operations").get(pk=routing_id)
    if routing.status != Routing.Status.DRAFT or not routing.operations.exists():
        raise ValidationError("只有包含工序的草稿工艺路线可以启用。")
    if not approval_reference.strip():
        raise ValidationError("启用工艺路线必须保留审批引用。")
    overlap = Routing.objects.filter(
        product_sku=routing.product_sku,
        status=Routing.Status.ACTIVE,
        valid_from__lt=routing.valid_to
        or datetime.max.replace(tzinfo=timezone.get_current_timezone()),
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=routing.valid_from))
    if overlap.exists():
        raise ValidationError("同一产品存在生效期重叠的工艺路线。")
    routing.status = Routing.Status.ACTIVE
    routing.approval_reference = approval_reference
    routing.row_version += 1
    routing.save()
    return routing


@transaction.atomic
def report_operation(
    *,
    production_order_id: int,
    operation_id: int,
    report_no: str,
    started_at: datetime,
    ended_at: datetime,
    good_qty: Decimal,
    rejected_qty: Decimal,
    labor_minutes: Decimal,
    operator: User,
) -> OperationReport:
    order = (
        ProductionOrder.objects.select_for_update()
        .select_related("routing")
        .get(pk=production_order_id)
    )
    operation = RoutingOperation.objects.get(pk=operation_id)
    if order.routing_id != operation.routing_id or order.status not in {
        ProductionOrder.Status.RELEASED,
        ProductionOrder.Status.IN_PROGRESS,
        ProductionOrder.Status.PARTIALLY_COMPLETED,
    }:
        raise ValidationError("工序不属于生产单工艺路线或生产单状态无效。")
    if ended_at <= started_at or good_qty + rejected_qty <= 0:
        raise ValidationError("报工时间或数量无效。")
    prior_operations = order.routing.operations.filter(sequence__lt=operation.sequence)
    for prior in prior_operations:
        prior_good = order.operation_reports.filter(operation=prior).aggregate(
            total=Sum("good_qty")
        )["total"] or Decimal(0)
        if prior_good < good_qty + rejected_qty:
            raise ValidationError("前序工序合格数量不足。")
    reported = order.operation_reports.filter(operation=operation).aggregate(
        good=Sum("good_qty"), rejected=Sum("rejected_qty")
    )
    total = (reported["good"] or Decimal(0)) + (reported["rejected"] or Decimal(0))
    if total + good_qty + rejected_qty > order.planned_qty:
        raise ValidationError("累计工序报工超过生产计划数量。")
    report = OperationReport.objects.create(
        production_order=order,
        operation=operation,
        report_no=report_no,
        started_at=started_at,
        ended_at=ended_at,
        good_qty=good_qty,
        rejected_qty=rejected_qty,
        labor_minutes=labor_minutes,
        operator=operator,
    )
    if order.status == ProductionOrder.Status.RELEASED:
        order.status = ProductionOrder.Status.IN_PROGRESS
        order.actual_start = started_at
        order.version_no += 1
        order.row_version += 1
        order.save()
    return report


@transaction.atomic
def convert_suggestion(
    *,
    suggestion_id: int,
    production_order_no: str,
    bom_id: int,
    routing_id: int | None,
    warehouse_id: int,
) -> ProductionOrder:
    suggestion = ProductionSuggestion.objects.select_for_update().get(pk=suggestion_id)
    if suggestion.status not in {"open", "accepted"}:
        raise ValidationError("生产建议已经处理。")
    bom = BillOfMaterial.objects.get(pk=bom_id)
    warehouse = Warehouse.objects.get(pk=warehouse_id)
    routing = Routing.objects.get(pk=routing_id) if routing_id else None
    if (
        bom.company_id != suggestion.company_id
        or bom.product_sku_id != suggestion.product_sku_id
        or warehouse.company_id != suggestion.company_id
        or (
            routing
            and (
                routing.product_sku_id != suggestion.product_sku_id
                or routing.status != Routing.Status.ACTIVE
            )
        )
    ):
        raise ValidationError("BOM、工艺路线、仓库与生产建议不匹配。")
    order = ProductionOrder.objects.create(
        company=suggestion.company,
        production_order_no=production_order_no,
        product_sku=suggestion.product_sku,
        bom=bom,
        routing=routing,
        planned_qty=suggestion.suggested_qty,
        warehouse=warehouse,
        planned_end=timezone.make_aware(
            datetime.combine(suggestion.required_date, datetime.min.time())
        ),
        source_type="production_suggestion",
        source_id=suggestion.pk,
    )
    suggestion.status = "converted"
    suggestion.production_order = order
    suggestion.row_version += 1
    suggestion.save()
    return order


@transaction.atomic
def approve_subcontract(*, order_id: int, actor: User) -> SubcontractOrder:
    order = (
        SubcontractOrder.objects.select_for_update().prefetch_related("materials").get(pk=order_id)
    )
    if order.status != SubcontractOrder.Status.DRAFT or not order.materials.exists():
        raise ValidationError("只有包含物料的草稿委外单可以批准。")
    if order.requested_by_id == actor.pk:
        raise ValidationError("委外申请人与审批人必须分离。")
    order.status = SubcontractOrder.Status.APPROVED
    order.approved_by = actor
    order.version_no += 1
    order.row_version += 1
    order.save()
    return order


@transaction.atomic
def send_subcontract_materials(
    *, order_id: int, actor: User, idempotency_key: str
) -> SubcontractOrder:
    order = (
        SubcontractOrder.objects.select_for_update()
        .prefetch_related("materials__source_balance")
        .get(pk=order_id)
    )
    if order.status == SubcontractOrder.Status.MATERIAL_SENT:
        return order
    if order.status != SubcontractOrder.Status.APPROVED:
        raise ValidationError("委外单尚未批准。")
    now = timezone.now()
    for material in order.materials.all():
        balance = material.source_balance
        if balance.company_id != order.company_id or balance.sku_id != material.component_sku_id:
            raise ValidationError("委外物料库存来源无效。")
        adjust_on_hand(
            balance_id=balance.pk,
            quantity_delta=-material.planned_qty,
            transaction_type="subcontract_material_sent",
            reference_type="subcontract_order",
            reference_id=order.pk,
            reference_no=order.subcontract_no,
            idempotency_key=f"{idempotency_key}:material:{material.pk}",
            operator=actor,
            occurred_at=now,
        )
        material.sent_qty = material.planned_qty
        material.row_version += 1
        material.save()
    order.status = SubcontractOrder.Status.MATERIAL_SENT
    order.sent_at = now
    order.version_no += 1
    order.row_version += 1
    order.save()
    return order


@transaction.atomic
def receive_subcontract(
    *,
    order_id: int,
    accepted_qty: Decimal,
    rejected_qty: Decimal,
    accepted_balance_id: int | None,
    rejected_balance_id: int | None,
    actor: User,
    idempotency_key: str,
) -> SubcontractOrder:
    order = SubcontractOrder.objects.select_for_update().get(pk=order_id)
    if order.status not in {
        SubcontractOrder.Status.MATERIAL_SENT,
        SubcontractOrder.Status.PROCESSING,
    }:
        raise ValidationError("委外单当前不能收回。")
    quantity = accepted_qty + rejected_qty
    if quantity <= 0 or order.received_qty + quantity > order.ordered_qty:
        raise ValidationError("委外收回数量无效。")
    now = timezone.now()
    for qty, balance_id, kind in [
        (accepted_qty, accepted_balance_id, "accepted"),
        (rejected_qty, rejected_balance_id, "rejected"),
    ]:
        if qty:
            if not balance_id:
                raise ValidationError("委外收回必须指定对应库存余额。")
            balance = InventoryBalance.objects.get(pk=balance_id)
            if balance.company_id != order.company_id or balance.sku_id != order.product_sku_id:
                raise ValidationError("委外收回库存余额无效。")
            adjust_on_hand(
                balance_id=balance.pk,
                quantity_delta=qty,
                transaction_type=f"subcontract_{kind}",
                reference_type="subcontract_order",
                reference_id=order.pk,
                reference_no=order.subcontract_no,
                idempotency_key=f"{idempotency_key}:{kind}",
                operator=actor,
                occurred_at=now,
            )
    order.received_qty += quantity
    order.accepted_qty += accepted_qty
    order.rejected_qty += rejected_qty
    order.status = (
        SubcontractOrder.Status.COMPLETED
        if order.received_qty == order.ordered_qty
        else SubcontractOrder.Status.RECEIVED
    )
    order.received_at = now
    order.version_no += 1
    order.row_version += 1
    order.save()
    append_outbox_event(
        company=order.company,
        aggregate_type="manufacturing.subcontract",
        aggregate_id=str(order.pk),
        aggregate_version=order.version_no,
        event_type="manufacturing.subcontract.received",
        payload={"order_id": order.pk, "quantity": str(quantity)},
    )
    return order

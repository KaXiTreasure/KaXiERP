from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from kaxi.sales.models import (
    PresaleAllocation,
    PresaleCampaign,
    SalesOrderLine,
    SupplyAllocation,
    SupplyDemand,
)
from kaxi.shared.outbox_service import append_outbox_event


@transaction.atomic
def create_supply_demand(
    *,
    sales_order_line_id: int,
    demand_no: str,
    strategy: str,
    required_date: date,
    idempotency_key: str,
) -> SupplyDemand:
    line = (
        SalesOrderLine.objects.select_for_update()
        .select_related("order__company")
        .get(pk=sales_order_line_id)
    )
    existing = SupplyDemand.objects.filter(
        company=line.order.company, idempotency_key=idempotency_key
    ).first()
    if existing:
        return existing
    shortage = line.ordered_qty - line.cancelled_qty - line.shipped_qty - line.reserved_qty
    existing_open = line.supply_demands.exclude(status=SupplyDemand.Status.CANCELLED).aggregate(
        total=Sum("shortage_qty")
    )["total"] or Decimal(0)
    shortage -= existing_open
    if shortage <= 0:
        raise ValidationError("订单行当前没有未记录的供应缺口。")
    demand = SupplyDemand.objects.create(
        company=line.order.company,
        demand_no=demand_no,
        sales_order_line=line,
        shortage_qty=shortage,
        strategy=strategy,
        required_date=required_date,
        idempotency_key=idempotency_key,
    )
    append_outbox_event(
        company=demand.company,
        aggregate_type="sales.supply_demand",
        aggregate_id=str(demand.pk),
        aggregate_version=demand.row_version,
        event_type=f"sales.supply_demand.{strategy}_requested",
        payload={"demand_id": demand.pk, "quantity": str(shortage)},
    )
    return demand


@transaction.atomic
def link_supply(
    *, demand_id: int, source_type: str, source_id: str, planned_qty: Decimal, expected_date=None
) -> SupplyAllocation:  # type: ignore[no-untyped-def]
    demand = SupplyDemand.objects.select_for_update().get(pk=demand_id)
    if demand.status in {SupplyDemand.Status.FULFILLED, SupplyDemand.Status.CANCELLED}:
        raise ValidationError("供应需求已经结束。")
    planned_total = demand.allocations.aggregate(total=Sum("planned_qty"))["total"] or Decimal(0)
    if planned_qty <= 0 or planned_total + planned_qty > demand.shortage_qty:
        raise ValidationError("计划供应数量超过需求缺口。")
    allocation = SupplyAllocation.objects.create(
        demand=demand,
        source_type=source_type,
        source_id=source_id,
        planned_qty=planned_qty,
        expected_date=expected_date,
    )
    demand.status = SupplyDemand.Status.PLANNED
    demand.promised_date = expected_date
    demand.row_version += 1
    demand.save()
    return allocation


@transaction.atomic
def receive_supply(*, allocation_id: int, quantity: Decimal) -> SupplyDemand:
    allocation = (
        SupplyAllocation.objects.select_for_update().select_related("demand").get(pk=allocation_id)
    )
    demand = SupplyDemand.objects.select_for_update().get(pk=allocation.demand_id)
    if quantity <= 0 or allocation.received_qty + quantity > allocation.planned_qty:
        raise ValidationError("到货/完工数量超过计划供应数量。")
    allocation.received_qty += quantity
    allocation.status = (
        "received" if allocation.received_qty == allocation.planned_qty else "partial"
    )
    allocation.row_version += 1
    allocation.save()
    demand.supplied_qty += quantity
    demand.status = (
        SupplyDemand.Status.FULFILLED
        if demand.supplied_qty == demand.shortage_qty
        else SupplyDemand.Status.PARTIAL
    )
    demand.row_version += 1
    demand.save()
    return demand


@transaction.atomic
def activate_presale(*, campaign_id: int) -> PresaleCampaign:
    campaign = PresaleCampaign.objects.select_for_update().get(pk=campaign_id)
    if campaign.status != PresaleCampaign.Status.DRAFT:
        raise ValidationError("只有草稿预售活动可以启用。")
    if campaign.ends_at <= timezone.now() or campaign.starts_at >= campaign.ends_at:
        raise ValidationError("预售活动有效期无效。")
    campaign.status = PresaleCampaign.Status.ACTIVE
    campaign.row_version += 1
    campaign.save()
    return campaign


@transaction.atomic
def allocate_presale(
    *, campaign_id: int, sales_order_line_id: int, quantity: Decimal
) -> PresaleAllocation:
    campaign = PresaleCampaign.objects.select_for_update().get(pk=campaign_id)
    line = (
        SalesOrderLine.objects.select_for_update()
        .select_related("order")
        .get(pk=sales_order_line_id)
    )
    now = timezone.now()
    if (
        campaign.status != PresaleCampaign.Status.ACTIVE
        or not campaign.starts_at <= now < campaign.ends_at
        or line.order.company_id != campaign.company_id
        or line.sku_id != campaign.sku_id
    ):
        raise ValidationError("预售活动与订单行不匹配或当前无效。")
    available_line_qty = line.ordered_qty - line.cancelled_qty - line.shipped_qty
    if (
        quantity <= 0
        or quantity > available_line_qty
        or campaign.allocated_qty + quantity > campaign.capacity_qty
    ):
        raise ValidationError("预售分配数量超过订单需求或活动容量。")
    allocation = PresaleAllocation.objects.create(
        campaign=campaign,
        sales_order_line=line,
        quantity=quantity,
        promised_delivery_date=campaign.promised_delivery_date,
    )
    campaign.allocated_qty += quantity
    campaign.row_version += 1
    campaign.save(update_fields=["allocated_qty", "row_version", "updated_at"])
    return allocation

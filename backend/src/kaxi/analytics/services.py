import hashlib
import json
from datetime import date
from decimal import Decimal

from django.db.models import DecimalField, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from kaxi.aftersales.models import AfterSalesCase, Refund
from kaxi.finance.models import CostRecord, JournalEntry, OpenItem
from kaxi.inventory.models import InventoryBalance
from kaxi.manufacturing.models import ProductionOrder, SubcontractOrder
from kaxi.purchasing.models import PurchaseOrder, PurchaseReturn
from kaxi.sales.models import SalesOrder, SupplyDemand
from kaxi.trade.models import Shipment

ZERO = Decimal("0")
DECIMAL = DecimalField(max_digits=20, decimal_places=6)


def dashboard(*, company_id: int) -> dict[str, object]:
    return {
        "sales_orders": SalesOrder.objects.filter(company_id=company_id).count(),
        "open_supply_demands": SupplyDemand.objects.filter(company_id=company_id)
        .exclude(status__in=["fulfilled", "cancelled"])
        .count(),
        "purchase_orders": PurchaseOrder.objects.filter(company_id=company_id).count(),
        "production_in_progress": ProductionOrder.objects.filter(
            company_id=company_id,
            status__in=["released", "waiting_material", "in_progress", "partially_completed"],
        ).count(),
        "shipments_in_transit": Shipment.objects.filter(
            company_id=company_id, status__in=["dispatched", "in_transit"]
        ).count(),
        "pending_journals": JournalEntry.objects.filter(company_id=company_id)
        .exclude(status__in=["posted", "reversed"])
        .count(),
        "open_aftersales": AfterSalesCase.objects.filter(company_id=company_id)
        .exclude(status__in=["completed", "rejected", "cancelled"])
        .count(),
    }


def inventory_summary(*, company_id: int):  # type: ignore[no-untyped-def]
    return list(
        InventoryBalance.objects.filter(company_id=company_id)
        .values("warehouse_id", "warehouse__name")
        .annotate(
            on_hand=Coalesce(Sum("on_hand_qty"), ZERO, output_field=DECIMAL),
            reserved=Coalesce(Sum("reserved_qty"), ZERO, output_field=DECIMAL),
            locked=Coalesce(Sum("locked_qty"), ZERO, output_field=DECIMAL),
        )
        .order_by("warehouse_id")
    )


def arap_aging(*, company_id: int, kind: str, as_of: date | None = None):  # type: ignore[no-untyped-def]
    as_of = as_of or timezone.localdate()
    items = OpenItem.objects.filter(company_id=company_id, kind=kind).exclude(status="settled")
    result = {"current": ZERO, "1_30": ZERO, "31_60": ZERO, "61_90": ZERO, "over_90": ZERO}
    for item in items.only("due_date", "original_amount", "allocated_amount"):
        days = (as_of - item.due_date).days
        key = (
            "current"
            if days <= 0
            else "1_30"
            if days <= 30
            else "31_60"
            if days <= 60
            else "61_90"
            if days <= 90
            else "over_90"
        )
        result[key] += item.original_amount - item.allocated_amount
    return result


def procurement_summary(*, company_id: int) -> dict[str, object]:
    order_value = PurchaseOrder.objects.filter(company_id=company_id).aggregate(
        value=Coalesce(Sum("base_total"), ZERO, output_field=DECIMAL)
    )["value"]
    return {
        "order_count": PurchaseOrder.objects.filter(company_id=company_id).count(),
        "base_order_value": order_value,
        "return_count": PurchaseReturn.objects.filter(company_id=company_id).count(),
    }


def production_summary(*, company_id: int) -> dict[str, object]:
    values = ProductionOrder.objects.filter(company_id=company_id).aggregate(
        planned=Coalesce(Sum("planned_qty"), ZERO, output_field=DECIMAL),
        accepted=Coalesce(Sum("accepted_qty"), ZERO, output_field=DECIMAL),
        rejected=Coalesce(Sum("rejected_qty"), ZERO, output_field=DECIMAL),
    )
    values["subcontract_open"] = (
        SubcontractOrder.objects.filter(company_id=company_id)
        .exclude(status__in=["completed", "cancelled"])
        .count()
    )
    return values


def profitability(*, company_id: int) -> dict[str, object]:
    revenue = SalesOrder.objects.filter(company_id=company_id).aggregate(
        value=Coalesce(Sum("lines__line_total"), ZERO, output_field=DECIMAL)
    )["value"]
    cogs = CostRecord.objects.filter(
        company_id=company_id, category=CostRecord.Category.COGS
    ).aggregate(value=Coalesce(Sum("base_total_cost"), ZERO, output_field=DECIMAL))["value"]
    aftersales = Refund.objects.filter(case__company_id=company_id, status="paid").aggregate(
        value=Coalesce(Sum("base_amount"), ZERO, output_field=DECIMAL)
    )["value"]
    return {
        "sales_original_currency_total": revenue,
        "base_cogs": -cogs,
        "base_refunds": aftersales,
        "base_margin_before_other_costs": revenue + cogs - aftersales,
    }


REPORT_RUNNERS = {
    "dashboard": dashboard,
    "inventory": inventory_summary,
    "receivables": lambda **kwargs: arap_aging(kind="receivable", **kwargs),
    "payables": lambda **kwargs: arap_aging(kind="payable", **kwargs),
    "procurement": procurement_summary,
    "production": production_summary,
    "profitability": profitability,
}


def run_report(*, report_type: str, company_id: int, filters: dict[str, object]):  # type: ignore[no-untyped-def]
    runner = REPORT_RUNNERS.get(report_type)
    if runner is None:
        raise ValueError(f"不支持的报表类型：{report_type}")
    accepted = {"as_of"} if report_type in {"receivables", "payables"} else set()
    unknown = set(filters) - accepted
    if unknown:
        raise ValueError(f"报表包含不支持的筛选条件：{', '.join(sorted(unknown))}")
    normalized = dict(filters)
    if "as_of" in normalized and isinstance(normalized["as_of"], str):
        normalized["as_of"] = date.fromisoformat(normalized["as_of"])
    return runner(company_id=company_id, **normalized)


def result_digest(result: object) -> str:
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()

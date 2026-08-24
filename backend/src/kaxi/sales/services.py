from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from kaxi.inventory.reservation_services import reserve_inventory
from kaxi.sales.credit_services import commit_credit
from kaxi.sales.models import (
    SalesOrder,
    SalesOrderConfirmation,
    SalesOrderLine,
    SalesOrderStatusHistory,
)
from kaxi.shared.outbox_service import append_outbox_event


class OrderVersionConflictError(ValueError):
    pass


@dataclass(frozen=True)
class LinePriceInput:
    line_id: int
    unit_price: Decimal
    price_source: str
    snapshot: dict[str, object]


@dataclass(frozen=True)
class StockAllocationInput:
    line_id: int
    balance_id: int
    quantity: Decimal
    reservation_no: str


@dataclass(frozen=True)
class OrderConfirmationResult:
    order_id: int
    version_no: int
    status: str
    repeated: bool


@dataclass(frozen=True)
class CreditInput:
    account_id: int
    amount: Decimal
    at: datetime
    approval_id: int | None = None


def _target_status(lines: list[SalesOrderLine]) -> str:
    if all(line.reserved_qty == line.ordered_qty for line in lines):
        return SalesOrder.Status.ALLOCATED
    if any(line.reserved_qty > 0 for line in lines):
        return SalesOrder.Status.ALLOCATING
    return SalesOrder.Status.CONFIRMED


@transaction.atomic
def confirm_sales_order(
    *,
    order_id: int,
    expected_version: int,
    idempotency_key: str,
    prices: list[LinePriceInput],
    allocations: list[StockAllocationInput],
    credit: CreditInput | None = None,
) -> OrderConfirmationResult:
    order = SalesOrder.objects.select_for_update().select_related("company").get(pk=order_id)
    repeated = SalesOrderConfirmation.objects.filter(
        company=order.company, idempotency_key=idempotency_key
    ).first()
    if repeated is not None:
        return OrderConfirmationResult(
            order.pk, repeated.confirmed_version, repeated.result_status, True
        )
    if order.status != SalesOrder.Status.DRAFT:
        raise ValueError("只有草稿订单可以确认")
    if order.version_no != expected_version:
        raise OrderVersionConflictError("订单版本已变化，请刷新后重试")

    lines = list(SalesOrderLine.objects.select_for_update().filter(order=order).order_by("id"))
    if not lines:
        raise ValueError("订单至少需要一个明细行")
    lines_by_id = {line.pk: line for line in lines}
    prices_by_line = {item.line_id: item for item in prices}
    if set(prices_by_line) != set(lines_by_id):
        raise ValueError("确认时必须为每个订单行提供价格快照")
    for line in lines:
        price = prices_by_line[line.pk]
        if price.unit_price < 0:
            raise ValueError("订单单价不能为负数")
        line.unit_price = price.unit_price
        line.line_total = price.unit_price * line.ordered_qty
        line.price_source = price.price_source
        line.price_snapshot = price.snapshot
        line.row_version += 1
        line.save(
            update_fields=[
                "unit_price",
                "line_total",
                "price_source",
                "price_snapshot",
                "row_version",
                "updated_at",
            ]
        )

    allocation_totals: dict[int, Decimal] = {}
    for allocation in allocations:
        if allocation.line_id not in lines_by_id:
            raise ValueError("库存分配包含非本订单明细")
        allocation_totals[allocation.line_id] = (
            allocation_totals.get(allocation.line_id, Decimal(0)) + allocation.quantity
        )
    for line_id, quantity in allocation_totals.items():
        if quantity > lines_by_id[line_id].ordered_qty:
            raise ValueError("库存分配数量不能超过订购数量")
    for allocation in sorted(allocations, key=lambda item: (item.balance_id, item.line_id)):
        reserve_inventory(
            balance_id=allocation.balance_id,
            order_line_id=allocation.line_id,
            quantity=allocation.quantity,
            reservation_no=allocation.reservation_no,
        )

    if credit is not None:
        commit_credit(
            account_id=credit.account_id,
            order=order,
            amount=credit.amount,
            at=credit.at,
            approval_id=credit.approval_id,
        )

    lines = list(SalesOrderLine.objects.filter(order=order).order_by("id"))
    old_status = order.status
    order.status = _target_status(lines)
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    SalesOrderStatusHistory.objects.create(
        order=order, from_status=old_status, to_status=order.status, reason="order_confirmation"
    )
    SalesOrderConfirmation.objects.create(
        company=order.company,
        order=order,
        idempotency_key=idempotency_key,
        confirmed_version=order.version_no,
        result_status=order.status,
    )
    append_outbox_event(
        company=order.company,
        aggregate_type="sales_order",
        aggregate_id=str(order.pk),
        aggregate_version=order.version_no,
        event_type="ORDER_CONFIRMED",
        payload={
            "order_id": order.pk,
            "order_no": order.order_no,
            "status": order.status,
            "version_no": order.version_no,
        },
    )
    return OrderConfirmationResult(order.pk, order.version_no, order.status, False)

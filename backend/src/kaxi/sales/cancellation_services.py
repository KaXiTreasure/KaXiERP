from django.db import transaction

from kaxi.inventory.models import InventoryReservation
from kaxi.inventory.reservation_services import release_reservation
from kaxi.sales.credit_services import release_credit
from kaxi.sales.models import (
    CreditCommitment,
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatusHistory,
)
from kaxi.shared.outbox_service import append_outbox_event


@transaction.atomic
def cancel_unshipped_order(*, order_id: int, reason: str) -> SalesOrder:
    order = SalesOrder.objects.select_for_update().select_related("company").get(pk=order_id)
    if order.status in {SalesOrder.Status.COMPLETED, SalesOrder.Status.CANCELLED}:
        raise ValueError("当前订单状态不允许取消")
    lines = list(SalesOrderLine.objects.select_for_update().filter(order=order).order_by("id"))
    if any(line.shipped_qty > 0 for line in lines):
        raise ValueError("已有发货的订单必须进入售后流程")
    reservations = InventoryReservation.objects.filter(
        sales_order_line__order=order, status=InventoryReservation.Status.ACTIVE
    ).order_by("id")
    for reservation in reservations:
        if reservation.remaining_qty > 0:
            release_reservation(reservation_id=reservation.pk, quantity=reservation.remaining_qty)
    commitments = CreditCommitment.objects.filter(
        order=order, status=CreditCommitment.Status.ACTIVE
    ).order_by("id")
    for commitment in commitments:
        remaining = commitment.amount - commitment.released_amount - commitment.converted_amount
        if remaining > 0:
            release_credit(commitment_id=commitment.pk, amount=remaining)
    for line in lines:
        line.cancelled_qty = line.ordered_qty
        line.row_version += 1
        line.save(update_fields=["cancelled_qty", "row_version", "updated_at"])
    old_status = order.status
    order.status = SalesOrder.Status.CANCELLED
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    SalesOrderStatusHistory.objects.create(
        order=order, from_status=old_status, to_status=order.status, reason=reason
    )
    append_outbox_event(
        company=order.company,
        aggregate_type="sales_order",
        aggregate_id=str(order.pk),
        aggregate_version=order.version_no,
        event_type="ORDER_CANCELLED",
        payload={"order_id": order.pk, "reason": reason},
    )
    return order

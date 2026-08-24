from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction

from kaxi.inventory.models import InventoryBalance, InventoryLedger, InventoryReservation
from kaxi.sales.models import SalesOrderLine
from kaxi.shared.outbox_service import append_outbox_event


@dataclass(frozen=True)
class ReservationResult:
    reservation_id: int
    remaining_qty: Decimal
    repeated: bool = False


@transaction.atomic
def reserve_inventory(
    *, balance_id: int, order_line_id: int, quantity: Decimal, reservation_no: str
) -> ReservationResult:
    if quantity <= 0:
        raise ValueError("预留数量必须大于零")
    line = SalesOrderLine.objects.select_for_update().select_related("order").get(pk=order_line_id)
    balance = (
        InventoryBalance.objects.select_for_update().select_related("company").get(pk=balance_id)
    )
    existing = InventoryReservation.objects.filter(
        company=balance.company, reservation_no=reservation_no
    ).first()
    if existing is not None:
        return ReservationResult(existing.pk, existing.remaining_qty, True)
    if balance.sku_id != line.sku_id or balance.company_id != line.order.company_id:
        raise ValueError("订单行与库存余额的公司或SKU不一致")
    if balance.physical_free_qty < quantity:
        raise ValueError("物理空闲库存不足")
    balance.reserved_qty += quantity
    balance.row_version += 1
    balance.save(update_fields=["reserved_qty", "row_version", "updated_at"])
    line.reserved_qty += quantity
    line.row_version += 1
    line.save(update_fields=["reserved_qty", "row_version", "updated_at"])
    reservation = InventoryReservation.objects.create(
        company=balance.company,
        reservation_no=reservation_no,
        sales_order_line=line,
        balance=balance,
        reserved_qty=quantity,
    )
    append_outbox_event(
        company=balance.company,
        aggregate_type="inventory_reservation",
        aggregate_id=str(reservation.pk),
        aggregate_version=reservation.row_version,
        event_type="INVENTORY_RESERVED",
        payload={"reservation_id": reservation.pk, "quantity": str(quantity)},
    )
    return ReservationResult(reservation.pk, quantity)


@transaction.atomic
def release_reservation(*, reservation_id: int, quantity: Decimal) -> ReservationResult:
    if quantity <= 0:
        raise ValueError("释放数量必须大于零")
    reservation = (
        InventoryReservation.objects.select_for_update()
        .select_related("company")
        .get(pk=reservation_id)
    )
    line = SalesOrderLine.objects.select_for_update().get(pk=reservation.sales_order_line_id)
    balance = InventoryBalance.objects.select_for_update().get(pk=reservation.balance_id)
    if quantity > reservation.remaining_qty:
        raise ValueError("释放数量超过预留剩余量")
    reservation.released_qty += quantity
    reservation.status = (
        InventoryReservation.Status.RELEASED
        if reservation.remaining_qty == 0
        else InventoryReservation.Status.ACTIVE
    )
    reservation.row_version += 1
    reservation.save(update_fields=["released_qty", "status", "row_version", "updated_at"])
    balance.reserved_qty -= quantity
    balance.row_version += 1
    balance.save(update_fields=["reserved_qty", "row_version", "updated_at"])
    line.reserved_qty -= quantity
    line.row_version += 1
    line.save(update_fields=["reserved_qty", "row_version", "updated_at"])
    append_outbox_event(
        company=reservation.company,
        aggregate_type="inventory_reservation",
        aggregate_id=str(reservation.pk),
        aggregate_version=reservation.row_version,
        event_type="INVENTORY_RESERVATION_RELEASED",
        payload={"reservation_id": reservation.pk, "quantity": str(quantity)},
    )
    return ReservationResult(reservation.pk, reservation.remaining_qty)


@transaction.atomic
def consume_reservation(
    *,
    reservation_id: int,
    quantity: Decimal,
    idempotency_key: str,
    reference_type: str,
    reference_id: int,
    reference_no: str,
    operator: object,
    occurred_at: datetime,
) -> ReservationResult:
    if quantity <= 0:
        raise ValueError("消耗数量必须大于零")
    existing = InventoryLedger.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        reservation = InventoryReservation.objects.get(pk=reservation_id)
        return ReservationResult(reservation.pk, reservation.remaining_qty, True)
    reservation = (
        InventoryReservation.objects.select_for_update()
        .select_related("company")
        .get(pk=reservation_id)
    )
    line = SalesOrderLine.objects.select_for_update().get(pk=reservation.sales_order_line_id)
    balance = InventoryBalance.objects.select_for_update().get(pk=reservation.balance_id)
    if quantity > reservation.remaining_qty:
        raise ValueError("消耗数量超过预留剩余量")
    before_qty = balance.on_hand_qty
    balance.on_hand_qty -= quantity
    balance.reserved_qty -= quantity
    balance.row_version += 1
    balance.save(update_fields=["on_hand_qty", "reserved_qty", "row_version", "updated_at"])
    reservation.consumed_qty += quantity
    reservation.status = (
        InventoryReservation.Status.CONSUMED
        if reservation.remaining_qty == 0
        else InventoryReservation.Status.ACTIVE
    )
    reservation.row_version += 1
    reservation.save(update_fields=["consumed_qty", "status", "row_version", "updated_at"])
    line.reserved_qty -= quantity
    line.shipped_qty += quantity
    line.row_version += 1
    line.save(update_fields=["reserved_qty", "shipped_qty", "row_version", "updated_at"])
    user_model = get_user_model()
    if not isinstance(operator, user_model):
        raise TypeError("operator必须是系统用户")
    InventoryLedger.objects.create(
        company=reservation.company,
        occurred_at=occurred_at,
        sku_id=balance.sku_id,
        warehouse_id=balance.warehouse_id,
        location_id=balance.location_id,
        inventory_status_id=balance.inventory_status_id,
        lot_id=balance.lot_id,
        transaction_type="ship",
        quantity_delta=-quantity,
        before_qty=before_qty,
        after_qty=balance.on_hand_qty,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_no=reference_no,
        idempotency_key=idempotency_key,
        operator=operator,
    )
    append_outbox_event(
        company=reservation.company,
        aggregate_type="inventory_reservation",
        aggregate_id=str(reservation.pk),
        aggregate_version=reservation.row_version,
        event_type="INVENTORY_RESERVATION_CONSUMED",
        payload={"reservation_id": reservation.pk, "quantity": str(quantity)},
    )
    return ReservationResult(reservation.pk, reservation.remaining_qty)

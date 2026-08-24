from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction

from kaxi.inventory.models import InventoryBalance, InventoryLedger
from kaxi.shared.outbox_service import append_outbox_event


class InsufficientInventoryError(ValueError):
    pass


@dataclass(frozen=True)
class StockMovementResult:
    ledger_id: int
    balance_id: int
    before_qty: Decimal
    after_qty: Decimal
    repeated: bool


@transaction.atomic
def adjust_on_hand(
    *,
    balance_id: int,
    quantity_delta: Decimal,
    transaction_type: str,
    reference_type: str,
    reference_id: int,
    reference_no: str,
    idempotency_key: str,
    operator: object,
    occurred_at: datetime,
) -> StockMovementResult:
    if quantity_delta == 0:
        raise ValueError("库存变化数量不能为零")

    balance = (
        InventoryBalance.objects.select_for_update().select_related("company").get(pk=balance_id)
    )
    existing = InventoryLedger.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return StockMovementResult(
            existing.pk, balance.pk, existing.before_qty, existing.after_qty, True
        )

    before_qty = balance.on_hand_qty
    after_qty = before_qty + quantity_delta
    if after_qty < balance.reserved_qty + balance.locked_qty:
        raise InsufficientInventoryError("库存调整后不能低于已预留量或锁定量")

    balance.on_hand_qty = after_qty
    balance.row_version += 1
    balance.save(update_fields=["on_hand_qty", "row_version", "updated_at"])
    user_model = get_user_model()
    if not isinstance(operator, user_model):
        raise TypeError("operator必须是系统用户")
    ledger = InventoryLedger.objects.create(
        company=balance.company,
        occurred_at=occurred_at,
        sku_id=balance.sku_id,
        warehouse_id=balance.warehouse_id,
        location_id=balance.location_id,
        inventory_status_id=balance.inventory_status_id,
        lot_id=balance.lot_id,
        transaction_type=transaction_type,
        quantity_delta=quantity_delta,
        before_qty=before_qty,
        after_qty=after_qty,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_no=reference_no,
        idempotency_key=idempotency_key,
        operator=operator,
    )
    append_outbox_event(
        company=balance.company,
        aggregate_type="inventory_balance",
        aggregate_id=str(balance.pk),
        aggregate_version=balance.row_version,
        event_type="INVENTORY_ON_HAND_CHANGED",
        payload={
            "balance_id": balance.pk,
            "ledger_id": ledger.pk,
            "quantity_delta": str(quantity_delta),
            "after_qty": str(after_qty),
        },
    )
    return StockMovementResult(ledger.pk, balance.pk, before_qty, after_qty, False)

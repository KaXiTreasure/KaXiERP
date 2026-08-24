from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from kaxi.identity.models import User
from kaxi.inventory.models import (
    InventoryBalance,
    StockCount,
    StockCountLine,
    StockTransfer,
    StockTransferLine,
)
from kaxi.inventory.services import adjust_on_hand
from kaxi.shared.outbox_service import append_outbox_event


@dataclass(frozen=True)
class OperationResult:
    object_id: int
    status: str
    version_no: int
    repeated: bool = False


def _validate_transfer_line(line: StockTransferLine) -> None:
    transfer = line.transfer
    source = line.source_balance
    destination = line.destination_balance
    if (
        source.company_id != transfer.company_id
        or destination.company_id != transfer.company_id
        or source.warehouse_id != transfer.source_warehouse_id
        or destination.warehouse_id != transfer.destination_warehouse_id
        or source.sku_id != line.sku_id
        or destination.sku_id != line.sku_id
    ):
        raise ValueError("调拨行库存余额与公司、SKU或调出/调入仓不一致")
    if (
        source.inventory_status_id != destination.inventory_status_id
        or source.lot_id != destination.lot_id
    ):
        raise ValueError("调拨前后库存状态和批次必须一致")


@transaction.atomic
def approve_stock_transfer(*, transfer_id: int, expected_version: int) -> OperationResult:
    transfer = (
        StockTransfer.objects.select_for_update().select_related("company").get(pk=transfer_id)
    )
    if transfer.version_no != expected_version:
        raise ValueError("调拨单版本已变化，请刷新后重试")
    if transfer.status != StockTransfer.Status.DRAFT:
        raise ValueError("只有草稿调拨单可以批准")
    lines = list(
        StockTransferLine.objects.select_related(
            "transfer", "source_balance", "destination_balance"
        ).filter(transfer=transfer)
    )
    if not lines:
        raise ValueError("调拨单至少需要一个明细行")
    for line in lines:
        _validate_transfer_line(line)
    transfer.status = StockTransfer.Status.APPROVED
    transfer.version_no += 1
    transfer.row_version += 1
    transfer.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    append_outbox_event(
        company=transfer.company,
        aggregate_type="stock_transfer",
        aggregate_id=str(transfer.pk),
        aggregate_version=transfer.version_no,
        event_type="STOCK_TRANSFER_APPROVED",
        payload={"transfer_id": transfer.pk},
    )
    return OperationResult(transfer.pk, transfer.status, transfer.version_no)


@transaction.atomic
def dispatch_stock_transfer(
    *, transfer_id: int, idempotency_key: str, operator: User, occurred_at: datetime
) -> OperationResult:
    transfer = (
        StockTransfer.objects.select_for_update().select_related("company").get(pk=transfer_id)
    )
    if transfer.dispatch_idempotency_key == idempotency_key:
        return OperationResult(transfer.pk, transfer.status, transfer.version_no, True)
    if StockTransfer.objects.filter(dispatch_idempotency_key=idempotency_key).exists():
        raise ValueError("调拨发出幂等键已被其他单据使用")
    if transfer.status != StockTransfer.Status.APPROVED:
        raise ValueError("只有已批准调拨单可以发出")
    lines = list(
        StockTransferLine.objects.select_for_update()
        .select_related("transfer", "source_balance", "destination_balance")
        .filter(transfer=transfer)
        .order_by("source_balance_id", "id")
    )
    for line in lines:
        _validate_transfer_line(line)
        adjust_on_hand(
            balance_id=line.source_balance_id,
            quantity_delta=-line.requested_qty,
            transaction_type="transfer_dispatch",
            reference_type="stock_transfer",
            reference_id=transfer.pk,
            reference_no=transfer.transfer_no,
            idempotency_key=f"{idempotency_key}:line:{line.pk}",
            operator=operator,
            occurred_at=occurred_at,
        )
        line.dispatched_qty = line.requested_qty
        line.row_version += 1
        line.save(update_fields=["dispatched_qty", "row_version", "updated_at"])
    transfer.status = StockTransfer.Status.IN_TRANSIT
    transfer.dispatch_idempotency_key = idempotency_key
    transfer.dispatched_at = occurred_at
    transfer.dispatched_by = operator
    transfer.version_no += 1
    transfer.row_version += 1
    transfer.save(
        update_fields=[
            "status",
            "dispatch_idempotency_key",
            "dispatched_at",
            "dispatched_by",
            "version_no",
            "row_version",
            "updated_at",
        ]
    )
    append_outbox_event(
        company=transfer.company,
        aggregate_type="stock_transfer",
        aggregate_id=str(transfer.pk),
        aggregate_version=transfer.version_no,
        event_type="STOCK_TRANSFER_DISPATCHED",
        payload={"transfer_id": transfer.pk},
    )
    return OperationResult(transfer.pk, transfer.status, transfer.version_no)


@transaction.atomic
def receive_stock_transfer(
    *,
    transfer_id: int,
    received_quantities: dict[int, Decimal],
    idempotency_key: str,
    operator: User,
    occurred_at: datetime,
) -> OperationResult:
    transfer = (
        StockTransfer.objects.select_for_update().select_related("company").get(pk=transfer_id)
    )
    if transfer.receipt_idempotency_key == idempotency_key:
        return OperationResult(transfer.pk, transfer.status, transfer.version_no, True)
    if StockTransfer.objects.filter(receipt_idempotency_key=idempotency_key).exists():
        raise ValueError("调拨接收幂等键已被其他单据使用")
    if transfer.status != StockTransfer.Status.IN_TRANSIT:
        raise ValueError("只有在途调拨单可以接收")
    lines = list(
        StockTransferLine.objects.select_for_update()
        .select_related("transfer", "source_balance", "destination_balance")
        .filter(transfer=transfer)
        .order_by("destination_balance_id", "id")
    )
    if set(received_quantities) != {line.pk for line in lines}:
        raise ValueError("必须提交调拨单全部明细的实收数量")
    for line in lines:
        _validate_transfer_line(line)
        quantity = received_quantities[line.pk]
        if quantity < 0 or quantity > line.dispatched_qty:
            raise ValueError("实收数量不能为负数或超过发出数量")
        if quantity > 0:
            adjust_on_hand(
                balance_id=line.destination_balance_id,
                quantity_delta=quantity,
                transaction_type="transfer_receipt",
                reference_type="stock_transfer",
                reference_id=transfer.pk,
                reference_no=transfer.transfer_no,
                idempotency_key=f"{idempotency_key}:line:{line.pk}",
                operator=operator,
                occurred_at=occurred_at,
            )
        line.received_qty = quantity
        line.difference_qty = quantity - line.dispatched_qty
        line.row_version += 1
        line.save(update_fields=["received_qty", "difference_qty", "row_version", "updated_at"])
    transfer.status = StockTransfer.Status.COMPLETED
    transfer.receipt_idempotency_key = idempotency_key
    transfer.received_at = occurred_at
    transfer.received_by = operator
    transfer.version_no += 1
    transfer.row_version += 1
    transfer.save(
        update_fields=[
            "status",
            "receipt_idempotency_key",
            "received_at",
            "received_by",
            "version_no",
            "row_version",
            "updated_at",
        ]
    )
    append_outbox_event(
        company=transfer.company,
        aggregate_type="stock_transfer",
        aggregate_id=str(transfer.pk),
        aggregate_version=transfer.version_no,
        event_type="STOCK_TRANSFER_RECEIVED",
        payload={
            "transfer_id": transfer.pk,
            "has_difference": any(line.difference_qty != 0 for line in lines),
        },
    )
    return OperationResult(transfer.pk, transfer.status, transfer.version_no)


@transaction.atomic
def start_stock_count(
    *, count_id: int, balance_ids: list[int], expected_version: int, started_at: datetime
) -> OperationResult:
    count = StockCount.objects.select_for_update().select_related("company").get(pk=count_id)
    if count.version_no != expected_version:
        raise ValueError("盘点单版本已变化，请刷新后重试")
    if count.status != StockCount.Status.DRAFT or count.lines.exists():
        raise ValueError("只有空白草稿盘点单可以开始")
    if not balance_ids or len(balance_ids) != len(set(balance_ids)):
        raise ValueError("盘点库存余额不能为空或重复")
    balances = list(
        InventoryBalance.objects.select_for_update().filter(pk__in=balance_ids).order_by("id")
    )
    if len(balances) != len(balance_ids):
        raise ValueError("盘点包含不存在的库存余额")
    for line_no, balance in enumerate(balances, start=1):
        if balance.company_id != count.company_id or balance.warehouse_id != count.warehouse_id:
            raise ValueError("盘点库存余额必须属于盘点公司和仓库")
        StockCountLine.objects.create(
            count=count, line_no=line_no, balance=balance, book_qty=balance.on_hand_qty
        )
    count.status = StockCount.Status.COUNTING
    count.started_at = started_at
    count.version_no += 1
    count.row_version += 1
    count.save(update_fields=["status", "started_at", "version_no", "row_version", "updated_at"])
    return OperationResult(count.pk, count.status, count.version_no)


@transaction.atomic
def submit_stock_count(
    *, count_id: int, counted_quantities: dict[int, Decimal], submitted_at: datetime
) -> OperationResult:
    count = StockCount.objects.select_for_update().get(pk=count_id)
    if count.status != StockCount.Status.COUNTING:
        raise ValueError("只有盘点中的单据可以提交")
    lines = list(StockCountLine.objects.select_for_update().filter(count=count))
    if set(counted_quantities) != {line.pk for line in lines}:
        raise ValueError("必须提交盘点单全部明细")
    for line in lines:
        quantity = counted_quantities[line.pk]
        if quantity < 0:
            raise ValueError("实盘数量不能为负数")
        line.counted_qty = quantity
        line.difference_qty = quantity - line.book_qty
        line.row_version += 1
        line.save(update_fields=["counted_qty", "difference_qty", "row_version", "updated_at"])
    count.status = StockCount.Status.PENDING_APPROVAL
    count.submitted_at = submitted_at
    count.version_no += 1
    count.row_version += 1
    count.save(update_fields=["status", "submitted_at", "version_no", "row_version", "updated_at"])
    return OperationResult(count.pk, count.status, count.version_no)


@transaction.atomic
def post_stock_count(
    *, count_id: int, idempotency_key: str, operator: User, occurred_at: datetime
) -> OperationResult:
    count = StockCount.objects.select_for_update().select_related("company").get(pk=count_id)
    if count.post_idempotency_key == idempotency_key:
        return OperationResult(count.pk, count.status, count.version_no, True)
    if StockCount.objects.filter(post_idempotency_key=idempotency_key).exists():
        raise ValueError("盘点过账幂等键已被其他单据使用")
    if count.status != StockCount.Status.PENDING_APPROVAL:
        raise ValueError("只有审批中的盘点单可以过账")
    lines = list(
        StockCountLine.objects.select_for_update().filter(count=count).order_by("balance_id")
    )
    for line in lines:
        if line.difference_qty is None:
            raise ValueError("盘点明细尚未完成")
        if line.difference_qty != 0:
            adjust_on_hand(
                balance_id=line.balance_id,
                quantity_delta=line.difference_qty,
                transaction_type="stock_count_adjustment",
                reference_type="stock_count",
                reference_id=count.pk,
                reference_no=count.count_no,
                idempotency_key=f"{idempotency_key}:line:{line.pk}",
                operator=operator,
                occurred_at=occurred_at,
            )
    count.status = StockCount.Status.POSTED
    count.post_idempotency_key = idempotency_key
    count.posted_at = occurred_at
    count.posted_by = operator
    count.version_no += 1
    count.row_version += 1
    count.save(
        update_fields=[
            "status",
            "post_idempotency_key",
            "posted_at",
            "posted_by",
            "version_no",
            "row_version",
            "updated_at",
        ]
    )
    append_outbox_event(
        company=count.company,
        aggregate_type="stock_count",
        aggregate_id=str(count.pk),
        aggregate_version=count.version_no,
        event_type="STOCK_COUNT_POSTED",
        payload={"count_id": count.pk},
    )
    return OperationResult(count.pk, count.status, count.version_no)

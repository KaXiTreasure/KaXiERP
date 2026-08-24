from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance
from kaxi.inventory.services import adjust_on_hand
from kaxi.products.models import ProductSerial, SerialShipmentAssignment, SkuBarcode
from kaxi.sales.fulfillment_services import transition_shipment
from kaxi.sales.models import SalesShipment
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.warehouse.models import WarehouseScanEvent, WarehouseTask, WarehouseTaskLine


def _validate_line(task: WarehouseTask, line: WarehouseTaskLine) -> None:
    if line.sku.company_id != task.company_id:
        raise ValueError("任务行 SKU 必须属于任务公司。")
    if task.task_type == WarehouseTask.TaskType.PUTAWAY:
        if not line.source_balance_id or not line.target_location_id:
            raise ValueError("上架任务行必须指定来源库存和目标库位。")
        if (
            line.source_balance.company_id != task.company_id
            or line.source_balance.warehouse_id != task.warehouse_id
            or line.source_balance.sku_id != line.sku_id
            or line.target_location.warehouse_id != task.warehouse_id
        ):
            raise ValueError("上架任务行的库存、SKU、仓库和目标库位必须一致。")
    else:
        if not line.sales_shipment_line_id or not task.sales_shipment_id:
            raise ValueError("拣货/复核任务行必须关联销售发货明细。")
        shipment_line = line.sales_shipment_line
        if (
            shipment_line.shipment_id != task.sales_shipment_id
            or shipment_line.order_line.sku_id != line.sku_id
            or line.planned_qty != shipment_line.quantity
        ):
            raise ValueError("任务行必须完整匹配销售发货明细。")


@transaction.atomic
def release_task(*, task_id: int, actor: User) -> WarehouseTask:
    task = WarehouseTask.objects.select_for_update().get(pk=task_id)
    if task.status != WarehouseTask.Status.DRAFT:
        raise ValueError("只有草稿仓储任务可以下达。")
    lines = list(WarehouseTaskLine.objects.select_for_update().filter(task=task))
    if not lines:
        raise ValueError("仓储任务至少需要一个明细行。")
    for line in lines:
        _validate_line(task, line)
    if task.task_type == WarehouseTask.TaskType.PICK:
        transition_shipment(
            shipment_id=task.sales_shipment_id,
            expected_version=task.sales_shipment.version_no,
            action="start_picking",
        )
    task.status = WarehouseTask.Status.RELEASED
    task.released_at = timezone.now()
    task.row_version += 1
    task.save()
    append_outbox_event(
        company=task.company,
        aggregate_type="warehouse_task",
        aggregate_id=str(task.pk),
        aggregate_version=task.row_version,
        event_type="warehouse.task.released",
        payload={"task_id": task.pk, "task_type": task.task_type, "actor_id": actor.pk},
    )
    return task


def _scan_value_matches(line: WarehouseTaskLine, value: str) -> bool:
    if line.sku.is_serialized:
        serial = ProductSerial.objects.filter(
            company_id=line.task.company_id, sku_id=line.sku_id, serial_no=value
        ).first()
        if not serial:
            return False
        if line.task.task_type in {WarehouseTask.TaskType.PICK, WarehouseTask.TaskType.PACK}:
            return SerialShipmentAssignment.objects.filter(
                shipment_line_id=line.sales_shipment_line_id, serial=serial
            ).exists()
        return True
    normalized = value.strip()
    return (
        normalized == line.sku.sku_code
        or SkuBarcode.objects.filter(
            company_id=line.task.company_id,
            sku_id=line.sku_id,
            normalized_value=normalized,
            is_active=True,
        ).exists()
    )


@transaction.atomic
def record_scan(
    *,
    task_id: int,
    line_id: int,
    scanned_value: str,
    quantity: Decimal,
    idempotency_key: str,
    actor: User,
    occurred_at: datetime,
    device_id: str = "",
) -> WarehouseScanEvent:
    existing = WarehouseScanEvent.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    task = WarehouseTask.objects.select_for_update().get(pk=task_id)
    existing = WarehouseScanEvent.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    if task.status not in {WarehouseTask.Status.RELEASED, WarehouseTask.Status.IN_PROGRESS}:
        raise ValueError("只有已下达或执行中的任务可以扫码。")
    if task.assigned_to_id and task.assigned_to_id != actor.pk and not actor.is_superuser:
        raise ValueError("任务已分配给其他操作人。")
    if quantity <= 0:
        raise ValueError("扫码数量必须大于零。")
    line = (
        WarehouseTaskLine.objects.select_for_update()
        .select_related("task", "sku")
        .get(pk=line_id, task=task)
    )
    if line.sku.is_serialized and quantity != 1:
        raise ValueError("单件追踪 SKU 每次只能扫描一个编号。")
    if not _scan_value_matches(line, scanned_value):
        raise ValueError("扫描值与任务行 SKU、条码或单件编号不匹配。")
    if line.scanned_qty + quantity > line.planned_qty:
        raise ValueError("累计扫码数量不能超过计划数量。")
    event = WarehouseScanEvent.objects.create(
        task=task,
        line=line,
        scan_type="serial" if line.sku.is_serialized else "sku_or_barcode",
        scanned_value=scanned_value,
        quantity=quantity,
        idempotency_key=idempotency_key,
        operator=actor,
        occurred_at=occurred_at,
        device_id=device_id,
    )
    line.scanned_qty += quantity
    line.row_version += 1
    line.save(update_fields=["scanned_qty", "row_version", "updated_at"])
    if task.status == WarehouseTask.Status.RELEASED:
        task.status = WarehouseTask.Status.IN_PROGRESS
        task.started_at = occurred_at
        task.row_version += 1
        task.save()
    return event


@transaction.atomic
def complete_task(*, task_id: int, actor: User, completed_at: datetime) -> WarehouseTask:
    task = WarehouseTask.objects.select_for_update().get(pk=task_id)
    if task.status not in {WarehouseTask.Status.RELEASED, WarehouseTask.Status.IN_PROGRESS}:
        raise ValueError("当前仓储任务不能完成。")
    lines = list(
        WarehouseTaskLine.objects.select_for_update()
        .filter(task=task)
        .order_by("source_balance_id", "id")
    )
    if any(line.scanned_qty != line.planned_qty for line in lines):
        raise ValueError("所有任务行必须完成计划数量扫码。")
    if task.task_type == WarehouseTask.TaskType.PUTAWAY:
        for line in lines:
            source = InventoryBalance.objects.select_for_update().get(pk=line.source_balance_id)
            target, _ = InventoryBalance.objects.get_or_create(
                company_id=source.company_id,
                sku_id=source.sku_id,
                warehouse_id=source.warehouse_id,
                location_id=line.target_location_id,
                inventory_status_id=source.inventory_status_id,
                lot_id=source.lot_id,
            )
            adjust_on_hand(
                balance_id=source.pk,
                quantity_delta=-line.planned_qty,
                transaction_type="putaway_out",
                reference_type="warehouse_task",
                reference_id=task.pk,
                reference_no=task.task_no,
                idempotency_key=f"wms-task:{task.pk}:line:{line.pk}:out",
                operator=actor,
                occurred_at=completed_at,
            )
            adjust_on_hand(
                balance_id=target.pk,
                quantity_delta=line.planned_qty,
                transaction_type="putaway_in",
                reference_type="warehouse_task",
                reference_id=task.pk,
                reference_no=task.task_no,
                idempotency_key=f"wms-task:{task.pk}:line:{line.pk}:in",
                operator=actor,
                occurred_at=completed_at,
            )
    elif task.task_type == WarehouseTask.TaskType.PICK:
        shipment = SalesShipment.objects.select_for_update().get(pk=task.sales_shipment_id)
        transition_shipment(
            shipment_id=shipment.pk,
            expected_version=shipment.version_no,
            action="complete_picking",
        )
    else:
        shipment = SalesShipment.objects.select_for_update().get(pk=task.sales_shipment_id)
        transition_shipment(
            shipment_id=shipment.pk,
            expected_version=shipment.version_no,
            action="verify",
        )
    for line in lines:
        line.completed_qty = line.planned_qty
        line.row_version += 1
        line.save(update_fields=["completed_qty", "row_version", "updated_at"])
    task.status = WarehouseTask.Status.COMPLETED
    task.completed_at = completed_at
    task.row_version += 1
    task.save()
    append_outbox_event(
        company=task.company,
        aggregate_type="warehouse_task",
        aggregate_id=str(task.pk),
        aggregate_version=task.row_version,
        event_type="warehouse.task.completed",
        payload={"task_id": task.pk, "task_type": task.task_type},
    )
    return task

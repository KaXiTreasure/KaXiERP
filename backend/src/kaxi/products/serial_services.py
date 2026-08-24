from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from kaxi.identity.models import User
from kaxi.manufacturing.models import ProductionOrder
from kaxi.products.models import (
    LimitedEditionPool,
    ProductSerial,
    SerialProductionAttempt,
    SerialReservation,
    SerialShipmentAssignment,
    SerialStatusHistory,
)
from kaxi.sales.models import SalesOrderLine, SalesShipmentLine
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.warehouse.models import WarehouseLocation


@dataclass(frozen=True)
class SerialOperationResult:
    object_id: int
    status: str
    repeated: bool = False


def _record_status(
    serial: ProductSerial,
    *,
    previous: str,
    reason: str,
    actor: User | None,
    reference_type: str = "",
    reference_id: int | None = None,
) -> None:
    SerialStatusHistory.objects.create(
        serial=serial,
        from_status=previous,
        to_status=serial.status,
        reason=reason,
        actor=actor,
        reference_type=reference_type,
        reference_id=reference_id,
    )


def _validate_numbering_rule(
    rule: dict[str, object],
) -> tuple[int, int, str, str, set[int], list[tuple[int, int]], int | None]:
    start = rule.get("start", 1)
    width = rule.get("width", 1)
    prefix = rule.get("prefix", "")
    suffix = rule.get("suffix", "")
    maximum = rule.get("maximum")
    excluded = rule.get("excluded_numbers", [])
    ranges = rule.get("excluded_ranges", [])
    if (
        not isinstance(start, int)
        or start < 0
        or not isinstance(width, int)
        or not 1 <= width <= 30
    ):
        raise ValueError("编号规则start必须为非负整数，width必须为1到30")
    if not isinstance(prefix, str) or not isinstance(suffix, str) or len(prefix) + len(suffix) > 80:
        raise ValueError("编号规则前后缀无效或过长")
    if maximum is not None and (not isinstance(maximum, int) or maximum < start):
        raise ValueError("编号规则maximum必须是不小于start的整数")
    if not isinstance(excluded, list) or any(
        not isinstance(value, int) or value < 0 for value in excluded
    ):
        raise ValueError("excluded_numbers必须是非负整数数组")
    parsed_ranges: list[tuple[int, int]] = []
    if not isinstance(ranges, list):
        raise ValueError("excluded_ranges必须是二维整数数组")
    for value in ranges:
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, int) for item in value)
            or value[0] < 0
            or value[1] < value[0]
        ):
            raise ValueError("excluded_ranges包含无效区间")
        parsed_ranges.append((value[0], value[1]))
    return start, width, prefix, suffix, set(excluded), parsed_ranges, maximum


def _is_excluded(value: int, excluded: set[int], ranges: list[tuple[int, int]]) -> bool:
    return value in excluded or any(start <= value <= end for start, end in ranges)


@transaction.atomic
def activate_serial_pool(*, pool_id: int) -> SerialOperationResult:
    pool = (
        LimitedEditionPool.objects.select_for_update()
        .select_related("company", "sku")
        .get(pk=pool_id)
    )
    if pool.status != LimitedEditionPool.Status.DRAFT:
        raise ValueError("只有草稿限量池可以启用")
    if not pool.sku.is_serialized or not pool.sku.is_limited_edition:
        raise ValueError("限量池SKU必须同时启用单件编号和限量标记")
    start, *_ = _validate_numbering_rule(pool.numbering_rule)
    pool.next_sort_value = start
    pool.status = LimitedEditionPool.Status.ACTIVE
    pool.row_version += 1
    pool.save(update_fields=["next_sort_value", "status", "row_version", "updated_at"])
    return SerialOperationResult(pool.pk, pool.status)


@transaction.atomic
def generate_serials(*, pool_id: int, quantity: int, actor: User) -> list[ProductSerial]:
    pool = (
        LimitedEditionPool.objects.select_for_update()
        .select_related("company", "sku")
        .get(pk=pool_id)
    )
    if pool.status != LimitedEditionPool.Status.ACTIVE:
        raise ValueError("只有启用中的限量池可以生成编号")
    if quantity <= 0 or pool.allocated_count + quantity > pool.total_limit:
        raise ValueError("生成数量必须大于零且不能超过剩余限量")
    start, width, prefix, suffix, excluded, ranges, maximum = _validate_numbering_rule(
        pool.numbering_rule
    )
    candidate = max(pool.next_sort_value, start)
    serials: list[ProductSerial] = []
    while len(serials) < quantity:
        if maximum is not None and candidate > maximum:
            raise ValueError("编号规则可用范围已耗尽")
        if not _is_excluded(candidate, excluded, ranges):
            serial_no = f"{prefix}{candidate:0{width}d}{suffix}"
            serial = ProductSerial.objects.create(
                company=pool.company,
                limited_pool=pool,
                sku=pool.sku,
                serial_no=serial_no,
                serial_sort_value=candidate,
                status=ProductSerial.Status.WAITING_PRODUCTION,
            )
            _record_status(
                serial,
                previous=ProductSerial.Status.PLANNED,
                reason="限量池生成",
                actor=actor,
                reference_type="limited_edition_pool",
                reference_id=pool.pk,
            )
            serials.append(serial)
        candidate += 1
    pool.next_sort_value = candidate
    pool.allocated_count += quantity
    pool.row_version += 1
    pool.save(update_fields=["next_sort_value", "allocated_count", "row_version", "updated_at"])
    append_outbox_event(
        company=pool.company,
        aggregate_type="limited_edition_pool",
        aggregate_id=str(pool.pk),
        aggregate_version=pool.row_version,
        event_type="PRODUCT_SERIALS_GENERATED",
        payload={"pool_id": pool.pk, "serial_ids": [serial.pk for serial in serials]},
    )
    return serials


@transaction.atomic
def start_serial_production(
    *,
    serial_id: int,
    production_order_id: int,
    idempotency_key: str,
    started_at: datetime,
    actor: User,
) -> SerialOperationResult:
    serial = ProductSerial.objects.select_for_update().select_related("company").get(pk=serial_id)
    existing = SerialProductionAttempt.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.serial_id != serial.pk:
            raise ValueError("生产尝试幂等键已被其他编号使用")
        return SerialOperationResult(existing.pk, existing.result, True)
    if serial.status not in {
        ProductSerial.Status.WAITING_PRODUCTION,
        ProductSerial.Status.NG,
        ProductSerial.Status.WAITING_REPRODUCTION,
        ProductSerial.Status.WAITING_REWORK,
    }:
        raise ValueError("当前编号状态不能开始生产")
    order = ProductionOrder.objects.select_for_update().get(pk=production_order_id)
    if order.company_id != serial.company_id or order.product_sku_id != serial.sku_id:
        raise ValueError("编号与生产订单的公司或成品SKU不一致")
    if order.status not in {
        ProductionOrder.Status.RELEASED,
        ProductionOrder.Status.IN_PROGRESS,
        ProductionOrder.Status.PARTIALLY_COMPLETED,
    }:
        raise ValueError("生产订单当前状态不能绑定编号生产")
    last_attempt = (
        SerialProductionAttempt.objects.filter(serial=serial).order_by("-attempt_no").first()
    )
    attempt_no = (last_attempt.attempt_no if last_attempt else 0) + 1
    attempt = SerialProductionAttempt.objects.create(
        serial=serial,
        production_order=order,
        attempt_no=attempt_no,
        started_at=started_at,
        previous_attempt=last_attempt,
        idempotency_key=idempotency_key,
    )
    previous = serial.status
    serial.status = ProductSerial.Status.IN_PRODUCTION
    serial.current_production_order = order
    serial.row_version += 1
    serial.save(update_fields=["status", "current_production_order", "row_version", "updated_at"])
    _record_status(
        serial,
        previous=previous,
        reason=f"开始第{attempt_no}次生产",
        actor=actor,
        reference_type="serial_production_attempt",
        reference_id=attempt.pk,
    )
    return SerialOperationResult(attempt.pk, attempt.result)


@transaction.atomic
def complete_serial_production(
    *,
    attempt_id: int,
    result: str,
    completed_at: datetime,
    actor: User,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    ng_reason: str = "",
    inspection_reference: str = "",
) -> SerialOperationResult:
    attempt = (
        SerialProductionAttempt.objects.select_for_update()
        .select_related("production_order")
        .get(pk=attempt_id)
    )
    serial = ProductSerial.objects.select_for_update().get(pk=attempt.serial_id)
    if attempt.result != SerialProductionAttempt.Result.IN_PROGRESS:
        return SerialOperationResult(attempt.pk, attempt.result, True)
    if serial.status != ProductSerial.Status.IN_PRODUCTION:
        raise ValueError("编号不在生产中，不能完成尝试")
    if result not in {SerialProductionAttempt.Result.GOOD, SerialProductionAttempt.Result.NG}:
        raise ValueError("生产尝试结果只能为good或ng")
    if result == SerialProductionAttempt.Result.GOOD:
        if warehouse_id is None or location_id is None:
            raise ValueError("合格编号必须提供入库仓库和库位")
        location = WarehouseLocation.objects.select_related("warehouse").get(pk=location_id)
        if (
            location.warehouse_id != warehouse_id
            or location.warehouse.company_id != serial.company_id
            or warehouse_id != attempt.production_order.warehouse_id
        ):
            raise ValueError("编号入库仓库或库位与生产订单不一致")
        serial.status = ProductSerial.Status.IN_STOCK
        serial.warehouse_id = warehouse_id
        serial.location_id = location_id
        if serial.limited_pool_id:
            pool = LimitedEditionPool.objects.select_for_update().get(pk=serial.limited_pool_id)
            pool.produced_good_count += 1
            pool.row_version += 1
            pool.save(update_fields=["produced_good_count", "row_version", "updated_at"])
    else:
        if not ng_reason:
            raise ValueError("NG结果必须填写原因")
        serial.status = ProductSerial.Status.NG
        serial.warehouse = None
        serial.location = None
    previous = ProductSerial.Status.IN_PRODUCTION
    serial.row_version += 1
    serial.save(update_fields=["status", "warehouse", "location", "row_version", "updated_at"])
    attempt.result = result
    attempt.completed_at = completed_at
    attempt.ng_reason = ng_reason
    attempt.inspection_reference = inspection_reference
    attempt.row_version += 1
    attempt.save(
        update_fields=[
            "result",
            "completed_at",
            "ng_reason",
            "inspection_reference",
            "row_version",
            "updated_at",
        ]
    )
    _record_status(
        serial,
        previous=previous,
        reason="生产合格" if result == SerialProductionAttempt.Result.GOOD else ng_reason,
        actor=actor,
        reference_type="serial_production_attempt",
        reference_id=attempt.pk,
    )
    append_outbox_event(
        company=serial.company,
        aggregate_type="product_serial",
        aggregate_id=str(serial.pk),
        aggregate_version=serial.row_version,
        event_type="PRODUCT_SERIAL_PRODUCTION_COMPLETED",
        payload={"serial_id": serial.pk, "attempt_id": attempt.pk, "result": result},
    )
    return SerialOperationResult(attempt.pk, attempt.result)


@transaction.atomic
def dispose_ng_serial(
    *, serial_id: int, action: str, reason: str, actor: User
) -> SerialOperationResult:
    serial = ProductSerial.objects.select_for_update().get(pk=serial_id)
    if serial.status != ProductSerial.Status.NG or not reason:
        raise ValueError("只有NG编号可处置且必须填写原因")
    targets = {
        "rework": ProductSerial.Status.WAITING_REWORK,
        "reproduce": ProductSerial.Status.WAITING_REPRODUCTION,
        "scrap": ProductSerial.Status.SCRAPPED,
        "void": ProductSerial.Status.VOID,
    }
    target = targets.get(action)
    if target is None:
        raise ValueError("不支持的NG处置方式")
    previous = serial.status
    serial.status = target
    serial.row_version += 1
    serial.save(update_fields=["status", "row_version", "updated_at"])
    _record_status(serial, previous=previous, reason=reason, actor=actor)
    return SerialOperationResult(serial.pk, serial.status)


@transaction.atomic
def reserve_product_serial(
    *,
    order_line_id: int,
    idempotency_key: str,
    allocation_type: str,
    actor: User,
    serial_id: int | None = None,
    expires_at: datetime | None = None,
) -> SerialOperationResult:
    existing = SerialReservation.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return SerialOperationResult(existing.pk, existing.status, True)
    line = (
        SalesOrderLine.objects.select_for_update()
        .select_related("order", "sku")
        .get(pk=order_line_id)
    )
    if not line.sku.is_serialized:
        raise ValueError("只有单件编号SKU可以分配编号")
    active_count = SerialReservation.objects.filter(
        sales_order_line=line, status=SerialReservation.Status.ACTIVE
    ).count()
    remaining_units = line.ordered_qty - line.shipped_qty - line.cancelled_qty
    if remaining_units != remaining_units.to_integral_value() or active_count >= int(
        remaining_units
    ):
        raise ValueError("订单行没有可分配的整数单件数量")
    if allocation_type == SerialReservation.AllocationType.SPECIFIED:
        if serial_id is None:
            raise ValueError("指定编号分配必须提供serial_id")
        serial = ProductSerial.objects.select_for_update().get(pk=serial_id)
    elif allocation_type == SerialReservation.AllocationType.AUTOMATIC:
        serial = (
            ProductSerial.objects.select_for_update(skip_locked=True)
            .filter(company=line.order.company, sku=line.sku, status=ProductSerial.Status.IN_STOCK)
            .order_by("serial_sort_value", "id")
            .first()
        )
        if serial is None:
            raise ValueError("没有可自动分配的在库编号")
    else:
        raise ValueError("编号分配类型无效")
    if (
        serial.company_id != line.order.company_id
        or serial.sku_id != line.sku_id
        or serial.status != ProductSerial.Status.IN_STOCK
    ):
        raise ValueError("指定编号与订单公司/SKU不一致或当前不可售")
    reservation = SerialReservation.objects.create(
        serial=serial,
        sales_order_line=line,
        allocation_type=allocation_type,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
    )
    previous = serial.status
    serial.status = ProductSerial.Status.RESERVED
    serial.current_sales_order = line.order
    serial.row_version += 1
    serial.save(update_fields=["status", "current_sales_order", "row_version", "updated_at"])
    _record_status(
        serial,
        previous=previous,
        reason="销售订单编号预留",
        actor=actor,
        reference_type="serial_reservation",
        reference_id=reservation.pk,
    )
    return SerialOperationResult(reservation.pk, reservation.status)


@transaction.atomic
def release_product_serial(
    *, reservation_id: int, reason: str, actor: User
) -> SerialOperationResult:
    reservation = SerialReservation.objects.select_for_update().get(pk=reservation_id)
    serial = ProductSerial.objects.select_for_update().get(pk=reservation.serial_id)
    if reservation.status != SerialReservation.Status.ACTIVE:
        return SerialOperationResult(reservation.pk, reservation.status, True)
    if serial.status not in {ProductSerial.Status.RESERVED, ProductSerial.Status.PICKED}:
        raise ValueError("已发货或不可用编号不能释放")
    if hasattr(reservation, "shipment_assignment"):
        raise ValueError("已关联发货单的编号必须先取消发货分配")
    reservation.status = SerialReservation.Status.RELEASED
    reservation.released_reason = reason
    reservation.row_version += 1
    reservation.save(update_fields=["status", "released_reason", "row_version", "updated_at"])
    previous = serial.status
    serial.status = ProductSerial.Status.IN_STOCK
    serial.current_sales_order = None
    serial.row_version += 1
    serial.save(update_fields=["status", "current_sales_order", "row_version", "updated_at"])
    _record_status(serial, previous=previous, reason=reason, actor=actor)
    return SerialOperationResult(reservation.pk, reservation.status)


@transaction.atomic
def assign_serial_to_shipment(
    *, reservation_id: int, shipment_line_id: int, actor: User
) -> SerialOperationResult:
    reservation = (
        SerialReservation.objects.select_for_update()
        .select_related("serial")
        .get(pk=reservation_id)
    )
    existing = SerialShipmentAssignment.objects.filter(reservation=reservation).first()
    if existing is not None:
        if existing.shipment_line_id != shipment_line_id:
            raise ValueError("编号预留已分配给其他发货行")
        return SerialOperationResult(existing.pk, existing.status, True)
    shipment_line = (
        SalesShipmentLine.objects.select_for_update()
        .select_related("shipment", "order_line__sku")
        .get(pk=shipment_line_id)
    )
    if (
        reservation.status != SerialReservation.Status.ACTIVE
        or reservation.sales_order_line_id != shipment_line.order_line_id
        or shipment_line.shipment.status != shipment_line.shipment.Status.DRAFT
    ):
        raise ValueError("编号预留与发货行不一致或当前状态不能分配")
    assigned_count = SerialShipmentAssignment.objects.filter(shipment_line=shipment_line).count()
    if (
        shipment_line.quantity != shipment_line.quantity.to_integral_value()
        or assigned_count >= int(shipment_line.quantity)
    ):
        raise ValueError("发货行编号分配已满或数量不是整数")
    assignment = SerialShipmentAssignment.objects.create(
        serial=reservation.serial,
        reservation=reservation,
        shipment_line=shipment_line,
    )
    _record_status(
        reservation.serial,
        previous=reservation.serial.status,
        reason="编号关联发货单",
        actor=actor,
        reference_type="sales_shipment_line",
        reference_id=shipment_line.pk,
    )
    return SerialOperationResult(assignment.pk, assignment.status)

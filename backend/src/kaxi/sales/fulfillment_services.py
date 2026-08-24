from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from kaxi.identity.models import User
from kaxi.inventory.reservation_services import consume_reservation
from kaxi.products.models import (
    ProductSerial,
    SerialReservation,
    SerialShipmentAssignment,
    SerialStatusHistory,
)
from kaxi.sales.models import (
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatusHistory,
    SalesShipment,
    SalesShipmentLine,
)
from kaxi.shared.outbox_service import append_outbox_event


@dataclass(frozen=True)
class ShipmentResult:
    shipment_id: int
    status: str
    version_no: int
    order_status: str
    repeated: bool = False


@transaction.atomic
def transition_shipment(*, shipment_id: int, expected_version: int, action: str) -> ShipmentResult:
    shipment = (
        SalesShipment.objects.select_for_update()
        .select_related("company", "order")
        .get(pk=shipment_id)
    )
    if shipment.version_no != expected_version:
        raise ValueError("发货单版本已变化，请刷新后重试")
    transitions = {
        "start_picking": (SalesShipment.Status.DRAFT, SalesShipment.Status.PICKING),
        "complete_picking": (SalesShipment.Status.PICKING, SalesShipment.Status.PICKED),
        "verify": (SalesShipment.Status.PICKED, SalesShipment.Status.VERIFIED),
    }
    transition = transitions.get(action)
    if transition is None or shipment.status != transition[0]:
        raise ValueError("发货单状态不允许执行此操作")
    lines = list(
        SalesShipmentLine.objects.select_for_update()
        .select_related("order_line__sku")
        .filter(shipment=shipment)
    )
    if not lines:
        raise ValueError("发货单至少需要一个明细行")
    if action == "complete_picking":
        for line in lines:
            if line.order_line.sku.is_serialized:
                if line.quantity != line.quantity.to_integral_value():
                    raise ValueError("单件编号发货行数量必须是整数")
                assignments = list(
                    SerialShipmentAssignment.objects.select_for_update()
                    .select_related("serial")
                    .filter(shipment_line=line)
                )
                if len(assignments) != int(line.quantity):
                    raise ValueError("单件编号发货行必须完整分配每一个编号")
                for assignment in assignments:
                    if assignment.status != SerialShipmentAssignment.Status.ASSIGNED:
                        raise ValueError("编号发货分配状态异常")
                    serial = assignment.serial
                    previous = serial.status
                    serial.status = ProductSerial.Status.PICKED
                    serial.row_version += 1
                    serial.save(update_fields=["status", "row_version", "updated_at"])
                    assignment.status = SerialShipmentAssignment.Status.PICKED
                    assignment.row_version += 1
                    assignment.save(update_fields=["status", "row_version", "updated_at"])
                    SerialStatusHistory.objects.create(
                        serial=serial,
                        from_status=previous,
                        to_status=serial.status,
                        reason="仓库完成拣货",
                        reference_type="sales_shipment",
                        reference_id=shipment.pk,
                    )
            line.picked_qty = line.quantity
            line.row_version += 1
            line.save(update_fields=["picked_qty", "row_version", "updated_at"])
    shipment.status = transition[1]
    shipment.version_no += 1
    shipment.row_version += 1
    shipment.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    order = SalesOrder.objects.select_for_update().get(pk=shipment.order_id)
    if action == "start_picking" and order.status in {
        SalesOrder.Status.CONFIRMED,
        SalesOrder.Status.ALLOCATING,
        SalesOrder.Status.ALLOCATED,
    }:
        previous = order.status
        order.status = SalesOrder.Status.FULFILLING
        order.version_no += 1
        order.row_version += 1
        order.save(update_fields=["status", "version_no", "row_version", "updated_at"])
        SalesOrderStatusHistory.objects.create(
            order=order, from_status=previous, to_status=order.status, reason="开始拣货"
        )
    append_outbox_event(
        company=shipment.company,
        aggregate_type="sales_shipment",
        aggregate_id=str(shipment.pk),
        aggregate_version=shipment.version_no,
        event_type=f"SALES_SHIPMENT_{action.upper()}",
        payload={"shipment_id": shipment.pk, "order_id": order.pk},
    )
    return ShipmentResult(shipment.pk, shipment.status, shipment.version_no, order.status)


@transaction.atomic
def ship_sales_shipment(
    *, shipment_id: int, idempotency_key: str, operator: User, shipped_at: datetime
) -> ShipmentResult:
    shipment = (
        SalesShipment.objects.select_for_update()
        .select_related("company", "order")
        .get(pk=shipment_id)
    )
    if shipment.ship_idempotency_key == idempotency_key:
        return ShipmentResult(
            shipment.pk, shipment.status, shipment.version_no, shipment.order.status, True
        )
    if SalesShipment.objects.filter(ship_idempotency_key=idempotency_key).exists():
        raise ValueError("发货幂等键已被其他发货单使用")
    if shipment.status != SalesShipment.Status.VERIFIED:
        raise ValueError("只有已复核发货单可以正式发货")
    lines = list(
        SalesShipmentLine.objects.select_for_update()
        .select_related("reservation")
        .filter(shipment=shipment)
        .order_by("reservation__balance_id", "id")
    )
    for line in lines:
        if line.order_line.sku.is_serialized:
            assignments = list(
                SerialShipmentAssignment.objects.select_for_update()
                .select_related("serial", "reservation")
                .filter(shipment_line=line)
            )
            if line.quantity != line.quantity.to_integral_value() or len(assignments) != int(
                line.quantity
            ):
                raise ValueError("单件编号发货行的编号分配不完整")
            if any(item.status != SerialShipmentAssignment.Status.PICKED for item in assignments):
                raise ValueError("单件编号尚未完成拣货")
        consume_reservation(
            reservation_id=line.reservation_id,
            quantity=line.quantity,
            idempotency_key=f"{idempotency_key}:line:{line.pk}",
            reference_type="sales_shipment",
            reference_id=shipment.pk,
            reference_no=shipment.shipment_no,
            operator=operator,
            occurred_at=shipped_at,
        )
        line.shipped_qty = line.quantity
        line.row_version += 1
        line.save(update_fields=["shipped_qty", "row_version", "updated_at"])
        if line.order_line.sku.is_serialized:
            for assignment in assignments:
                serial = assignment.serial
                previous = serial.status
                serial.status = ProductSerial.Status.SHIPPED
                serial.current_customer = shipment.order.customer
                serial.current_sales_order = shipment.order
                serial.warehouse = None
                serial.location = None
                serial.row_version += 1
                serial.save(
                    update_fields=[
                        "status",
                        "current_customer",
                        "current_sales_order",
                        "warehouse",
                        "location",
                        "row_version",
                        "updated_at",
                    ]
                )
                assignment.status = SerialShipmentAssignment.Status.SHIPPED
                assignment.row_version += 1
                assignment.save(update_fields=["status", "row_version", "updated_at"])
                serial_reservation = assignment.reservation
                serial_reservation.status = SerialReservation.Status.CONSUMED
                serial_reservation.row_version += 1
                serial_reservation.save(update_fields=["status", "row_version", "updated_at"])
                SerialStatusHistory.objects.create(
                    serial=serial,
                    from_status=previous,
                    to_status=serial.status,
                    reason="销售发货",
                    reference_type="sales_shipment",
                    reference_id=shipment.pk,
                    actor=operator,
                )

    order = SalesOrder.objects.select_for_update().get(pk=shipment.order_id)
    order_lines = list(SalesOrderLine.objects.select_for_update().filter(order=order))
    previous_order_status = order.status
    if all(line.shipped_qty + line.cancelled_qty == line.ordered_qty for line in order_lines):
        order.status = SalesOrder.Status.COMPLETED
    else:
        order.status = SalesOrder.Status.FULFILLING
    order.version_no += 1
    order.row_version += 1
    order.save(update_fields=["status", "version_no", "row_version", "updated_at"])
    if order.status != previous_order_status:
        SalesOrderStatusHistory.objects.create(
            order=order,
            from_status=previous_order_status,
            to_status=order.status,
            reason="销售发货",
        )

    shipment.status = SalesShipment.Status.SHIPPED
    shipment.ship_idempotency_key = idempotency_key
    shipment.shipped_at = shipped_at
    shipment.shipped_by = operator
    shipment.version_no += 1
    shipment.row_version += 1
    shipment.save(
        update_fields=[
            "status",
            "ship_idempotency_key",
            "shipped_at",
            "shipped_by",
            "version_no",
            "row_version",
            "updated_at",
        ]
    )
    append_outbox_event(
        company=shipment.company,
        aggregate_type="sales_shipment",
        aggregate_id=str(shipment.pk),
        aggregate_version=shipment.version_no,
        event_type="SALES_SHIPMENT_SHIPPED",
        payload={"shipment_id": shipment.pk, "order_id": order.pk},
    )
    return ShipmentResult(shipment.pk, shipment.status, shipment.version_no, order.status)

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from django.db import close_old_connections

from kaxi.identity.models import User
from kaxi.inventory.models import (
    InventoryBalance,
    InventoryLot,
    InventoryReservation,
    InventoryStatus,
)
from kaxi.manufacturing.models import BillOfMaterial, ProductionOrder
from kaxi.master_data.models import Address, Company, Currency, Party, Region, UnitOfMeasure
from kaxi.products.models import (
    LimitedEditionPool,
    ProductCategory,
    ProductSerial,
    ProductSku,
    ProductSpu,
    SerialProductionAttempt,
    SerialReservation,
    SerialShipmentAssignment,
)
from kaxi.products.serial_services import (
    activate_serial_pool,
    assign_serial_to_shipment,
    complete_serial_production,
    dispose_ng_serial,
    generate_serials,
    reserve_product_serial,
    start_serial_production,
)
from kaxi.sales.fulfillment_services import ship_sales_shipment, transition_shipment
from kaxi.sales.models import (
    SalesChannel,
    SalesOrder,
    SalesOrderLine,
    SalesShipment,
    SalesShipmentLine,
)
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation


@pytest.mark.django_db(transaction=True)
def test_limited_serial_ng_reproduction_reservation_and_shipment_trace() -> None:
    now = datetime.now(UTC)
    currency = Currency.objects.create(code="CNY", name="人民币")
    region = Region.objects.create(code="CN", name_zh="中国")
    company = Company.objects.create(
        company_code="SER", legal_name="编号测试", display_name="编号测试", base_currency=currency
    )
    user = User.objects.create_user(
        username="serial-user", display_name="编号操作员", company=company
    )
    uom = UnitOfMeasure.objects.create(
        uom_code="SER-PCS", name_zh="件", symbol="件", dimension=UnitOfMeasure.Dimension.COUNT
    )
    category = ProductCategory.objects.create(company=company, category_code="SER", name_zh="编号")
    product_spu = ProductSpu.objects.create(
        company=company, spu_code="SER-FG-SPU", name_zh="限量成品", category=category
    )
    product = ProductSku.objects.create(
        company=company,
        sku_code="SER-FG",
        spu=product_spu,
        name_zh="限量成品",
        base_uom=uom,
        is_serialized=True,
        is_limited_edition=True,
    )
    warehouse = Warehouse.objects.create(company=company, warehouse_code="SER-WH", name="编号仓")
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="A", name="A", area_type="storage"
    )
    location = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="A-1",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    bom = BillOfMaterial.objects.create(
        company=company,
        bom_no="SER-BOM",
        product_sku=product,
        bom_type=BillOfMaterial.BomType.PRODUCTION,
        version="1",
        output_qty=1,
        valid_from=now,
        status=BillOfMaterial.Status.ACTIVE,
        approval_reference="TEST",
    )
    production_order = ProductionOrder.objects.create(
        company=company,
        production_order_no="SER-MO",
        product_sku=product,
        bom=bom,
        planned_qty=1,
        warehouse=warehouse,
        status=ProductionOrder.Status.RELEASED,
    )
    pool = LimitedEditionPool.objects.create(
        company=company,
        sku=product,
        edition_code="ED-2026",
        total_limit=5,
        numbering_rule={"start": 1, "width": 3, "excluded_numbers": [4]},
    )
    activate_serial_pool(pool_id=pool.pk)
    serials = generate_serials(pool_id=pool.pk, quantity=5, actor=user)
    assert [serial.serial_no for serial in serials] == ["001", "002", "003", "005", "006"]

    first = start_serial_production(
        serial_id=serials[0].pk,
        production_order_id=production_order.pk,
        idempotency_key="serial-attempt-1",
        started_at=now,
        actor=user,
    )
    complete_serial_production(
        attempt_id=first.object_id,
        result=SerialProductionAttempt.Result.NG,
        completed_at=now,
        actor=user,
        ng_reason="表面缺陷",
    )
    dispose_ng_serial(serial_id=serials[0].pk, action="reproduce", reason="批准重生产", actor=user)
    second = start_serial_production(
        serial_id=serials[0].pk,
        production_order_id=production_order.pk,
        idempotency_key="serial-attempt-2",
        started_at=now,
        actor=user,
    )
    complete_serial_production(
        attempt_id=second.object_id,
        result=SerialProductionAttempt.Result.GOOD,
        completed_at=now,
        actor=user,
        warehouse_id=warehouse.pk,
        location_id=location.pk,
    )
    pool.refresh_from_db()
    serial = ProductSerial.objects.get(pk=serials[0].pk)
    assert pool.allocated_count == 5
    assert pool.produced_good_count == 1
    assert serial.production_attempts.count() == 2
    assert serial.status == ProductSerial.Status.IN_STOCK

    customer = Party.objects.create(
        company=company,
        party_no="SER-CUS",
        party_type=Party.PartyType.ORGANIZATION,
        legal_name="客户",
        display_name="客户",
        country_region=region,
        default_currency=currency,
        status=Party.Status.ACTIVE,
    )
    address = Address.objects.create(
        party=customer,
        address_code="A1",
        address_type="shipping",
        country_region=region,
        address_line1="地址",
    )
    channel = SalesChannel.objects.create(company=company, channel_code="SER-DIRECT", name="直营")
    order = SalesOrder.objects.create(
        company=company,
        order_no="SER-SO",
        customer=customer,
        channel=channel,
        shipping_address=address,
        currency=currency,
        order_date=now,
        status=SalesOrder.Status.ALLOCATED,
    )
    order_line = SalesOrderLine.objects.create(
        order=order,
        line_no=1,
        sku=product,
        ordered_qty=1,
        reserved_qty=1,
        unit_price=100,
        line_total=100,
        price_source="test",
    )
    status = InventoryStatus.objects.create(company=company, status_code="NORMAL", name="正常")
    lot = InventoryLot.objects.create(company=company, sku=product, lot_no="SER-LOT")
    balance = InventoryBalance.objects.create(
        company=company,
        sku=product,
        warehouse=warehouse,
        location=location,
        inventory_status=status,
        lot=lot,
        on_hand_qty=1,
        reserved_qty=1,
    )
    inventory_reservation = InventoryReservation.objects.create(
        company=company,
        reservation_no="SER-INV-RES",
        sales_order_line=order_line,
        balance=balance,
        reserved_qty=1,
    )
    serial_reservation_result = reserve_product_serial(
        order_line_id=order_line.pk,
        serial_id=serial.pk,
        allocation_type=SerialReservation.AllocationType.SPECIFIED,
        idempotency_key="serial-sales-res",
        actor=user,
    )
    shipment = SalesShipment.objects.create(
        company=company,
        shipment_no="SER-SHP",
        order=order,
        warehouse=warehouse,
        carrier_code="TEST",
        tracking_no="SER-TRACK",
    )
    shipment_line = SalesShipmentLine.objects.create(
        shipment=shipment,
        line_no=1,
        order_line=order_line,
        reservation=inventory_reservation,
        quantity=1,
    )
    assign_serial_to_shipment(
        reservation_id=serial_reservation_result.object_id,
        shipment_line_id=shipment_line.pk,
        actor=user,
    )
    transition_shipment(shipment_id=shipment.pk, expected_version=1, action="start_picking")
    transition_shipment(shipment_id=shipment.pk, expected_version=2, action="complete_picking")
    transition_shipment(shipment_id=shipment.pk, expected_version=3, action="verify")
    ship_sales_shipment(
        shipment_id=shipment.pk, idempotency_key="serial-ship", operator=user, shipped_at=now
    )
    serial.refresh_from_db()
    serial_reservation = SerialReservation.objects.get(pk=serial_reservation_result.object_id)
    assignment = SerialShipmentAssignment.objects.get(serial=serial)
    assert serial.status == ProductSerial.Status.SHIPPED
    assert serial.current_customer_id == customer.pk
    assert serial_reservation.status == SerialReservation.Status.CONSUMED
    assert assignment.status == SerialShipmentAssignment.Status.SHIPPED
    assert serial.status_history.count() >= 7

    concurrent_pool = LimitedEditionPool.objects.create(
        company=company,
        sku=product,
        edition_code="ED-CONCURRENT",
        total_limit=10,
        numbering_rule={"start": 100, "width": 3},
    )
    activate_serial_pool(pool_id=concurrent_pool.pk)

    def generate_batch() -> list[str]:
        close_old_connections()
        try:
            return [
                item.serial_no
                for item in generate_serials(pool_id=concurrent_pool.pk, quantity=5, actor=user)
            ]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        batches = list(executor.map(lambda _: generate_batch(), range(2)))
    generated = [serial_no for batch in batches for serial_no in batch]
    concurrent_pool.refresh_from_db()
    assert len(generated) == len(set(generated)) == 10
    assert concurrent_pool.allocated_count == 10

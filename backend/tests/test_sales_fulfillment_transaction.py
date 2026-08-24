from datetime import UTC, datetime

import pytest

from kaxi.identity.models import User
from kaxi.inventory.models import (
    InventoryBalance,
    InventoryLot,
    InventoryReservation,
    InventoryStatus,
)
from kaxi.master_data.models import Address, Company, Currency, Party, Region, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
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
def test_pick_verify_ship_consumes_reservation_once_and_completes_order() -> None:
    currency = Currency.objects.create(code="CNY", name="人民币")
    region = Region.objects.create(code="CN", name_zh="中国")
    company = Company.objects.create(
        company_code="SHIP", legal_name="发货测试", display_name="发货测试", base_currency=currency
    )
    user = User.objects.create_user(username="ship-user", display_name="发货员", company=company)
    customer = Party.objects.create(
        company=company,
        party_no="CUS-1",
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
        address_line1="测试地址",
    )
    uom = UnitOfMeasure.objects.create(
        uom_code="SHIP-PCS", name_zh="件", symbol="件", dimension=UnitOfMeasure.Dimension.COUNT
    )
    category = ProductCategory.objects.create(company=company, category_code="SHIP", name_zh="测试")
    spu = ProductSpu.objects.create(
        company=company, spu_code="SHIP-SPU", name_zh="测试", category=category
    )
    sku = ProductSku.objects.create(
        company=company, sku_code="SHIP-SKU", spu=spu, name_zh="测试SKU", base_uom=uom
    )
    warehouse = Warehouse.objects.create(company=company, warehouse_code="SHIP-WH", name="发货仓")
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="A", name="A", area_type="storage"
    )
    location = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="A-1",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    inventory_status = InventoryStatus.objects.create(
        company=company, status_code="NORMAL", name="正常"
    )
    lot = InventoryLot.objects.create(company=company, sku=sku, lot_no="SHIP-LOT")
    balance = InventoryBalance.objects.create(
        company=company,
        sku=sku,
        warehouse=warehouse,
        location=location,
        inventory_status=inventory_status,
        lot=lot,
        on_hand_qty=4,
        reserved_qty=4,
    )
    channel = SalesChannel.objects.create(company=company, channel_code="DIRECT", name="直营")
    order = SalesOrder.objects.create(
        company=company,
        order_no="SO-SHIP-1",
        customer=customer,
        channel=channel,
        shipping_address=address,
        currency=currency,
        order_date=datetime.now(UTC),
        status=SalesOrder.Status.ALLOCATED,
    )
    order_line = SalesOrderLine.objects.create(
        order=order,
        line_no=1,
        sku=sku,
        ordered_qty=4,
        reserved_qty=4,
        unit_price=10,
        line_total=40,
        price_source="test",
    )
    reservation = InventoryReservation.objects.create(
        company=company,
        reservation_no="RES-SHIP-1",
        sales_order_line=order_line,
        balance=balance,
        reserved_qty=4,
    )
    shipment = SalesShipment.objects.create(
        company=company,
        shipment_no="SHP-1",
        order=order,
        warehouse=warehouse,
        carrier_code="TEST",
        tracking_no="TRACK-1",
    )
    SalesShipmentLine.objects.create(
        shipment=shipment, line_no=1, order_line=order_line, reservation=reservation, quantity=4
    )

    transition_shipment(shipment_id=shipment.pk, expected_version=1, action="start_picking")
    transition_shipment(shipment_id=shipment.pk, expected_version=2, action="complete_picking")
    transition_shipment(shipment_id=shipment.pk, expected_version=3, action="verify")
    result = ship_sales_shipment(
        shipment_id=shipment.pk,
        idempotency_key="ship-idem-1",
        operator=user,
        shipped_at=datetime.now(UTC),
    )
    balance.refresh_from_db()
    reservation.refresh_from_db()
    order.refresh_from_db()
    assert result.status == SalesShipment.Status.SHIPPED
    assert balance.on_hand_qty == 0 and balance.reserved_qty == 0
    assert reservation.status == InventoryReservation.Status.CONSUMED
    assert order.status == SalesOrder.Status.COMPLETED

    repeated = ship_sales_shipment(
        shipment_id=shipment.pk,
        idempotency_key="ship-idem-1",
        operator=user,
        shipped_at=datetime.now(UTC),
    )
    balance.refresh_from_db()
    assert repeated.repeated is True
    assert balance.on_hand_qty == 0

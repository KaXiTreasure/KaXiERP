from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance, InventoryLedger, InventoryLot, InventoryStatus
from kaxi.inventory.services import adjust_on_hand
from kaxi.master_data.models import Company, Currency, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
from kaxi.shared.outbox import OutboxEvent
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation


@pytest.mark.django_db(transaction=True)
def test_stock_adjustment_is_atomic_idempotent_and_emits_outbox() -> None:
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="KAXI", legal_name="KAXI Test", display_name="KAXI", base_currency=currency
    )
    user = User.objects.create_user(username="stock-test", display_name="库存测试")
    uom = UnitOfMeasure.objects.create(
        uom_code="PCS", name_zh="件", symbol="件", dimension=UnitOfMeasure.Dimension.COUNT
    )
    category = ProductCategory.objects.create(company=company, category_code="TEST", name_zh="测试")
    spu = ProductSpu.objects.create(
        company=company, spu_code="SPU-1", name_zh="测试商品", category=category
    )
    sku = ProductSku.objects.create(
        company=company, sku_code="SKU-1", spu=spu, name_zh="测试SKU", base_uom=uom
    )
    warehouse = Warehouse.objects.create(company=company, warehouse_code="WH-1", name="测试仓")
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="A", name="测试区", area_type="storage"
    )
    location = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="A-01",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    inventory_status = InventoryStatus.objects.create(
        company=company, status_code="NORMAL", name="普通"
    )
    lot = InventoryLot.objects.create(
        company=company, sku=sku, lot_no="NO-LOT", is_no_lot_sentinel=True
    )
    balance = InventoryBalance.objects.create(
        company=company,
        sku=sku,
        warehouse=warehouse,
        location=location,
        inventory_status=inventory_status,
        lot=lot,
    )

    first = adjust_on_hand(
        balance_id=balance.pk,
        quantity_delta=Decimal("10"),
        transaction_type="initial_receipt",
        reference_type="test_fixture",
        reference_id=1,
        reference_no="TEST-1",
        idempotency_key="inventory-test-1",
        operator=user,
        occurred_at=datetime.now(UTC),
    )
    repeated = adjust_on_hand(
        balance_id=balance.pk,
        quantity_delta=Decimal("10"),
        transaction_type="initial_receipt",
        reference_type="test_fixture",
        reference_id=1,
        reference_no="TEST-1",
        idempotency_key="inventory-test-1",
        operator=user,
        occurred_at=datetime.now(UTC),
    )

    balance.refresh_from_db()
    assert balance.on_hand_qty == Decimal("10")
    assert first.repeated is False
    assert repeated.repeated is True
    assert InventoryLedger.objects.count() == 1
    assert OutboxEvent.objects.filter(event_type="INVENTORY_ON_HAND_CHANGED").count() == 1

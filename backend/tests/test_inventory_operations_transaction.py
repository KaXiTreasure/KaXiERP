from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kaxi.identity.models import User
from kaxi.inventory.models import (
    InventoryBalance,
    InventoryLot,
    InventoryStatus,
    StockCount,
    StockTransfer,
    StockTransferLine,
)
from kaxi.inventory.operation_services import (
    approve_stock_transfer,
    dispatch_stock_transfer,
    post_stock_count,
    receive_stock_transfer,
    start_stock_count,
    submit_stock_count,
)
from kaxi.inventory.services import adjust_on_hand
from kaxi.master_data.models import Company, Currency, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation


@pytest.mark.django_db(transaction=True)
def test_transfer_in_transit_receipt_difference_and_stock_count_are_atomic() -> None:
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="OPS",
        legal_name="库存作业测试",
        display_name="库存作业",
        base_currency=currency,
    )
    user = User.objects.create_user(username="ops-user", display_name="仓库员", company=company)
    uom = UnitOfMeasure.objects.create(
        uom_code="OPS-PCS", name_zh="件", symbol="件", dimension=UnitOfMeasure.Dimension.COUNT
    )
    category = ProductCategory.objects.create(company=company, category_code="OPS", name_zh="测试")
    spu = ProductSpu.objects.create(
        company=company, spu_code="OPS-SPU", name_zh="测试", category=category
    )
    sku = ProductSku.objects.create(
        company=company, sku_code="OPS-SKU", spu=spu, name_zh="测试SKU", base_uom=uom
    )
    source_warehouse = Warehouse.objects.create(
        company=company, warehouse_code="OPS-S", name="调出仓"
    )
    destination_warehouse = Warehouse.objects.create(
        company=company, warehouse_code="OPS-D", name="调入仓"
    )
    source_area = WarehouseArea.objects.create(
        warehouse=source_warehouse, area_code="A", name="A", area_type="storage"
    )
    destination_area = WarehouseArea.objects.create(
        warehouse=destination_warehouse, area_code="A", name="A", area_type="storage"
    )
    source_location = WarehouseLocation.objects.create(
        warehouse=source_warehouse,
        area=source_area,
        location_code="A-1",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    destination_location = WarehouseLocation.objects.create(
        warehouse=destination_warehouse,
        area=destination_area,
        location_code="A-1",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    inventory_status = InventoryStatus.objects.create(
        company=company, status_code="NORMAL", name="正常"
    )
    lot = InventoryLot.objects.create(company=company, sku=sku, lot_no="OPS-LOT")
    source = InventoryBalance.objects.create(
        company=company,
        sku=sku,
        warehouse=source_warehouse,
        location=source_location,
        inventory_status=inventory_status,
        lot=lot,
    )
    destination = InventoryBalance.objects.create(
        company=company,
        sku=sku,
        warehouse=destination_warehouse,
        location=destination_location,
        inventory_status=inventory_status,
        lot=lot,
    )
    now = datetime.now(UTC)
    adjust_on_hand(
        balance_id=source.pk,
        quantity_delta=Decimal("10"),
        transaction_type="opening",
        reference_type="test",
        reference_id=1,
        reference_no="OPEN",
        idempotency_key="ops-open",
        operator=user,
        occurred_at=now,
    )
    transfer = StockTransfer.objects.create(
        company=company,
        transfer_no="TR-1",
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
    )
    transfer_line = StockTransferLine.objects.create(
        transfer=transfer,
        line_no=1,
        sku=sku,
        source_balance=source,
        destination_balance=destination,
        requested_qty=Decimal("6"),
    )

    approve_stock_transfer(transfer_id=transfer.pk, expected_version=1)
    dispatch_stock_transfer(
        transfer_id=transfer.pk, idempotency_key="tr-dispatch-1", operator=user, occurred_at=now
    )
    source.refresh_from_db()
    destination.refresh_from_db()
    transfer.refresh_from_db()
    assert source.on_hand_qty == Decimal("4")
    assert destination.on_hand_qty == 0
    assert transfer.status == StockTransfer.Status.IN_TRANSIT

    received = receive_stock_transfer(
        transfer_id=transfer.pk,
        received_quantities={transfer_line.pk: Decimal("5")},
        idempotency_key="tr-receipt-1",
        operator=user,
        occurred_at=now,
    )
    destination.refresh_from_db()
    transfer_line.refresh_from_db()
    assert received.repeated is False
    assert destination.on_hand_qty == Decimal("5")
    assert transfer_line.difference_qty == Decimal("-1")
    repeated = receive_stock_transfer(
        transfer_id=transfer.pk,
        received_quantities={},
        idempotency_key="tr-receipt-1",
        operator=user,
        occurred_at=now,
    )
    assert repeated.repeated is True
    destination.refresh_from_db()
    assert destination.on_hand_qty == Decimal("5")

    count = StockCount.objects.create(
        company=company, count_no="COUNT-1", warehouse=destination_warehouse
    )
    started = start_stock_count(
        count_id=count.pk, balance_ids=[destination.pk], expected_version=1, started_at=now
    )
    line = count.lines.get()
    assert started.status == StockCount.Status.COUNTING
    submit_stock_count(
        count_id=count.pk, counted_quantities={line.pk: Decimal("6")}, submitted_at=now
    )
    posted = post_stock_count(
        count_id=count.pk, idempotency_key="count-post-1", operator=user, occurred_at=now
    )
    destination.refresh_from_db()
    assert posted.status == StockCount.Status.POSTED
    assert destination.on_hand_qty == Decimal("6")

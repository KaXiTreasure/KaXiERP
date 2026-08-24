from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance, InventoryLedger, InventoryLot, InventoryStatus
from kaxi.inventory.services import adjust_on_hand
from kaxi.master_data.models import Company, Currency, Party, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
from kaxi.purchasing.models import GoodsReceipt, PurchaseOrder
from kaxi.warehouse.models import (
    Warehouse,
    WarehouseArea,
    WarehouseLocation,
    WarehouseTask,
    WarehouseTaskLine,
)
from kaxi.warehouse.task_services import complete_task, record_scan, release_task

pytestmark = pytest.mark.django_db(transaction=True)


def test_putaway_scan_is_idempotent_and_moves_inventory_atomically():
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="WMS", legal_name="仓储测试", display_name="仓储测试", base_currency=currency
    )
    user = User.objects.create_user(
        username="wms-operator", display_name="仓库员", company=company, status=User.Status.ACTIVE
    )
    supplier = Party.objects.create(
        company=company,
        party_no="SUP-1",
        party_type=Party.PartyType.ORGANIZATION,
        legal_name="测试供应商",
        display_name="测试供应商",
    )
    uom = UnitOfMeasure.objects.create(
        uom_code="WMS-PC", name_zh="件", symbol="件", dimension=UnitOfMeasure.Dimension.COUNT
    )
    category = ProductCategory.objects.create(company=company, category_code="WMS", name_zh="仓储")
    spu = ProductSpu.objects.create(
        company=company, spu_code="WMS-SPU", name_zh="商品", category=category
    )
    sku = ProductSku.objects.create(
        company=company, sku_code="WMS-SKU", spu=spu, name_zh="商品", base_uom=uom
    )
    warehouse = Warehouse.objects.create(company=company, warehouse_code="WMS", name="主仓")
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="A", name="A区", area_type="storage"
    )
    staging = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="STAGE",
        location_type=WarehouseLocation.LocationType.STAGING,
    )
    storage = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="A-01",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    inventory_status = InventoryStatus.objects.create(
        company=company, status_code="NORMAL", name="正常"
    )
    lot = InventoryLot.objects.create(company=company, sku=sku, lot_no="LOT-1")
    source = InventoryBalance.objects.create(
        company=company,
        sku=sku,
        warehouse=warehouse,
        location=staging,
        inventory_status=inventory_status,
        lot=lot,
    )
    now = datetime.now(UTC)
    adjust_on_hand(
        balance_id=source.pk,
        quantity_delta=Decimal("5"),
        transaction_type="inspection_accept",
        reference_type="test",
        reference_id=1,
        reference_no="OPEN",
        idempotency_key="wms-opening",
        operator=user,
        occurred_at=now,
    )
    order = PurchaseOrder.objects.create(
        company=company,
        purchase_order_no="PO-1",
        supplier=supplier,
        order_date=date.today(),
        currency=currency,
        exchange_rate=1,
        warehouse=warehouse,
    )
    receipt = GoodsReceipt.objects.create(
        company=company,
        receipt_no="GR-1",
        purchase_order=order,
        supplier=supplier,
        warehouse=warehouse,
        received_at=now,
        received_by=user,
    )
    task = WarehouseTask.objects.create(
        company=company,
        warehouse=warehouse,
        task_no="PUT-1",
        task_type=WarehouseTask.TaskType.PUTAWAY,
        goods_receipt=receipt,
        assigned_to=user,
    )
    line = WarehouseTaskLine.objects.create(
        task=task,
        line_no=1,
        sku=sku,
        source_balance=source,
        target_location=storage,
        planned_qty=Decimal("3"),
    )

    release_task(task_id=task.pk, actor=user)
    first = record_scan(
        task_id=task.pk,
        line_id=line.pk,
        scanned_value=sku.sku_code,
        quantity=Decimal("3"),
        idempotency_key="scan-put-1",
        actor=user,
        occurred_at=now,
    )
    repeated = record_scan(
        task_id=task.pk,
        line_id=line.pk,
        scanned_value=sku.sku_code,
        quantity=Decimal("3"),
        idempotency_key="scan-put-1",
        actor=user,
        occurred_at=now,
    )
    assert repeated.pk == first.pk
    line.refresh_from_db()
    assert line.scanned_qty == Decimal("3")

    complete_task(task_id=task.pk, actor=user, completed_at=now)
    source.refresh_from_db()
    target = InventoryBalance.objects.get(location=storage, sku=sku, lot=lot)
    task.refresh_from_db()
    assert source.on_hand_qty == Decimal("2")
    assert target.on_hand_qty == Decimal("3")
    assert task.status == WarehouseTask.Status.COMPLETED
    assert (
        InventoryLedger.objects.filter(
            reference_type="warehouse_task", reference_id=task.pk
        ).count()
        == 2
    )

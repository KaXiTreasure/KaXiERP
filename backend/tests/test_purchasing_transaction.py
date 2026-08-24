from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance, InventoryLedger, InventoryLot, InventoryStatus
from kaxi.master_data.models import Company, Currency, Party, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
from kaxi.purchasing.models import GoodsReceipt, PurchaseOrder, PurchaseOrderLine
from kaxi.purchasing.services import (
    InspectionLineInput,
    ReceiptLineInput,
    complete_purchase_inspection,
    receive_purchase_order,
)
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation


@pytest.mark.django_db(transaction=True)
def test_receipt_does_not_change_stock_and_inspection_posts_accepted_and_rejected() -> None:
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="KAXI-PUR",
        legal_name="KAXI采购测试",
        display_name="KAXI采购测试",
        base_currency=currency,
    )
    user = User.objects.create_user(username="buyer", display_name="采购员", company=company)
    supplier = Party.objects.create(
        company=company,
        party_no="SUP-1",
        party_type=Party.PartyType.ORGANIZATION,
        legal_name="测试供应商",
        display_name="测试供应商",
        default_currency=currency,
        status=Party.Status.ACTIVE,
    )
    uom = UnitOfMeasure.objects.create(
        uom_code="PUR-PCS",
        name_zh="件",
        symbol="件",
        dimension=UnitOfMeasure.Dimension.COUNT,
    )
    category = ProductCategory.objects.create(
        company=company, category_code="PUR-CAT", name_zh="采购测试"
    )
    spu = ProductSpu.objects.create(
        company=company, spu_code="PUR-SPU", name_zh="采购测试商品", category=category
    )
    sku = ProductSku.objects.create(
        company=company, sku_code="PUR-SKU", spu=spu, name_zh="采购SKU", base_uom=uom
    )
    warehouse = Warehouse.objects.create(
        company=company, warehouse_code="PUR-WH", name="采购测试仓"
    )
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="PUR-A", name="采购区", area_type="storage"
    )
    staging = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="PUR-STAGE",
        location_type=WarehouseLocation.LocationType.INSPECTION,
    )
    storage = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="PUR-OK",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    exception = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="PUR-NG",
        location_type=WarehouseLocation.LocationType.EXCEPTION,
    )
    normal_status = InventoryStatus.objects.create(
        company=company, status_code="PUR-NORMAL", name="合格"
    )
    rejected_status = InventoryStatus.objects.create(
        company=company, status_code="PUR-REJECTED", name="不合格"
    )
    lot = InventoryLot.objects.create(company=company, sku=sku, lot_no="PUR-LOT")
    accepted_balance = InventoryBalance.objects.create(
        company=company,
        sku=sku,
        warehouse=warehouse,
        location=storage,
        inventory_status=normal_status,
        lot=lot,
    )
    rejected_balance = InventoryBalance.objects.create(
        company=company,
        sku=sku,
        warehouse=warehouse,
        location=exception,
        inventory_status=rejected_status,
        lot=lot,
    )
    order = PurchaseOrder.objects.create(
        company=company,
        purchase_order_no="PO-1",
        supplier=supplier,
        order_date=date.today(),
        currency=currency,
        exchange_rate=1,
        warehouse=warehouse,
        total=100,
        base_total=100,
        status=PurchaseOrder.Status.ISSUED,
        approval_status="approved",
    )
    order_line = PurchaseOrderLine.objects.create(
        order=order,
        line_no=1,
        sku=sku,
        ordered_qty=10,
        unit_price=10,
        line_total=100,
        base_line_total=100,
    )

    received = receive_purchase_order(
        order_id=order.pk,
        receipt_no="GR-1",
        received_at=datetime.now(UTC),
        received_by=user,
        lines=[ReceiptLineInput(order_line.pk, Decimal("10"), staging.pk, "PUR-LOT")],
    )
    assert received.repeated is False
    assert InventoryLedger.objects.count() == 0
    accepted_balance.refresh_from_db()
    assert accepted_balance.on_hand_qty == 0

    receipt = GoodsReceipt.objects.get(pk=received.receipt_id)
    receipt_line = receipt.lines.get()
    inspected = complete_purchase_inspection(
        receipt_id=receipt.pk,
        inspection_no="QI-1",
        inspector=user,
        completed_at=datetime.now(UTC),
        lines=[
            InspectionLineInput(
                receipt_line.pk,
                Decimal("8"),
                Decimal("2"),
                accepted_balance.pk,
                rejected_balance.pk,
                disposition="return",
            )
        ],
    )
    accepted_balance.refresh_from_db()
    rejected_balance.refresh_from_db()
    order_line.refresh_from_db()
    receipt.refresh_from_db()
    assert inspected.result == "partial"
    assert accepted_balance.on_hand_qty == Decimal("8")
    assert rejected_balance.on_hand_qty == Decimal("2")
    assert order_line.accepted_qty == Decimal("8")
    assert order_line.rejected_qty == Decimal("2")
    assert receipt.status == GoodsReceipt.Status.COMPLETED
    assert InventoryLedger.objects.filter(reference_type="quality_inspection").count() == 2

    repeated = complete_purchase_inspection(
        receipt_id=receipt.pk,
        inspection_no="QI-1",
        inspector=user,
        completed_at=datetime.now(UTC),
        lines=[],
    )
    assert repeated.repeated is True
    assert InventoryLedger.objects.filter(reference_type="quality_inspection").count() == 2

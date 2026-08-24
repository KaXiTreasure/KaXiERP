from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance, InventoryLot, InventoryStatus
from kaxi.manufacturing.models import (
    BillOfMaterial,
    BillOfMaterialItem,
    ProductionConsumption,
    ProductionOrder,
)
from kaxi.manufacturing.services import (
    CompletionConsumptionInput,
    MaterialIssueInput,
    complete_production,
    issue_production_materials,
    transition_bom,
    transition_production_order,
)
from kaxi.master_data.models import Company, Currency, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation


@pytest.mark.django_db(transaction=True)
def test_material_issue_and_completion_preserve_stock_and_consumption_variance() -> None:
    now = datetime.now(UTC)
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="MFG", legal_name="生产测试", display_name="生产测试", base_currency=currency
    )
    user = User.objects.create_user(username="mfg-user", display_name="生产员", company=company)
    uom = UnitOfMeasure.objects.create(
        uom_code="MFG-PCS", name_zh="件", symbol="件", dimension=UnitOfMeasure.Dimension.COUNT
    )
    category = ProductCategory.objects.create(company=company, category_code="MFG", name_zh="生产")
    component_spu = ProductSpu.objects.create(
        company=company, spu_code="MAT-SPU", name_zh="材料", category=category
    )
    product_spu = ProductSpu.objects.create(
        company=company, spu_code="FG-SPU", name_zh="成品", category=category
    )
    component = ProductSku.objects.create(
        company=company, sku_code="MAT", spu=component_spu, name_zh="材料", base_uom=uom
    )
    product = ProductSku.objects.create(
        company=company, sku_code="FG", spu=product_spu, name_zh="成品", base_uom=uom
    )
    warehouse = Warehouse.objects.create(company=company, warehouse_code="MFG-WH", name="生产仓")
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="A", name="A", area_type="production"
    )
    storage = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="OK",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    exception = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="NG",
        location_type=WarehouseLocation.LocationType.EXCEPTION,
    )
    normal_status = InventoryStatus.objects.create(
        company=company, status_code="NORMAL", name="正常"
    )
    rejected_status = InventoryStatus.objects.create(company=company, status_code="NG", name="异常")
    component_lot = InventoryLot.objects.create(company=company, sku=component, lot_no="MAT-LOT")
    product_lot = InventoryLot.objects.create(company=company, sku=product, lot_no="FG-LOT")
    component_balance = InventoryBalance.objects.create(
        company=company,
        sku=component,
        warehouse=warehouse,
        location=storage,
        inventory_status=normal_status,
        lot=component_lot,
        on_hand_qty=11,
    )
    accepted_balance = InventoryBalance.objects.create(
        company=company,
        sku=product,
        warehouse=warehouse,
        location=storage,
        inventory_status=normal_status,
        lot=product_lot,
    )
    rejected_balance = InventoryBalance.objects.create(
        company=company,
        sku=product,
        warehouse=warehouse,
        location=exception,
        inventory_status=rejected_status,
        lot=product_lot,
    )
    bom = BillOfMaterial.objects.create(
        company=company,
        bom_no="BOM-1",
        product_sku=product,
        bom_type=BillOfMaterial.BomType.PRODUCTION,
        version="1",
        output_qty=1,
        valid_from=now,
        approval_reference="TEST-APPROVAL",
    )
    BillOfMaterialItem.objects.create(
        bom=bom,
        line_no=1,
        component_sku=component,
        standard_qty=2,
        uom=uom,
        expected_loss_rate=Decimal("0.1"),
        is_critical=True,
    )
    transition_bom(bom_id=bom.pk, action="approve")
    transition_bom(bom_id=bom.pk, action="activate")
    order = ProductionOrder.objects.create(
        company=company,
        production_order_no="MO-1",
        product_sku=product,
        bom=bom,
        planned_qty=5,
        warehouse=warehouse,
    )
    transition_production_order(order_id=order.pk, expected_version=1, action="approve")
    transition_production_order(order_id=order.pk, expected_version=2, action="release")
    issue_production_materials(
        order_id=order.pk,
        issue_no="MI-1",
        idempotency_key="mfg-issue-1",
        lines=[MaterialIssueInput(component.pk, component_balance.pk, Decimal("11"))],
        operator=user,
        occurred_at=now,
    )
    component_balance.refresh_from_db()
    assert component_balance.on_hand_qty == 0

    completed = complete_production(
        order_id=order.pk,
        completion_no="MC-1",
        idempotency_key="mfg-complete-1",
        accepted_qty=Decimal("4"),
        rejected_qty=Decimal("1"),
        accepted_balance_id=accepted_balance.pk,
        rejected_balance_id=rejected_balance.pk,
        consumptions=[CompletionConsumptionInput(component.pk, Decimal("11"))],
        operator=user,
        occurred_at=now,
    )
    order.refresh_from_db()
    accepted_balance.refresh_from_db()
    rejected_balance.refresh_from_db()
    consumption = ProductionConsumption.objects.get(production_order=order, component_sku=component)
    assert completed.status == ProductionOrder.Status.COMPLETED
    assert accepted_balance.on_hand_qty == Decimal("4")
    assert rejected_balance.on_hand_qty == Decimal("1")
    assert consumption.standard_qty == Decimal("10")
    assert consumption.actual_consumed_qty == Decimal("11")
    assert consumption.loss_qty == Decimal("1")
    repeated = complete_production(
        order_id=order.pk,
        completion_no="MC-1",
        idempotency_key="mfg-complete-1",
        accepted_qty=0,
        rejected_qty=0,
        accepted_balance_id=None,
        rejected_balance_id=None,
        consumptions=[],
        operator=user,
        occurred_at=now,
    )
    assert repeated.repeated is True
    accepted_balance.refresh_from_db()
    assert accepted_balance.on_hand_qty == Decimal("4")

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance, InventoryLot, InventoryStatus
from kaxi.master_data.models import Company, Currency, UnitOfMeasure
from kaxi.prepack.models import PackagingPlan, PackagingPlanItem, PrepackOrder
from kaxi.prepack.services import (
    BreakdownMaterialInput,
    MaterialUsageInput,
    activate_packaging_plan,
    approve_prepack_order,
    breakdown_prepack,
    execute_prepack,
)
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation


@pytest.mark.django_db(transaction=True)
def test_prepack_and_approved_breakdown_move_product_and_returnable_material_atomically() -> None:
    now = datetime.now(UTC)
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="PPK",
        legal_name="预包装测试",
        display_name="预包装测试",
        base_currency=currency,
    )
    user = User.objects.create_user(username="ppk-user", display_name="包装员", company=company)
    uom = UnitOfMeasure.objects.create(
        uom_code="PPK-PCS", name_zh="件", symbol="件", dimension=UnitOfMeasure.Dimension.COUNT
    )
    category = ProductCategory.objects.create(
        company=company, category_code="PPK", name_zh="预包装"
    )
    product_spu = ProductSpu.objects.create(
        company=company, spu_code="PPK-PRODUCT-SPU", name_zh="产品", category=category
    )
    material_spu = ProductSpu.objects.create(
        company=company, spu_code="PPK-MATERIAL-SPU", name_zh="包装材料", category=category
    )
    product = ProductSku.objects.create(
        company=company, sku_code="PPK-PRODUCT", spu=product_spu, name_zh="产品", base_uom=uom
    )
    material = ProductSku.objects.create(
        company=company, sku_code="PPK-MATERIAL", spu=material_spu, name_zh="包装材料", base_uom=uom
    )
    warehouse = Warehouse.objects.create(company=company, warehouse_code="PPK-WH", name="包装仓")
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="A", name="A", area_type="prepack"
    )
    raw_location = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="RAW",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    packed_location = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="PACKED",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    material_location = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="MATERIAL",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    status = InventoryStatus.objects.create(company=company, status_code="NORMAL", name="正常")
    product_lot = InventoryLot.objects.create(company=company, sku=product, lot_no="PRODUCT-LOT")
    material_lot = InventoryLot.objects.create(company=company, sku=material, lot_no="MATERIAL-LOT")
    raw_balance = InventoryBalance.objects.create(
        company=company,
        sku=product,
        warehouse=warehouse,
        location=raw_location,
        inventory_status=status,
        lot=product_lot,
        on_hand_qty=3,
    )
    packed_balance = InventoryBalance.objects.create(
        company=company,
        sku=product,
        warehouse=warehouse,
        location=packed_location,
        inventory_status=status,
        lot=product_lot,
    )
    material_balance = InventoryBalance.objects.create(
        company=company,
        sku=material,
        warehouse=warehouse,
        location=material_location,
        inventory_status=status,
        lot=material_lot,
        on_hand_qty=6,
    )
    plan = PackagingPlan.objects.create(
        company=company,
        plan_no="PLAN-1",
        name="标准包装",
        product_sku=product,
        version="1",
        approval_reference="APPROVAL-1",
    )
    plan_item = PackagingPlanItem.objects.create(
        plan=plan,
        line_no=1,
        material_sku=material,
        standard_qty=2,
        uom=uom,
        returnable_on_breakdown=True,
    )
    activate_packaging_plan(plan_id=plan.pk)
    order = PrepackOrder.objects.create(
        company=company,
        prepack_order_no="PPK-1",
        warehouse=warehouse,
        product_sku=product,
        packaging_plan=plan,
        planned_qty=3,
        source_location=raw_location,
        target_location=packed_location,
    )
    approve_prepack_order(order_id=order.pk, expected_version=1)
    result = execute_prepack(
        order_id=order.pk,
        execution_no="EXEC-1",
        quantity=3,
        source_balance_id=raw_balance.pk,
        target_balance_id=packed_balance.pk,
        materials=[MaterialUsageInput(plan_item.pk, material_balance.pk, Decimal("6"))],
        idempotency_key="ppk-exec-1",
        operator=user,
        occurred_at=now,
    )
    raw_balance.refresh_from_db()
    packed_balance.refresh_from_db()
    material_balance.refresh_from_db()
    assert result.status == PrepackOrder.Status.COMPLETED
    assert raw_balance.on_hand_qty == 0
    assert packed_balance.on_hand_qty == Decimal("3")
    assert material_balance.on_hand_qty == 0

    breakdown_prepack(
        order_id=order.pk,
        breakdown_no="BREAK-1",
        quantity=1,
        prepacked_balance_id=packed_balance.pk,
        restored_product_balance_id=raw_balance.pk,
        returned_materials=[
            BreakdownMaterialInput(plan_item.pk, material_balance.pk, Decimal("1"))
        ],
        approval_reference="BREAK-APPROVAL",
        idempotency_key="ppk-break-1",
        operator=user,
        occurred_at=now,
    )
    raw_balance.refresh_from_db()
    packed_balance.refresh_from_db()
    material_balance.refresh_from_db()
    assert raw_balance.on_hand_qty == Decimal("1")
    assert packed_balance.on_hand_qty == Decimal("2")
    assert material_balance.on_hand_qty == Decimal("1")
    repeated = breakdown_prepack(
        order_id=order.pk,
        breakdown_no="BREAK-1",
        quantity=1,
        prepacked_balance_id=packed_balance.pk,
        restored_product_balance_id=raw_balance.pk,
        returned_materials=[],
        approval_reference="BREAK-APPROVAL",
        idempotency_key="ppk-break-1",
        operator=user,
        occurred_at=now,
    )
    assert repeated.repeated is True
    packed_balance.refresh_from_db()
    assert packed_balance.on_hand_qty == Decimal("2")

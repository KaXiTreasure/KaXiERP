from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance, InventoryLedger, InventoryStatus
from kaxi.master_data.models import Company, Currency, Party, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku, ProductSpu
from kaxi.system.import_services import commit_batch, stage_csv, validate_batch
from kaxi.system.models import DataImportBatch
from kaxi.warehouse.models import Warehouse, WarehouseArea, WarehouseLocation

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def import_context():  # type: ignore[no-untyped-def]
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="IMP", legal_name="导入测试", display_name="导入测试", base_currency=currency
    )
    user = User.objects.create_user(username="importer", password="test", company=company)
    return company, user, currency


def test_party_import_is_staged_validated_committed_and_idempotent(import_context):  # type: ignore[no-untyped-def]
    company, user, _ = import_context
    content = (
        "party_no,party_type,legal_name,display_name,status\n"
        "C001,organization,测试客户,测试客户,active\n"
    ).encode()
    batch = stage_csv(
        company_id=company.pk,
        entity_type=DataImportBatch.Entity.PARTY,
        filename="parties.csv",
        content=content,
        actor=user,
    )
    assert (
        stage_csv(
            company_id=company.pk,
            entity_type=DataImportBatch.Entity.PARTY,
            filename="same.csv",
            content=content,
            actor=user,
        ).pk
        == batch.pk
    )
    validate_batch(batch_id=batch.pk)
    committed = commit_batch(batch_id=batch.pk, actor=user)
    assert committed.status == DataImportBatch.Status.COMMITTED
    assert Party.objects.get(company=company, party_no="C001").display_name == "测试客户"
    assert commit_batch(batch_id=batch.pk, actor=user).pk == batch.pk
    assert Party.objects.filter(company=company, party_no="C001").count() == 1


def test_invalid_import_cannot_partially_commit(import_context):  # type: ignore[no-untyped-def]
    company, user, _ = import_context
    batch = stage_csv(
        company_id=company.pk,
        entity_type=DataImportBatch.Entity.PARTY,
        filename="invalid.csv",
        content=(
            "party_no,party_type,legal_name,display_name\n"
            "C001,organization,有效客户,有效客户\n"
            "C002,wrong,无效客户,无效客户\n"
        ).encode(),
        actor=user,
    )
    validated = validate_batch(batch_id=batch.pk)
    assert validated.invalid_rows == 1
    with pytest.raises(ValidationError):
        commit_batch(batch_id=batch.pk, actor=user)
    assert not Party.objects.filter(company=company).exists()


def test_opening_inventory_import_uses_immutable_ledger(import_context):  # type: ignore[no-untyped-def]
    company, user, _ = import_context
    uom = UnitOfMeasure.objects.create(
        uom_code="PCS",
        name_zh="件",
        symbol="件",
        dimension=UnitOfMeasure.Dimension.COUNT,
        decimal_places=0,
    )
    category = ProductCategory.objects.create(
        company=company, category_code="JEWEL", name_zh="饰品"
    )
    spu = ProductSpu.objects.create(
        company=company, spu_code="SPU-1", name_zh="测试商品", category=category
    )
    sku = ProductSku.objects.create(
        company=company, sku_code="SKU-1", spu=spu, name_zh="测试SKU", base_uom=uom
    )
    warehouse = Warehouse.objects.create(company=company, warehouse_code="GZ", name="广州仓")
    area = WarehouseArea.objects.create(
        warehouse=warehouse, area_code="MAIN", name="主区", area_type="product"
    )
    location = WarehouseLocation.objects.create(
        warehouse=warehouse,
        area=area,
        location_code="A-01",
        location_type=WarehouseLocation.LocationType.STORAGE,
    )
    inventory_status = InventoryStatus.objects.create(
        company=company, status_code="NORMAL", name="正常"
    )
    content = (
        b"reference_no,sku_code,warehouse_code,location_code,status_code,quantity,occurred_at\n"
        b"OPEN-001,SKU-1,GZ,A-01,NORMAL,25,2026-08-01T09:00:00+08:00\n"
    )
    batch = stage_csv(
        company_id=company.pk,
        entity_type=DataImportBatch.Entity.OPENING_INVENTORY,
        filename="opening.csv",
        content=content,
        actor=user,
    )
    validate_batch(batch_id=batch.pk)
    commit_batch(batch_id=batch.pk, actor=user)
    balance = InventoryBalance.objects.get(
        company=company,
        sku=sku,
        warehouse=warehouse,
        location=location,
        inventory_status=inventory_status,
    )
    ledger = InventoryLedger.objects.get(reference_type="data_import_row")
    assert balance.on_hand_qty == Decimal("25")
    assert ledger.quantity_delta == Decimal("25")
    assert ledger.transaction_type == "opening"

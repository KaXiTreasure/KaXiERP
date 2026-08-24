from kaxi.master_data.models import Address, Party, UnitOfMeasure
from kaxi.products.models import Material, ProductSku, ProductSpu, ProductTradeProfile, SkuBarcode
from kaxi.warehouse.models import Warehouse, WarehouseLocation


def test_db03_tables_are_explicitly_named() -> None:
    assert UnitOfMeasure._meta.db_table == "md_unit_of_measure"
    assert ProductSpu._meta.db_table == "prd_spu"
    assert ProductSku._meta.db_table == "prd_sku"
    assert SkuBarcode._meta.db_table == "prd_sku_barcode"
    assert Warehouse._meta.db_table == "wms_warehouse"
    assert WarehouseLocation._meta.db_table == "wms_location"


def test_sku_code_is_unique_per_company() -> None:
    names = {constraint.name for constraint in ProductSku._meta.constraints}
    assert "prd_sku_company_code_uniq" in names


def test_location_code_is_unique_per_warehouse() -> None:
    names = {constraint.name for constraint in WarehouseLocation._meta.constraints}
    assert "wms_location_warehouse_code_uniq" in names


def test_sku_supports_multiple_barcodes() -> None:
    relation = SkuBarcode._meta.get_field("sku")
    assert relation.remote_field.related_name == "barcodes"


def test_party_supports_multiple_addresses() -> None:
    assert Party._meta.db_table == "mdm_party"
    assert Address._meta.get_field("party").remote_field.related_name == "addresses"


def test_product_extensions_are_relational_models() -> None:
    assert Material._meta.db_table == "prd_material"
    assert ProductTradeProfile._meta.db_table == "prd_trade_profile"

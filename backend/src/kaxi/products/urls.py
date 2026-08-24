from rest_framework.routers import DefaultRouter

from kaxi.products.models import (
    AttributeValue,
    Brand,
    CategoryAttribute,
    Material,
    ProductAttribute,
    ProductCategory,
    ProductSku,
    ProductSpu,
    ProductTradeProfile,
    SkuAttributeValue,
    SkuBarcode,
    SkuMaterial,
)
from kaxi.shared.crud import crud_for

router = DefaultRouter()
router.register(
    "categories", crud_for(ProductCategory, "product.master.manage"), basename="category"
)
router.register("brands", crud_for(Brand, "product.master.manage"), basename="brand")
router.register("spus", crud_for(ProductSpu, "product.master.manage"), basename="spu")
router.register("skus", crud_for(ProductSku, "product.master.manage"), basename="sku")
router.register("barcodes", crud_for(SkuBarcode, "product.master.manage"), basename="barcode")
router.register("materials", crud_for(Material, "product.master.manage"), basename="material")
router.register(
    "sku-materials",
    crud_for(SkuMaterial, "product.master.manage", "sku__company_id"),
    basename="sku-material",
)
router.register(
    "attributes", crud_for(ProductAttribute, "product.master.manage"), basename="attribute"
)
router.register(
    "attribute-values",
    crud_for(AttributeValue, "product.master.manage", "attribute__company_id"),
    basename="attribute-value",
)
router.register(
    "category-attributes",
    crud_for(CategoryAttribute, "product.master.manage", "category__company_id"),
    basename="category-attribute",
)
router.register(
    "sku-attributes",
    crud_for(SkuAttributeValue, "product.master.manage", "sku__company_id"),
    basename="sku-attribute",
)
router.register(
    "trade-profiles",
    crud_for(ProductTradeProfile, "product.trade.manage", "sku__company_id"),
    basename="product-trade-profile",
)
urlpatterns = router.urls

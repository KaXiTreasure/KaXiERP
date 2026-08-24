from rest_framework.routers import DefaultRouter

from kaxi.purchasing.api import GoodsReceiptViewSet, PurchaseOrderViewSet
from kaxi.purchasing.extended_api import (
    PerformanceViewSet,
    QuoteViewSet,
    RequisitionViewSet,
    ReturnViewSet,
    RfqViewSet,
)

router = DefaultRouter()
router.register("orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("receipts", GoodsReceiptViewSet, basename="goods-receipt")
router.register("requisitions", RequisitionViewSet)
router.register("rfqs", RfqViewSet)
router.register("quotes", QuoteViewSet)
router.register("returns", ReturnViewSet)
router.register("supplier-performance", PerformanceViewSet)
urlpatterns = router.urls

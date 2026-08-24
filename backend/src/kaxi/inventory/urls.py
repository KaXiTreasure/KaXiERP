from rest_framework.routers import DefaultRouter

from kaxi.inventory.api import InventoryBalanceViewSet, StockCountViewSet, StockTransferViewSet

router = DefaultRouter()
router.register("balances", InventoryBalanceViewSet, basename="inventory-balance")
router.register("transfers", StockTransferViewSet, basename="stock-transfer")
router.register("counts", StockCountViewSet, basename="stock-count")
urlpatterns = router.urls

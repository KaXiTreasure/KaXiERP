from rest_framework.routers import DefaultRouter

from kaxi.trade.api import (
    ContractViewSet,
    CustomsDeclarationViewSet,
    ForwarderSettlementViewSet,
    OverseasWarehouseViewSet,
    PackageViewSet,
    ShipmentViewSet,
    TradeCostViewSet,
    TradeDetailViewSet,
    TradeDocumentViewSet,
)

router = DefaultRouter()
router.register("contracts", ContractViewSet)
router.register("order-details", TradeDetailViewSet)
router.register("shipments", ShipmentViewSet)
router.register("packages", PackageViewSet)
router.register("documents", TradeDocumentViewSet)
router.register("customs-declarations", CustomsDeclarationViewSet)
router.register("costs", TradeCostViewSet)
router.register("forwarder-settlements", ForwarderSettlementViewSet)
router.register("overseas-warehouses", OverseasWarehouseViewSet)
urlpatterns = router.urls

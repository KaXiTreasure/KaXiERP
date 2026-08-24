from rest_framework.routers import DefaultRouter

from kaxi.sales.api import SalesOrderViewSet, SalesShipmentViewSet
from kaxi.sales.penetration_api import (
    PresaleCampaignViewSet,
    SupplyAllocationViewSet,
    SupplyDemandViewSet,
)

router = DefaultRouter()
router.register("orders", SalesOrderViewSet, basename="sales-order")
router.register("shipments", SalesShipmentViewSet, basename="sales-shipment")
router.register("supply-demands", SupplyDemandViewSet)
router.register("supply-allocations", SupplyAllocationViewSet)
router.register("presale-campaigns", PresaleCampaignViewSet)

urlpatterns = router.urls

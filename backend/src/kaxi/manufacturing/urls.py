from rest_framework.routers import DefaultRouter

from kaxi.manufacturing.api import BomViewSet, ProductionOrderViewSet
from kaxi.manufacturing.extended_api import (
    ReportViewSet,
    RoutingViewSet,
    SubcontractViewSet,
    SuggestionViewSet,
    WorkCenterViewSet,
)

router = DefaultRouter()
router.register("boms", BomViewSet, basename="bom")
router.register("orders", ProductionOrderViewSet, basename="production-order")
router.register("work-centers", WorkCenterViewSet)
router.register("routings", RoutingViewSet)
router.register("operation-reports", ReportViewSet)
router.register("suggestions", SuggestionViewSet)
router.register("subcontracts", SubcontractViewSet)
urlpatterns = router.urls

from rest_framework.routers import DefaultRouter

from kaxi.analytics.api import (
    AnalyticsViewSet,
    DefinitionViewSet,
    ExportJobViewSet,
    SnapshotViewSet,
)

router = DefaultRouter()
router.register("reports", AnalyticsViewSet, basename="analytics")
router.register("definitions", DefinitionViewSet)
router.register("snapshots", SnapshotViewSet)
router.register("exports", ExportJobViewSet)
urlpatterns = router.urls

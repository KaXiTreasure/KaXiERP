from rest_framework.routers import DefaultRouter

from kaxi.integrations.api import (
    AccountViewSet,
    ConnectorViewSet,
    CursorViewSet,
    EventViewSet,
    MappingViewSet,
    WebhookViewSet,
)

router = DefaultRouter()
router.register("connectors", ConnectorViewSet)
router.register("accounts", AccountViewSet)
router.register("mappings", MappingViewSet)
router.register("cursors", CursorViewSet)
router.register("events", EventViewSet)
router.register("webhooks", WebhookViewSet)
urlpatterns = router.urls

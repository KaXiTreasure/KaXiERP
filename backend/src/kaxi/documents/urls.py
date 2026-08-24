from rest_framework.routers import DefaultRouter

from kaxi.documents.api import (
    AuditViewSet,
    CategoryViewSet,
    DisposalViewSet,
    FileViewSet,
    LinkViewSet,
    PermissionViewSet,
    RetentionViewSet,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet)
router.register("retention-policies", RetentionViewSet)
router.register("files", FileViewSet)
router.register("links", LinkViewSet)
router.register("permissions", PermissionViewSet)
router.register("disposal-batches", DisposalViewSet)
router.register("audit-events", AuditViewSet, basename="file-audit")
urlpatterns = router.urls

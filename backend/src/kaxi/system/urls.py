from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .branding_api import (
    branding,
    delete_font,
    refresh_bing_branding_background,
    upload_branding_asset,
    upload_font,
)
from .import_api import DataImportViewSet
from .management_api import (
    BackgroundTaskViewSet,
    DictionaryItemViewSet,
    DictionaryTypeViewSet,
    NumberRuleViewSet,
    NumberSequenceViewSet,
    OutboxViewSet,
)
from .views import HealthView

router = DefaultRouter()
router.register("data-imports", DataImportViewSet, basename="data-import")
router.register("dictionary-types", DictionaryTypeViewSet, basename="dictionary-type")
router.register("dictionary-items", DictionaryItemViewSet, basename="dictionary-item")
router.register("number-rules", NumberRuleViewSet, basename="number-rule")
router.register("number-sequences", NumberSequenceViewSet, basename="number-sequence")
router.register("jobs", BackgroundTaskViewSet, basename="background-job")
router.register("outbox-events", OutboxViewSet, basename="outbox-event")
urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("branding/", branding, name="branding"),
    path("branding/assets/<str:kind>/", upload_branding_asset, name="branding-asset"),
    path(
        "branding/background/bing/refresh/",
        refresh_bing_branding_background,
        name="branding-bing-background-refresh",
    ),
    path("branding/fonts/", upload_font, name="branding-font-upload"),
    path("branding/fonts/<int:pk>/", delete_font, name="branding-font-delete"),
    path("", include(router.urls)),
]

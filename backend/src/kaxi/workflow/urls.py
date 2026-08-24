from rest_framework.routers import DefaultRouter

from kaxi.workflow.api import (
    DefinitionViewSet,
    InstanceViewSet,
    NotificationViewSet,
    PreferenceViewSet,
    RuleViewSet,
    TaskViewSet,
)

router = DefaultRouter()
router.register("definitions", DefinitionViewSet)
router.register("rules", RuleViewSet)
router.register("instances", InstanceViewSet)
router.register("tasks", TaskViewSet)
router.register("notifications", NotificationViewSet, basename="notification")
router.register("notification-preferences", PreferenceViewSet, basename="notification-preference")
urlpatterns = router.urls

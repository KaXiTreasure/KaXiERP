from rest_framework.routers import DefaultRouter

from kaxi.prepack.api import PackagingPlanViewSet, PrepackOrderViewSet

router = DefaultRouter()
router.register("plans", PackagingPlanViewSet, basename="packaging-plan")
router.register("orders", PrepackOrderViewSet, basename="prepack-order")
urlpatterns = router.urls

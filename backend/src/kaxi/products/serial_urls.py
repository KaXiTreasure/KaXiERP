from rest_framework.routers import DefaultRouter

from kaxi.products.serial_api import (
    LimitedEditionPoolViewSet,
    ProductSerialViewSet,
    SerialAttemptViewSet,
    SerialReservationViewSet,
)

router = DefaultRouter()
router.register("pools", LimitedEditionPoolViewSet, basename="serial-pool")
router.register("serials", ProductSerialViewSet, basename="product-serial")
router.register("attempts", SerialAttemptViewSet, basename="serial-attempt")
router.register("reservations", SerialReservationViewSet, basename="serial-reservation")
urlpatterns = router.urls

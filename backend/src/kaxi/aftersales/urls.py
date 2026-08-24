from rest_framework.routers import DefaultRouter

from kaxi.aftersales.api import CaseViewSet, ReceiptViewSet, RefundViewSet

router = DefaultRouter()
router.register("cases", CaseViewSet)
router.register("receipts", ReceiptViewSet)
router.register("refunds", RefundViewSet)
urlpatterns = router.urls

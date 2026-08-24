from rest_framework.routers import DefaultRouter

from kaxi.finance.api import (
    AccountViewSet,
    ChartViewSet,
    JournalViewSet,
    LedgerViewSet,
    OpenItemViewSet,
    PeriodViewSet,
    SettlementViewSet,
    ThreeWayMatchViewSet,
)
from kaxi.finance.cost_api import CostBalanceViewSet, CostRecordViewSet, SerialCostViewSet
from kaxi.finance.peripheral_api import (
    DepreciationViewSet,
    ExpenseClaimViewSet,
    FixedAssetViewSet,
    PayrollViewSet,
    TaxInvoiceViewSet,
)

router = DefaultRouter()
router.register("ledgers", LedgerViewSet)
router.register("charts", ChartViewSet)
router.register("accounts", AccountViewSet)
router.register("periods", PeriodViewSet)
router.register("journals", JournalViewSet)
router.register("open-items", OpenItemViewSet)
router.register("settlements", SettlementViewSet)
router.register("three-way-matches", ThreeWayMatchViewSet)
router.register("cost-balances", CostBalanceViewSet, basename="cost-balance")
router.register("cost-records", CostRecordViewSet, basename="cost-record")
router.register("serial-costs", SerialCostViewSet, basename="serial-cost")
router.register("expense-claims", ExpenseClaimViewSet)
router.register("fixed-assets", FixedAssetViewSet)
router.register("depreciations", DepreciationViewSet)
router.register("payroll-runs", PayrollViewSet)
router.register("tax-invoices", TaxInvoiceViewSet)
urlpatterns = router.urls

from django.urls import reverse


def test_workflow_document_integration_trade_and_aftersales_routes() -> None:
    assert reverse("user-list") == "/api/v1/auth/users/"
    assert reverse("role-list") == "/api/v1/auth/roles/"
    assert reverse("userpermissionoverride-approve", kwargs={"pk": 1}) == (
        "/api/v1/auth/overrides/1/approve/"
    )
    assert reverse("data-import-stage") == "/api/v1/system/data-imports/stage/"
    assert reverse("data-import-validate", kwargs={"pk": 1}) == (
        "/api/v1/system/data-imports/1/validate/"
    )
    assert reverse("data-import-commit", kwargs={"pk": 1}) == (
        "/api/v1/system/data-imports/1/commit/"
    )
    assert reverse("sku-list") == "/api/v1/products/skus/"
    assert reverse("party-list") == "/api/v1/master-data/parties/"
    assert reverse("warehouse-list") == "/api/v1/warehouses/warehouses/"
    assert reverse("price-list-list") == "/api/v1/pricing/price-lists/"
    assert reverse("approvaldefinition-list") == "/api/v1/workflow/definitions/"
    assert reverse("approvaltask-decide", kwargs={"pk": 1}) == "/api/v1/workflow/tasks/1/decide/"
    assert reverse("fileobject-add-version", kwargs={"pk": 1}) == (
        "/api/v1/documents/files/1/versions/"
    )
    assert reverse("fileobject-prepare-upload", kwargs={"pk": 1}) == (
        "/api/v1/documents/files/1/prepare-upload/"
    )
    assert reverse("disposalbatch-approve", kwargs={"pk": 1}) == (
        "/api/v1/documents/disposal-batches/1/approve/"
    )
    assert reverse("integrationevent-retry", kwargs={"pk": 1}) == (
        "/api/v1/integrations/events/1/retry/"
    )
    assert reverse("shipment-dispatch", kwargs={"pk": 1}) == ("/api/v1/trade/shipments/1/dispatch/")
    assert reverse("package-review", kwargs={"pk": 1}) == ("/api/v1/trade/packages/1/review/")
    assert reverse("aftersalescase-receive", kwargs={"pk": 1}) == (
        "/api/v1/aftersales/cases/1/receive/"
    )
    assert reverse("refund-mark-paid", kwargs={"pk": 1}) == (
        "/api/v1/aftersales/refunds/1/mark-paid/"
    )
    assert reverse("purchaserequisition-submit", kwargs={"pk": 1}) == (
        "/api/v1/purchasing/requisitions/1/submit/"
    )
    assert reverse("requestforquotation-award", kwargs={"pk": 1}) == (
        "/api/v1/purchasing/rfqs/1/award/"
    )
    assert reverse("purchasereturn-dispatch", kwargs={"pk": 1}) == (
        "/api/v1/purchasing/returns/1/dispatch/"
    )
    assert reverse("supplydemand-link", kwargs={"pk": 1}) == (
        "/api/v1/sales/supply-demands/1/link/"
    )
    assert reverse("presalecampaign-allocate", kwargs={"pk": 1}) == (
        "/api/v1/sales/presale-campaigns/1/allocate/"
    )
    assert reverse("routing-activate", kwargs={"pk": 1}) == (
        "/api/v1/manufacturing/routings/1/activate/"
    )
    assert reverse("subcontractorder-send-materials", kwargs={"pk": 1}) == (
        "/api/v1/manufacturing/subcontracts/1/send-materials/"
    )
    assert reverse("cost-record-receive") == "/api/v1/finance/cost-records/receive/"
    assert reverse("serial-cost-assign") == "/api/v1/finance/serial-costs/assign/"
    assert reverse("analytics-profitability") == ("/api/v1/analytics/reports/profitability/")
    assert reverse("reportdefinition-snapshot", kwargs={"pk": 1}) == (
        "/api/v1/analytics/definitions/1/snapshot/"
    )
    assert reverse("expenseclaim-transition", kwargs={"pk": 1}) == (
        "/api/v1/finance/expense-claims/1/transition/"
    )
    assert reverse("fixedasset-depreciate", kwargs={"pk": 1}) == (
        "/api/v1/finance/fixed-assets/1/depreciate/"
    )
    assert reverse("payrollrun-calculate", kwargs={"pk": 1}) == (
        "/api/v1/finance/payroll-runs/1/calculate/"
    )
    assert reverse("taxinvoice-transition", kwargs={"pk": 1}) == (
        "/api/v1/finance/tax-invoices/1/transition/"
    )
    assert reverse("ledger-balance-sheet", kwargs={"pk": 1}) == (
        "/api/v1/finance/ledgers/1/balance-sheet/"
    )
    assert reverse("ledger-income-statement", kwargs={"pk": 1}) == (
        "/api/v1/finance/ledgers/1/income-statement/"
    )
    assert reverse("ledger-cash-flow", kwargs={"pk": 1}) == ("/api/v1/finance/ledgers/1/cash-flow/")

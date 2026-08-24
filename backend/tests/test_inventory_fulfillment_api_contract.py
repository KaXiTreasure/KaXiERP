from django.urls import reverse


def test_inventory_and_fulfillment_routes_are_registered() -> None:
    assert reverse("inventory-balance-list") == "/api/v1/inventory/balances/"
    assert reverse("stock-transfer-dispatch", kwargs={"pk": 1}) == (
        "/api/v1/inventory/transfers/1/dispatch/"
    )
    assert reverse("stock-transfer-receive", kwargs={"pk": 1}) == (
        "/api/v1/inventory/transfers/1/receive/"
    )
    assert reverse("stock-count-post", kwargs={"pk": 1}) == "/api/v1/inventory/counts/1/post/"
    assert reverse("sales-shipment-start-picking", kwargs={"pk": 1}) == (
        "/api/v1/sales/shipments/1/start-picking/"
    )
    assert reverse("sales-shipment-ship", kwargs={"pk": 1}) == ("/api/v1/sales/shipments/1/ship/")

from django.urls import reverse


def test_sales_order_routes_are_registered() -> None:
    assert reverse("sales-order-list") == "/api/v1/sales/orders/"
    assert reverse("sales-order-confirm", kwargs={"pk": 1}) == "/api/v1/sales/orders/1/confirm/"
    assert reverse("sales-order-cancel", kwargs={"pk": 1}) == "/api/v1/sales/orders/1/cancel/"

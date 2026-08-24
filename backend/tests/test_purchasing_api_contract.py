from django.urls import reverse


def test_purchasing_routes_are_registered() -> None:
    assert reverse("purchase-order-list") == "/api/v1/purchasing/orders/"
    assert (
        reverse("purchase-order-approve", kwargs={"pk": 1})
        == "/api/v1/purchasing/orders/1/approve/"
    )
    assert reverse("purchase-order-issue", kwargs={"pk": 1}) == "/api/v1/purchasing/orders/1/issue/"
    assert (
        reverse("purchase-order-receive", kwargs={"pk": 1})
        == "/api/v1/purchasing/orders/1/receive/"
    )
    assert reverse("goods-receipt-complete-inspection", kwargs={"pk": 1}) == (
        "/api/v1/purchasing/receipts/1/complete-inspection/"
    )

from django.urls import reverse


def test_serial_traceability_routes_are_registered() -> None:
    assert reverse("serial-pool-generate", kwargs={"pk": 1}) == (
        "/api/v1/product-serials/pools/1/generate/"
    )
    assert reverse("product-serial-start-production", kwargs={"pk": 1}) == (
        "/api/v1/product-serials/serials/1/start-production/"
    )
    assert reverse("product-serial-auto-reserve") == (
        "/api/v1/product-serials/serials/auto-reserve/"
    )
    assert reverse("serial-attempt-complete", kwargs={"pk": 1}) == (
        "/api/v1/product-serials/attempts/1/complete/"
    )
    assert reverse("serial-reservation-assign-shipment", kwargs={"pk": 1}) == (
        "/api/v1/product-serials/reservations/1/assign-shipment/"
    )

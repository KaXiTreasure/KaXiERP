from django.urls import reverse


def test_manufacturing_and_prepack_routes_are_registered() -> None:
    assert reverse("bom-activate", kwargs={"pk": 1}) == "/api/v1/manufacturing/boms/1/activate/"
    assert reverse("production-order-issue-materials", kwargs={"pk": 1}) == (
        "/api/v1/manufacturing/orders/1/issue-materials/"
    )
    assert reverse("production-order-complete", kwargs={"pk": 1}) == (
        "/api/v1/manufacturing/orders/1/complete/"
    )
    assert reverse("packaging-plan-activate", kwargs={"pk": 1}) == (
        "/api/v1/prepack/plans/1/activate/"
    )
    assert reverse("prepack-order-execute", kwargs={"pk": 1}) == (
        "/api/v1/prepack/orders/1/execute/"
    )
    assert reverse("prepack-order-breakdown", kwargs={"pk": 1}) == (
        "/api/v1/prepack/orders/1/breakdown/"
    )

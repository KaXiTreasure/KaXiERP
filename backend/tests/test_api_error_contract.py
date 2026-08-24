from rest_framework.test import APIRequestFactory

from kaxi.sales.services import OrderVersionConflictError
from kaxi.shared.api_exceptions import kaxi_exception_handler


def test_domain_error_uses_stable_api_shape() -> None:
    request = APIRequestFactory().post("/api/v1/sales/orders/1/confirm/", {})
    response = kaxi_exception_handler(OrderVersionConflictError("版本冲突"), {"request": request})
    assert response is not None
    assert response.status_code == 409
    assert set(response.data) == {"code", "message", "details", "trace_id"}
    assert response.data["code"] == "VERSION_CONFLICT"

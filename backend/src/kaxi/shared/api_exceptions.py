from uuid import uuid4

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from kaxi.inventory.services import InsufficientInventoryError
from kaxi.pricing.services import PriceFloorViolationError, PriceNotFoundError
from kaxi.sales.credit_services import CreditLimitExceededError
from kaxi.sales.services import OrderVersionConflictError


def kaxi_exception_handler(exc: Exception, context: dict[str, object]) -> Response | None:
    response = exception_handler(exc, context)
    trace_id = str(uuid4())
    if response is not None:
        response.data = {
            "code": "VALIDATION_ERROR" if response.status_code == 400 else "REQUEST_ERROR",
            "message": "请求校验失败" if response.status_code == 400 else "请求处理失败",
            "details": response.data,
            "trace_id": trace_id,
        }
        return response

    mappings: tuple[tuple[type[Exception], str, int], ...] = (
        (OrderVersionConflictError, "VERSION_CONFLICT", status.HTTP_409_CONFLICT),
        (InsufficientInventoryError, "INVENTORY_INSUFFICIENT", status.HTTP_409_CONFLICT),
        (CreditLimitExceededError, "CREDIT_LIMIT_EXCEEDED", status.HTTP_409_CONFLICT),
        (PriceFloorViolationError, "PRICE_FLOOR_VIOLATION", status.HTTP_409_CONFLICT),
        (PriceNotFoundError, "PRICE_NOT_FOUND", status.HTTP_422_UNPROCESSABLE_ENTITY),
        (ObjectDoesNotExist, "RESOURCE_NOT_FOUND", status.HTTP_404_NOT_FOUND),
        (ValueError, "BUSINESS_RULE_VIOLATION", status.HTTP_422_UNPROCESSABLE_ENTITY),
    )
    for exception_type, code, status_code in mappings:
        if isinstance(exc, exception_type):
            return Response(
                {"code": code, "message": str(exc), "details": {}, "trace_id": trace_id},
                status=status_code,
            )
    return None

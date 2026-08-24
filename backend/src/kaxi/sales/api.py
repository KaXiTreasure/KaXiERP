from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.sales.cancellation_services import cancel_unshipped_order
from kaxi.sales.fulfillment_services import ship_sales_shipment, transition_shipment
from kaxi.sales.models import SalesOrder, SalesShipment
from kaxi.sales.serializers import (
    CancelOrderSerializer,
    ConfirmOrderSerializer,
    SalesOrderSerializer,
    SalesShipmentSerializer,
    ShipmentTransitionSerializer,
    ShipShipmentSerializer,
)
from kaxi.sales.services import (
    CreditInput,
    LinePriceInput,
    StockAllocationInput,
    confirm_sales_order,
)


class SalesOrderViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[SalesOrder],
):
    queryset = SalesOrder.objects.select_related(
        "company", "customer", "channel", "shipping_address", "currency"
    ).prefetch_related("lines")
    serializer_class = SalesOrderSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "sales.order.view",
        "retrieve": "sales.order.view",
        "create": "sales.order.create",
        "confirm": "sales.order.confirm",
        "cancel": "sales.order.cancel",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: SalesOrderSerializer) -> None:
        company_id = company_id_for_request(self.request)
        requested_company_id = serializer.validated_data["company"].pk
        if company_id is not None and requested_company_id != company_id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("不能为其他公司创建销售订单。")
        serializer.save()

    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = ConfirmOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        prices = [LinePriceInput(**item) for item in data["prices"]]
        allocations = [StockAllocationInput(**item) for item in data["allocations"]]
        credit_data = data.get("credit")
        credit = CreditInput(**credit_data) if credit_data else None
        result = confirm_sales_order(
            order_id=order.pk,
            expected_version=data["expected_version"],
            idempotency_key=data["idempotency_key"],
            prices=prices,
            allocations=allocations,
            credit=credit,
        )
        return Response(result.__dict__, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cancelled = cancel_unshipped_order(
            order_id=order.pk, reason=serializer.validated_data["reason"]
        )
        return Response(SalesOrderSerializer(cancelled).data, status=status.HTTP_200_OK)


class SalesShipmentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[SalesShipment],
):
    queryset = SalesShipment.objects.select_related(
        "company", "order", "warehouse", "shipped_by"
    ).prefetch_related("lines")
    serializer_class = SalesShipmentSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "sales.fulfillment.read",
        "retrieve": "sales.fulfillment.read",
        "create": "warehouse.pick.process",
        "start_picking": "warehouse.pick.process",
        "complete_picking": "warehouse.pick.process",
        "verify": "warehouse.ship.process",
        "ship": "warehouse.ship.process",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: SalesShipmentSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("不能为其他公司创建发货单。")
        serializer.save()

    def _transition(self, request: Request, action_name: str) -> Response:
        shipment = self.get_object()
        serializer = ShipmentTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = transition_shipment(
            shipment_id=shipment.pk,
            expected_version=serializer.validated_data["expected_version"],
            action=action_name,
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"], url_path="start-picking")
    def start_picking(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, "start_picking")

    @action(detail=True, methods=["post"], url_path="complete-picking")
    def complete_picking(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, "complete_picking")

    @action(detail=True, methods=["post"])
    def verify(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, "verify")

    @action(detail=True, methods=["post"])
    def ship(self, request: Request, pk: str | None = None) -> Response:
        shipment = self.get_object()
        serializer = ShipShipmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not isinstance(user, User):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("需要有效业务用户。")
        result = ship_sales_shipment(
            shipment_id=shipment.pk,
            idempotency_key=serializer.validated_data["idempotency_key"],
            operator=user,
            shipped_at=serializer.validated_data["shipped_at"],
        )
        return Response(result.__dict__)

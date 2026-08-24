from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.products.models import (
    LimitedEditionPool,
    ProductSerial,
    SerialProductionAttempt,
    SerialReservation,
)
from kaxi.products.serial_serializers import (
    AssignShipmentSerializer,
    CompleteAttemptSerializer,
    DisposeSerialSerializer,
    GenerateSerialsSerializer,
    LimitedEditionPoolSerializer,
    ProductSerialSerializer,
    ReleaseSerialSerializer,
    ReserveSerialSerializer,
    SerialAttemptSerializer,
    SerialReservationSerializer,
    StartProductionSerializer,
)
from kaxi.products.serial_services import (
    activate_serial_pool,
    assign_serial_to_shipment,
    complete_serial_production,
    dispose_ng_serial,
    generate_serials,
    release_product_serial,
    reserve_product_serial,
    start_serial_production,
)


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class LimitedEditionPoolViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[LimitedEditionPool],
):
    queryset = LimitedEditionPool.objects.select_related("company", "sku")
    serializer_class = LimitedEditionPoolSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "product.serial_rule.manage",
        "retrieve": "product.serial_rule.manage",
        "create": "product.serial_rule.manage",
        "activate": "product.serial_rule.manage",
        "generate": "product.serial_rule.manage",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: LimitedEditionPoolSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能为其他公司创建限量池。")
        serializer.save()

    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        pool = self.get_object()
        result = activate_serial_pool(pool_id=pool.pk)
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def generate(self, request: Request, pk: str | None = None) -> Response:
        pool = self.get_object()
        serializer = GenerateSerialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serials = generate_serials(
            pool_id=pool.pk, quantity=serializer.validated_data["quantity"], actor=_user(request)
        )
        return Response(ProductSerialSerializer(serials, many=True).data)


class ProductSerialViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[ProductSerial]
):
    queryset = ProductSerial.objects.select_related(
        "company",
        "sku",
        "limited_pool",
        "warehouse",
        "location",
        "current_customer",
        "current_sales_order",
        "current_production_order",
    ).prefetch_related("production_attempts", "status_history")
    serializer_class = ProductSerialSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "product.serial.read",
        "retrieve": "product.serial.read",
        "start_production": "manufacturing.quality.process",
        "dispose": "manufacturing.quality.process",
        "reserve": "sales.serial.assign",
        "auto_reserve": "sales.serial.assign",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=True, methods=["post"], url_path="start-production")
    def start_production(self, request: Request, pk: str | None = None) -> Response:
        serial = self.get_object()
        serializer = StartProductionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = start_serial_production(
            serial_id=serial.pk,
            production_order_id=data["production_order_id"],
            idempotency_key=data["idempotency_key"],
            started_at=data["started_at"],
            actor=_user(request),
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def dispose(self, request: Request, pk: str | None = None) -> Response:
        serial = self.get_object()
        serializer = DisposeSerialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = dispose_ng_serial(
            serial_id=serial.pk,
            action=serializer.validated_data["action"],
            reason=serializer.validated_data["reason"],
            actor=_user(request),
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def reserve(self, request: Request, pk: str | None = None) -> Response:
        serial = self.get_object()
        serializer = ReserveSerialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = reserve_product_serial(
            order_line_id=data["order_line_id"],
            idempotency_key=data["idempotency_key"],
            allocation_type=SerialReservation.AllocationType.SPECIFIED,
            serial_id=serial.pk,
            expires_at=data.get("expires_at"),
            actor=_user(request),
        )
        return Response(result.__dict__)

    @action(detail=False, methods=["post"], url_path="auto-reserve")
    def auto_reserve(self, request: Request) -> Response:
        serializer = ReserveSerialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = reserve_product_serial(
            order_line_id=data["order_line_id"],
            idempotency_key=data["idempotency_key"],
            allocation_type=SerialReservation.AllocationType.AUTOMATIC,
            expires_at=data.get("expires_at"),
            actor=_user(request),
        )
        return Response(result.__dict__)


class SerialAttemptViewSet(
    mixins.RetrieveModelMixin, viewsets.GenericViewSet[SerialProductionAttempt]
):
    queryset = SerialProductionAttempt.objects.select_related("serial", "production_order")
    serializer_class = SerialAttemptSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "retrieve": "product.serial.read",
        "complete": "manufacturing.quality.process",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(serial__company_id=company_id)

    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        attempt = self.get_object()
        serializer = CompleteAttemptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = complete_serial_production(
            attempt_id=attempt.pk,
            result=data["result"],
            completed_at=data["completed_at"],
            actor=_user(request),
            warehouse_id=data.get("warehouse_id"),
            location_id=data.get("location_id"),
            ng_reason=data["ng_reason"],
            inspection_reference=data["inspection_reference"],
        )
        return Response(result.__dict__)


class SerialReservationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[SerialReservation]
):
    queryset = SerialReservation.objects.select_related("serial", "sales_order_line__order")
    serializer_class = SerialReservationSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "sales.serial.assign",
        "retrieve": "sales.serial.assign",
        "release": "sales.serial.assign",
        "assign_shipment": "warehouse.pick.process",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(serial__company_id=company_id)

    @action(detail=True, methods=["post"])
    def release(self, request: Request, pk: str | None = None) -> Response:
        reservation = self.get_object()
        serializer = ReleaseSerialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = release_product_serial(
            reservation_id=reservation.pk,
            reason=serializer.validated_data["reason"],
            actor=_user(request),
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"], url_path="assign-shipment")
    def assign_shipment(self, request: Request, pk: str | None = None) -> Response:
        reservation = self.get_object()
        serializer = AssignShipmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = assign_serial_to_shipment(
            reservation_id=reservation.pk,
            shipment_line_id=serializer.validated_data["shipment_line_id"],
            actor=_user(request),
        )
        return Response(result.__dict__)

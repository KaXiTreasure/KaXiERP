from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.manufacturing.extended_serializers import (
    ActivateSerializer,
    ConvertSerializer,
    IdempotencySerializer,
    ReceiveSerializer,
    ReportSerializer,
    RoutingSerializer,
    SubcontractSerializer,
    SuggestionSerializer,
    WorkCenterSerializer,
)
from kaxi.manufacturing.extended_services import (
    activate_routing,
    approve_subcontract,
    convert_suggestion,
    receive_subcontract,
    report_operation,
    send_subcontract_materials,
)
from kaxi.manufacturing.models import (
    OperationReport,
    ProductionSuggestion,
    Routing,
    SubcontractOrder,
    WorkCenter,
)


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class CompanyViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)


class WorkCenterViewSet(CompanyViewSet):
    queryset = WorkCenter.objects.all()
    serializer_class = WorkCenterSerializer
    atomic_permissions = {
        name: "manufacturing.routing.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class RoutingViewSet(CompanyViewSet):
    queryset = Routing.objects.select_related("company", "product_sku").prefetch_related(
        "operations"
    )
    serializer_class = RoutingSerializer
    atomic_permissions = {
        name: "manufacturing.routing.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "activate",
        ]
    }

    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        serializer = ActivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = activate_routing(routing_id=self.get_object().pk, **serializer.validated_data)
        return Response(self.get_serializer(item).data)


class ReportViewSet(viewsets.ModelViewSet[OperationReport]):
    queryset = OperationReport.objects.select_related("production_order", "operation", "operator")
    serializer_class = ReportSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "manufacturing.order.manage" for name in ["list", "retrieve", "create"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return (
            queryset
            if company_id is None
            else queryset.filter(production_order__company_id=company_id)
        )

    def create(self, request: Request, *args, **kwargs) -> Response:  # type: ignore[no-untyped-def]
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        item = report_operation(
            production_order_id=data["production_order"].pk,
            operation_id=data["operation"].pk,
            report_no=data["report_no"],
            started_at=data["started_at"],
            ended_at=data["ended_at"],
            good_qty=data["good_qty"],
            rejected_qty=data["rejected_qty"],
            labor_minutes=data["labor_minutes"],
            operator=_user(request),
        )
        return Response(self.get_serializer(item).data, status=201)


class SuggestionViewSet(CompanyViewSet):
    queryset = ProductionSuggestion.objects.select_related("company", "product_sku")
    serializer_class = SuggestionSerializer
    atomic_permissions = {
        name: "manufacturing.suggestion.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy", "convert"]
    }

    @action(detail=True, methods=["post"])
    def convert(self, request: Request, pk: str | None = None) -> Response:
        serializer = ConvertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = convert_suggestion(suggestion_id=self.get_object().pk, **serializer.validated_data)
        return Response({"production_order_id": item.pk}, status=201)


class SubcontractViewSet(CompanyViewSet):
    queryset = SubcontractOrder.objects.select_related(
        "company", "supplier", "product_sku"
    ).prefetch_related("materials")
    serializer_class = SubcontractSerializer
    atomic_permissions = {
        "list": "manufacturing.subcontract.manage",
        "retrieve": "manufacturing.subcontract.manage",
        "create": "manufacturing.subcontract.manage",
        "update": "manufacturing.subcontract.manage",
        "partial_update": "manufacturing.subcontract.manage",
        "destroy": "manufacturing.subcontract.manage",
        "approve": "manufacturing.subcontract.manage",
        "send_materials": "manufacturing.material_issue",
        "receive": "manufacturing.subcontract.manage",
    }

    def perform_create(self, serializer: SubcontractSerializer) -> None:
        serializer.save(requested_by=_user(self.request))

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        item = approve_subcontract(order_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"], url_path="send-materials")
    def send_materials(self, request: Request, pk: str | None = None) -> Response:
        serializer = IdempotencySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = send_subcontract_materials(
            order_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = receive_subcontract(
            order_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(self.get_serializer(item).data)

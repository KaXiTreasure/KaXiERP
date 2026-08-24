from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.manufacturing.models import BillOfMaterial, ProductionOrder
from kaxi.manufacturing.serializers import (
    BomSerializer,
    CompletionInputSerializer,
    MaterialIssueInputSerializer,
    ProductionOrderSerializer,
    VersionSerializer,
)
from kaxi.manufacturing.services import (
    CompletionConsumptionInput,
    MaterialIssueInput,
    complete_production,
    issue_production_materials,
    transition_bom,
    transition_production_order,
)


class CompanyScopedCreateMixin:
    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()  # type: ignore[misc]
        company_id = company_id_for_request(self.request)  # type: ignore[attr-defined]
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def validate_company(self, serializer) -> None:  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)  # type: ignore[attr-defined]
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能为其他公司创建生产数据。")


class BomViewSet(
    CompanyScopedCreateMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[BillOfMaterial],
):
    queryset = BillOfMaterial.objects.select_related("company", "product_sku").prefetch_related(
        "items"
    )
    serializer_class = BomSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "manufacturing.bom.manage",
        "retrieve": "manufacturing.bom.manage",
        "create": "manufacturing.bom.manage",
        "approve": "manufacturing.bom.approve",
        "activate": "manufacturing.bom.approve",
        "obsolete": "manufacturing.bom.approve",
    }

    def perform_create(self, serializer: BomSerializer) -> None:
        self.validate_company(serializer)
        serializer.save()

    def _transition(self, action_name: str) -> Response:
        bom = self.get_object()
        result = transition_bom(bom_id=bom.pk, action=action_name)
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        return self._transition("approve")

    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        return self._transition("activate")

    @action(detail=True, methods=["post"])
    def obsolete(self, request: Request, pk: str | None = None) -> Response:
        return self._transition("obsolete")


class ProductionOrderViewSet(
    CompanyScopedCreateMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[ProductionOrder],
):
    queryset = ProductionOrder.objects.select_related(
        "company", "product_sku", "bom", "warehouse"
    ).prefetch_related("consumptions", "issues", "completions")
    serializer_class = ProductionOrderSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "manufacturing.order.manage",
        "retrieve": "manufacturing.order.manage",
        "create": "manufacturing.order.manage",
        "approve": "manufacturing.order.approve",
        "release": "manufacturing.order.manage",
        "close": "manufacturing.order.manage",
        "issue_materials": "manufacturing.material.issue",
        "complete": "manufacturing.completion.post",
    }

    def perform_create(self, serializer: ProductionOrderSerializer) -> None:
        self.validate_company(serializer)
        serializer.save()

    def _transition(self, request: Request, action_name: str) -> Response:
        order = self.get_object()
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = transition_production_order(
            order_id=order.pk,
            expected_version=serializer.validated_data["expected_version"],
            action=action_name,
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, "approve")

    @action(detail=True, methods=["post"])
    def release(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, "release")

    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, "close")

    @action(detail=True, methods=["post"], url_path="issue-materials")
    def issue_materials(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = MaterialIssueInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = issue_production_materials(
            order_id=order.pk,
            issue_no=data["issue_no"],
            idempotency_key=data["idempotency_key"],
            lines=[MaterialIssueInput(**line) for line in data["lines"]],
            operator=user,
            occurred_at=data["occurred_at"],
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = CompletionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = complete_production(
            order_id=order.pk,
            completion_no=data["completion_no"],
            idempotency_key=data["idempotency_key"],
            accepted_qty=data["accepted_qty"],
            rejected_qty=data["rejected_qty"],
            accepted_balance_id=data.get("accepted_balance_id"),
            rejected_balance_id=data.get("rejected_balance_id"),
            consumptions=[CompletionConsumptionInput(**item) for item in data["consumptions"]],
            operator=user,
            occurred_at=data["occurred_at"],
        )
        return Response(result.__dict__)

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.prepack.models import PackagingPlan, PrepackOrder
from kaxi.prepack.serializers import (
    BreakdownPrepackSerializer,
    ExecutePrepackSerializer,
    PackagingPlanSerializer,
    PrepackOrderSerializer,
    VersionSerializer,
)
from kaxi.prepack.services import (
    BreakdownMaterialInput,
    MaterialUsageInput,
    activate_packaging_plan,
    approve_prepack_order,
    breakdown_prepack,
    execute_prepack,
)


class CompanyScopedCreateMixin:
    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()  # type: ignore[misc]
        company_id = company_id_for_request(self.request)  # type: ignore[attr-defined]
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def validate_company(self, serializer) -> None:  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)  # type: ignore[attr-defined]
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能为其他公司创建预包装数据。")


class PackagingPlanViewSet(
    CompanyScopedCreateMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[PackagingPlan],
):
    queryset = PackagingPlan.objects.select_related(
        "company", "product_sku", "channel"
    ).prefetch_related("items")
    serializer_class = PackagingPlanSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "prepack.plan.manage",
        "retrieve": "prepack.plan.manage",
        "create": "prepack.plan.manage",
        "activate": "prepack.plan.approve",
    }

    def perform_create(self, serializer: PackagingPlanSerializer) -> None:
        self.validate_company(serializer)
        serializer.save()

    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        plan = self.get_object()
        result = activate_packaging_plan(plan_id=plan.pk)
        return Response(result.__dict__)


class PrepackOrderViewSet(
    CompanyScopedCreateMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[PrepackOrder],
):
    queryset = PrepackOrder.objects.select_related(
        "company",
        "warehouse",
        "product_sku",
        "packaging_plan",
        "source_location",
        "target_location",
    ).prefetch_related("executions", "breakdowns")
    serializer_class = PrepackOrderSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "prepack.order.manage",
        "retrieve": "prepack.order.manage",
        "create": "prepack.order.manage",
        "approve": "prepack.order.approve",
        "execute": "prepack.order.execute",
        "breakdown": "prepack.breakdown.approve",
    }

    def perform_create(self, serializer: PrepackOrderSerializer) -> None:
        self.validate_company(serializer)
        serializer.save()

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = approve_prepack_order(
            order_id=order.pk, expected_version=serializer.validated_data["expected_version"]
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = ExecutePrepackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = execute_prepack(
            order_id=order.pk,
            execution_no=data["execution_no"],
            quantity=data["quantity"],
            source_balance_id=data["source_balance_id"],
            target_balance_id=data["target_balance_id"],
            materials=[MaterialUsageInput(**item) for item in data["materials"]],
            idempotency_key=data["idempotency_key"],
            operator=user,
            occurred_at=data["occurred_at"],
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def breakdown(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = BreakdownPrepackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = breakdown_prepack(
            order_id=order.pk,
            breakdown_no=data["breakdown_no"],
            quantity=data["quantity"],
            prepacked_balance_id=data["prepacked_balance_id"],
            restored_product_balance_id=data["restored_product_balance_id"],
            returned_materials=[
                BreakdownMaterialInput(**item) for item in data["returned_materials"]
            ],
            approval_reference=data["approval_reference"],
            idempotency_key=data["idempotency_key"],
            operator=user,
            occurred_at=data["occurred_at"],
        )
        return Response(result.__dict__)

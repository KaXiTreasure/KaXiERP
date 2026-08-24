from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.analytics.export_services import create_snapshot
from kaxi.analytics.models import ExportJob, ReportDefinition, ReportSnapshot
from kaxi.analytics.serializers import (
    AnalyticsResponseSerializer,
    DefinitionSerializer,
    ExportJobSerializer,
    SnapshotRequestSerializer,
    SnapshotSerializer,
)
from kaxi.analytics.services import (
    arap_aging,
    dashboard,
    inventory_summary,
    procurement_summary,
    production_summary,
    profitability,
)
from kaxi.analytics.tasks import execute_export_task
from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request


def _company_id(request: Request) -> int:
    company_id = company_id_for_request(request)
    if company_id is not None:
        return company_id
    value = request.query_params.get("company_id")
    if not value or not value.isdigit():
        raise ValidationError("超级管理员查询必须指定 company_id。")
    return int(value)


class AnalyticsViewSet(viewsets.ViewSet):
    serializer_class = AnalyticsResponseSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "dashboard": "analytics.dashboard.read",
        "inventory": "analytics.inventory.read",
        "receivables": "analytics.finance.read",
        "payables": "analytics.finance.read",
        "procurement": "analytics.procurement.read",
        "production": "analytics.production.read",
        "profitability": "analytics.profitability.read",
    }
    atomic_permissions["snapshot"] = "analytics.snapshot.generate"

    @action(detail=False, methods=["get"])
    def dashboard(self, request: Request) -> Response:
        return Response(dashboard(company_id=_company_id(request)))

    @action(detail=False, methods=["get"])
    def inventory(self, request: Request) -> Response:
        return Response(inventory_summary(company_id=_company_id(request)))

    def _aging(self, request: Request, kind: str) -> Response:
        raw = request.query_params.get("as_of", "")
        as_of = parse_date(raw) if raw else None
        if raw and as_of is None:
            raise ValidationError("as_of 必须为 YYYY-MM-DD。")
        return Response(arap_aging(company_id=_company_id(request), kind=kind, as_of=as_of))

    @action(detail=False, methods=["get"])
    def receivables(self, request: Request) -> Response:
        return self._aging(request, "receivable")

    @action(detail=False, methods=["get"])
    def payables(self, request: Request) -> Response:
        return self._aging(request, "payable")

    @action(detail=False, methods=["get"])
    def procurement(self, request: Request) -> Response:
        return Response(procurement_summary(company_id=_company_id(request)))

    @action(detail=False, methods=["get"])
    def production(self, request: Request) -> Response:
        return Response(production_summary(company_id=_company_id(request)))

    @action(detail=False, methods=["get"])
    def profitability(self, request: Request) -> Response:
        return Response(profitability(company_id=_company_id(request)))


class DefinitionViewSet(viewsets.ModelViewSet[ReportDefinition]):
    queryset = ReportDefinition.objects.all()
    serializer_class = DefinitionSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "analytics.definition.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return (
            queryset
            if company_id is None
            else queryset.filter(Q(company_id=company_id) | Q(company__isnull=True))
        )

    @action(detail=True, methods=["post"])
    def snapshot(self, request: Request, pk: str | None = None) -> Response:
        serializer = SnapshotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        company_id = user.company_id or serializer.validated_data.get("company_id")
        if not company_id:
            raise ValidationError("超级管理员生成快照必须指定 company_id。")
        snapshot = create_snapshot(
            definition_id=self.get_object().pk,
            company_id=company_id,
            filters=serializer.validated_data["filters"],
            actor=user,
        )
        return Response(SnapshotSerializer(snapshot).data, status=201)


class SnapshotViewSet(viewsets.ReadOnlyModelViewSet[ReportSnapshot]):
    queryset = ReportSnapshot.objects.select_related("company", "definition", "generated_by")
    serializer_class = SnapshotSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {"list": "analytics.snapshot.read", "retrieve": "analytics.snapshot.read"}

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)


class ExportJobViewSet(viewsets.ModelViewSet[ExportJob]):
    queryset = ExportJob.objects.select_related("company", "definition", "requested_by")
    serializer_class = ExportJobSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {name: "analytics.export" for name in ["list", "retrieve", "create"]}

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: ExportJobSerializer) -> None:
        user = self.request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        company = serializer.validated_data["company"]
        definition = serializer.validated_data["definition"]
        if user.company_id is not None and company.pk != user.company_id:
            raise PermissionDenied("不能为其他公司创建导出任务。")
        if definition.company_id not in {None, company.pk}:
            raise ValidationError("报表定义不属于导出公司。")
        if set(serializer.validated_data.get("filters", {})) - set(definition.allowed_filters):
            raise ValidationError("导出筛选条件不在报表定义允许范围内。")
        job = serializer.save(
            requested_by=user,
            expires_at=serializer.validated_data.get("expires_at")
            or timezone.now() + timedelta(days=7),
        )
        transaction.on_commit(lambda: execute_export_task.delay(job.pk))

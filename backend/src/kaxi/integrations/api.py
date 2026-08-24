from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.integrations.models import (
    Connector,
    ExternalObjectMapping,
    IntegrationAccount,
    IntegrationEvent,
    SyncCursor,
    WebhookEndpoint,
)
from kaxi.integrations.serializers import (
    AccountSerializer,
    ConnectorSerializer,
    CursorSerializer,
    EventSerializer,
    MappingSerializer,
    RetrySerializer,
    WebhookSerializer,
)


class ConnectorViewSet(viewsets.ModelViewSet[Connector]):
    queryset = Connector.objects.all()
    serializer_class = ConnectorSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "integration.connector.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class CompanyOwnedViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        if company_id is None:
            return queryset
        if queryset.model is IntegrationAccount:
            return queryset.filter(company_id=company_id)
        return queryset.filter(account__company_id=company_id)

    def _company_id(self, instance) -> int:  # type: ignore[no-untyped-def]
        return (
            instance.company_id
            if isinstance(instance, IntegrationAccount)
            else instance.account.company_id
        )

    def _assert_company(self, instance) -> None:  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        if company_id is not None and self._company_id(instance) != company_id:
            raise PermissionDenied("不能写入其他公司的集成数据。")

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())


class AccountViewSet(CompanyOwnedViewSet):
    queryset = IntegrationAccount.objects.select_related("company", "connector")
    serializer_class = AccountSerializer
    atomic_permissions = {
        name: "integration.connector.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class MappingViewSet(CompanyOwnedViewSet):
    queryset = ExternalObjectMapping.objects.select_related("account")
    serializer_class = MappingSerializer
    atomic_permissions = {
        name: "integration.product_mapping.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class CursorViewSet(CompanyOwnedViewSet):
    queryset = SyncCursor.objects.select_related("account")
    serializer_class = CursorSerializer
    atomic_permissions = {
        name: "integration.sync.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class EventViewSet(CompanyOwnedViewSet):
    queryset = IntegrationEvent.objects.select_related("account")
    serializer_class = EventSerializer
    atomic_permissions = {
        "list": "integration.payload.read",
        "retrieve": "integration.payload.read",
        "create": "integration.sync.manage",
        "update": "integration.error.resolve",
        "partial_update": "integration.error.resolve",
        "destroy": "integration.error.resolve",
        "retry": "integration.error.resolve",
        "ignore": "integration.error.resolve",
        "monitor": "integration.monitor.read",
    }

    @action(detail=False, methods=["get"])
    def monitor(self, request: Request) -> Response:
        raw_hours = request.query_params.get("hours", "24")
        if not raw_hours.isdigit() or not 1 <= int(raw_hours) <= 24 * 31:
            return Response({"detail": "hours 必须为 1 至 744 的整数。"}, status=400)
        since = timezone.now() - timedelta(hours=int(raw_hours))
        events = list(self.get_queryset().filter(created_at__gte=since))
        counts = {value: 0 for value, _ in IntegrationEvent.Status.choices}
        latencies = []
        by_type: dict[str, dict[str, int]] = {}
        for event in events:
            counts[event.status] += 1
            bucket = by_type.setdefault(event.event_type, {"total": 0, "succeeded": 0, "failed": 0})
            bucket["total"] += 1
            if event.status == IntegrationEvent.Status.SUCCEEDED:
                bucket["succeeded"] += 1
                latencies.append((event.updated_at - event.created_at).total_seconds() * 1000)
            elif event.status in {IntegrationEvent.Status.FAILED, IntegrationEvent.Status.DEAD}:
                bucket["failed"] += 1
        completed = counts["succeeded"] + counts["failed"] + counts["dead"]
        return Response(
            {
                "window_hours": int(raw_hours),
                "total": len(events),
                "status_counts": counts,
                "success_rate": counts["succeeded"] / completed if completed else None,
                "average_latency_ms": sum(latencies) / len(latencies) if latencies else None,
                "by_event_type": by_type,
            }
        )

    @action(detail=True, methods=["post"])
    def retry(self, request: Request, pk: str | None = None) -> Response:
        serializer = RetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = self.get_object()
        if event.status not in {IntegrationEvent.Status.FAILED, IntegrationEvent.Status.DEAD}:
            return Response({"detail": "只有失败或死信事件可以重试。"}, status=409)
        event.status = IntegrationEvent.Status.PENDING
        event.next_attempt_at = timezone.now()
        event.error_message = f"人工重试：{serializer.validated_data['reason']}"
        event.row_version += 1
        event.save()
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["post"])
    def ignore(self, request: Request, pk: str | None = None) -> Response:
        serializer = RetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = self.get_object()
        event.status = IntegrationEvent.Status.IGNORED
        event.error_message = f"人工忽略：{serializer.validated_data['reason']}"
        event.row_version += 1
        event.save()
        return Response(self.get_serializer(event).data)


class WebhookViewSet(CompanyOwnedViewSet):
    queryset = WebhookEndpoint.objects.select_related("account")
    serializer_class = WebhookSerializer
    atomic_permissions = {
        name: "integration.webhook.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

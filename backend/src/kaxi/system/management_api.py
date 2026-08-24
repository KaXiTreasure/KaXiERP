from celery import current_app
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.shared.crud import ScopedCrudViewSet
from kaxi.shared.outbox import OutboxEvent
from kaxi.system.models import (
    BackgroundTaskExecution,
    DictionaryItem,
    DictionaryType,
    NumberRule,
    NumberSequence,
)


class DictionaryTypeSerializer(serializers.ModelSerializer[DictionaryType]):
    class Meta:
        model = DictionaryType
        fields = "__all__"


class DictionaryItemSerializer(serializers.ModelSerializer[DictionaryItem]):
    class Meta:
        model = DictionaryItem
        fields = "__all__"

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        dictionary_type = attrs.get(
            "dictionary_type", getattr(self.instance, "dictionary_type", None)
        )
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent and parent.dictionary_type_id != getattr(dictionary_type, "pk", None):
            raise ValidationError("父级字典项必须属于同一字典类型。")
        return attrs


class NumberRuleSerializer(serializers.ModelSerializer[NumberRule]):
    class Meta:
        model = NumberRule
        fields = "__all__"


class NumberSequenceSerializer(serializers.ModelSerializer[NumberSequence]):
    class Meta:
        model = NumberSequence
        fields = "__all__"


class BackgroundTaskSerializer(serializers.ModelSerializer[BackgroundTaskExecution]):
    class Meta:
        model = BackgroundTaskExecution
        fields = "__all__"


class OutboxSerializer(serializers.ModelSerializer[OutboxEvent]):
    class Meta:
        model = OutboxEvent
        fields = "__all__"


class DictionaryTypeViewSet(ScopedCrudViewSet):
    queryset = DictionaryType.objects.all().order_by("dictionary_code")
    serializer_class = DictionaryTypeSerializer
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "system.config.manage",
    )

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = self.queryset.all()
        company_id = company_id_for_request(self.request)
        return (
            queryset
            if company_id is None
            else queryset.filter(Q(company_id=company_id) | Q(company__isnull=True))
        )

    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        selected = serializer.validated_data.get("company")
        if company_id is not None and getattr(selected, "pk", None) != company_id:
            raise PermissionDenied("不能创建全局或其他公司的系统字典。")
        serializer.save()

    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        selected = serializer.validated_data.get("company", serializer.instance.company)
        if company_id is not None and getattr(selected, "pk", None) != company_id:
            raise PermissionDenied("不能修改全局或其他公司的系统字典。")
        serializer.save()


class DictionaryItemViewSet(ScopedCrudViewSet):
    queryset = DictionaryItem.objects.select_related("dictionary_type", "parent")
    serializer_class = DictionaryItemSerializer
    company_lookup = "dictionary_type__company_id"
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "system.config.manage",
    )

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = self.queryset.all()
        company_id = company_id_for_request(self.request)
        return (
            queryset
            if company_id is None
            else queryset.filter(
                Q(dictionary_type__company_id=company_id) | Q(dictionary_type__company__isnull=True)
            )
        )

    def _assert_company(self, instance):  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        if company_id is not None and instance.dictionary_type.company_id != company_id:
            raise PermissionDenied("不能修改全局或其他公司的字典项。")


class NumberRuleViewSet(ScopedCrudViewSet):
    queryset = NumberRule.objects.all().order_by("rule_code")
    serializer_class = NumberRuleSerializer
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "system.config.manage",
    )


class NumberSequenceViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = NumberSequence.objects.select_related("rule", "updated_by")
    serializer_class = NumberSequenceSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {"list": "system.config.manage", "retrieve": "system.config.manage"}

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(rule__company_id=company_id)


class BackgroundTaskViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = BackgroundTaskExecution.objects.order_by("-scheduled_at")
    serializer_class = BackgroundTaskSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "system.job.manage",
        "retrieve": "system.job.manage",
        "retry": "system.job.manage",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def retry(self, request: Request, pk: str | None = None) -> Response:
        execution = self.get_object()
        if execution.status not in {
            BackgroundTaskExecution.Status.FAILED,
            BackgroundTaskExecution.Status.DEAD,
        }:
            raise ValidationError("只有失败或死信任务可以人工重试。")
        execution.status = BackgroundTaskExecution.Status.PENDING
        execution.next_retry_at = timezone.now()
        execution.finished_at = None
        execution.save(update_fields=["status", "next_retry_at", "finished_at"])
        transaction.on_commit(
            lambda: current_app.send_task(execution.task_name, queue=execution.queue)
        )
        return Response(self.get_serializer(execution).data, status=status.HTTP_202_ACCEPTED)


class OutboxViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = OutboxEvent.objects.order_by("-occurred_at")
    serializer_class = OutboxSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "system.job.manage",
        "retrieve": "system.job.manage",
        "retry": "system.job.manage",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=True, methods=["post"])
    def retry(self, request: Request, pk: str | None = None) -> Response:
        event = self.get_object()
        if event.status not in {OutboxEvent.Status.FAILED, OutboxEvent.Status.DEAD}:
            raise ValidationError("只有失败或死信事件可以重新排队。")
        event.status = OutboxEvent.Status.PENDING
        event.next_attempt_at = timezone.now()
        event.lease_until = None
        event.worker_id = ""
        event.last_error = ""
        event.save(
            update_fields=["status", "next_attempt_at", "lease_until", "worker_id", "last_error"]
        )
        return Response(self.get_serializer(event).data, status=status.HTTP_202_ACCEPTED)

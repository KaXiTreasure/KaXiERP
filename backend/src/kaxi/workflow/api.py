from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.workflow.models import (
    ApprovalDefinition,
    ApprovalInstance,
    ApprovalRule,
    ApprovalTask,
    Notification,
    NotificationPreference,
)
from kaxi.workflow.serializers import (
    DecisionSerializer,
    DefinitionSerializer,
    InstanceSerializer,
    NotificationSerializer,
    PreferenceSerializer,
    RuleSerializer,
    StartApprovalSerializer,
    TaskSerializer,
    TransferSerializer,
)
from kaxi.workflow.services import decide_task, start_approval, transfer_task


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class DefinitionViewSet(viewsets.ModelViewSet[ApprovalDefinition]):
    queryset = ApprovalDefinition.objects.prefetch_related("nodes")
    serializer_class = DefinitionSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "workflow.definition.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)


class RuleViewSet(viewsets.ModelViewSet[ApprovalRule]):
    queryset = ApprovalRule.objects.select_related("company", "definition")
    serializer_class = RuleSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "workflow.definition.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)


class InstanceViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[ApprovalInstance]
):
    queryset = ApprovalInstance.objects.select_related("company", "applicant").prefetch_related(
        "tasks"
    )
    serializer_class = InstanceSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "workflow.task.process",
        "retrieve": "workflow.task.process",
        "start": "workflow.task.process",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=False, methods=["post"])
    def start(self, request: Request) -> Response:
        serializer = StartApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        company_id = company_id_for_request(request)
        if company_id is not None and data["company_id"] != company_id:
            raise PermissionDenied("不能为其他公司发起审批。")
        instance = start_approval(applicant=_user(request), **data)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)


class TaskViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[ApprovalTask]
):
    queryset = ApprovalTask.objects.select_related("instance", "node", "assignee", "assignee_role")
    serializer_class = TaskSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "workflow.task.process",
        "retrieve": "workflow.task.process",
        "decide": "workflow.task.process",
        "transfer": "workflow.task.delegate",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        user = _user(self.request)
        now = timezone.now()
        return (
            queryset.filter(
                Q(assignee=user)
                | Q(
                    assignee_role__userrole__user=user,
                    assignee_role__userrole__starts_at__lte=now,
                )
            )
            .filter(
                Q(assignee_role__userrole__expires_at__isnull=True)
                | Q(assignee_role__userrole__expires_at__gt=now)
                | Q(assignee=user)
            )
            .distinct()
        )

    @action(detail=True, methods=["post"])
    def decide(self, request: Request, pk: str | None = None) -> Response:
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = decide_task(
            task_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(InstanceSerializer(instance).data)

    @action(detail=True, methods=["post"])
    def transfer(self, request: Request, pk: str | None = None) -> Response:
        serializer = TransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = User.objects.get(pk=serializer.validated_data["target_user_id"])
        task = transfer_task(
            task_id=self.get_object().pk,
            actor=_user(request),
            target=target,
            comment=serializer.validated_data["comment"],
        )
        return Response(self.get_serializer(task).data, status=status.HTTP_201_CREATED)


class NotificationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[Notification]
):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "notification.read",
        "retrieve": "notification.read",
        "read": "notification.read",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return Notification.objects.filter(user=_user(self.request)).order_by("-created_at")

    @action(detail=True, methods=["post"])
    def read(self, request: Request, pk: str | None = None) -> Response:
        notice = self.get_object()
        if notice.read_at is None:
            notice.read_at = timezone.now()
            notice.row_version += 1
            notice.save(update_fields=["read_at", "row_version", "updated_at"])
        return Response(self.get_serializer(notice).data)


class PreferenceViewSet(viewsets.ModelViewSet[NotificationPreference]):
    queryset = NotificationPreference.objects.all()
    serializer_class = PreferenceSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "notification.read"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        return NotificationPreference.objects.filter(user=_user(self.request))

    def perform_create(self, serializer: PreferenceSerializer) -> None:
        serializer.save(user=_user(self.request))

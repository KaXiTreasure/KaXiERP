from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.management_serializers import (
    DepartmentSerializer,
    IdentityAuditSerializer,
    IdentityPermissionSerializer,
    OverrideSerializer,
    PositionSerializer,
    RoleSerializer,
    UserManagementSerializer,
    UserRoleSerializer,
)
from kaxi.identity.models import (
    AtomicPermission,
    AuditLog,
    Department,
    Position,
    Role,
    User,
    UserPermissionOverride,
    UserRole,
)
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


def _audit(request: Request, instance, action: str, changes: dict | None = None) -> None:  # type: ignore[no-untyped-def]
    company = getattr(instance, "company", None)
    if company is None and hasattr(instance, "user"):
        company = instance.user.company
    AuditLog.objects.create(
        company=company,
        actor=_user(request),
        action=action,
        object_type=instance._meta.label_lower,
        object_id=str(instance.pk),
        trace_id=getattr(request, "trace_id", ""),
        source_ip=request.META.get("REMOTE_ADDR") or None,
        changes=changes or {},
    )


class CompanyCrudViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]
    company_lookup = "company_id"

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return (
            queryset if company_id is None else queryset.filter(**{self.company_lookup: company_id})
        )

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        instance = serializer.save()
        company_id = company_id_for_request(self.request)
        if company_id is not None:
            actual = instance
            for part in self.company_lookup.removesuffix("_id").split("__"):
                actual = getattr(actual, part)
            if getattr(actual, "pk", actual) != company_id:
                raise PermissionDenied("不能为其他公司创建身份或权限数据。")
        _audit(self.request, instance, "identity.create")

    def _assert_company(self, instance):  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        if company_id is None:
            return
        actual = instance
        for part in self.company_lookup.removesuffix("_id").split("__"):
            actual = getattr(actual, part)
        if getattr(actual, "pk", actual) != company_id:
            raise PermissionDenied("不能把身份或权限数据转移到其他公司。")

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        instance = serializer.save()
        self._assert_company(instance)
        _audit(
            self.request, instance, "identity.update", {"fields": list(serializer.validated_data)}
        )

    @transaction.atomic
    def perform_destroy(self, instance):  # type: ignore[no-untyped-def]
        self._assert_company(instance)
        identity = (
            instance._meta.label_lower,
            str(instance.pk),
            getattr(instance, "company", None),
        )
        instance.delete()
        AuditLog.objects.create(
            company=identity[2],
            actor=_user(self.request),
            action="identity.delete",
            object_type=identity[0],
            object_id=identity[1],
            changes={},
        )


class DepartmentViewSet(CompanyCrudViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "auth.organization.manage",
    )


class PositionViewSet(DepartmentViewSet):
    queryset = Position.objects.all()
    serializer_class = PositionSerializer


class UserViewSet(CompanyCrudViewSet):
    queryset = User.objects.select_related("company", "department", "position")
    serializer_class = UserManagementSerializer
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "auth.user.manage",
    )

    def destroy(self, request: Request, *args, **kwargs) -> Response:  # type: ignore[no-untyped-def]
        user = self.get_object()
        user.status = User.Status.DISABLED
        user.is_active = False
        user.row_version += 1
        user.save()
        _audit(request, user, "identity.user.disable")
        return Response(status=204)


class PermissionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AtomicPermission.objects.order_by("permission_code")
    serializer_class = IdentityPermissionSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {"list": "auth.role.manage", "retrieve": "auth.role.manage"}


class RoleViewSet(CompanyCrudViewSet):
    queryset = Role.objects.prefetch_related("permissions")
    serializer_class = RoleSerializer
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "auth.role.manage",
    )

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = self.queryset.all()
        company_id = company_id_for_request(self.request)
        return (
            queryset
            if company_id is None
            else queryset.filter(Q(company_id=company_id) | Q(company__isnull=True))
        )


class UserRoleViewSet(CompanyCrudViewSet):
    queryset = UserRole.objects.select_related("user", "role")
    serializer_class = UserRoleSerializer
    company_lookup = "user__company_id"
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "auth.role.manage",
    )


class OverrideViewSet(CompanyCrudViewSet):
    queryset = UserPermissionOverride.objects.select_related(
        "user", "permission", "requested_by", "approved_by", "revoked_by"
    )
    serializer_class = OverrideSerializer
    company_lookup = "user__company_id"
    atomic_permissions = {
        "list": "auth.override.manage",
        "retrieve": "auth.override.manage",
        "create": "auth.override.manage",
        "approve": "auth.override.approve",
        "reject": "auth.override.approve",
        "revoke": "auth.override.revoke",
    }

    def perform_create(self, serializer: OverrideSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["user"].company_id != company_id:
            raise PermissionDenied("不能为其他公司用户申请权限覆盖。")
        override = serializer.save(requested_by=_user(self.request))
        _audit(self.request, override, "identity.override.request")

    def _decide(self, request: Request, decision: str) -> Response:
        override = self.get_object()
        actor = _user(request)
        if override.approval_status != "pending":
            raise ValidationError("授权申请已经处理。")
        if actor.pk in {override.user_id, override.requested_by_id}:
            raise PermissionDenied("授权对象、申请人和审批人必须分离。")
        override.approval_status = decision
        override.approved_by = actor
        override.approved_at = timezone.now()
        override.row_version += 1
        override.save()
        _audit(request, override, f"identity.override.{decision}")
        return Response(self.get_serializer(override).data)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        return self._decide(request, "approved")

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        return self._decide(request, "rejected")

    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, pk: str | None = None) -> Response:
        override = self.get_object()
        if override.revoked_at is None:
            override.revoked_by = _user(request)
            override.revoked_at = timezone.now()
            override.row_version += 1
            override.save()
            _audit(request, override, "identity.override.revoke")
        return Response(self.get_serializer(override).data)


class AuditViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AuditLog.objects.select_related("company", "actor").order_by("-occurred_at")
    serializer_class = IdentityAuditSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {"list": "audit.log.read", "retrieve": "audit.log.read"}

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

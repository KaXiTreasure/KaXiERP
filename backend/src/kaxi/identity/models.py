from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models.functions import Lower

from kaxi.master_data.models import Company
from kaxi.shared.models import AuditedModel


class Department(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    department_code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sys_department"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "department_code"], name="sys_department_company_code_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["company", "parent", "is_active"], name="sys_dept_tree_active_idx")
        ]


class Position(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    position_code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sys_position"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "position_code"], name="sys_position_company_code_uniq"
            )
        ]


class KaxiUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):  # type: ignore[no-untyped-def]
        extra_fields.setdefault("display_name", username)
        extra_fields.setdefault("status", "active")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Status(models.TextChoices):
        INVITED = "invited", "待激活"
        ACTIVE = "active", "正常"
        LOCKED = "locked", "锁定"
        DISABLED = "disabled", "停用"

    display_name = models.CharField(max_length=200)
    employee_no = models.CharField(max_length=100, blank=True)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT)
    position = models.ForeignKey(Position, null=True, blank=True, on_delete=models.PROTECT)
    mobile = models.CharField(max_length=50, blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    locale = models.CharField(max_length=20, default="zh-CN")
    status = models.CharField(max_length=32, choices=Status, default=Status.INVITED)
    must_change_password = models.BooleanField(default=False)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_reason = models.CharField(max_length=200, blank=True)
    row_version = models.PositiveBigIntegerField(default=1)
    objects = KaxiUserManager()

    class Meta:
        db_table = "sys_user"
        constraints = [
            models.UniqueConstraint(Lower("username"), name="sys_user_username_ci_uniq"),
            models.UniqueConstraint(
                fields=["company", "employee_no"],
                condition=~models.Q(employee_no=""),
                name="sys_user_company_employee_no_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "department", "status"], name="sys_user_org_status_idx")
        ]


class AtomicPermission(AuditedModel):
    permission_code = models.CharField(max_length=150, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    risk_level = models.CharField(max_length=16, default="normal")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sys_permission"


class Role(AuditedModel):
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    role_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    permissions = models.ManyToManyField(AtomicPermission, through="RolePermission")
    users = models.ManyToManyField(User, through="UserRole")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sys_role"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "role_code"], name="sys_role_company_code_uniq"
            )
        ]


class RolePermission(AuditedModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(AtomicPermission, on_delete=models.CASCADE)

    class Meta:
        db_table = "sys_role_permission"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="sys_role_permission_uniq")
        ]


class UserRole(AuditedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sys_user_role"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "starts_at"], name="sys_user_role_start_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("starts_at")),
                name="sys_user_role_valid_period_ck",
            ),
        ]


class UserPermissionOverride(AuditedModel):
    class Effect(models.TextChoices):
        ALLOW = "allow", "允许"
        DENY = "deny", "拒绝"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    permission = models.ForeignKey(AtomicPermission, on_delete=models.PROTECT)
    effect = models.CharField(max_length=16, choices=Effect)
    data_scope_type = models.CharField(max_length=50, blank=True)
    data_scope_value = models.JSONField(null=True, blank=True)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField()
    approval_status = models.CharField(max_length=32, default="pending")
    requested_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="requested_permission_overrides",
    )
    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_permission_overrides",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_permission_overrides",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sys_user_permission_override"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("starts_at")),
                name="sys_user_perm_override_period_ck",
            )
        ]
        indexes = [
            models.Index(
                fields=["user", "permission", "starts_at", "expires_at"],
                name="sys_user_perm_effective_idx",
            )
        ]


class AuditLog(models.Model):
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    trace_id = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    changes = models.JSONField(default=dict)

    class Meta:
        db_table = "sys_audit_log"
        indexes = [
            models.Index(fields=["company", "occurred_at"], name="sys_audit_company_time_idx"),
            models.Index(
                fields=["object_type", "object_id", "occurred_at"], name="sys_audit_object_time_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action}:{self.object_type}:{self.object_id}"

from django.conf import settings
from django.db import models

from kaxi.identity.models import Role
from kaxi.master_data.models import Company
from kaxi.shared.models import AuditedModel


class ApprovalDefinition(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        RETIRED = "retired", "停用"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    definition_code = models.CharField(max_length=100)
    business_type = models.CharField(max_length=80)
    name = models.CharField(max_length=200)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wf_approval_definition"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "definition_code", "version"],
                name="wf_definition_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="wf_definition_dates_ck",
            ),
        ]


class ApprovalNode(AuditedModel):
    class Mode(models.TextChoices):
        ANY = "any", "任一通过"
        ALL = "all", "全部通过"

    definition = models.ForeignKey(
        ApprovalDefinition, on_delete=models.PROTECT, related_name="nodes"
    )
    step_no = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    approval_mode = models.CharField(max_length=8, choices=Mode, default=Mode.ANY)
    approver_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    approver_role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.PROTECT)
    timeout_hours = models.PositiveIntegerField(default=24)

    class Meta:
        db_table = "wf_approval_node"
        constraints = [
            models.UniqueConstraint(fields=["definition", "step_no"], name="wf_node_step_uniq"),
            models.CheckConstraint(
                condition=(
                    models.Q(approver_user__isnull=False, approver_role__isnull=True)
                    | models.Q(approver_user__isnull=True, approver_role__isnull=False)
                ),
                name="wf_node_one_approver_ck",
            ),
        ]


class ApprovalRule(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    rule_code = models.CharField(max_length=100)
    business_type = models.CharField(max_length=80)
    trigger_type = models.CharField(max_length=80)
    condition_data = models.JSONField(default=dict)
    priority = models.IntegerField(default=100)
    definition = models.ForeignKey(ApprovalDefinition, on_delete=models.PROTECT)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "wf_approval_rule"
        constraints = [
            models.UniqueConstraint(fields=["company", "rule_code"], name="wf_rule_code_uniq")
        ]


class ApprovalInstance(AuditedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待审批"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已拒绝"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    definition = models.ForeignKey(ApprovalDefinition, on_delete=models.PROTECT)
    rule = models.ForeignKey(ApprovalRule, null=True, blank=True, on_delete=models.PROTECT)
    business_type = models.CharField(max_length=80)
    business_id = models.CharField(max_length=100)
    trigger_type = models.CharField(max_length=80, blank=True)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_requests"
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    current_step = models.PositiveIntegerField(default=1)
    business_snapshot = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=100)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wf_approval_instance"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"], name="wf_instance_idem_uniq"
            )
        ]


class ApprovalTask(AuditedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已拒绝"
        TRANSFERRED = "transferred", "已转交"
        CANCELLED = "cancelled", "已取消"

    instance = models.ForeignKey(ApprovalInstance, on_delete=models.PROTECT, related_name="tasks")
    node = models.ForeignKey(ApprovalNode, on_delete=models.PROTECT)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approval_tasks",
    )
    assignee_role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approval_decisions",
    )
    decision_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)
    due_at = models.DateTimeField()
    transferred_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "wf_approval_task"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(assignee__isnull=False) | models.Q(assignee_role__isnull=False),
                name="wf_task_assignee_ck",
            )
        ]
        indexes = [models.Index(fields=["assignee", "status", "due_at"], name="wf_task_inbox_idx")]


class Notification(AuditedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(max_length=50)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)
    business_type = models.CharField(max_length=80, blank=True)
    business_id = models.CharField(max_length=100, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sys_notification"
        indexes = [
            models.Index(fields=["user", "read_at", "-created_at"], name="sys_notice_inbox_idx")
        ]


class NotificationPreference(AuditedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notification_type = models.CharField(max_length=50)
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "sys_notification_preference"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "notification_type"], name="sys_notice_pref_uniq"
            )
        ]

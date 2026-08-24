from django.db import models

from kaxi.master_data.models import Company
from kaxi.shared.models import AuditedModel


class Connector(AuditedModel):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    connector_type = models.CharField(max_length=32)
    capabilities = models.JSONField(default=list)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "int_connector"


class IntegrationAccount(AuditedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        EXPIRED = "expired", "已过期"
        REVOKED = "revoked", "已撤销"
        ERROR = "error", "异常"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    connector = models.ForeignKey(Connector, on_delete=models.PROTECT)
    account_code = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    credential_reference = models.CharField(max_length=500)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    authorization_expires_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "int_account"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "connector", "account_code"], name="int_account_code_uniq"
            )
        ]


class ExternalObjectMapping(AuditedModel):
    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT)
    object_type = models.CharField(max_length=50)
    internal_id = models.CharField(max_length=100)
    external_id = models.CharField(max_length=300)
    external_code = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=16, default="active")

    class Meta:
        db_table = "int_external_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "object_type", "external_id"],
                name="int_mapping_external_uniq",
            ),
            models.UniqueConstraint(
                fields=["account", "object_type", "internal_id"],
                name="int_mapping_internal_uniq",
            ),
        ]


class SyncCursor(AuditedModel):
    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT)
    object_type = models.CharField(max_length=50)
    cursor = models.CharField(max_length=1000, blank=True)
    watermark = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "int_sync_cursor"
        constraints = [
            models.UniqueConstraint(fields=["account", "object_type"], name="int_sync_cursor_uniq")
        ]


class IntegrationEvent(AuditedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        PROCESSING = "processing", "处理中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        DEAD = "dead", "死信"
        IGNORED = "ignored", "忽略"

    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT)
    direction = models.CharField(max_length=8, choices=[("in", "入站"), ("out", "出站")])
    event_type = models.CharField(max_length=100)
    external_id = models.CharField(max_length=300, blank=True)
    idempotency_key = models.CharField(max_length=200)
    payload_reference = models.CharField(max_length=1000)
    payload_sha256 = models.CharField(max_length=64)
    signature_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=8)
    next_attempt_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=100, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    internal_object_type = models.CharField(max_length=50, blank=True)
    internal_object_id = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "int_event"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "direction", "idempotency_key"],
                name="int_event_idem_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gt=0), name="int_event_max_attempts_ck"
            ),
        ]
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="int_event_queue_idx")]


class WebhookEndpoint(AuditedModel):
    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT)
    event_type = models.CharField(max_length=100)
    callback_url = models.URLField(max_length=1000)
    secret_reference = models.CharField(max_length=500)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "int_webhook_endpoint"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "event_type", "callback_url"], name="int_webhook_uniq"
            )
        ]

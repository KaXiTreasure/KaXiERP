from django.db import models
from django.utils import timezone

from kaxi.master_data.models import Company


class OutboxEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待投递"
        PROCESSING = "processing", "处理中"
        PUBLISHED = "published", "已投递"
        FAILED = "failed", "失败"
        DEAD = "dead", "死信"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    aggregate_type = models.CharField(max_length=100)
    aggregate_id = models.CharField(max_length=100)
    aggregate_version = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=150)
    event_version = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField()
    occurred_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    priority = models.SmallIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=100, blank=True)
    trace_id = models.CharField(max_length=64, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        db_table = "evt_outbox"
        constraints = [
            models.UniqueConstraint(
                fields=["aggregate_type", "aggregate_id", "event_type", "aggregate_version"],
                name="evt_outbox_aggregate_event_version_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at", "priority", "id"],
                name="evt_outbox_pending_claim_idx",
                condition=models.Q(status="pending"),
            ),
            models.Index(fields=["company", "occurred_at"], name="evt_outbox_company_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}:{self.aggregate_type}:{self.aggregate_id}"

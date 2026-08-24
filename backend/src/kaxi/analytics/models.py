from django.conf import settings
from django.db import models

from kaxi.master_data.models import Company
from kaxi.shared.models import AuditedModel


class ReportDefinition(AuditedModel):
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    report_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=50)
    allowed_filters = models.JSONField(default=list)
    default_columns = models.JSONField(default=list)
    permission_code = models.CharField(max_length=150)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "ana_report_definition"
        constraints = [
            models.UniqueConstraint(fields=["company", "report_code"], name="ana_report_code_uniq")
        ]


class ReportSnapshot(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    definition = models.ForeignKey(ReportDefinition, on_delete=models.PROTECT)
    snapshot_no = models.CharField(max_length=100)
    as_of = models.DateTimeField()
    filters = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    result_sha256 = models.CharField(max_length=64)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        db_table = "ana_report_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "snapshot_no"], name="ana_report_snapshot_no_uniq"
            )
        ]


class ExportJob(AuditedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        PROCESSING = "processing", "处理中"
        COMPLETED = "completed", "完成"
        FAILED = "failed", "失败"
        EXPIRED = "expired", "已过期"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    definition = models.ForeignKey(ReportDefinition, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    format = models.CharField(max_length=8, choices=[("csv", "CSV"), ("xlsx", "Excel")])
    filters = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    file_object = models.ForeignKey(
        "documents.FileObject", null=True, blank=True, on_delete=models.PROTECT
    )
    error_message = models.TextField(blank=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "ana_export_job"

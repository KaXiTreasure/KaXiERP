from django.conf import settings
from django.db import models

from kaxi.master_data.models import Company
from kaxi.shared.models import AuditedModel


class FileCategory(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "doc_file_category"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="doc_category_code_uniq")
        ]


class RetentionPolicy(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    retain_days = models.PositiveIntegerField()
    archive_after_days = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "doc_retention_policy"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="doc_retention_code_uniq")
        ]


class FileObject(AuditedModel):
    class Security(models.TextChoices):
        L1 = "L1", "公开业务"
        L2 = "L2", "内部"
        L3 = "L3", "敏感"
        L4 = "L4", "高度敏感"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "有效"
        VOID = "void", "作废"
        ARCHIVED = "archived", "归档"
        RECYCLED = "recycled", "回收站"
        DISPOSED = "disposed", "已销毁"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    file_no = models.CharField(max_length=50)
    title = models.CharField(max_length=500)
    category = models.ForeignKey(FileCategory, on_delete=models.PROTECT)
    security_level = models.CharField(max_length=2, choices=Security, default=Security.L2)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    retention_policy = models.ForeignKey(
        RetentionPolicy, null=True, blank=True, on_delete=models.PROTECT
    )
    current_version = models.ForeignKey(
        "FileVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_files",
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    legal_hold = models.BooleanField(default=False)
    legal_hold_reason = models.TextField(blank=True)

    class Meta:
        db_table = "doc_file_object"
        constraints = [
            models.UniqueConstraint(fields=["company", "file_no"], name="doc_file_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_from__isnull=True)
                | models.Q(valid_to__gte=models.F("valid_from")),
                name="doc_file_valid_dates_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "category", "status", "security_level"],
                name="doc_file_library_idx",
            )
        ]


class FileVersion(AuditedModel):
    class ScanStatus(models.TextChoices):
        PENDING = "pending", "待扫描"
        CLEAN = "clean", "安全"
        QUARANTINED = "quarantined", "隔离"
        FAILED = "failed", "扫描失败"

    file_object = models.ForeignKey(FileObject, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    original_filename = models.CharField(max_length=500)
    storage_provider = models.CharField(max_length=50, default="minio")
    storage_key = models.CharField(max_length=1000, unique=True)
    mime_type = models.CharField(max_length=200)
    extension = models.CharField(max_length=32, blank=True)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    scan_status = models.CharField(max_length=16, choices=ScanStatus, default=ScanStatus.PENDING)
    source_type = models.CharField(max_length=32, default="upload")
    template_version = models.CharField(max_length=50, blank=True)
    business_snapshot = models.JSONField(null=True, blank=True)
    change_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        db_table = "doc_file_version"
        constraints = [
            models.UniqueConstraint(
                fields=["file_object", "version_no"], name="doc_file_version_uniq"
            )
        ]
        indexes = [models.Index(fields=["sha256", "size_bytes"], name="doc_version_hash_idx")]


class FileTag(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "doc_file_tag"
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="doc_tag_name_uniq")
        ]


class FileObjectTag(AuditedModel):
    file_object = models.ForeignKey(FileObject, on_delete=models.CASCADE)
    tag = models.ForeignKey(FileTag, on_delete=models.CASCADE)

    class Meta:
        db_table = "doc_file_object_tag"
        constraints = [
            models.UniqueConstraint(fields=["file_object", "tag"], name="doc_file_tag_uniq")
        ]


class FileBusinessLink(AuditedModel):
    file_object = models.ForeignKey(
        FileObject, on_delete=models.PROTECT, related_name="business_links"
    )
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=100)
    relation_type = models.CharField(max_length=50)
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "doc_file_business_link"
        constraints = [
            models.UniqueConstraint(
                fields=["file_object", "object_type", "object_id", "relation_type"],
                name="doc_file_business_link_uniq",
            )
        ]


class FilePermission(AuditedModel):
    class Action(models.TextChoices):
        READ = "read", "查看"
        DOWNLOAD = "download", "下载"
        MANAGE = "manage", "管理"

    file_object = models.ForeignKey(FileObject, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=16, choices=Action)
    expires_at = models.DateTimeField(null=True, blank=True)
    approval_reference = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "doc_file_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["file_object", "user", "action"], name="doc_file_permission_uniq"
            )
        ]


class ShareLink(AuditedModel):
    file_object = models.ForeignKey(FileObject, on_delete=models.PROTECT, related_name="shares")
    token_hash = models.CharField(max_length=64, unique=True)
    password_hash = models.CharField(max_length=200, blank=True)
    expires_at = models.DateTimeField()
    max_downloads = models.PositiveIntegerField(default=1)
    download_count = models.PositiveIntegerField(default=0)
    watermark = models.CharField(max_length=300, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        db_table = "doc_file_share_link"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(download_count__lte=models.F("max_downloads")),
                name="doc_share_download_limit_ck",
            )
        ]


class FileAuditLog(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    file_object = models.ForeignKey(FileObject, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=50)
    detail = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "doc_file_audit_log"
        indexes = [models.Index(fields=["file_object", "-occurred_at"], name="doc_audit_file_idx")]

    def __str__(self) -> str:
        return f"{self.file_object_id}:{self.action}:{self.occurred_at.isoformat()}"


class DisposalBatch(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        EXECUTED = "executed", "已执行"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    batch_no = models.CharField(max_length=50)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="disposal_requests"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_disposals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "doc_disposal_batch"
        constraints = [
            models.UniqueConstraint(fields=["company", "batch_no"], name="doc_disposal_no_uniq")
        ]


class DisposalItem(AuditedModel):
    batch = models.ForeignKey(DisposalBatch, on_delete=models.PROTECT, related_name="items")
    file_object = models.ForeignKey(FileObject, on_delete=models.PROTECT)
    reason = models.TextField()

    class Meta:
        db_table = "doc_disposal_item"
        constraints = [
            models.UniqueConstraint(fields=["batch", "file_object"], name="doc_disposal_item_uniq")
        ]

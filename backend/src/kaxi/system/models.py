from django.conf import settings
from django.db import models

from kaxi.master_data.models import Company
from kaxi.shared.models import AuditedModel


class DictionaryType(AuditedModel):
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    dictionary_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sys_dictionary_type"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "dictionary_code"],
                nulls_distinct=False,
                name="sys_dict_type_company_code_uniq",
            )
        ]


class DictionaryItem(AuditedModel):
    dictionary_type = models.ForeignKey(
        DictionaryType, on_delete=models.PROTECT, related_name="items"
    )
    item_value = models.CharField(max_length=100)
    label_zh = models.CharField(max_length=200)
    label_en = models.CharField(max_length=200, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    sort_order = models.IntegerField(default=0)
    extension_data = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sys_dictionary_item"
        constraints = [
            models.UniqueConstraint(
                fields=["dictionary_type", "item_value"], name="sys_dict_item_type_value_uniq"
            )
        ]
        indexes = [
            models.Index(
                fields=["dictionary_type", "is_active", "sort_order"],
                name="sys_dict_item_lookup_idx",
            )
        ]


class NumberRule(AuditedModel):
    class ResetPeriod(models.TextChoices):
        NEVER = "never", "不重置"
        YEAR = "year", "每年"
        MONTH = "month", "每月"
        DAY = "day", "每日"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    rule_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    prefix_template = models.CharField(max_length=100, blank=True)
    date_format = models.CharField(max_length=32, blank=True)
    separator = models.CharField(max_length=5, blank=True)
    sequence_length = models.PositiveSmallIntegerField(default=6)
    reset_period = models.CharField(max_length=16, choices=ResetPeriod, default=ResetPeriod.NEVER)
    starts_from = models.PositiveBigIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sys_number_rule"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "rule_code"], name="sys_number_rule_company_code_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_length__gte=1, sequence_length__lte=20),
                name="sys_number_rule_seq_length_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(starts_from__gte=1), name="sys_number_rule_starts_from_ck"
            ),
        ]


class NumberSequence(models.Model):
    rule = models.ForeignKey(NumberRule, on_delete=models.PROTECT, related_name="sequences")
    period_key = models.CharField(max_length=16)
    last_value = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        db_table = "sys_number_sequence"
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "period_key"], name="sys_number_sequence_rule_period_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.rule_id}:{self.period_key}:{self.last_value}"


class FontAsset(AuditedModel):
    class Coverage(models.TextChoices):
        COMBINED = "combined", "中西文"
        CJK_ONLY = "cjk_only", "仅中文"
        LATIN_ONLY = "latin_only", "仅西文"

    family_name = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200)
    storage_key = models.CharField(max_length=1000, unique=True)
    mime_type = models.CharField(max_length=100)
    original_filename = models.CharField(max_length=500)
    coverage = models.CharField(max_length=20, choices=Coverage)
    latin_supported = models.BooleanField(default=False)
    cjk_glyph_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "sys_font_asset"


class BrandingConfiguration(AuditedModel):
    class BackgroundSource(models.TextChoices):
        LOCAL = "local", "本地上传"
        BING = "bing", "Bing 每日图片"

    singleton_key = models.CharField(max_length=20, unique=True, default="global", editable=False)
    app_name = models.CharField(max_length=80, default="KAXI ERP")
    version_name = models.CharField(max_length=40, default="V1.0")
    theme = models.CharField(max_length=20, default="forest")
    login_card_opacity = models.PositiveSmallIntegerField(default=92)
    login_footer_text = models.CharField(
        max_length=300, default="V1.0 · 全链路追溯", blank=True
    )
    login_footer_links = models.JSONField(default=list, blank=True)
    login_slogan = models.CharField(max_length=120, default="Slogan", blank=True)
    login_slogan_1 = models.CharField(max_length=120, default="Slogan1", blank=True)
    login_slogan_2 = models.CharField(max_length=500, default="Slogan2", blank=True)
    logo_storage_key = models.CharField(max_length=1000, blank=True)
    logo_mime_type = models.CharField(max_length=100, blank=True)
    background_storage_key = models.CharField(max_length=1000, blank=True)
    background_mime_type = models.CharField(max_length=100, blank=True)
    background_source = models.CharField(
        max_length=16, choices=BackgroundSource, default=BackgroundSource.LOCAL
    )
    bing_image_title = models.CharField(max_length=300, blank=True)
    bing_image_copyright = models.CharField(max_length=1000, blank=True)
    bing_image_date = models.CharField(max_length=8, blank=True)
    bing_last_synced_at = models.DateTimeField(null=True, blank=True)
    primary_font = models.ForeignKey(
        FontAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="primary_for"
    )
    western_font = models.ForeignKey(
        FontAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="western_for"
    )

    class Meta:
        db_table = "sys_branding_configuration"


class BackgroundTaskExecution(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        PROCESSING = "processing", "执行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        DEAD = "dead", "死信"

    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    task_name = models.CharField(max_length=150)
    task_version = models.PositiveSmallIntegerField(default=1)
    idempotency_key = models.CharField(max_length=200)
    source_type = models.CharField(max_length=80, blank=True)
    source_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    priority = models.SmallIntegerField(default=0)
    queue = models.CharField(max_length=32)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    scheduled_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_summary = models.TextField(blank=True)
    trace_id = models.CharField(max_length=64, blank=True)
    result_reference = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "sys_background_task_execution"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "task_name", "task_version", "idempotency_key"],
                nulls_distinct=False,
                name="sys_task_execution_idem_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["status", "queue", "scheduled_at"], name="sys_task_status_queue_idx"
            ),
            models.Index(fields=["task_name", "finished_at"], name="sys_task_name_finish_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.task_name}:{self.idempotency_key}:{self.status}"


class DataImportBatch(AuditedModel):
    class Entity(models.TextChoices):
        PARTY = "party", "客商"
        SKU = "sku", "SKU"
        OPENING_INVENTORY = "opening_inventory", "期初库存"

    class Status(models.TextChoices):
        STAGED = "staged", "已暂存"
        VALIDATED = "validated", "校验通过"
        INVALID = "invalid", "校验失败"
        COMMITTED = "committed", "已提交"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    batch_no = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=32, choices=Entity)
    source_filename = models.CharField(max_length=300)
    source_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status, default=Status.STAGED)
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    invalid_rows = models.PositiveIntegerField(default=0)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sys_data_import_batch"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "batch_no"], name="sys_import_batch_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["company", "entity_type", "source_sha256"],
                name="sys_import_source_idem_uniq",
            ),
        ]


class DataImportRow(models.Model):
    class Status(models.TextChoices):
        STAGED = "staged", "已暂存"
        VALID = "valid", "有效"
        INVALID = "invalid", "无效"
        COMMITTED = "committed", "已提交"

    batch = models.ForeignKey(DataImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    source_data = models.JSONField()
    normalized_data = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status, default=Status.STAGED)
    errors = models.JSONField(default=list)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "sys_data_import_row"
        constraints = [
            models.UniqueConstraint(fields=["batch", "row_number"], name="sys_import_row_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.batch_id}:{self.row_number}:{self.status}"

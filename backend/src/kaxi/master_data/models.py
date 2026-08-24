from django.conf import settings
from django.db import models
from django.utils import timezone

from kaxi.shared.models import AuditedModel


class RecordStatus(models.TextChoices):
    ACTIVE = "active", "启用"
    INACTIVE = "inactive", "停用"


class Currency(AuditedModel):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    status = models.CharField(max_length=32, choices=RecordStatus, default=RecordStatus.ACTIVE)

    class Meta:
        db_table = "md_currency"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(decimal_places__lte=6),
                name="md_currency_decimal_places_lte_6",
            ),
        ]


class Region(AuditedModel):
    code = models.CharField(max_length=32, unique=True)
    name_zh = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, choices=RecordStatus, default=RecordStatus.ACTIVE)

    class Meta:
        db_table = "md_region"
        indexes = [models.Index(fields=["parent", "status"], name="md_region_parent_status_idx")]


class Company(AuditedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    company_code = models.CharField(max_length=50, unique=True)
    legal_name = models.CharField(max_length=300)
    display_name = models.CharField(max_length=300)
    base_currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    registered_region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.PROTECT)
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    status = models.CharField(max_length=32, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "sys_company"


class UnitOfMeasure(AuditedModel):
    class Dimension(models.TextChoices):
        COUNT = "count", "数量"
        WEIGHT = "weight", "重量"
        LENGTH = "length", "长度"
        AREA = "area", "面积"
        VOLUME = "volume", "体积"
        OTHER = "other", "其他"

    uom_code = models.CharField(max_length=32, unique=True)
    name_zh = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100, blank=True)
    symbol = models.CharField(max_length=20)
    dimension = models.CharField(max_length=16, choices=Dimension)
    decimal_places = models.PositiveSmallIntegerField(default=6)
    status = models.CharField(max_length=32, choices=RecordStatus, default=RecordStatus.ACTIVE)

    class Meta:
        db_table = "md_unit_of_measure"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(decimal_places__lte=6), name="md_uom_decimal_places_lte_6"
            )
        ]


class Party(AuditedModel):
    class PartyType(models.TextChoices):
        ORGANIZATION = "organization", "组织"
        PERSON = "person", "个人"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        SUSPENDED = "suspended", "暂停"
        INACTIVE = "inactive", "停用"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    party_no = models.CharField(max_length=50)
    party_type = models.CharField(max_length=16, choices=PartyType)
    legal_name = models.CharField(max_length=300)
    display_name = models.CharField(max_length=300)
    country_region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.PROTECT)
    default_language = models.CharField(max_length=20, blank=True)
    default_currency = models.ForeignKey(Currency, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    risk_level = models.CharField(max_length=32, blank=True)
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_sources"
    )
    merged_at = models.DateTimeField(null=True, blank=True)
    merged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merged_parties",
    )

    class Meta:
        db_table = "mdm_party"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "party_no"], name="mdm_party_company_no_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["company", "status", "display_name"], name="mdm_party_lookup_idx")
        ]


class PartyMergeCandidate(AuditedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        APPROVED = "approved", "已合并"
        REJECTED = "rejected", "非重复"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    canonical_party = models.ForeignKey(
        Party, on_delete=models.PROTECT, related_name="canonical_merge_candidates"
    )
    duplicate_party = models.ForeignKey(
        Party, on_delete=models.PROTECT, related_name="duplicate_merge_candidates"
    )
    match_score = models.DecimalField(max_digits=5, decimal_places=4)
    match_reasons = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_party_merges"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decided_party_merges",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True)
    reference_counts = models.JSONField(default=dict)

    class Meta:
        db_table = "mdm_party_merge_candidate"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "canonical_party", "duplicate_party"],
                name="mdm_party_merge_pair_uniq",
            ),
            models.CheckConstraint(
                condition=~models.Q(canonical_party=models.F("duplicate_party")),
                name="mdm_party_merge_distinct_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(match_score__gte=0) & models.Q(match_score__lte=1),
                name="mdm_party_merge_score_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status", "-created_at"], name="mdm_merge_queue_idx")
        ]

    def mark_decided(self, *, actor, status: str, reason: str = "") -> None:  # type: ignore[no-untyped-def]
        self.status = status
        self.decided_by = actor
        self.decided_at = timezone.now()
        self.decision_reason = reason


class CustomerProfile(AuditedModel):
    party = models.OneToOneField(Party, primary_key=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, default="active")

    class Meta:
        db_table = "mdm_customer_profile"


class SupplierProfile(AuditedModel):
    party = models.OneToOneField(Party, primary_key=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, default="active")

    class Meta:
        db_table = "mdm_supplier_profile"


class PartyContact(AuditedModel):
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="contacts")
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=50, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "mdm_party_contact"
        indexes = [models.Index(fields=["party", "is_active"], name="mdm_contact_party_active_idx")]


class Address(AuditedModel):
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="addresses")
    address_code = models.CharField(max_length=50)
    address_type = models.CharField(max_length=16)
    country_region = models.ForeignKey(Region, on_delete=models.PROTECT)
    province = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    address_line1 = models.CharField(max_length=500)
    address_line2 = models.CharField(max_length=500, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    recipient_name = models.CharField(max_length=200, blank=True)
    recipient_phone = models.CharField(max_length=50, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "mdm_address"
        constraints = [
            models.UniqueConstraint(
                fields=["party", "address_code"], name="mdm_address_party_code_uniq"
            )
        ]

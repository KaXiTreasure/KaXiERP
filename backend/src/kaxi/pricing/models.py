from django.db import models

from kaxi.master_data.models import Company, Currency, Party, UnitOfMeasure
from kaxi.products.models import ProductCategory, ProductSku
from kaxi.sales.models import SalesChannel
from kaxi.shared.models import AuditedModel


class PricingPolicy(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    policy_code = models.CharField(max_length=50)
    customer_special_priority = models.IntegerField(default=500)
    agent_sku_priority = models.IntegerField(default=400)
    agent_category_priority = models.IntegerField(default=300)
    channel_priority = models.IntegerField(default=200)
    standard_priority = models.IntegerField(default=100)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prc_policy"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "policy_code", "valid_from"],
                name="prc_policy_company_code_start_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="prc_policy_period_ck",
            ),
        ]


class PriceList(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        ACTIVE = "active", "启用"
        EXPIRED = "expired", "已过期"
        DISABLED = "disabled", "停用"

    class TaxMode(models.TextChoices):
        INCLUDED = "tax_included", "含税"
        EXCLUDED = "tax_excluded", "未税"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    price_list_no = models.CharField(max_length=100)
    name = models.CharField(max_length=300)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    channel = models.ForeignKey(SalesChannel, null=True, blank=True, on_delete=models.PROTECT)
    customer_type = models.CharField(max_length=32, blank=True)
    tax_mode = models.CharField(max_length=20, choices=TaxMode)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    priority = models.IntegerField(default=0)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)

    class Meta:
        db_table = "prc_price_list"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "price_list_no"], name="prc_price_list_company_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="prc_price_list_period_ck",
            ),
        ]


class PriceListItem(AuditedModel):
    price_list = models.ForeignKey(PriceList, on_delete=models.PROTECT, related_name="items")
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    unit_price = models.DecimalField(max_digits=20, decimal_places=6)
    minimum_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    minimum_discount_rate = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )
    min_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    max_qty = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prc_price_list_item"
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "sku", "uom", "min_qty"],
                name="prc_price_item_scope_qty_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="prc_item_price_nonnegative_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_price__isnull=True) | models.Q(minimum_price__gte=0),
                name="prc_item_floor_nonnegative_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(max_qty__isnull=True)
                | models.Q(max_qty__gt=models.F("min_qty")),
                name="prc_item_qty_range_ck",
            ),
        ]


class AgentLevel(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    level_code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    sort_order = models.IntegerField(default=0)
    default_discount_rate = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prc_agent_level"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "level_code"], name="prc_agent_level_company_code_uniq"
            )
        ]


class AgentProfile(AuditedModel):
    party = models.OneToOneField(Party, primary_key=True, on_delete=models.PROTECT)
    agent_level = models.ForeignKey(AgentLevel, on_delete=models.PROTECT)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, default="active")

    class Meta:
        db_table = "prc_agent_profile"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gt=models.F("effective_from")),
                name="prc_agent_profile_period_ck",
            )
        ]


class AgentDiscountRule(AuditedModel):
    agent_level = models.ForeignKey(AgentLevel, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, null=True, blank=True, on_delete=models.PROTECT)
    product_category = models.ForeignKey(
        ProductCategory, null=True, blank=True, on_delete=models.PROTECT
    )
    discount_rate = models.DecimalField(max_digits=12, decimal_places=6)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prc_agent_discount_rule"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(sku__isnull=False) & models.Q(product_category__isnull=True))
                | (models.Q(sku__isnull=True) & models.Q(product_category__isnull=False)),
                name="prc_agent_rule_one_scope_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_rate__gt=0, discount_rate__lte=1),
                name="prc_agent_rule_discount_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="prc_agent_rule_period_ck",
            ),
        ]


class CustomerSpecialPrice(AuditedModel):
    customer = models.ForeignKey(Party, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    special_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    special_discount_rate = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )
    priority = models.IntegerField(default=0)
    can_break_floor = models.BooleanField(default=False)
    approval_id = models.PositiveBigIntegerField(null=True, blank=True)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    reason = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prc_customer_special_price"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(special_price__isnull=False)
                    & models.Q(special_discount_rate__isnull=True)
                )
                | (
                    models.Q(special_price__isnull=True)
                    & models.Q(special_discount_rate__isnull=False)
                ),
                name="prc_special_price_one_method_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(special_discount_rate__isnull=True)
                | models.Q(special_discount_rate__gt=0, special_discount_rate__lte=1),
                name="prc_special_discount_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(can_break_floor=False) | models.Q(approval_id__isnull=False),
                name="prc_special_floor_approval_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="prc_special_period_ck",
            ),
        ]

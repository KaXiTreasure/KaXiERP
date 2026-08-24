from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from kaxi.master_data.models import Company, Currency, Party
from kaxi.shared.models import AuditedModel


class Ledger(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    base_currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "fin_ledger"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="fin_ledger_code_uniq")
        ]


class ChartOfAccounts(AuditedModel):
    ledger = models.ForeignKey(Ledger, on_delete=models.PROTECT, related_name="charts")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "fin_chart_of_accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["ledger", "code", "version"], name="fin_chart_version_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="fin_chart_dates_ck",
            ),
        ]


class Account(AuditedModel):
    class Type(models.TextChoices):
        ASSET = "asset", "资产"
        LIABILITY = "liability", "负债"
        EQUITY = "equity", "权益"
        REVENUE = "revenue", "收入"
        EXPENSE = "expense", "费用"

    class Balance(models.TextChoices):
        DEBIT = "debit", "借"
        CREDIT = "credit", "贷"

    class CashFlow(models.TextChoices):
        NONE = "", "不适用"
        OPERATING = "operating", "经营活动"
        INVESTING = "investing", "投资活动"
        FINANCING = "financing", "筹资活动"
        CASH = "cash", "现金及现金等价物"

    chart = models.ForeignKey(ChartOfAccounts, on_delete=models.PROTECT, related_name="accounts")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=16, choices=Type)
    normal_balance = models.CharField(max_length=8, choices=Balance)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    allow_posting = models.BooleanField(default=True)
    requires_party = models.BooleanField(default=False)
    cash_flow_category = models.CharField(max_length=16, choices=CashFlow, blank=True, default="")
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "fin_account"
        constraints = [
            models.UniqueConstraint(fields=["chart", "code"], name="fin_account_code_uniq")
        ]
        indexes = [models.Index(fields=["chart", "active", "code"], name="fin_account_lookup_idx")]


class FiscalPeriod(AuditedModel):
    class Status(models.TextChoices):
        OPEN = "open", "开放"
        CLOSED = "closed", "已结账"
        REOPENED = "reopened", "已重开"

    ledger = models.ForeignKey(Ledger, on_delete=models.PROTECT, related_name="periods")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="closed_periods",
    )
    reopen_reason = models.TextField(blank=True)

    class Meta:
        db_table = "fin_fiscal_period"
        constraints = [
            models.UniqueConstraint(fields=["ledger", "year", "month"], name="fin_period_ym_uniq"),
            models.CheckConstraint(
                condition=models.Q(month__gte=1) & models.Q(month__lte=12),
                name="fin_period_month_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")), name="fin_period_dates_ck"
            ),
        ]


class JournalEntry(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已审核"
        POSTED = "posted", "已过账"
        REVERSED = "reversed", "已冲销"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    ledger = models.ForeignKey(Ledger, on_delete=models.PROTECT, related_name="journals")
    period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT, related_name="journals")
    voucher_no = models.CharField(max_length=64)
    entry_type = models.CharField(max_length=32, default="general")
    entry_date = models.DateField()
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    source_type = models.CharField(max_length=64, blank=True)
    source_id = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=100, blank=True, default="")
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal"
    )
    total_debit_base = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    total_credit_base = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_journals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="posted_journals",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fin_journal_entry"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "ledger", "period", "entry_type", "voucher_no"],
                name="fin_voucher_no_uniq",
            ),
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="fin_journal_idem_uniq",
            ),
        ]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values("status").first()
            if old and old["status"] in {self.Status.POSTED, self.Status.REVERSED}:
                raise ValidationError("已过账凭证不可直接修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.status in {self.Status.POSTED, self.Status.REVERSED}:
            raise ValidationError("已过账凭证不可删除。")
        return super().delete(*args, **kwargs)


class JournalEntryLine(AuditedModel):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    summary = models.CharField(max_length=500, blank=True)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    debit_original = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    credit_original = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    debit_base = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    credit_base = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "fin_journal_entry_line"
        constraints = [
            models.UniqueConstraint(fields=["entry", "line_no"], name="fin_journal_line_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(exchange_rate__gt=0), name="fin_journal_rate_positive_ck"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(debit_base__gt=0, credit_base=0)
                    | models.Q(credit_base__gt=0, debit_base=0)
                ),
                name="fin_journal_one_side_ck",
            ),
        ]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if (
            self.entry_id
            and JournalEntry.objects.filter(
                pk=self.entry_id,
                status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED],
            ).exists()
        ):
            raise ValidationError("已过账凭证分录不可修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.entry.status in {JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED}:
            raise ValidationError("已过账凭证分录不可删除。")
        return super().delete(*args, **kwargs)


class OpenItem(AuditedModel):
    class Kind(models.TextChoices):
        RECEIVABLE = "receivable", "应收"
        PAYABLE = "payable", "应付"

    class Status(models.TextChoices):
        OPEN = "open", "未核销"
        PARTIAL = "partial", "部分核销"
        SETTLED = "settled", "已核销"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind)
    item_no = models.CharField(max_length=64)
    party = models.ForeignKey(Party, on_delete=models.PROTECT)
    source_type = models.CharField(max_length=64)
    source_id = models.CharField(max_length=100)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    original_amount = models.DecimalField(max_digits=20, decimal_places=6)
    base_amount = models.DecimalField(max_digits=20, decimal_places=6)
    allocated_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    allocated_base_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    due_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    journal = models.ForeignKey(JournalEntry, on_delete=models.PROTECT)

    class Meta:
        db_table = "fin_open_item"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind", "item_no"], name="fin_open_item_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(original_amount__gt=0) & models.Q(base_amount__gt=0),
                name="fin_open_item_amount_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(allocated_amount__gte=0)
                & models.Q(allocated_amount__lte=models.F("original_amount")),
                name="fin_open_item_alloc_ck",
            ),
        ]


class Settlement(AuditedModel):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "收款"
        PAYMENT = "payment", "付款"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind)
    settlement_no = models.CharField(max_length=64)
    party = models.ForeignKey(Party, on_delete=models.PROTECT)
    settlement_date = models.DateField()
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    base_amount = models.DecimalField(max_digits=20, decimal_places=6)
    allocated_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    external_transaction_id = models.CharField(max_length=100, blank=True, default="")
    journal = models.ForeignKey(JournalEntry, on_delete=models.PROTECT)

    class Meta:
        db_table = "fin_settlement"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind", "settlement_no"], name="fin_settlement_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["company", "external_transaction_id"],
                condition=~models.Q(external_transaction_id=""),
                name="fin_settlement_external_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0) & models.Q(base_amount__gt=0),
                name="fin_settlement_amount_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(allocated_amount__gte=0)
                & models.Q(allocated_amount__lte=models.F("amount")),
                name="fin_settlement_alloc_ck",
            ),
        ]


class Allocation(AuditedModel):
    settlement = models.ForeignKey(Settlement, on_delete=models.PROTECT, related_name="allocations")
    open_item = models.ForeignKey(OpenItem, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    base_amount = models.DecimalField(max_digits=20, decimal_places=6)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal"
    )

    class Meta:
        db_table = "fin_allocation"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0) & ~models.Q(base_amount=0),
                name="fin_allocation_nonzero_ck",
            ),
        ]


class ThreeWayMatch(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    purchase_order = models.ForeignKey("purchasing.PurchaseOrder", on_delete=models.PROTECT)
    goods_receipt = models.ForeignKey("purchasing.GoodsReceipt", on_delete=models.PROTECT)
    supplier_invoice_no = models.CharField(max_length=100)
    invoice_amount = models.DecimalField(max_digits=20, decimal_places=6)
    matched_amount = models.DecimalField(max_digits=20, decimal_places=6)
    variance_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    status = models.CharField(max_length=16, default="matched")

    class Meta:
        db_table = "fin_three_way_match"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "supplier_invoice_no"], name="fin_supplier_invoice_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(invoice_amount__gt=0) & models.Q(matched_amount__gte=0),
                name="fin_match_amount_ck",
            ),
        ]


class InventoryCostBalance(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    sku = models.ForeignKey("products.ProductSku", on_delete=models.PROTECT)
    warehouse = models.ForeignKey("warehouse.Warehouse", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    total_cost_base = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    average_unit_cost_base = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "fin_inventory_cost_balance"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "sku", "warehouse"], name="fin_cost_balance_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0)
                & models.Q(total_cost_base__gte=0)
                & models.Q(average_unit_cost_base__gte=0),
                name="fin_cost_balance_values_ck",
            ),
        ]


class CostRecord(AuditedModel):
    class Category(models.TextChoices):
        PURCHASE = "purchase", "采购"
        MATERIAL = "material", "材料"
        PRODUCTION = "production", "生产"
        PACKAGING = "packaging", "包装"
        DOMESTIC_FREIGHT = "domestic_freight", "国内物流"
        INTERNATIONAL_FREIGHT = "international_freight", "国际运费"
        INSURANCE = "insurance", "保险"
        CUSTOMS = "customs", "报关"
        PLATFORM_FEE = "platform_fee", "平台费用"
        FORWARDER_FEE = "forwarder_fee", "货代费用"
        AFTERSALES = "aftersales", "售后"
        LABOR = "labor", "人工"
        OVERHEAD = "overhead", "制造费用"
        COGS = "cogs", "销售成本"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    cost_record_no = models.CharField(max_length=100)
    object_type = models.CharField(max_length=50)
    object_id = models.CharField(max_length=100)
    category = models.CharField(max_length=32, choices=Category)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    unit_cost = models.DecimalField(max_digits=20, decimal_places=6)
    total_cost = models.DecimalField(max_digits=20, decimal_places=6)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    base_total_cost = models.DecimalField(max_digits=20, decimal_places=6)
    source_type = models.CharField(max_length=50)
    source_id = models.CharField(max_length=100)
    effective_date = models.DateField()
    idempotency_key = models.CharField(max_length=100)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal"
    )

    class Meta:
        db_table = "fin_cost_record"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "cost_record_no"], name="fin_cost_record_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["company", "idempotency_key"], name="fin_cost_record_idem_uniq"
            ),
            models.CheckConstraint(
                condition=~models.Q(quantity=0)
                & models.Q(unit_cost__gte=0)
                & ~models.Q(total_cost=0)
                & models.Q(exchange_rate__gt=0)
                & ~models.Q(base_total_cost=0),
                name="fin_cost_record_values_ck",
            ),
        ]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("成本记录不可直接修改，只能冲销。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValidationError("成本记录不可删除，只能冲销。")


class SerialCost(AuditedModel):
    serial = models.OneToOneField(
        "products.ProductSerial", on_delete=models.PROTECT, related_name="cost"
    )
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    original_cost = models.DecimalField(max_digits=20, decimal_places=6)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    base_cost = models.DecimalField(max_digits=20, decimal_places=6)
    source_type = models.CharField(max_length=50)
    source_id = models.CharField(max_length=100)

    class Meta:
        db_table = "fin_serial_cost"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(original_cost__gte=0)
                & models.Q(exchange_rate__gt=0)
                & models.Q(base_cost__gte=0),
                name="fin_serial_cost_values_ck",
            )
        ]


class ExpenseClaim(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        SUBMITTED = "submitted", "已提交"
        APPROVED = "approved", "已批准"
        POSTED = "posted", "已入账"
        PAID = "paid", "已支付"
        REJECTED = "rejected", "已拒绝"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    claim_no = models.CharField(max_length=64)
    claimant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    expense_date = models.DateField()
    description = models.CharField(max_length=500)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    base_amount = models.DecimalField(max_digits=20, decimal_places=6)
    cost_center = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_expense_claims",
    )
    journal = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "fin_expense_claim"
        constraints = [
            models.UniqueConstraint(fields=["company", "claim_no"], name="fin_claim_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0)
                & models.Q(base_amount__gt=0)
                & models.Q(exchange_rate__gt=0),
                name="fin_claim_amount_ck",
            ),
        ]


class FixedAsset(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "使用中"
        FULLY_DEPRECIATED = "fully_depreciated", "已提足"
        DISPOSED = "disposed", "已处置"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    asset_no = models.CharField(max_length=64)
    name = models.CharField(max_length=300)
    category = models.CharField(max_length=100)
    acquisition_date = models.DateField()
    in_service_date = models.DateField()
    original_cost = models.DecimalField(max_digits=20, decimal_places=6)
    residual_value = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    useful_life_months = models.PositiveIntegerField()
    accumulated_depreciation = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    location = models.CharField(max_length=200, blank=True)
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    status = models.CharField(max_length=24, choices=Status, default=Status.DRAFT)
    disposal_date = models.DateField(null=True, blank=True)
    disposal_proceeds = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "fin_fixed_asset"
        constraints = [
            models.UniqueConstraint(fields=["company", "asset_no"], name="fin_asset_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(original_cost__gt=0)
                & models.Q(residual_value__gte=0)
                & models.Q(residual_value__lt=models.F("original_cost"))
                & models.Q(accumulated_depreciation__gte=0),
                name="fin_asset_values_ck",
            ),
        ]


class DepreciationEntry(AuditedModel):
    asset = models.ForeignKey(FixedAsset, on_delete=models.PROTECT, related_name="depreciations")
    period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    journal = models.ForeignKey(JournalEntry, on_delete=models.PROTECT)

    class Meta:
        db_table = "fin_depreciation_entry"
        constraints = [
            models.UniqueConstraint(fields=["asset", "period"], name="fin_asset_period_dep_uniq"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="fin_dep_amount_ck"),
        ]


class PayrollRun(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        CALCULATED = "calculated", "已计算"
        APPROVED = "approved", "已批准"
        POSTED = "posted", "已计提"
        PAID = "paid", "已发放"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    run_no = models.CharField(max_length=64)
    period = models.ForeignKey(FiscalPeriod, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    gross_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    deduction_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    net_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    calculated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="calculated_payrolls"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_payrolls",
    )
    journal = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "fin_payroll_run"
        constraints = [
            models.UniqueConstraint(fields=["company", "run_no"], name="fin_payroll_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(gross_amount__gte=0)
                & models.Q(deduction_amount__gte=0)
                & models.Q(net_amount__gte=0),
                name="fin_payroll_totals_ck",
            ),
        ]


class PayrollLine(AuditedModel):
    payroll = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="lines")
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    gross_amount = models.DecimalField(max_digits=20, decimal_places=6)
    deduction_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    net_amount = models.DecimalField(max_digits=20, decimal_places=6)
    detail = models.JSONField(default=dict)

    class Meta:
        db_table = "fin_payroll_line"
        constraints = [
            models.UniqueConstraint(
                fields=["payroll", "employee"], name="fin_payroll_employee_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(gross_amount__gte=0)
                & models.Q(deduction_amount__gte=0)
                & models.Q(net_amount=models.F("gross_amount") - models.F("deduction_amount")),
                name="fin_payroll_line_values_ck",
            ),
        ]


class TaxInvoice(AuditedModel):
    class Direction(models.TextChoices):
        INPUT = "input", "进项"
        OUTPUT = "output", "销项"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        VERIFIED = "verified", "已核验"
        POSTED = "posted", "已入账"
        VOID = "void", "已作废"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    direction = models.CharField(max_length=8, choices=Direction)
    invoice_code = models.CharField(max_length=64, blank=True)
    invoice_no = models.CharField(max_length=64)
    party = models.ForeignKey(Party, on_delete=models.PROTECT)
    issue_date = models.DateField()
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    amount_excluding_tax = models.DecimalField(max_digits=20, decimal_places=6)
    tax_amount = models.DecimalField(max_digits=20, decimal_places=6)
    total_amount = models.DecimalField(max_digits=20, decimal_places=6)
    tax_detail = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    journal = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "fin_tax_invoice"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "direction", "invoice_code", "invoice_no"],
                name="fin_tax_invoice_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_excluding_tax__gte=0)
                & models.Q(tax_amount__gte=0)
                & models.Q(total_amount=models.F("amount_excluding_tax") + models.F("tax_amount")),
                name="fin_tax_invoice_amount_ck",
            ),
        ]

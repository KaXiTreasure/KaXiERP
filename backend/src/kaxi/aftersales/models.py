from django.conf import settings
from django.db import models

from kaxi.finance.models import JournalEntry
from kaxi.inventory.models import InventoryBalance
from kaxi.master_data.models import Company, Currency, Party
from kaxi.sales.models import SalesOrder, SalesOrderLine
from kaxi.shared.models import AuditedModel


class AfterSalesCase(AuditedModel):
    class Type(models.TextChoices):
        RETURN = "return", "退货"
        REFUND = "refund", "退款"
        EXCHANGE = "exchange", "换货"
        RESHIP = "reship", "补发"
        DISCOUNT = "discount", "折让"
        CLAIM = "claim", "索赔"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PENDING_APPROVAL = "pending_approval", "待审批"
        APPROVED = "approved", "已批准"
        RETURNING = "returning", "退货中"
        PROCESSING = "processing", "处理中"
        COMPLETED = "completed", "已完成"
        REJECTED = "rejected", "已拒绝"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    case_no = models.CharField(max_length=100)
    case_type = models.CharField(max_length=16, choices=Type)
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="aftersales_cases"
    )
    customer = models.ForeignKey(Party, on_delete=models.PROTECT)
    reason_code = models.CharField(max_length=50)
    reason_detail = models.TextField()
    status = models.CharField(max_length=24, choices=Status, default=Status.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="aftersales_requests"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_aftersales_cases",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "sal_aftersales_case"
        constraints = [
            models.UniqueConstraint(fields=["company", "case_no"], name="sal_after_case_no_uniq")
        ]


class AfterSalesLine(AuditedModel):
    case = models.ForeignKey(AfterSalesCase, on_delete=models.PROTECT, related_name="lines")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT)
    requested_qty = models.DecimalField(max_digits=20, decimal_places=6)
    received_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    accepted_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "sal_aftersales_line"
        constraints = [
            models.UniqueConstraint(
                fields=["case", "sales_order_line"], name="sal_after_case_line_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(requested_qty__gt=0)
                & models.Q(received_qty__gte=0)
                & models.Q(accepted_qty__gte=0)
                & models.Q(rejected_qty__gte=0),
                name="sal_after_line_qty_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(received_qty__lte=models.F("requested_qty")),
                name="sal_after_received_lte_requested_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    received_qty=models.F("accepted_qty") + models.F("rejected_qty")
                ),
                name="sal_after_disposition_sum_ck",
            ),
        ]


class ReturnReceipt(AuditedModel):
    case = models.OneToOneField(
        AfterSalesCase, on_delete=models.PROTECT, related_name="return_receipt"
    )
    receipt_no = models.CharField(max_length=100)
    received_at = models.DateTimeField()
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = "sal_return_receipt"


class ReturnReceiptLine(AuditedModel):
    receipt = models.ForeignKey(ReturnReceipt, on_delete=models.PROTECT, related_name="lines")
    aftersales_line = models.OneToOneField(AfterSalesLine, on_delete=models.PROTECT)
    received_qty = models.DecimalField(max_digits=20, decimal_places=6)
    accepted_qty = models.DecimalField(max_digits=20, decimal_places=6)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6)
    accepted_balance = models.ForeignKey(
        InventoryBalance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_returns",
    )
    exception_balance = models.ForeignKey(
        InventoryBalance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="exception_returns",
    )

    class Meta:
        db_table = "sal_return_receipt_line"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(received_qty__gt=0)
                & models.Q(accepted_qty__gte=0)
                & models.Q(rejected_qty__gte=0)
                & models.Q(received_qty=models.F("accepted_qty") + models.F("rejected_qty")),
                name="sal_return_receipt_qty_ck",
            )
        ]


class Refund(AuditedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待退款"
        APPROVED = "approved", "已批准"
        PAID = "paid", "已退款"
        CANCELLED = "cancelled", "已取消"

    case = models.ForeignKey(AfterSalesCase, on_delete=models.PROTECT, related_name="refunds")
    refund_no = models.CharField(max_length=100)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    base_amount = models.DecimalField(max_digits=20, decimal_places=6)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    external_refund_id = models.CharField(max_length=200, blank=True)
    journal = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "sal_refund"
        constraints = [
            models.UniqueConstraint(fields=["case", "refund_no"], name="sal_refund_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0)
                & models.Q(base_amount__gt=0)
                & models.Q(exchange_rate__gt=0),
                name="sal_refund_amount_ck",
            ),
        ]


class ReplacementOrder(AuditedModel):
    case = models.ForeignKey(AfterSalesCase, on_delete=models.PROTECT, related_name="replacements")
    replacement_order = models.OneToOneField(SalesOrder, on_delete=models.PROTECT)
    replacement_type = models.CharField(
        max_length=16, choices=[("exchange", "换货"), ("reship", "补发")]
    )

    class Meta:
        db_table = "sal_replacement_order"

from django.conf import settings
from django.db import models

from kaxi.master_data.models import Company, Currency, Party
from kaxi.products.models import ProductSku
from kaxi.shared.models import AuditedModel
from kaxi.warehouse.models import Warehouse, WarehouseLocation


class PurchaseOrder(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已审批"
        ISSUED = "issued", "已下达"
        PARTIALLY_RECEIVED = "partially_received", "部分收货"
        RECEIVED = "received", "全部收货"
        CLOSED = "closed", "已关闭"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    purchase_order_no = models.CharField(max_length=100)
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT)
    order_date = models.DateField()
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    expected_delivery_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    tax_total = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    total = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    base_total = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    approval_status = models.CharField(max_length=32, default="pending")
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "pur_purchase_order"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "purchase_order_no"], name="pur_po_company_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(exchange_rate__gt=0), name="pur_po_exchange_rate_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0)
                & models.Q(tax_total__gte=0)
                & models.Q(total__gte=0)
                & models.Q(base_total__gte=0),
                name="pur_po_amounts_nonnegative_ck",
            ),
        ]
        indexes = [models.Index(fields=["company", "supplier", "status"], name="pur_po_lookup_idx")]


class PurchaseOrderLine(AuditedModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    ordered_qty = models.DecimalField(max_digits=20, decimal_places=6)
    received_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    accepted_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    returned_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    unit_price = models.DecimalField(max_digits=20, decimal_places=6)
    tax_rate = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    line_total = models.DecimalField(max_digits=20, decimal_places=6)
    base_line_total = models.DecimalField(max_digits=20, decimal_places=6)
    expected_delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, default="open")

    class Meta:
        db_table = "pur_purchase_order_line"
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="pur_po_line_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(ordered_qty__gt=0)
                & models.Q(received_qty__gte=0)
                & models.Q(accepted_qty__gte=0)
                & models.Q(rejected_qty__gte=0)
                & models.Q(returned_qty__gte=0),
                name="pur_po_line_quantities_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(ordered_qty__gte=models.F("received_qty")),
                name="pur_po_line_received_lte_ordered_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    received_qty__gte=models.F("accepted_qty") + models.F("rejected_qty")
                ),
                name="pur_po_line_inspected_lte_received_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(returned_qty__lte=models.F("rejected_qty")),
                name="pur_po_line_returned_lte_rejected_ck",
            ),
        ]


class GoodsReceipt(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        RECEIVED = "received", "已收货"
        INSPECTION = "inspection", "待验收"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    receipt_no = models.CharField(max_length=100)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="receipts"
    )
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    received_at = models.DateTimeField()
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    supplier_delivery_no = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "pur_goods_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "receipt_no"], name="pur_receipt_company_no_uniq"
            )
        ]


class GoodsReceiptLine(AuditedModel):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="lines")
    purchase_order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    received_qty = models.DecimalField(max_digits=20, decimal_places=6)
    pending_inspection_qty = models.DecimalField(max_digits=20, decimal_places=6)
    lot_no = models.CharField(max_length=100, blank=True)
    staging_location = models.ForeignKey(WarehouseLocation, on_delete=models.PROTECT)

    class Meta:
        db_table = "pur_goods_receipt_line"
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "purchase_order_line"], name="pur_receipt_po_line_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(received_qty__gt=0)
                & models.Q(pending_inspection_qty__gte=0)
                & models.Q(received_qty__gte=models.F("pending_inspection_qty")),
                name="pur_receipt_line_quantities_ck",
            ),
        ]


class QualityInspection(AuditedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "待检"
        IN_PROGRESS = "in_progress", "检验中"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    inspection_no = models.CharField(max_length=100)
    receipt = models.OneToOneField(
        GoodsReceipt, on_delete=models.PROTECT, related_name="inspection"
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=32, default="pending")
    status = models.CharField(max_length=32, choices=Status, default=Status.PENDING)

    class Meta:
        db_table = "pur_quality_inspection"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "inspection_no"], name="pur_inspection_company_no_uniq"
            )
        ]


class QualityInspectionLine(AuditedModel):
    inspection = models.ForeignKey(
        QualityInspection, on_delete=models.PROTECT, related_name="lines"
    )
    receipt_line = models.OneToOneField(GoodsReceiptLine, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    inspected_qty = models.DecimalField(max_digits=20, decimal_places=6)
    accepted_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    pending_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    disposition = models.CharField(max_length=32, blank=True)
    defect_code = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        db_table = "pur_quality_inspection_line"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(inspected_qty__gt=0)
                & models.Q(accepted_qty__gte=0)
                & models.Q(rejected_qty__gte=0)
                & models.Q(pending_qty__gte=0),
                name="pur_inspection_line_quantities_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    inspected_qty=models.F("accepted_qty")
                    + models.F("rejected_qty")
                    + models.F("pending_qty")
                ),
                name="pur_inspection_line_sum_ck",
            ),
        ]


class PurchaseRequisition(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        SUBMITTED = "submitted", "已提交"
        APPROVED = "approved", "已批准"
        SOURCING = "sourcing", "询价中"
        ORDERED = "ordered", "已下单"
        CLOSED = "closed", "已关闭"
        REJECTED = "rejected", "已拒绝"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    requisition_no = models.CharField(max_length=100)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_requisitions",
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    required_date = models.DateField()
    source_type = models.CharField(max_length=50, default="manual")
    source_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_purchase_requisitions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "pur_requisition"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "requisition_no"], name="pur_requisition_no_uniq"
            )
        ]


class PurchaseRequisitionLine(AuditedModel):
    requisition = models.ForeignKey(
        PurchaseRequisition, on_delete=models.PROTECT, related_name="lines"
    )
    line_no = models.PositiveIntegerField()
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    requested_qty = models.DecimalField(max_digits=20, decimal_places=6)
    ordered_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    suggested_supplier = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT)
    reason = models.TextField(blank=True)

    class Meta:
        db_table = "pur_requisition_line"
        constraints = [
            models.UniqueConstraint(
                fields=["requisition", "line_no"], name="pur_requisition_line_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(requested_qty__gt=0)
                & models.Q(ordered_qty__gte=0)
                & models.Q(ordered_qty__lte=models.F("requested_qty")),
                name="pur_requisition_line_qty_ck",
            ),
        ]


class RequestForQuotation(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ISSUED = "issued", "已发出"
        EVALUATING = "evaluating", "评估中"
        AWARDED = "awarded", "已定标"
        CLOSED = "closed", "已关闭"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    rfq_no = models.CharField(max_length=100)
    requisition = models.ForeignKey(
        PurchaseRequisition, on_delete=models.PROTECT, related_name="rfqs"
    )
    quote_deadline = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    awarded_quote = models.OneToOneField(
        "SupplierQuote",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="awarded_rfq",
    )

    class Meta:
        db_table = "pur_rfq"
        constraints = [
            models.UniqueConstraint(fields=["company", "rfq_no"], name="pur_rfq_no_uniq")
        ]


class RfqSupplier(AuditedModel):
    rfq = models.ForeignKey(RequestForQuotation, on_delete=models.PROTECT, related_name="suppliers")
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT)
    invited_at = models.DateTimeField()
    response_status = models.CharField(max_length=16, default="pending")

    class Meta:
        db_table = "pur_rfq_supplier"
        constraints = [
            models.UniqueConstraint(fields=["rfq", "supplier"], name="pur_rfq_supplier_uniq")
        ]


class SupplierQuote(AuditedModel):
    rfq = models.ForeignKey(RequestForQuotation, on_delete=models.PROTECT, related_name="quotes")
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT)
    quote_no = models.CharField(max_length=100)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    freight_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    tax_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    total_amount = models.DecimalField(max_digits=20, decimal_places=6)
    delivery_date = models.DateField()
    valid_until = models.DateField()
    status = models.CharField(max_length=16, default="submitted")
    score_snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "pur_supplier_quote"
        constraints = [
            models.UniqueConstraint(
                fields=["rfq", "supplier", "quote_no"], name="pur_quote_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(exchange_rate__gt=0)
                & models.Q(freight_amount__gte=0)
                & models.Q(tax_amount__gte=0)
                & models.Q(total_amount__gte=0),
                name="pur_quote_amount_ck",
            ),
        ]


class SupplierQuoteLine(AuditedModel):
    quote = models.ForeignKey(SupplierQuote, on_delete=models.PROTECT, related_name="lines")
    requisition_line = models.ForeignKey(PurchaseRequisitionLine, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    unit_price = models.DecimalField(max_digits=20, decimal_places=6)
    tax_rate = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    class Meta:
        db_table = "pur_supplier_quote_line"
        constraints = [
            models.UniqueConstraint(
                fields=["quote", "requisition_line"], name="pur_quote_req_line_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0)
                & models.Q(unit_price__gte=0)
                & models.Q(tax_rate__gte=0),
                name="pur_quote_line_values_ck",
            ),
        ]


class PurchaseReturn(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        DISPATCHED = "dispatched", "已退运"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    return_no = models.CharField(max_length=100)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_returns"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_purchase_returns",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=100, blank=True)
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "pur_return"
        constraints = [
            models.UniqueConstraint(fields=["company", "return_no"], name="pur_return_no_uniq"),
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="pur_return_idem_uniq",
            ),
        ]


class PurchaseReturnLine(AuditedModel):
    purchase_return = models.ForeignKey(
        PurchaseReturn, on_delete=models.PROTECT, related_name="lines"
    )
    purchase_order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT)
    inventory_balance = models.ForeignKey("inventory.InventoryBalance", on_delete=models.PROTECT)
    return_qty = models.DecimalField(max_digits=20, decimal_places=6)
    dispatched_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "pur_return_line"
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_return", "purchase_order_line"],
                name="pur_return_order_line_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(return_qty__gt=0)
                & models.Q(dispatched_qty__gte=0)
                & models.Q(dispatched_qty__lte=models.F("return_qty")),
                name="pur_return_line_qty_ck",
            ),
        ]


class SupplierPerformanceSnapshot(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT)
    period_start = models.DateField()
    period_end = models.DateField()
    on_time_rate = models.DecimalField(max_digits=12, decimal_places=6)
    acceptance_rate = models.DecimalField(max_digits=12, decimal_places=6)
    price_variance_rate = models.DecimalField(max_digits=12, decimal_places=6)
    score = models.DecimalField(max_digits=12, decimal_places=6)
    metric_snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "pur_supplier_performance"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "supplier", "period_start", "period_end"],
                name="pur_supplier_perf_period_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="pur_supplier_perf_dates_ck",
            ),
        ]

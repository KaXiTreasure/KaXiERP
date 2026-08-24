from django.conf import settings
from django.db import models

from kaxi.master_data.models import Company, Currency, Party, Region
from kaxi.products.models import ProductSerial, ProductSku
from kaxi.sales.models import SalesOrder, SalesOrderLine
from kaxi.shared.models import AuditedModel
from kaxi.warehouse.models import Warehouse


class TradeContract(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        ACTIVE = "active", "履行中"
        COMPLETED = "completed", "已完成"
        TERMINATED = "terminated", "已终止"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    contract_no = models.CharField(max_length=100)
    customer = models.ForeignKey(Party, on_delete=models.PROTECT)
    trade_type = models.CharField(max_length=32)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    contract_date = models.DateField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    incoterm = models.CharField(max_length=10, blank=True)
    incoterm_place = models.CharField(max_length=300, blank=True)
    payment_terms = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=20, decimal_places=6)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_trade_contracts",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_trade_contracts",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "trd_contract"
        constraints = [
            models.UniqueConstraint(fields=["company", "contract_no"], name="trd_contract_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0), name="trd_contract_amount_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="trd_contract_dates_ck",
            ),
        ]


class SalesOrderTradeDetail(AuditedModel):
    sales_order = models.OneToOneField(
        SalesOrder, primary_key=True, on_delete=models.PROTECT, related_name="trade_detail"
    )
    contract = models.ForeignKey(TradeContract, null=True, blank=True, on_delete=models.PROTECT)
    incoterm = models.CharField(max_length=10, blank=True)
    incoterm_place = models.CharField(max_length=300, blank=True)
    origin_place = models.CharField(max_length=300, blank=True)
    origin_port = models.CharField(max_length=300, blank=True)
    destination_port = models.CharField(max_length=300, blank=True)
    final_destination = models.CharField(max_length=500, blank=True)
    transport_mode = models.CharField(max_length=32)
    freight_forwarder = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT)
    planned_ship_date = models.DateField(null=True, blank=True)
    requested_delivery_date = models.DateField(null=True, blank=True)
    deposit_rate = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    declaration_currency = models.ForeignKey(
        Currency, null=True, blank=True, on_delete=models.PROTECT
    )
    remarks = models.TextField(blank=True)

    class Meta:
        db_table = "trd_sales_order_detail"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(deposit_rate__gte=0) & models.Q(deposit_rate__lte=1),
                name="trd_order_deposit_rate_ck",
            )
        ]


class Shipment(AuditedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "计划中"
        ARRANGING = "arranging", "待安排运输"
        CONFIRMED = "confirmed", "已确认运输"
        PACKING = "packing", "待装箱"
        DOCUMENTS = "documents", "待单证"
        DISPATCH_READY = "dispatch_ready", "待交运"
        DISPATCHED = "dispatched", "已交运"
        IN_TRANSIT = "in_transit", "在途"
        ARRIVED = "arrived", "已到达"
        DELIVERED = "delivered", "已签收"
        COMPLETED = "completed", "已完成"
        EXCEPTION = "exception", "异常"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    shipment_no = models.CharField(max_length=100)
    trade_type = models.CharField(max_length=32)
    transport_mode = models.CharField(max_length=32)
    forwarder = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT)
    carrier_name = models.CharField(max_length=300, blank=True)
    tracking_or_booking_no = models.CharField(max_length=200, blank=True)
    planned_ship_at = models.DateTimeField(null=True, blank=True)
    actual_ship_at = models.DateTimeField(null=True, blank=True)
    estimated_arrival_at = models.DateTimeField(null=True, blank=True)
    actual_arrival_at = models.DateTimeField(null=True, blank=True)
    origin = models.CharField(max_length=500, blank=True)
    destination = models.CharField(max_length=500, blank=True)
    package_count = models.PositiveIntegerField(default=0)
    gross_weight = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    net_weight = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    volume = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    status = models.CharField(max_length=24, choices=Status, default=Status.PLANNED)
    exception_type = models.CharField(max_length=50, blank=True)
    exception_detail = models.TextField(blank=True)
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "trd_shipment"
        constraints = [
            models.UniqueConstraint(fields=["company", "shipment_no"], name="trd_shipment_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(gross_weight__gte=0)
                & models.Q(net_weight__gte=0)
                & models.Q(volume__gte=0),
                name="trd_shipment_measures_ck",
            ),
        ]


class ShipmentOrder(AuditedModel):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="orders")
    sales_order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT)

    class Meta:
        db_table = "trd_shipment_order"
        constraints = [
            models.UniqueConstraint(
                fields=["shipment", "sales_order"], name="trd_shipment_order_uniq"
            )
        ]


class Package(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿箱"
        PACKING = "packing", "装箱中"
        REVIEW = "review", "待复核"
        SEALED = "sealed", "已封箱"
        DISPATCHED = "dispatched", "已交运"

    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="packages")
    package_no = models.CharField(max_length=100)
    package_type = models.CharField(max_length=50, blank=True)
    length = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    width = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    height = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    net_weight = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    gross_weight = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    volume = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    shipping_mark = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    sealed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        db_table = "trd_package"
        constraints = [
            models.UniqueConstraint(fields=["shipment", "package_no"], name="trd_package_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(length__gte=0)
                & models.Q(width__gte=0)
                & models.Q(height__gte=0)
                & models.Q(net_weight__gte=0)
                & models.Q(gross_weight__gte=0)
                & models.Q(volume__gte=0),
                name="trd_package_measures_ck",
            ),
        ]


class PackageItem(AuditedModel):
    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name="items")
    sales_order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    product_serial = models.ForeignKey(
        ProductSerial, null=True, blank=True, on_delete=models.PROTECT
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)

    class Meta:
        db_table = "trd_package_item"
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="trd_package_qty_ck"),
            models.UniqueConstraint(
                fields=["product_serial"],
                condition=models.Q(product_serial__isnull=False),
                name="trd_package_serial_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(product_serial__isnull=True) | models.Q(quantity=1),
                name="trd_package_serial_qty_ck",
            ),
        ]


class ShipmentMilestone(AuditedModel):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="milestones")
    milestone_type = models.CharField(max_length=50)
    occurred_at = models.DateTimeField()
    location = models.CharField(max_length=500, blank=True)
    detail = models.JSONField(default=dict)
    external_event_id = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "trd_shipment_milestone"
        constraints = [
            models.UniqueConstraint(
                fields=["shipment", "external_event_id"],
                condition=~models.Q(external_event_id=""),
                name="trd_milestone_external_uniq",
            )
        ]


class ShipmentClaim(AuditedModel):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="claims")
    claim_no = models.CharField(max_length=100)
    claim_type = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default="open")
    description = models.TextField()

    class Meta:
        db_table = "trd_shipment_claim"
        constraints = [
            models.UniqueConstraint(
                fields=["shipment", "claim_no"], name="trd_shipment_claim_no_uniq"
            ),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="trd_claim_amount_ck"),
        ]


class TradeDocument(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        GENERATED = "generated", "已生成"
        ISSUED = "issued", "已签发"
        VOID = "void", "已作废"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="documents")
    document_type = models.CharField(max_length=32)
    document_no = models.CharField(max_length=100)
    language = models.CharField(max_length=16, default="zh-CN")
    template_version = models.CharField(max_length=50)
    snapshot = models.JSONField(default=dict)
    content_sha256 = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_trade_documents"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issued_trade_documents",
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)

    class Meta:
        db_table = "trd_document"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "document_no"], name="trd_document_company_no_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["shipment", "document_type", "status"], name="trd_doc_lookup_idx")
        ]


class CustomsDeclaration(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        SUBMITTED = "submitted", "已申报"
        CLEARED = "cleared", "已放行"
        REJECTED = "rejected", "退单"
        CANCELLED = "cancelled", "取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    shipment = models.OneToOneField(
        Shipment, on_delete=models.PROTECT, related_name="customs_declaration"
    )
    declaration_no = models.CharField(max_length=100, blank=True)
    customs_office = models.CharField(max_length=200)
    declaration_mode = models.CharField(max_length=50)
    declaration_date = models.DateField(null=True, blank=True)
    declaration_currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    declared_amount = models.DecimalField(max_digits=20, decimal_places=6)
    item_snapshot = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    rebate_status = models.CharField(max_length=32, default="not_started")
    rebate_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "trd_customs_declaration"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(declared_amount__gte=0), name="trd_customs_amount_ck"
            ),
            models.UniqueConstraint(
                fields=["company", "declaration_no"],
                condition=~models.Q(declaration_no=""),
                name="trd_customs_company_no_uniq",
            ),
        ]


class TradeCost(AuditedModel):
    class Status(models.TextChoices):
        ESTIMATED = "estimated", "预估"
        CONFIRMED = "confirmed", "已确认"
        SETTLED = "settled", "已结算"
        REVERSED = "reversed", "已冲销"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="trade_costs")
    cost_type = models.CharField(max_length=50)
    service_party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    exchange_rate = models.DecimalField(max_digits=20, decimal_places=10)
    base_amount = models.DecimalField(max_digits=20, decimal_places=6)
    allocation_basis = models.CharField(max_length=32)
    allocation_snapshot = models.JSONField(default=list)
    external_reference = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.ESTIMATED)

    class Meta:
        db_table = "trd_cost"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0)
                & models.Q(exchange_rate__gt=0)
                & models.Q(base_amount__gte=0),
                name="trd_cost_amounts_ck",
            )
        ]
        indexes = [
            models.Index(fields=["shipment", "cost_type", "status"], name="trd_cost_lookup_idx")
        ]


class ForwarderSettlement(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        CONFIRMED = "confirmed", "已确认"
        PAID = "paid", "已支付"
        RECONCILED = "reconciled", "已对账"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    settlement_no = models.CharField(max_length=100)
    forwarder = models.ForeignKey(Party, on_delete=models.PROTECT)
    period_start = models.DateField()
    period_end = models.DateField()
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    receivable_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    fee_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    received_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    difference_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    detail_snapshot = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)

    class Meta:
        db_table = "trd_forwarder_settlement"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "settlement_no"], name="trd_forwarder_settlement_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="trd_forwarder_settlement_period_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(receivable_amount__gte=0)
                & models.Q(fee_amount__gte=0)
                & models.Q(received_amount__gte=0),
                name="trd_forwarder_settlement_amounts_ck",
            ),
        ]


class OverseasWarehouseProfile(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    warehouse = models.OneToOneField(
        Warehouse, on_delete=models.PROTECT, related_name="overseas_profile"
    )
    country_region = models.ForeignKey(Region, on_delete=models.PROTECT)
    operator = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT)
    external_warehouse_code = models.CharField(max_length=100, blank=True)
    customs_mode = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "trd_overseas_warehouse"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "external_warehouse_code"],
                condition=~models.Q(external_warehouse_code=""),
                name="trd_overseas_wh_external_uniq",
            )
        ]

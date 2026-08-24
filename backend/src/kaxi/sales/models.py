from django.db import models

from kaxi.master_data.models import Address, Company, Currency, Party
from kaxi.products.models import ProductSku
from kaxi.shared.models import AuditedModel
from kaxi.warehouse.models import Warehouse


class SalesChannel(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    channel_code = models.CharField(max_length=50)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sal_channel"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "channel_code"], name="sal_channel_company_code_uniq"
            )
        ]


class SalesOrder(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        CONFIRMED = "confirmed", "已确认"
        ALLOCATING = "allocating", "分配中"
        ALLOCATED = "allocated", "已分配"
        FULFILLING = "fulfilling", "履约中"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    order_no = models.CharField(max_length=100)
    customer = models.ForeignKey(Party, on_delete=models.PROTECT)
    channel = models.ForeignKey(SalesChannel, on_delete=models.PROTECT)
    shipping_address = models.ForeignKey(Address, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    order_date = models.DateTimeField()
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    version_no = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "sal_order"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "order_no"], name="sal_order_company_no_uniq"
            )
        ]
        indexes = [
            models.Index(
                fields=["company", "status", "order_date"], name="sal_order_status_date_idx"
            )
        ]


class SalesOrderLine(AuditedModel):
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    ordered_qty = models.DecimalField(max_digits=20, decimal_places=6)
    unit_price = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    line_total = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    price_source = models.CharField(max_length=50, blank=True)
    price_snapshot = models.JSONField(default=dict, blank=True)
    reserved_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    shipped_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    returned_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    cancelled_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    row_version = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "sal_order_line"
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="sal_order_line_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(ordered_qty__gt=0), name="sal_order_line_ordered_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__isnull=True) | models.Q(unit_price__gte=0),
                name="sal_order_line_unit_price_nonnegative_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__isnull=True) | models.Q(line_total__gte=0),
                name="sal_order_line_total_nonnegative_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_qty__gte=0)
                & models.Q(shipped_qty__gte=0)
                & models.Q(returned_qty__gte=0)
                & models.Q(cancelled_qty__gte=0),
                name="sal_order_line_quantities_nonnegative_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    ordered_qty__gte=models.F("shipped_qty") + models.F("cancelled_qty")
                ),
                name="sal_order_line_shipped_cancelled_lte_ordered_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    ordered_qty__gte=models.F("reserved_qty")
                    + models.F("shipped_qty")
                    + models.F("cancelled_qty")
                ),
                name="sal_order_line_committed_lte_ordered_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(returned_qty__lte=models.F("shipped_qty")),
                name="sal_order_line_returned_lte_shipped_ck",
            ),
        ]


class SalesOrderConfirmation(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="confirmations")
    idempotency_key = models.CharField(max_length=200)
    confirmed_version = models.PositiveIntegerField()
    result_status = models.CharField(max_length=32)

    class Meta:
        db_table = "sal_order_confirmation"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"], name="sal_confirmation_company_idem_uniq"
            ),
            models.UniqueConstraint(
                fields=["order", "confirmed_version"], name="sal_confirmation_order_version_uniq"
            ),
        ]


class SalesOrderStatusHistory(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField(max_length=32)
    to_status = models.CharField(max_length=32)
    reason = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sal_order_status_history"
        indexes = [models.Index(fields=["order", "occurred_at"], name="sal_order_history_time_idx")]

    def __str__(self) -> str:
        return f"{self.order_id}:{self.from_status}->{self.to_status}"


class CreditAccount(AuditedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        FROZEN = "frozen", "冻结"
        CLOSED = "closed", "关闭"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    customer = models.ForeignKey(Party, on_delete=models.PROTECT)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    permanent_limit = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    temporary_limit = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    temporary_valid_to = models.DateTimeField(null=True, blank=True)
    committed_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    receivable_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    status = models.CharField(max_length=32, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "sal_credit_account"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "customer", "currency"], name="sal_credit_account_scope_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(permanent_limit__gte=0)
                & models.Q(temporary_limit__gte=0)
                & models.Q(committed_amount__gte=0)
                & models.Q(receivable_amount__gte=0),
                name="sal_credit_account_amounts_nonnegative_ck",
            ),
        ]


class CreditCommitment(AuditedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "占用中"
        RELEASED = "released", "已释放"
        CONVERTED = "converted", "已转应收"

    account = models.ForeignKey(CreditAccount, on_delete=models.PROTECT, related_name="commitments")
    order = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="credit_commitments"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    released_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    converted_amount = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    approval_id = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "sal_credit_commitment"
        constraints = [
            models.UniqueConstraint(fields=["account", "order"], name="sal_credit_order_uniq"),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="sal_credit_commitment_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(released_amount__gte=0)
                & models.Q(converted_amount__gte=0)
                & models.Q(amount__gte=models.F("released_amount") + models.F("converted_amount")),
                name="sal_credit_commitment_usage_ck",
            ),
        ]


class SalesShipment(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PICKING = "picking", "拣货中"
        PICKED = "picked", "已拣货"
        VERIFIED = "verified", "已复核"
        SHIPPED = "shipped", "已发货"
        DELIVERED = "delivered", "已签收"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    shipment_no = models.CharField(max_length=100)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="shipments")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    version_no = models.PositiveBigIntegerField(default=1)
    carrier_code = models.CharField(max_length=100, blank=True)
    tracking_no = models.CharField(max_length=200, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    shipped_by = models.ForeignKey("identity.User", null=True, blank=True, on_delete=models.PROTECT)
    ship_idempotency_key = models.CharField(max_length=200, null=True, blank=True, unique=True)

    class Meta:
        db_table = "sal_shipment"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "shipment_no"], name="sal_shipment_company_no_uniq"
            )
        ]
        indexes = [
            models.Index(
                fields=["company", "status", "created_at"], name="sal_shipment_status_idx"
            ),
            models.Index(fields=["carrier_code", "tracking_no"], name="sal_shipment_tracking_idx"),
        ]


class SalesShipmentLine(AuditedModel):
    shipment = models.ForeignKey(SalesShipment, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT)
    reservation = models.ForeignKey("inventory.InventoryReservation", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    picked_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    shipped_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "sal_shipment_line"
        constraints = [
            models.UniqueConstraint(
                fields=["shipment", "line_no"], name="sal_shipment_line_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["shipment", "reservation"], name="sal_shipment_reservation_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0)
                & models.Q(picked_qty__gte=0)
                & models.Q(shipped_qty__gte=0),
                name="sal_shipment_line_quantities_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=models.F("picked_qty")),
                name="sal_shipment_picked_lte_qty_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(picked_qty__gte=models.F("shipped_qty")),
                name="sal_shipment_shipped_lte_picked_ck",
            ),
        ]


class SupplyDemand(AuditedModel):
    class Strategy(models.TextChoices):
        PURCHASE = "purchase", "采购"
        PRODUCTION = "production", "生产"
        PREPACK = "prepack", "预包装"
        TRANSFER = "transfer", "调拨"
        PRESALE = "presale", "预售等待"

    class Status(models.TextChoices):
        OPEN = "open", "待处理"
        PLANNED = "planned", "已计划"
        PARTIAL = "partial", "部分供应"
        FULFILLED = "fulfilled", "已满足"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    demand_no = models.CharField(max_length=100)
    sales_order_line = models.ForeignKey(
        SalesOrderLine, on_delete=models.PROTECT, related_name="supply_demands"
    )
    shortage_qty = models.DecimalField(max_digits=20, decimal_places=6)
    supplied_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    strategy = models.CharField(max_length=16, choices=Strategy)
    required_date = models.DateField()
    promised_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.OPEN)
    idempotency_key = models.CharField(max_length=100)

    class Meta:
        db_table = "sal_supply_demand"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "demand_no"], name="sal_supply_demand_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["company", "idempotency_key"], name="sal_supply_demand_idem_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(shortage_qty__gt=0)
                & models.Q(supplied_qty__gte=0)
                & models.Q(supplied_qty__lte=models.F("shortage_qty")),
                name="sal_supply_demand_qty_ck",
            ),
        ]


class SupplyAllocation(AuditedModel):
    demand = models.ForeignKey(SupplyDemand, on_delete=models.PROTECT, related_name="allocations")
    source_type = models.CharField(max_length=32)
    source_id = models.CharField(max_length=100)
    planned_qty = models.DecimalField(max_digits=20, decimal_places=6)
    received_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, default="planned")

    class Meta:
        db_table = "sal_supply_allocation"
        constraints = [
            models.UniqueConstraint(
                fields=["demand", "source_type", "source_id"], name="sal_supply_source_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gt=0)
                & models.Q(received_qty__gte=0)
                & models.Q(received_qty__lte=models.F("planned_qty")),
                name="sal_supply_allocation_qty_ck",
            ),
        ]


class PresaleCampaign(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        CLOSED = "closed", "关闭"
        CANCELLED = "cancelled", "取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    campaign_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    sales_channel = models.ForeignKey(SalesChannel, null=True, blank=True, on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    promised_delivery_date = models.DateField()
    capacity_qty = models.DecimalField(max_digits=20, decimal_places=6)
    allocated_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)

    class Meta:
        db_table = "sal_presale_campaign"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "campaign_code"], name="sal_presale_campaign_code_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="sal_presale_dates_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_qty__gt=0)
                & models.Q(allocated_qty__gte=0)
                & models.Q(allocated_qty__lte=models.F("capacity_qty")),
                name="sal_presale_capacity_ck",
            ),
        ]


class PresaleAllocation(AuditedModel):
    campaign = models.ForeignKey(
        PresaleCampaign, on_delete=models.PROTECT, related_name="allocations"
    )
    sales_order_line = models.OneToOneField(
        SalesOrderLine, on_delete=models.PROTECT, related_name="presale_allocation"
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    promised_delivery_date = models.DateField()
    status = models.CharField(max_length=16, default="allocated")

    class Meta:
        db_table = "sal_presale_allocation"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="sal_presale_allocation_qty_ck"
            )
        ]

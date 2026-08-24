from decimal import Decimal

from django.conf import settings
from django.db import models

from kaxi.master_data.models import Company
from kaxi.products.models import ProductSku
from kaxi.shared.models import AuditedModel
from kaxi.warehouse.models import Warehouse, WarehouseLocation


class InventoryStatus(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    status_code = models.CharField(max_length=50)
    name = models.CharField(max_length=100)
    is_physical = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "inv_status"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "status_code"], name="inv_status_company_code_uniq"
            )
        ]


class InventoryLot(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="lots")
    lot_no = models.CharField(max_length=100)
    supplier_lot_no = models.CharField(max_length=100, blank=True)
    manufactured_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    is_no_lot_sentinel = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "inv_lot"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "sku", "lot_no"], name="inv_lot_company_sku_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(expires_on__isnull=True)
                | models.Q(manufactured_on__isnull=True)
                | models.Q(expires_on__gt=models.F("manufactured_on")),
                name="inv_lot_dates_ck",
            ),
        ]


class InventoryBalance(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    location = models.ForeignKey(WarehouseLocation, on_delete=models.PROTECT)
    inventory_status = models.ForeignKey(InventoryStatus, on_delete=models.PROTECT)
    lot = models.ForeignKey(InventoryLot, on_delete=models.PROTECT)
    on_hand_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    reserved_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    locked_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    row_version = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inv_balance"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "company",
                    "sku",
                    "warehouse",
                    "location",
                    "inventory_status",
                    "lot",
                ],
                name="inv_balance_dimension_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(on_hand_qty__gte=0), name="inv_balance_on_hand_nonnegative_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_qty__gte=0), name="inv_balance_reserved_nonnegative_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(locked_qty__gte=0), name="inv_balance_locked_nonnegative_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    on_hand_qty__gte=models.F("reserved_qty") + models.F("locked_qty")
                ),
                name="inv_balance_committed_lte_on_hand_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "warehouse", "sku", "inventory_status"],
                name="inv_balance_stock_lookup_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.sku_id}:{self.location_id}:{self.on_hand_qty}"

    @property
    def physical_free_qty(self) -> Decimal:
        return self.on_hand_qty - self.reserved_qty - self.locked_qty


class ImmutableLedgerQuerySet(models.QuerySet["InventoryLedger"]):
    def update(self, **kwargs: object) -> int:
        raise RuntimeError("库存流水只允许追加，禁止更新")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise RuntimeError("库存流水只允许追加，禁止删除")


class InventoryLedger(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField()
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    location = models.ForeignKey(WarehouseLocation, on_delete=models.PROTECT)
    inventory_status = models.ForeignKey(InventoryStatus, on_delete=models.PROTECT)
    lot = models.ForeignKey(InventoryLot, on_delete=models.PROTECT)
    transaction_type = models.CharField(max_length=50)
    quantity_delta = models.DecimalField(max_digits=20, decimal_places=6)
    before_qty = models.DecimalField(max_digits=20, decimal_places=6)
    after_qty = models.DecimalField(max_digits=20, decimal_places=6)
    reference_type = models.CharField(max_length=80)
    reference_id = models.PositiveBigIntegerField()
    reference_no = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=200, unique=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableLedgerQuerySet.as_manager()

    class Meta:
        db_table = "inv_ledger"
        indexes = [
            models.Index(
                fields=["company", "sku", "occurred_at", "id"],
                name="inv_ledger_sku_time_idx",
            ),
            models.Index(fields=["reference_type", "reference_id"], name="inv_ledger_ref_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.idempotency_key}:{self.quantity_delta}"

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is not None:
            raise RuntimeError("库存流水只允许追加，禁止更新")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise RuntimeError("库存流水只允许追加，禁止删除")


class InventoryReservation(AuditedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        CONSUMED = "consumed", "已消耗"
        RELEASED = "released", "已释放"
        EXPIRED = "expired", "已过期"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    reservation_no = models.CharField(max_length=100)
    sales_order_line = models.ForeignKey(
        "sales.SalesOrderLine", on_delete=models.PROTECT, related_name="inventory_reservations"
    )
    balance = models.ForeignKey(InventoryBalance, on_delete=models.PROTECT)
    reserved_qty = models.DecimalField(max_digits=20, decimal_places=6)
    consumed_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    released_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    status = models.CharField(max_length=32, choices=Status, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inv_reservation"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "reservation_no"], name="inv_reservation_company_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_qty__gt=0), name="inv_reservation_reserved_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(consumed_qty__gte=0) & models.Q(released_qty__gte=0),
                name="inv_reservation_used_nonnegative_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    reserved_qty__gte=models.F("consumed_qty") + models.F("released_qty")
                ),
                name="inv_reservation_used_lte_reserved_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["sales_order_line", "status"], name="inv_reservation_order_line_idx"
            ),
            models.Index(fields=["balance", "status"], name="inv_reservation_balance_idx"),
        ]

    @property
    def remaining_qty(self) -> Decimal:
        return self.reserved_qty - self.consumed_qty - self.released_qty


class StockTransfer(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        IN_TRANSIT = "in_transit", "在途"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    transfer_no = models.CharField(max_length=100)
    source_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="outbound_transfers"
    )
    destination_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="inbound_transfers"
    )
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    version_no = models.PositiveBigIntegerField(default=1)
    dispatch_idempotency_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    receipt_idempotency_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dispatched_stock_transfers",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_stock_transfers",
    )

    class Meta:
        db_table = "inv_stock_transfer"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "transfer_no"], name="inv_transfer_company_no_uniq"
            ),
            models.CheckConstraint(
                condition=~models.Q(source_warehouse=models.F("destination_warehouse")),
                name="inv_transfer_warehouses_different_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status", "created_at"], name="inv_transfer_status_idx")
        ]


class StockTransferLine(AuditedModel):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    source_balance = models.ForeignKey(
        InventoryBalance, on_delete=models.PROTECT, related_name="transfer_source_lines"
    )
    destination_balance = models.ForeignKey(
        InventoryBalance, on_delete=models.PROTECT, related_name="transfer_destination_lines"
    )
    requested_qty = models.DecimalField(max_digits=20, decimal_places=6)
    dispatched_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    received_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    difference_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "inv_stock_transfer_line"
        constraints = [
            models.UniqueConstraint(
                fields=["transfer", "line_no"], name="inv_transfer_line_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(requested_qty__gt=0)
                & models.Q(dispatched_qty__gte=0)
                & models.Q(received_qty__gte=0),
                name="inv_transfer_line_quantities_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(requested_qty__gte=models.F("dispatched_qty")),
                name="inv_transfer_dispatched_lte_requested_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(dispatched_qty__gte=models.F("received_qty")),
                name="inv_transfer_received_lte_dispatched_ck",
            ),
        ]


class StockCount(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        COUNTING = "counting", "盘点中"
        PENDING_APPROVAL = "pending_approval", "待审批"
        POSTED = "posted", "已过账"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    count_no = models.CharField(max_length=100)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    version_no = models.PositiveBigIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    post_idempotency_key = models.CharField(max_length=200, null=True, blank=True, unique=True)

    class Meta:
        db_table = "inv_stock_count"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "count_no"], name="inv_count_company_no_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["company", "warehouse", "status"], name="inv_count_lookup_idx")
        ]


class StockCountLine(AuditedModel):
    count = models.ForeignKey(StockCount, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    balance = models.ForeignKey(InventoryBalance, on_delete=models.PROTECT)
    book_qty = models.DecimalField(max_digits=20, decimal_places=6)
    counted_qty = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    difference_qty = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        db_table = "inv_stock_count_line"
        constraints = [
            models.UniqueConstraint(fields=["count", "line_no"], name="inv_count_line_no_uniq"),
            models.UniqueConstraint(fields=["count", "balance"], name="inv_count_balance_uniq"),
            models.CheckConstraint(
                condition=models.Q(book_qty__gte=0)
                & (models.Q(counted_qty__isnull=True) | models.Q(counted_qty__gte=0)),
                name="inv_count_line_quantities_ck",
            ),
        ]

from django.db import models

from kaxi.master_data.models import Company
from kaxi.shared.models import AuditedModel


class Warehouse(AuditedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    warehouse_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    status = models.CharField(max_length=32, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "wms_warehouse"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "warehouse_code"], name="wms_warehouse_company_code_uniq"
            )
        ]


class WarehouseArea(AuditedModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="areas")
    area_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    area_type = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "wms_area"
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "area_code"], name="wms_area_warehouse_code_uniq"
            )
        ]


class WarehouseRack(AuditedModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="racks")
    area = models.ForeignKey(WarehouseArea, on_delete=models.PROTECT, related_name="racks")
    rack_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "wms_rack"
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "rack_code"], name="wms_rack_warehouse_code_uniq"
            )
        ]


class WarehouseLocation(AuditedModel):
    class LocationType(models.TextChoices):
        STORAGE = "storage", "存储"
        STAGING = "staging", "暂存"
        INSPECTION = "inspection", "质检"
        EXCEPTION = "exception", "异常"
        PICKING = "picking", "拣货"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        BLOCKED = "blocked", "冻结"
        INACTIVE = "inactive", "停用"

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="locations")
    area = models.ForeignKey(WarehouseArea, on_delete=models.PROTECT, related_name="locations")
    rack = models.ForeignKey(
        WarehouseRack, null=True, blank=True, on_delete=models.PROTECT, related_name="locations"
    )
    location_code = models.CharField(max_length=100)
    name = models.CharField(max_length=200, blank=True)
    location_type = models.CharField(max_length=32, choices=LocationType)
    allow_mixed_sku = models.BooleanField(default=False)
    capacity_qty = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    capacity_weight = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    capacity_volume = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status, default=Status.ACTIVE)

    class Meta:
        db_table = "wms_location"
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "location_code"], name="wms_location_warehouse_code_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_qty__isnull=True) | models.Q(capacity_qty__gte=0),
                name="wms_location_capacity_qty_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_weight__isnull=True) | models.Q(capacity_weight__gte=0),
                name="wms_location_capacity_weight_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_volume__isnull=True) | models.Q(capacity_volume__gte=0),
                name="wms_location_capacity_volume_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["warehouse", "area", "status"], name="wms_location_area_status_idx"
            )
        ]


class WarehouseTask(AuditedModel):
    class TaskType(models.TextChoices):
        PUTAWAY = "putaway", "上架"
        PICK = "pick", "拣货"
        PACK = "pack", "打包复核"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        RELEASED = "released", "已下达"
        IN_PROGRESS = "in_progress", "执行中"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    task_no = models.CharField(max_length=100)
    task_type = models.CharField(max_length=16, choices=TaskType)
    goods_receipt = models.ForeignKey(
        "purchasing.GoodsReceipt", null=True, blank=True, on_delete=models.PROTECT
    )
    sales_shipment = models.ForeignKey(
        "sales.SalesShipment", null=True, blank=True, on_delete=models.PROTECT
    )
    wave_no = models.CharField(max_length=100, blank=True)
    assigned_to = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assigned_warehouse_tasks",
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    released_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wms_task"
        constraints = [
            models.UniqueConstraint(fields=["company", "task_no"], name="wms_task_no_uniq"),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        task_type="putaway",
                        goods_receipt__isnull=False,
                        sales_shipment__isnull=True,
                    )
                    | models.Q(
                        task_type__in=["pick", "pack"],
                        goods_receipt__isnull=True,
                        sales_shipment__isnull=False,
                    )
                ),
                name="wms_task_source_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "warehouse", "status", "task_type"], name="wms_task_queue_idx"
            )
        ]


class WarehouseTaskLine(AuditedModel):
    task = models.ForeignKey(WarehouseTask, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    sku = models.ForeignKey("products.ProductSku", on_delete=models.PROTECT)
    source_balance = models.ForeignKey(
        "inventory.InventoryBalance", null=True, blank=True, on_delete=models.PROTECT
    )
    target_location = models.ForeignKey(
        WarehouseLocation, null=True, blank=True, on_delete=models.PROTECT
    )
    sales_shipment_line = models.ForeignKey(
        "sales.SalesShipmentLine", null=True, blank=True, on_delete=models.PROTECT
    )
    planned_qty = models.DecimalField(max_digits=20, decimal_places=6)
    scanned_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    completed_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    exception_code = models.CharField(max_length=50, blank=True)
    exception_detail = models.TextField(blank=True)

    class Meta:
        db_table = "wms_task_line"
        constraints = [
            models.UniqueConstraint(fields=["task", "line_no"], name="wms_task_line_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gt=0)
                & models.Q(scanned_qty__gte=0)
                & models.Q(completed_qty__gte=0)
                & models.Q(planned_qty__gte=models.F("scanned_qty"))
                & models.Q(scanned_qty__gte=models.F("completed_qty")),
                name="wms_task_line_qty_ck",
            ),
        ]


class WarehouseScanEvent(models.Model):
    task = models.ForeignKey(WarehouseTask, on_delete=models.PROTECT, related_name="scan_events")
    line = models.ForeignKey(
        WarehouseTaskLine, on_delete=models.PROTECT, related_name="scan_events"
    )
    scan_type = models.CharField(max_length=32)
    scanned_value = models.CharField(max_length=300)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    idempotency_key = models.CharField(max_length=200, unique=True)
    operator = models.ForeignKey("identity.User", on_delete=models.PROTECT)
    occurred_at = models.DateTimeField()
    device_id = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "wms_scan_event"
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="wms_scan_qty_ck")
        ]
        indexes = [
            models.Index(fields=["task", "occurred_at", "id"], name="wms_scan_task_time_idx")
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.line_id}:{self.scanned_value}"

from django.db import models
from django.db.models.functions import Lower

from kaxi.master_data.models import Company, Region, UnitOfMeasure
from kaxi.shared.models import AuditedModel


class ProductCategory(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    category_code = models.CharField(max_length=100)
    name_zh = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prd_category"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "category_code"], name="prd_category_company_code_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["company", "parent", "is_active"], name="prd_category_tree_idx")
        ]


class Brand(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    brand_code = models.CharField(max_length=100)
    name_zh = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prd_brand"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "brand_code"], name="prd_brand_company_code_uniq"
            )
        ]


class ProductSpu(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    spu_code = models.CharField(max_length=100)
    name_zh = models.CharField(max_length=500)
    name_en = models.CharField(max_length=500, blank=True)
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    extension_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "prd_spu"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "spu_code"], name="prd_spu_company_code_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["company", "category", "status"], name="prd_spu_catalog_idx")
        ]


class ProductSku(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"
        DISCONTINUED = "discontinued", "终止"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    sku_code = models.CharField(max_length=100)
    spu = models.ForeignKey(ProductSpu, on_delete=models.PROTECT, related_name="skus")
    name_zh = models.CharField(max_length=500)
    name_en = models.CharField(max_length=500, blank=True)
    base_uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    is_serialized = models.BooleanField(default=False)
    is_limited_edition = models.BooleanField(default=False)
    is_lot_tracked = models.BooleanField(default=False)
    allow_oversell = models.BooleanField(default=False)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)

    class Meta:
        db_table = "prd_sku"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "sku_code"], name="prd_sku_company_code_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(is_limited_edition=False) | models.Q(is_serialized=True),
                name="prd_sku_limited_requires_serial_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "spu", "status"], name="prd_sku_spu_status_idx"),
            models.Index(Lower("name_zh"), name="prd_sku_name_zh_lower_idx"),
        ]


class SkuBarcode(AuditedModel):
    class BarcodeType(models.TextChoices):
        EAN13 = "ean13", "EAN-13"
        UPC = "upc", "UPC"
        CODE128 = "code128", "Code 128"
        QR = "qr", "二维码"
        INTERNAL = "internal", "内部码"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="barcodes")
    barcode_type = models.CharField(max_length=16, choices=BarcodeType)
    barcode_value = models.CharField(max_length=200)
    normalized_value = models.CharField(max_length=200)
    purpose = models.CharField(max_length=50, blank=True)
    channel_code = models.CharField(max_length=50, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prd_sku_barcode"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "normalized_value"], name="prd_barcode_company_value_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_from__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="prd_barcode_valid_period_ck",
            ),
        ]
        indexes = [models.Index(fields=["sku", "is_active"], name="prd_barcode_sku_active_idx")]


class Material(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    material_code = models.CharField(max_length=100)
    name_zh = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True)
    is_high_value = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prd_material"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "material_code"], name="prd_material_company_code_uniq"
            )
        ]


class SkuMaterial(AuditedModel):
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="materials")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    content_percentage = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    standard_quantity = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    uom = models.ForeignKey(UnitOfMeasure, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        db_table = "prd_sku_material"
        constraints = [
            models.UniqueConstraint(fields=["sku", "material"], name="prd_sku_material_uniq"),
            models.CheckConstraint(
                condition=models.Q(content_percentage__isnull=True)
                | models.Q(content_percentage__gte=0, content_percentage__lte=100),
                name="prd_sku_material_percentage_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(standard_quantity__isnull=True)
                | models.Q(standard_quantity__gte=0),
                name="prd_sku_material_quantity_ck",
            ),
        ]


class ProductAttribute(AuditedModel):
    class DataType(models.TextChoices):
        TEXT = "text", "文本"
        NUMBER = "number", "数值"
        BOOLEAN = "boolean", "布尔"
        CHOICE = "choice", "选项"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    attribute_code = models.CharField(max_length=100)
    name_zh = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True)
    data_type = models.CharField(max_length=16, choices=DataType)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prd_attribute"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "attribute_code"], name="prd_attribute_company_code_uniq"
            )
        ]


class AttributeValue(AuditedModel):
    attribute = models.ForeignKey(ProductAttribute, on_delete=models.PROTECT, related_name="values")
    value_code = models.CharField(max_length=100)
    label_zh = models.CharField(max_length=200)
    label_en = models.CharField(max_length=200, blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prd_attribute_value"
        constraints = [
            models.UniqueConstraint(
                fields=["attribute", "value_code"], name="prd_attribute_value_code_uniq"
            )
        ]


class CategoryAttribute(AuditedModel):
    category = models.ForeignKey(
        ProductCategory, on_delete=models.PROTECT, related_name="attribute_rules"
    )
    attribute = models.ForeignKey(ProductAttribute, on_delete=models.PROTECT)
    is_required = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "prd_category_attribute"
        constraints = [
            models.UniqueConstraint(
                fields=["category", "attribute"], name="prd_category_attribute_uniq"
            )
        ]


class SkuAttributeValue(AuditedModel):
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="attribute_values")
    attribute = models.ForeignKey(ProductAttribute, on_delete=models.PROTECT)
    choice_value = models.ForeignKey(
        AttributeValue, null=True, blank=True, on_delete=models.PROTECT
    )
    text_value = models.CharField(max_length=500, blank=True)
    number_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "prd_sku_attribute_value"
        constraints = [
            models.UniqueConstraint(fields=["sku", "attribute"], name="prd_sku_attribute_uniq")
        ]


class ProductTradeProfile(AuditedModel):
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="trade_profiles")
    country_region = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.PROTECT, related_name="trade_profiles"
    )
    language = models.CharField(max_length=20)
    declared_name = models.CharField(max_length=500)
    hs_code = models.CharField(max_length=50, blank=True)
    origin_country = models.ForeignKey(
        Region, null=True, blank=True, on_delete=models.PROTECT, related_name="origin_products"
    )
    declaration_uom = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.PROTECT
    )
    declaration_elements = models.JSONField(default=dict, blank=True)
    net_weight = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    gross_weight = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    volume = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "prd_trade_profile"
        constraints = [
            models.UniqueConstraint(
                fields=["sku", "country_region", "language", "valid_from"],
                nulls_distinct=False,
                name="prd_trade_profile_scope_start_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_from__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="prd_trade_profile_period_ck",
            ),
            models.CheckConstraint(
                condition=(models.Q(net_weight__isnull=True) | models.Q(net_weight__gte=0))
                & (models.Q(gross_weight__isnull=True) | models.Q(gross_weight__gte=0))
                & (models.Q(volume__isnull=True) | models.Q(volume__gte=0)),
                name="prd_trade_profile_measure_ck",
            ),
        ]


class LimitedEditionPool(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        CLOSED = "closed", "关闭"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="limited_pools")
    edition_code = models.CharField(max_length=100)
    total_limit = models.PositiveBigIntegerField()
    numbering_rule = models.JSONField(default=dict)
    allocated_count = models.PositiveBigIntegerField(default=0)
    produced_good_count = models.PositiveBigIntegerField(default=0)
    next_sort_value = models.PositiveBigIntegerField(default=1)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)

    class Meta:
        db_table = "prd_limited_edition_pool"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "edition_code"], name="prd_limited_pool_company_code_uniq"
            ),
            models.UniqueConstraint(
                fields=["sku", "edition_code"], name="prd_limited_pool_sku_edition_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(total_limit__gt=0), name="prd_limited_pool_total_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(total_limit__gte=models.F("allocated_count")),
                name="prd_limited_pool_allocated_lte_total_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(allocated_count__gte=models.F("produced_good_count")),
                name="prd_limited_pool_good_lte_allocated_ck",
            ),
        ]


class ProductSerial(AuditedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "已规划"
        WAITING_PRODUCTION = "waiting_production", "待生产"
        IN_PRODUCTION = "in_production", "生产中"
        IN_STOCK = "in_stock", "在库可售"
        RESERVED = "reserved", "已预留"
        PICKED = "picked", "已拣货"
        SHIPPED = "shipped", "已发货"
        SOLD = "sold", "已售完成"
        NG = "ng", "NG"
        WAITING_REWORK = "waiting_rework", "待返工"
        WAITING_REPRODUCTION = "waiting_reproduction", "待重生产"
        SCRAPPED = "scrapped", "报废"
        VOID = "void", "作废"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    limited_pool = models.ForeignKey(
        LimitedEditionPool, null=True, blank=True, on_delete=models.PROTECT, related_name="serials"
    )
    sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="serials")
    serial_no = models.CharField(max_length=100)
    serial_sort_value = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status, default=Status.PLANNED)
    warehouse = models.ForeignKey(
        "warehouse.Warehouse", null=True, blank=True, on_delete=models.PROTECT
    )
    location = models.ForeignKey(
        "warehouse.WarehouseLocation", null=True, blank=True, on_delete=models.PROTECT
    )
    current_customer = models.ForeignKey(
        "master_data.Party", null=True, blank=True, on_delete=models.PROTECT
    )
    current_sales_order = models.ForeignKey(
        "sales.SalesOrder", null=True, blank=True, on_delete=models.PROTECT
    )
    current_production_order = models.ForeignKey(
        "manufacturing.ProductionOrder", null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        db_table = "prd_product_serial"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "sku", "serial_no"], name="prd_serial_company_sku_no_uniq"
            ),
            models.UniqueConstraint(
                fields=["limited_pool", "serial_sort_value"],
                condition=models.Q(limited_pool__isnull=False),
                name="prd_serial_pool_sort_uniq",
            ),
        ]
        indexes = [models.Index(fields=["company", "sku", "status"], name="prd_serial_lookup_idx")]


class SerialProductionAttempt(AuditedModel):
    class Result(models.TextChoices):
        IN_PROGRESS = "in_progress", "生产中"
        GOOD = "good", "合格"
        NG = "ng", "NG"
        CANCELLED = "cancelled", "取消"

    serial = models.ForeignKey(
        ProductSerial, on_delete=models.PROTECT, related_name="production_attempts"
    )
    production_order = models.ForeignKey(
        "manufacturing.ProductionOrder", on_delete=models.PROTECT, related_name="serial_attempts"
    )
    attempt_no = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(max_length=32, choices=Result, default=Result.IN_PROGRESS)
    ng_reason = models.TextField(blank=True)
    previous_attempt = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    inspection_reference = models.CharField(max_length=200, blank=True)
    idempotency_key = models.CharField(max_length=200, unique=True)

    class Meta:
        db_table = "prd_serial_production_attempt"
        constraints = [
            models.UniqueConstraint(
                fields=["serial", "attempt_no"], name="prd_serial_attempt_no_uniq"
            )
        ]


class SerialReservation(AuditedModel):
    class AllocationType(models.TextChoices):
        AUTOMATIC = "automatic", "自动分配"
        SPECIFIED = "specified", "指定编号"

    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        RELEASED = "released", "已释放"
        CONSUMED = "consumed", "已消耗"
        EXPIRED = "expired", "已过期"

    serial = models.ForeignKey(ProductSerial, on_delete=models.PROTECT, related_name="reservations")
    sales_order_line = models.ForeignKey(
        "sales.SalesOrderLine", on_delete=models.PROTECT, related_name="serial_reservations"
    )
    allocation_type = models.CharField(max_length=32, choices=AllocationType)
    status = models.CharField(max_length=32, choices=Status, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    released_reason = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=200, unique=True)

    class Meta:
        db_table = "prd_serial_reservation"
        constraints = [
            models.UniqueConstraint(
                fields=["serial"],
                condition=models.Q(status="active"),
                name="prd_serial_one_active_reservation_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["sales_order_line", "status"], name="prd_serial_res_order_idx")
        ]


class SerialShipmentAssignment(AuditedModel):
    class Status(models.TextChoices):
        ASSIGNED = "assigned", "已分配"
        PICKED = "picked", "已拣货"
        SHIPPED = "shipped", "已发货"

    serial = models.OneToOneField(
        ProductSerial, on_delete=models.PROTECT, related_name="shipment_assignment"
    )
    reservation = models.OneToOneField(
        SerialReservation, on_delete=models.PROTECT, related_name="shipment_assignment"
    )
    shipment_line = models.ForeignKey(
        "sales.SalesShipmentLine", on_delete=models.PROTECT, related_name="serial_assignments"
    )
    status = models.CharField(max_length=32, choices=Status, default=Status.ASSIGNED)

    class Meta:
        db_table = "prd_serial_shipment_assignment"


class SerialStatusHistory(models.Model):
    serial = models.ForeignKey(
        ProductSerial, on_delete=models.PROTECT, related_name="status_history"
    )
    from_status = models.CharField(max_length=32)
    to_status = models.CharField(max_length=32)
    reason = models.TextField(blank=True)
    reference_type = models.CharField(max_length=80, blank=True)
    reference_id = models.PositiveBigIntegerField(null=True, blank=True)
    actor = models.ForeignKey("identity.User", null=True, blank=True, on_delete=models.PROTECT)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prd_serial_status_history"
        indexes = [models.Index(fields=["serial", "occurred_at"], name="prd_serial_history_idx")]

    def __str__(self) -> str:
        return f"{self.serial_id}:{self.from_status}->{self.to_status}"

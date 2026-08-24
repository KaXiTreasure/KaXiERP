from django.conf import settings
from django.db import models

from kaxi.inventory.models import InventoryBalance
from kaxi.master_data.models import Company, Currency, Party, UnitOfMeasure
from kaxi.products.models import ProductSku
from kaxi.shared.models import AuditedModel
from kaxi.warehouse.models import Warehouse


class BillOfMaterial(AuditedModel):
    class BomType(models.TextChoices):
        PRODUCTION = "production", "生产BOM"
        PACKAGING = "packaging", "包装BOM"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        ACTIVE = "active", "启用"
        OBSOLETE = "obsolete", "已作废"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    bom_no = models.CharField(max_length=100)
    product_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT, related_name="boms")
    bom_type = models.CharField(max_length=32, choices=BomType)
    version = models.CharField(max_length=50)
    output_qty = models.DecimalField(max_digits=20, decimal_places=6)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    approval_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "mfg_bom"
        constraints = [
            models.UniqueConstraint(fields=["company", "bom_no"], name="mfg_bom_company_no_uniq"),
            models.UniqueConstraint(
                fields=["product_sku", "bom_type", "version"],
                name="mfg_bom_product_type_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(output_qty__gt=0), name="mfg_bom_output_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="mfg_bom_valid_period_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "product_sku", "bom_type", "status", "valid_from"],
                name="mfg_bom_effective_idx",
            )
        ]


class BillOfMaterialItem(AuditedModel):
    class IssueMethod(models.TextChoices):
        MANUAL = "manual", "手工领料"
        BACKFLUSH = "backflush", "倒冲"

    bom = models.ForeignKey(BillOfMaterial, on_delete=models.PROTECT, related_name="items")
    line_no = models.PositiveIntegerField()
    component_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    standard_qty = models.DecimalField(max_digits=20, decimal_places=6)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    expected_loss_rate = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    issue_method = models.CharField(max_length=32, choices=IssueMethod, default=IssueMethod.MANUAL)
    is_critical = models.BooleanField(default=False)

    class Meta:
        db_table = "mfg_bom_item"
        constraints = [
            models.UniqueConstraint(fields=["bom", "line_no"], name="mfg_bom_item_line_uniq"),
            models.UniqueConstraint(fields=["bom", "component_sku"], name="mfg_bom_component_uniq"),
            models.CheckConstraint(
                condition=models.Q(standard_qty__gt=0), name="mfg_bom_item_qty_positive_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(expected_loss_rate__gte=0) & models.Q(expected_loss_rate__lte=1),
                name="mfg_bom_item_loss_rate_ck",
            ),
        ]


class ProductionOrder(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        RELEASED = "released", "已下达"
        WAITING_MATERIAL = "waiting_material", "待料"
        IN_PROGRESS = "in_progress", "生产中"
        PARTIALLY_COMPLETED = "partially_completed", "部分完工"
        COMPLETED = "completed", "已完工"
        CLOSED = "closed", "已结案"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    production_order_no = models.CharField(max_length=100)
    product_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    bom = models.ForeignKey(BillOfMaterial, on_delete=models.PROTECT)
    routing = models.ForeignKey("Routing", null=True, blank=True, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=20, decimal_places=6)
    completed_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    accepted_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    source_type = models.CharField(max_length=50, blank=True)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "mfg_production_order"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "production_order_no"], name="mfg_order_company_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gt=0)
                & models.Q(completed_qty__gte=0)
                & models.Q(accepted_qty__gte=0)
                & models.Q(rejected_qty__gte=0),
                name="mfg_order_quantities_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gte=models.F("completed_qty")),
                name="mfg_order_completed_lte_planned_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    completed_qty=models.F("accepted_qty") + models.F("rejected_qty")
                ),
                name="mfg_order_result_sum_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status", "planned_start"], name="mfg_order_status_idx")
        ]


class ProductionConsumption(AuditedModel):
    production_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="consumptions"
    )
    component_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    standard_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    issued_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    returned_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    actual_consumed_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    loss_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    loss_rate = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    unit_cost = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    base_cost = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)

    class Meta:
        db_table = "mfg_consumption"
        constraints = [
            models.UniqueConstraint(
                fields=["production_order", "component_sku"], name="mfg_consumption_component_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(standard_qty__gte=0)
                & models.Q(issued_qty__gte=0)
                & models.Q(returned_qty__gte=0)
                & models.Q(actual_consumed_qty__gte=0)
                & models.Q(loss_qty__gte=0),
                name="mfg_consumption_quantities_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    issued_qty__gte=models.F("returned_qty") + models.F("actual_consumed_qty")
                ),
                name="mfg_consumption_usage_lte_issued_ck",
            ),
        ]


class MaterialIssue(AuditedModel):
    production_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="issues"
    )
    issue_no = models.CharField(max_length=100)
    source_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=32, default="posted")

    class Meta:
        db_table = "mfg_material_issue"
        constraints = [
            models.UniqueConstraint(
                fields=["production_order", "issue_no"], name="mfg_issue_order_no_uniq"
            )
        ]


class MaterialIssueLine(AuditedModel):
    issue = models.ForeignKey(MaterialIssue, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    component_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    source_balance = models.ForeignKey(InventoryBalance, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=20, decimal_places=6)
    actual_qty = models.DecimalField(max_digits=20, decimal_places=6)

    class Meta:
        db_table = "mfg_material_issue_line"
        constraints = [
            models.UniqueConstraint(fields=["issue", "line_no"], name="mfg_issue_line_no_uniq"),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gte=0) & models.Q(actual_qty__gt=0),
                name="mfg_issue_line_quantities_ck",
            ),
        ]


class ProductionCompletion(AuditedModel):
    production_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="completions"
    )
    completion_no = models.CharField(max_length=100)
    accepted_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    accepted_balance = models.ForeignKey(
        InventoryBalance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_completions",
    )
    rejected_balance = models.ForeignKey(
        InventoryBalance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="rejected_completions",
    )
    completed_at = models.DateTimeField()
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=200, unique=True)

    class Meta:
        db_table = "mfg_production_completion"
        constraints = [
            models.UniqueConstraint(
                fields=["production_order", "completion_no"], name="mfg_completion_order_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(accepted_qty__gte=0)
                & models.Q(rejected_qty__gte=0)
                & (models.Q(accepted_qty__gt=0) | models.Q(rejected_qty__gt=0)),
                name="mfg_completion_quantities_ck",
            ),
        ]


class WorkCenter(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    work_center_code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    capacity_per_hour = models.DecimalField(max_digits=20, decimal_places=6)
    hourly_rate = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "mfg_work_center"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "work_center_code"], name="mfg_work_center_code_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_per_hour__gt=0) & models.Q(hourly_rate__gte=0),
                name="mfg_work_center_values_ck",
            ),
        ]


class Routing(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        OBSOLETE = "obsolete", "作废"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    routing_no = models.CharField(max_length=100)
    product_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    version = models.CharField(max_length=50)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)
    approval_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "mfg_routing"
        constraints = [
            models.UniqueConstraint(fields=["company", "routing_no"], name="mfg_routing_no_uniq"),
            models.UniqueConstraint(
                fields=["product_sku", "version"], name="mfg_routing_product_version_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="mfg_routing_dates_ck",
            ),
        ]


class RoutingOperation(AuditedModel):
    routing = models.ForeignKey(Routing, on_delete=models.PROTECT, related_name="operations")
    sequence = models.PositiveIntegerField()
    operation_code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    work_center = models.ForeignKey(WorkCenter, on_delete=models.PROTECT)
    setup_minutes = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    run_minutes_per_unit = models.DecimalField(max_digits=20, decimal_places=6)
    queue_minutes = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    inspection_required = models.BooleanField(default=False)

    class Meta:
        db_table = "mfg_routing_operation"
        constraints = [
            models.UniqueConstraint(
                fields=["routing", "sequence"], name="mfg_routing_operation_seq_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(setup_minutes__gte=0)
                & models.Q(run_minutes_per_unit__gt=0)
                & models.Q(queue_minutes__gte=0),
                name="mfg_routing_operation_time_ck",
            ),
        ]


class OperationReport(AuditedModel):
    production_order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="operation_reports"
    )
    operation = models.ForeignKey(RoutingOperation, on_delete=models.PROTECT)
    report_no = models.CharField(max_length=100)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    good_qty = models.DecimalField(max_digits=20, decimal_places=6)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    labor_minutes = models.DecimalField(max_digits=20, decimal_places=6)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        db_table = "mfg_operation_report"
        constraints = [
            models.UniqueConstraint(
                fields=["production_order", "report_no"], name="mfg_operation_report_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__gt=models.F("started_at")),
                name="mfg_operation_report_dates_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(good_qty__gte=0)
                & models.Q(rejected_qty__gte=0)
                & models.Q(labor_minutes__gte=0),
                name="mfg_operation_report_values_ck",
            ),
        ]


class ProductionSuggestion(AuditedModel):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    suggestion_no = models.CharField(max_length=100)
    product_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    suggested_qty = models.DecimalField(max_digits=20, decimal_places=6)
    required_date = models.DateField()
    source_type = models.CharField(max_length=50)
    source_id = models.CharField(max_length=100)
    reason_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=16, default="open")
    production_order = models.OneToOneField(
        ProductionOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_suggestion",
    )

    class Meta:
        db_table = "mfg_production_suggestion"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "suggestion_no"], name="mfg_suggestion_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(suggested_qty__gt=0), name="mfg_suggestion_qty_ck"
            ),
        ]


class SubcontractOrder(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        MATERIAL_SENT = "material_sent", "已发料"
        PROCESSING = "processing", "加工中"
        RECEIVED = "received", "已收回"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    subcontract_no = models.CharField(max_length=100)
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT)
    production_order = models.ForeignKey(
        ProductionOrder, null=True, blank=True, on_delete=models.PROTECT
    )
    product_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    ordered_qty = models.DecimalField(max_digits=20, decimal_places=6)
    received_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    accepted_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    rejected_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    processing_unit_price = models.DecimalField(max_digits=20, decimal_places=6)
    expected_return_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="subcontract_requests"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_subcontracts",
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "mfg_subcontract_order"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "subcontract_no"], name="mfg_subcontract_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(ordered_qty__gt=0)
                & models.Q(received_qty__gte=0)
                & models.Q(accepted_qty__gte=0)
                & models.Q(rejected_qty__gte=0)
                & models.Q(processing_unit_price__gte=0),
                name="mfg_subcontract_values_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(received_qty=models.F("accepted_qty") + models.F("rejected_qty"))
                & models.Q(received_qty__lte=models.F("ordered_qty")),
                name="mfg_subcontract_result_ck",
            ),
        ]


class SubcontractMaterial(AuditedModel):
    subcontract_order = models.ForeignKey(
        SubcontractOrder, on_delete=models.PROTECT, related_name="materials"
    )
    component_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    source_balance = models.ForeignKey(InventoryBalance, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=20, decimal_places=6)
    sent_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    consumed_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    returned_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "mfg_subcontract_material"
        constraints = [
            models.UniqueConstraint(
                fields=["subcontract_order", "component_sku"],
                name="mfg_subcontract_material_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gt=0)
                & models.Q(sent_qty__gte=0)
                & models.Q(consumed_qty__gte=0)
                & models.Q(returned_qty__gte=0)
                & models.Q(sent_qty__lte=models.F("planned_qty"))
                & models.Q(sent_qty__gte=models.F("consumed_qty") + models.F("returned_qty")),
                name="mfg_subcontract_material_qty_ck",
            ),
        ]

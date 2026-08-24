from django.conf import settings
from django.db import models

from kaxi.inventory.models import InventoryBalance
from kaxi.master_data.models import Company, UnitOfMeasure
from kaxi.products.models import ProductSku
from kaxi.sales.models import SalesChannel
from kaxi.shared.models import AuditedModel
from kaxi.warehouse.models import Warehouse, WarehouseLocation


class PackagingPlan(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        OBSOLETE = "obsolete", "已作废"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    plan_no = models.CharField(max_length=100)
    name = models.CharField(max_length=300)
    product_sku = models.ForeignKey(
        ProductSku, on_delete=models.PROTECT, related_name="packaging_plans"
    )
    channel = models.ForeignKey(SalesChannel, null=True, blank=True, on_delete=models.PROTECT)
    trade_type = models.CharField(max_length=50, blank=True)
    version = models.CharField(max_length=50)
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    approval_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "ppk_packaging_plan"
        constraints = [
            models.UniqueConstraint(fields=["company", "plan_no"], name="ppk_plan_company_no_uniq"),
            models.UniqueConstraint(
                fields=["product_sku", "channel", "trade_type", "version"],
                name="ppk_plan_scope_version_uniq",
            ),
        ]


class PackagingPlanItem(AuditedModel):
    plan = models.ForeignKey(PackagingPlan, on_delete=models.PROTECT, related_name="items")
    line_no = models.PositiveIntegerField()
    material_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    standard_qty = models.DecimalField(max_digits=20, decimal_places=6)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT)
    allowed_loss_rate = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    returnable_on_breakdown = models.BooleanField(default=False)

    class Meta:
        db_table = "ppk_packaging_plan_item"
        constraints = [
            models.UniqueConstraint(fields=["plan", "line_no"], name="ppk_plan_item_line_uniq"),
            models.UniqueConstraint(fields=["plan", "material_sku"], name="ppk_plan_material_uniq"),
            models.CheckConstraint(
                condition=models.Q(standard_qty__gt=0), name="ppk_plan_item_qty_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(allowed_loss_rate__gte=0) & models.Q(allowed_loss_rate__lte=1),
                name="ppk_plan_item_loss_ck",
            ),
        ]


class PrepackOrder(AuditedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        APPROVED = "approved", "已批准"
        PACKAGING = "packaging", "包装中"
        PARTIALLY_COMPLETED = "partially_completed", "部分完成"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    prepack_order_no = models.CharField(max_length=100)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    product_sku = models.ForeignKey(ProductSku, on_delete=models.PROTECT)
    packaging_plan = models.ForeignKey(PackagingPlan, on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=20, decimal_places=6)
    completed_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    broken_down_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    source_location = models.ForeignKey(
        WarehouseLocation, on_delete=models.PROTECT, related_name="prepack_source_orders"
    )
    target_location = models.ForeignKey(
        WarehouseLocation, on_delete=models.PROTECT, related_name="prepack_target_orders"
    )
    status = models.CharField(max_length=32, choices=Status, default=Status.DRAFT)
    version_no = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "ppk_order"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "prepack_order_no"], name="ppk_order_company_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gt=0)
                & models.Q(completed_qty__gte=0)
                & models.Q(broken_down_qty__gte=0),
                name="ppk_order_quantities_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(planned_qty__gte=models.F("completed_qty")),
                name="ppk_order_completed_lte_planned_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(completed_qty__gte=models.F("broken_down_qty")),
                name="ppk_order_breakdown_lte_completed_ck",
            ),
        ]


class PrepackExecution(AuditedModel):
    order = models.ForeignKey(PrepackOrder, on_delete=models.PROTECT, related_name="executions")
    execution_no = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    source_balance = models.ForeignKey(
        InventoryBalance, on_delete=models.PROTECT, related_name="prepack_source_executions"
    )
    target_balance = models.ForeignKey(
        InventoryBalance, on_delete=models.PROTECT, related_name="prepack_target_executions"
    )
    executed_at = models.DateTimeField()
    executed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=200, unique=True)

    class Meta:
        db_table = "ppk_execution"
        constraints = [
            models.UniqueConstraint(
                fields=["order", "execution_no"], name="ppk_execution_order_no_uniq"
            ),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="ppk_execution_qty_ck"),
        ]


class PrepackMaterialUsage(AuditedModel):
    execution = models.ForeignKey(
        PrepackExecution, on_delete=models.PROTECT, related_name="material_usages"
    )
    plan_item = models.ForeignKey(PackagingPlanItem, on_delete=models.PROTECT)
    material_balance = models.ForeignKey(InventoryBalance, on_delete=models.PROTECT)
    standard_qty = models.DecimalField(max_digits=20, decimal_places=6)
    actual_used_qty = models.DecimalField(max_digits=20, decimal_places=6)
    loss_qty = models.DecimalField(max_digits=20, decimal_places=6, default=0)

    class Meta:
        db_table = "ppk_material_usage"
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "plan_item"], name="ppk_usage_plan_item_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(standard_qty__gte=0)
                & models.Q(actual_used_qty__gt=0)
                & models.Q(loss_qty__gte=0),
                name="ppk_usage_quantities_ck",
            ),
        ]


class PrepackBreakdown(AuditedModel):
    order = models.ForeignKey(PrepackOrder, on_delete=models.PROTECT, related_name="breakdowns")
    breakdown_no = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    prepacked_balance = models.ForeignKey(
        InventoryBalance, on_delete=models.PROTECT, related_name="prepack_breakdown_sources"
    )
    restored_product_balance = models.ForeignKey(
        InventoryBalance, on_delete=models.PROTECT, related_name="prepack_breakdown_products"
    )
    approval_reference = models.CharField(max_length=200)
    occurred_at = models.DateTimeField()
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=200, unique=True)

    class Meta:
        db_table = "ppk_breakdown"
        constraints = [
            models.UniqueConstraint(
                fields=["order", "breakdown_no"], name="ppk_breakdown_order_no_uniq"
            ),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="ppk_breakdown_qty_ck"),
        ]


class PrepackBreakdownMaterial(AuditedModel):
    breakdown = models.ForeignKey(
        PrepackBreakdown, on_delete=models.PROTECT, related_name="returned_materials"
    )
    plan_item = models.ForeignKey(PackagingPlanItem, on_delete=models.PROTECT)
    return_balance = models.ForeignKey(InventoryBalance, on_delete=models.PROTECT)
    returned_qty = models.DecimalField(max_digits=20, decimal_places=6)

    class Meta:
        db_table = "ppk_breakdown_material"
        constraints = [
            models.UniqueConstraint(
                fields=["breakdown", "plan_item"], name="ppk_breakdown_plan_item_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(returned_qty__gt=0), name="ppk_breakdown_return_qty_ck"
            ),
        ]

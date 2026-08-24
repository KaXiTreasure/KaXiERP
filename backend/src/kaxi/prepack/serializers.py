from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from kaxi.prepack.models import PackagingPlan, PackagingPlanItem, PrepackOrder


class PackagingPlanItemSerializer(serializers.ModelSerializer[PackagingPlanItem]):
    class Meta:
        model = PackagingPlanItem
        fields = [
            "id",
            "line_no",
            "material_sku",
            "standard_qty",
            "uom",
            "allowed_loss_rate",
            "returnable_on_breakdown",
            "row_version",
        ]
        read_only_fields = ["row_version"]


class PackagingPlanSerializer(serializers.ModelSerializer[PackagingPlan]):
    items = PackagingPlanItemSerializer(many=True)

    class Meta:
        model = PackagingPlan
        fields = [
            "id",
            "company",
            "plan_no",
            "name",
            "product_sku",
            "channel",
            "trade_type",
            "version",
            "status",
            "approval_reference",
            "row_version",
            "items",
        ]
        read_only_fields = ["status", "row_version"]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        company = attrs["company"]
        product = attrs["product_sku"]
        channel = attrs.get("channel")
        items = attrs.get("items", [])
        if product.company_id != company.pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("包装方案产品必须属于方案公司。")
        if channel is not None and channel.company_id != company.pk:  # type: ignore[union-attr]
            raise serializers.ValidationError("包装方案渠道必须属于方案公司。")
        if not items:
            raise serializers.ValidationError("包装方案至少需要一个物料明细。")
        line_numbers = [item["line_no"] for item in items]  # type: ignore[index]
        material_ids = [item["material_sku"].pk for item in items]  # type: ignore[index,union-attr]
        if len(line_numbers) != len(set(line_numbers)) or len(material_ids) != len(
            set(material_ids)
        ):
            raise serializers.ValidationError("包装方案行号和物料SKU不能重复。")
        if any(item["material_sku"].company_id != company.pk for item in items):  # type: ignore[index,union-attr]
            raise serializers.ValidationError("包装物料必须属于方案公司。")
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict[str, object]) -> PackagingPlan:
        items = validated_data.pop("items")
        plan = PackagingPlan.objects.create(**validated_data)
        for item in items:  # type: ignore[assignment]
            PackagingPlanItem.objects.create(plan=plan, **item)
        return plan


class PrepackOrderSerializer(serializers.ModelSerializer[PrepackOrder]):
    class Meta:
        model = PrepackOrder
        fields = [
            "id",
            "company",
            "prepack_order_no",
            "warehouse",
            "product_sku",
            "packaging_plan",
            "planned_qty",
            "completed_qty",
            "broken_down_qty",
            "source_location",
            "target_location",
            "status",
            "version_no",
        ]
        read_only_fields = ["completed_qty", "broken_down_qty", "status", "version_no"]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        company = attrs["company"]
        warehouse = attrs["warehouse"]
        product = attrs["product_sku"]
        plan = attrs["packaging_plan"]
        source = attrs["source_location"]
        target = attrs["target_location"]
        if (
            warehouse.company_id != company.pk  # type: ignore[attr-defined]
            or product.company_id != company.pk  # type: ignore[attr-defined]
            or plan.company_id != company.pk  # type: ignore[attr-defined]
            or plan.product_sku_id != product.pk  # type: ignore[attr-defined]
            or source.warehouse_id != warehouse.pk  # type: ignore[attr-defined]
            or target.warehouse_id != warehouse.pk  # type: ignore[attr-defined]
            or source.pk == target.pk  # type: ignore[attr-defined]
        ):
            raise serializers.ValidationError("预包装单的公司、仓库、产品、方案或库位不一致。")
        return attrs


class VersionSerializer(serializers.Serializer[dict[str, object]]):
    expected_version = serializers.IntegerField(min_value=1)


class MaterialUsageSerializer(serializers.Serializer[dict[str, object]]):
    plan_item_id = serializers.IntegerField(min_value=1)
    balance_id = serializers.IntegerField(min_value=1)
    actual_used_qty = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )


class ExecutePrepackSerializer(serializers.Serializer[dict[str, object]]):
    execution_no = serializers.CharField(max_length=100)
    quantity = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )
    source_balance_id = serializers.IntegerField(min_value=1)
    target_balance_id = serializers.IntegerField(min_value=1)
    materials = MaterialUsageSerializer(many=True, allow_empty=False)
    idempotency_key = serializers.CharField(max_length=200)
    occurred_at = serializers.DateTimeField()


class BreakdownMaterialSerializer(serializers.Serializer[dict[str, object]]):
    plan_item_id = serializers.IntegerField(min_value=1)
    return_balance_id = serializers.IntegerField(min_value=1)
    returned_qty = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )


class BreakdownPrepackSerializer(serializers.Serializer[dict[str, object]]):
    breakdown_no = serializers.CharField(max_length=100)
    quantity = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )
    prepacked_balance_id = serializers.IntegerField(min_value=1)
    restored_product_balance_id = serializers.IntegerField(min_value=1)
    returned_materials = BreakdownMaterialSerializer(many=True, required=False, default=list)
    approval_reference = serializers.CharField(max_length=200)
    idempotency_key = serializers.CharField(max_length=200)
    occurred_at = serializers.DateTimeField()

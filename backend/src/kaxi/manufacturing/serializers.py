from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from kaxi.manufacturing.models import (
    BillOfMaterial,
    BillOfMaterialItem,
    ProductionOrder,
)


class BomItemSerializer(serializers.ModelSerializer[BillOfMaterialItem]):
    class Meta:
        model = BillOfMaterialItem
        fields = [
            "id",
            "line_no",
            "component_sku",
            "standard_qty",
            "uom",
            "expected_loss_rate",
            "issue_method",
            "is_critical",
            "row_version",
        ]
        read_only_fields = ["row_version"]


class BomSerializer(serializers.ModelSerializer[BillOfMaterial]):
    items = BomItemSerializer(many=True)

    class Meta:
        model = BillOfMaterial
        fields = [
            "id",
            "company",
            "bom_no",
            "product_sku",
            "bom_type",
            "version",
            "output_qty",
            "valid_from",
            "valid_to",
            "status",
            "approval_reference",
            "row_version",
            "items",
        ]
        read_only_fields = ["status", "row_version"]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        company = attrs["company"]
        product = attrs["product_sku"]
        items = attrs.get("items", [])
        if product.company_id != company.pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("BOM成品必须属于BOM公司。")
        if not items:
            raise serializers.ValidationError("BOM至少需要一个明细行。")
        line_numbers = [item["line_no"] for item in items]  # type: ignore[index]
        components = [item["component_sku"].pk for item in items]  # type: ignore[index,union-attr]
        if len(line_numbers) != len(set(line_numbers)) or len(components) != len(set(components)):
            raise serializers.ValidationError("BOM行号和组件SKU不能重复。")
        if product.pk in components or any(  # type: ignore[attr-defined]
            item["component_sku"].company_id != company.pk
            for item in items  # type: ignore[index,union-attr]
        ):
            raise serializers.ValidationError("BOM组件必须属于同公司且不能等于成品。")
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict[str, object]) -> BillOfMaterial:
        items = validated_data.pop("items")
        bom = BillOfMaterial.objects.create(**validated_data)
        for item in items:  # type: ignore[assignment]
            BillOfMaterialItem.objects.create(bom=bom, **item)
        return bom


class ProductionOrderSerializer(serializers.ModelSerializer[ProductionOrder]):
    class Meta:
        model = ProductionOrder
        fields = [
            "id",
            "company",
            "production_order_no",
            "product_sku",
            "bom",
            "planned_qty",
            "completed_qty",
            "accepted_qty",
            "rejected_qty",
            "warehouse",
            "planned_start",
            "planned_end",
            "actual_start",
            "actual_end",
            "source_type",
            "source_id",
            "status",
            "version_no",
        ]
        read_only_fields = [
            "completed_qty",
            "accepted_qty",
            "rejected_qty",
            "actual_start",
            "actual_end",
            "status",
            "version_no",
        ]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        company = attrs["company"]
        product = attrs["product_sku"]
        bom = attrs["bom"]
        warehouse = attrs["warehouse"]
        if (
            product.company_id != company.pk  # type: ignore[attr-defined]
            or bom.company_id != company.pk  # type: ignore[attr-defined]
            or bom.product_sku_id != product.pk  # type: ignore[attr-defined]
            or warehouse.company_id != company.pk  # type: ignore[attr-defined]
        ):
            raise serializers.ValidationError("生产订单的公司、成品、BOM和仓库不一致。")
        return attrs


class VersionSerializer(serializers.Serializer[dict[str, object]]):
    expected_version = serializers.IntegerField(min_value=1)


class MaterialIssueLineInputSerializer(serializers.Serializer[dict[str, object]]):
    component_sku_id = serializers.IntegerField(min_value=1)
    balance_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )


class MaterialIssueInputSerializer(serializers.Serializer[dict[str, object]]):
    issue_no = serializers.CharField(max_length=100)
    idempotency_key = serializers.CharField(max_length=200)
    occurred_at = serializers.DateTimeField()
    lines = MaterialIssueLineInputSerializer(many=True, allow_empty=False)


class ConsumptionInputSerializer(serializers.Serializer[dict[str, object]]):
    component_sku_id = serializers.IntegerField(min_value=1)
    actual_consumed_qty = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal(0)
    )


class CompletionInputSerializer(serializers.Serializer[dict[str, object]]):
    completion_no = serializers.CharField(max_length=100)
    idempotency_key = serializers.CharField(max_length=200)
    accepted_qty = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal(0))
    rejected_qty = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal(0))
    accepted_balance_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    rejected_balance_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    occurred_at = serializers.DateTimeField()
    consumptions = ConsumptionInputSerializer(many=True)

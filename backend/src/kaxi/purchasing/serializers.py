from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from kaxi.purchasing.models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine


class PurchaseOrderLineSerializer(serializers.ModelSerializer[PurchaseOrderLine]):
    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id",
            "line_no",
            "sku",
            "ordered_qty",
            "received_qty",
            "accepted_qty",
            "rejected_qty",
            "returned_qty",
            "unit_price",
            "tax_rate",
            "line_total",
            "base_line_total",
            "expected_delivery_date",
            "status",
            "row_version",
        ]
        read_only_fields = [
            "received_qty",
            "accepted_qty",
            "rejected_qty",
            "returned_qty",
            "line_total",
            "base_line_total",
            "status",
            "row_version",
        ]


class PurchaseOrderSerializer(serializers.ModelSerializer[PurchaseOrder]):
    lines = PurchaseOrderLineSerializer(many=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "company",
            "purchase_order_no",
            "supplier",
            "order_date",
            "currency",
            "exchange_rate",
            "warehouse",
            "expected_delivery_date",
            "subtotal",
            "tax_total",
            "total",
            "base_total",
            "status",
            "approval_status",
            "version_no",
            "lines",
        ]
        read_only_fields = [
            "subtotal",
            "tax_total",
            "total",
            "base_total",
            "status",
            "approval_status",
            "version_no",
        ]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        company = attrs["company"]
        supplier = attrs["supplier"]
        warehouse = attrs["warehouse"]
        lines = attrs.get("lines", [])
        if supplier.company_id != company.pk or warehouse.company_id != company.pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("供应商和收货仓必须属于采购公司。")
        if not lines:
            raise serializers.ValidationError("采购订单至少需要一个明细行。")
        line_numbers = [line["line_no"] for line in lines]  # type: ignore[index]
        if len(line_numbers) != len(set(line_numbers)):
            raise serializers.ValidationError("采购订单行号不能重复。")
        if any(line["sku"].company_id != company.pk for line in lines):  # type: ignore[index,union-attr]
            raise serializers.ValidationError("采购SKU必须属于采购公司。")
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict[str, object]) -> PurchaseOrder:
        lines = validated_data.pop("lines")
        exchange_rate = Decimal(validated_data["exchange_rate"])  # type: ignore[arg-type]
        subtotal = sum(
            (line["ordered_qty"] * line["unit_price"] for line in lines),  # type: ignore[index,operator]
            Decimal(0),
        )
        tax_total = sum(
            (
                line["ordered_qty"] * line["unit_price"] * line["tax_rate"]  # type: ignore[index,operator]
                for line in lines
            ),
            Decimal(0),
        )
        order = PurchaseOrder.objects.create(
            **validated_data,
            subtotal=subtotal,
            tax_total=tax_total,
            total=subtotal + tax_total,
            base_total=(subtotal + tax_total) * exchange_rate,
        )
        for line in lines:
            line_total = line["ordered_qty"] * line["unit_price"]  # type: ignore[index,operator]
            PurchaseOrderLine.objects.create(
                order=order,
                **line,
                line_total=line_total,
                base_line_total=line_total * exchange_rate,
            )
        return order


class GoodsReceiptLineSerializer(serializers.ModelSerializer[GoodsReceiptLine]):
    class Meta:
        model = GoodsReceiptLine
        fields = [
            "id",
            "purchase_order_line",
            "sku",
            "received_qty",
            "pending_inspection_qty",
            "lot_no",
            "staging_location",
            "row_version",
        ]


class GoodsReceiptSerializer(serializers.ModelSerializer[GoodsReceipt]):
    lines = GoodsReceiptLineSerializer(many=True, read_only=True)

    class Meta:
        model = GoodsReceipt
        fields = [
            "id",
            "company",
            "receipt_no",
            "purchase_order",
            "supplier",
            "warehouse",
            "received_at",
            "received_by",
            "status",
            "supplier_delivery_no",
            "lines",
        ]


class ReceiveLineInputSerializer(serializers.Serializer[dict[str, object]]):
    purchase_order_line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )
    staging_location_id = serializers.IntegerField(min_value=1)
    lot_no = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class ReceivePurchaseOrderSerializer(serializers.Serializer[dict[str, object]]):
    receipt_no = serializers.CharField(max_length=100)
    received_at = serializers.DateTimeField()
    supplier_delivery_no = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    lines = ReceiveLineInputSerializer(many=True, allow_empty=False)


class InspectionLineInputSerializer(serializers.Serializer[dict[str, object]]):
    receipt_line_id = serializers.IntegerField(min_value=1)
    accepted_qty = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal(0))
    rejected_qty = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal(0))
    accepted_balance_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    rejected_balance_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    disposition = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    defect_code = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    remarks = serializers.CharField(required=False, allow_blank=True, default="")


class CompleteInspectionSerializer(serializers.Serializer[dict[str, object]]):
    inspection_no = serializers.CharField(max_length=100)
    completed_at = serializers.DateTimeField()
    lines = InspectionLineInputSerializer(many=True, allow_empty=False)


class PurchaseOrderTransitionSerializer(serializers.Serializer[dict[str, object]]):
    expected_version = serializers.IntegerField(min_value=1)

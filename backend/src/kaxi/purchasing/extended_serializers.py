from rest_framework import serializers

from kaxi.purchasing.models import (
    PurchaseRequisition,
    PurchaseRequisitionLine,
    PurchaseReturn,
    PurchaseReturnLine,
    RequestForQuotation,
    RfqSupplier,
    SupplierPerformanceSnapshot,
    SupplierQuote,
    SupplierQuoteLine,
)


class RequisitionLineSerializer(serializers.ModelSerializer[PurchaseRequisitionLine]):
    class Meta:
        model = PurchaseRequisitionLine
        fields = "__all__"
        read_only_fields = ["requisition", "ordered_qty", "row_version"]


class RequisitionSerializer(serializers.ModelSerializer[PurchaseRequisition]):
    lines = RequisitionLineSerializer(many=True)

    class Meta:
        model = PurchaseRequisition
        fields = "__all__"
        read_only_fields = [
            "requested_by",
            "status",
            "approved_by",
            "approved_at",
            "version_no",
            "row_version",
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs["company"]
        if attrs["warehouse"].company_id != company.pk:
            raise serializers.ValidationError("需求仓库必须属于当前公司。")
        lines = attrs.get("lines", [])
        if not lines or any(line["sku"].company_id != company.pk for line in lines):
            raise serializers.ValidationError("采购需求行不能为空且 SKU 必须属于当前公司。")
        return attrs

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        lines = validated_data.pop("lines")
        requisition = PurchaseRequisition.objects.create(**validated_data)
        for line in lines:
            PurchaseRequisitionLine.objects.create(requisition=requisition, **line)
        return requisition


class RfqSupplierSerializer(serializers.ModelSerializer[RfqSupplier]):
    class Meta:
        model = RfqSupplier
        fields = "__all__"
        read_only_fields = ["rfq", "row_version"]


class RfqSerializer(serializers.ModelSerializer[RequestForQuotation]):
    suppliers = RfqSupplierSerializer(many=True)

    class Meta:
        model = RequestForQuotation
        fields = "__all__"
        read_only_fields = ["status", "awarded_quote", "row_version"]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        suppliers = validated_data.pop("suppliers")
        rfq = RequestForQuotation.objects.create(**validated_data)
        for supplier in suppliers:
            RfqSupplier.objects.create(rfq=rfq, **supplier)
        return rfq


class QuoteLineSerializer(serializers.ModelSerializer[SupplierQuoteLine]):
    class Meta:
        model = SupplierQuoteLine
        fields = "__all__"
        read_only_fields = ["quote", "row_version"]


class QuoteSerializer(serializers.ModelSerializer[SupplierQuote]):
    lines = QuoteLineSerializer(many=True)

    class Meta:
        model = SupplierQuote
        fields = "__all__"
        read_only_fields = ["status", "score_snapshot", "row_version"]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        lines = validated_data.pop("lines")
        quote = SupplierQuote.objects.create(**validated_data)
        for line in lines:
            SupplierQuoteLine.objects.create(quote=quote, **line)
        return quote


class PurchaseReturnLineSerializer(serializers.ModelSerializer[PurchaseReturnLine]):
    class Meta:
        model = PurchaseReturnLine
        fields = "__all__"
        read_only_fields = ["purchase_return", "dispatched_qty", "row_version"]


class PurchaseReturnSerializer(serializers.ModelSerializer[PurchaseReturn]):
    lines = PurchaseReturnLineSerializer(many=True)

    class Meta:
        model = PurchaseReturn
        fields = "__all__"
        read_only_fields = [
            "requested_by",
            "status",
            "approved_by",
            "approved_at",
            "dispatched_at",
            "idempotency_key",
            "version_no",
            "row_version",
        ]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        lines = validated_data.pop("lines")
        purchase_return = PurchaseReturn.objects.create(**validated_data)
        for line in lines:
            PurchaseReturnLine.objects.create(purchase_return=purchase_return, **line)
        return purchase_return


class PerformanceSerializer(serializers.ModelSerializer[SupplierPerformanceSnapshot]):
    class Meta:
        model = SupplierPerformanceSnapshot
        fields = "__all__"


class ApprovalSerializer(serializers.Serializer[dict[str, object]]):
    approved = serializers.BooleanField(default=True)


class AwardSerializer(serializers.Serializer[dict[str, object]]):
    quote_id = serializers.IntegerField()
    purchase_order_no = serializers.CharField(max_length=100)


class DispatchSerializer(serializers.Serializer[dict[str, object]]):
    idempotency_key = serializers.CharField(max_length=100)

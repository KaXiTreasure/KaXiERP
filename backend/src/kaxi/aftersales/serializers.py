from rest_framework import serializers

from kaxi.aftersales.models import (
    AfterSalesCase,
    AfterSalesLine,
    Refund,
    ReplacementOrder,
    ReturnReceipt,
    ReturnReceiptLine,
)


class CaseLineSerializer(serializers.ModelSerializer[AfterSalesLine]):
    class Meta:
        model = AfterSalesLine
        fields = "__all__"
        read_only_fields = ["case", "received_qty", "accepted_qty", "rejected_qty", "row_version"]


class RefundSerializer(serializers.ModelSerializer[Refund]):
    class Meta:
        model = Refund
        fields = "__all__"
        read_only_fields = ["status", "external_refund_id", "journal", "row_version"]


class ReplacementSerializer(serializers.ModelSerializer[ReplacementOrder]):
    class Meta:
        model = ReplacementOrder
        fields = "__all__"


class CaseSerializer(serializers.ModelSerializer[AfterSalesCase]):
    lines = CaseLineSerializer(many=True)
    refunds = RefundSerializer(many=True, read_only=True)
    replacements = ReplacementSerializer(many=True, read_only=True)

    class Meta:
        model = AfterSalesCase
        fields = "__all__"
        read_only_fields = [
            "status",
            "requested_by",
            "approved_by",
            "approved_at",
            "completed_at",
            "version_no",
            "row_version",
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        if attrs["sales_order"].company_id != attrs["company"].pk:
            raise serializers.ValidationError("售后单公司与销售订单不一致。")
        if attrs["customer"].pk != attrs["sales_order"].customer_id:
            raise serializers.ValidationError("售后客户与原订单客户不一致。")
        if not attrs.get("lines"):
            raise serializers.ValidationError("售后单至少需要一个明细行。")
        return attrs

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        lines = validated_data.pop("lines")
        case = AfterSalesCase.objects.create(**validated_data)
        for line in lines:
            AfterSalesLine.objects.create(case=case, **line)
        return case


class ReceiptLineSerializer(serializers.ModelSerializer[ReturnReceiptLine]):
    class Meta:
        model = ReturnReceiptLine
        fields = "__all__"


class ReceiptSerializer(serializers.ModelSerializer[ReturnReceipt]):
    lines = ReceiptLineSerializer(many=True, read_only=True)

    class Meta:
        model = ReturnReceipt
        fields = "__all__"


class ApprovalSerializer(serializers.Serializer[dict[str, object]]):
    approved = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ReturnLineInputSerializer(serializers.Serializer[dict[str, object]]):
    aftersales_line_id = serializers.IntegerField()
    received_qty = serializers.DecimalField(max_digits=20, decimal_places=6)
    accepted_qty = serializers.DecimalField(max_digits=20, decimal_places=6)
    rejected_qty = serializers.DecimalField(max_digits=20, decimal_places=6)
    accepted_balance_id = serializers.IntegerField(required=False, allow_null=True)
    exception_balance_id = serializers.IntegerField(required=False, allow_null=True)


class ReceiveSerializer(serializers.Serializer[dict[str, object]]):
    receipt_no = serializers.CharField(max_length=100)
    idempotency_key = serializers.CharField(max_length=100)
    lines = ReturnLineInputSerializer(many=True, allow_empty=False)


class PaidSerializer(serializers.Serializer[dict[str, object]]):
    external_refund_id = serializers.CharField(max_length=200)

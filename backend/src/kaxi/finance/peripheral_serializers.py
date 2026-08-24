from rest_framework import serializers

from kaxi.finance.models import (
    DepreciationEntry,
    ExpenseClaim,
    FixedAsset,
    PayrollLine,
    PayrollRun,
    TaxInvoice,
)


class ExpenseClaimSerializer(serializers.ModelSerializer[ExpenseClaim]):
    class Meta:
        model = ExpenseClaim
        fields = "__all__"
        read_only_fields = ["status", "approved_by", "row_version"]


class FixedAssetSerializer(serializers.ModelSerializer[FixedAsset]):
    class Meta:
        model = FixedAsset
        fields = "__all__"
        read_only_fields = [
            "status",
            "accumulated_depreciation",
            "disposal_date",
            "disposal_proceeds",
            "row_version",
        ]


class DepreciationSerializer(serializers.ModelSerializer[DepreciationEntry]):
    class Meta:
        model = DepreciationEntry
        fields = "__all__"
        read_only_fields = ["row_version"]


class PayrollLineSerializer(serializers.ModelSerializer[PayrollLine]):
    class Meta:
        model = PayrollLine
        exclude = ["created_at", "updated_at"]


class PayrollSerializer(serializers.ModelSerializer[PayrollRun]):
    lines = PayrollLineSerializer(many=True, required=False)

    class Meta:
        model = PayrollRun
        fields = "__all__"
        read_only_fields = [
            "status",
            "gross_amount",
            "deduction_amount",
            "net_amount",
            "calculated_by",
            "approved_by",
            "row_version",
        ]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        lines = validated_data.pop("lines", [])
        payroll = PayrollRun.objects.create(**validated_data)
        for line in lines:
            PayrollLine.objects.create(payroll=payroll, **line)
        return payroll


class TaxInvoiceSerializer(serializers.ModelSerializer[TaxInvoice]):
    class Meta:
        model = TaxInvoice
        fields = "__all__"
        read_only_fields = ["status", "verified_by", "row_version"]


class TransitionSerializer(serializers.Serializer[dict[str, object]]):
    target = serializers.CharField(max_length=24)


class DepreciateSerializer(serializers.Serializer[dict[str, object]]):
    period_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=6)
    journal_id = serializers.IntegerField()


class DisposeSerializer(serializers.Serializer[dict[str, object]]):
    disposal_date = serializers.DateField()
    proceeds = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=0)

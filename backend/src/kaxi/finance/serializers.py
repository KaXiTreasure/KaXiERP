from decimal import Decimal

from rest_framework import serializers

from kaxi.finance.models import (
    Account,
    Allocation,
    ChartOfAccounts,
    FiscalPeriod,
    JournalEntry,
    JournalEntryLine,
    Ledger,
    OpenItem,
    Settlement,
    ThreeWayMatch,
)


class LedgerSerializer(serializers.ModelSerializer[Ledger]):
    class Meta:
        model = Ledger
        fields = "__all__"


class ChartSerializer(serializers.ModelSerializer[ChartOfAccounts]):
    class Meta:
        model = ChartOfAccounts
        fields = "__all__"


class AccountSerializer(serializers.ModelSerializer[Account]):
    class Meta:
        model = Account
        fields = "__all__"
        ref_name = "FinanceAccount"

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        chart = attrs.get("chart", getattr(self.instance, "chart", None))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent is not None and parent.chart_id != chart.pk:
            raise serializers.ValidationError("上级科目必须属于同一科目表。")
        return attrs


class PeriodSerializer(serializers.ModelSerializer[FiscalPeriod]):
    class Meta:
        model = FiscalPeriod
        fields = "__all__"
        read_only_fields = ["closed_at", "closed_by", "reopen_reason", "row_version"]


class JournalLineSerializer(serializers.ModelSerializer[JournalEntryLine]):
    class Meta:
        model = JournalEntryLine
        exclude = ["created_at", "updated_at"]
        read_only_fields = ["entry", "row_version"]


class JournalSerializer(serializers.ModelSerializer[JournalEntry]):
    lines = JournalLineSerializer(many=True)

    class Meta:
        model = JournalEntry
        fields = "__all__"
        read_only_fields = [
            "status",
            "total_debit_base",
            "total_credit_base",
            "approved_by",
            "approved_at",
            "posted_by",
            "posted_at",
            "reversal_of",
            "row_version",
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        ledger = attrs.get("ledger", getattr(self.instance, "ledger", None))
        period = attrs.get("period", getattr(self.instance, "period", None))
        if ledger.company_id != company.pk or period.ledger_id != ledger.pk:
            raise serializers.ValidationError("公司、账簿和期间不一致。")
        lines = attrs.get("lines")
        if lines is not None and (
            len(lines) < 2 or len({line["line_no"] for line in lines}) != len(lines)
        ):
            raise serializers.ValidationError("凭证至少两行且行号不得重复。")
        for line in lines or []:
            if line["account"].chart.ledger_id != ledger.pk:
                raise serializers.ValidationError("凭证科目必须属于当前账簿。")
            if line.get("party") is not None and line["party"].company_id != company.pk:
                raise serializers.ValidationError("凭证往来单位必须属于同一公司。")
        return attrs

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        lines = validated_data.pop("lines")
        entry = JournalEntry.objects.create(**validated_data)
        for line in lines:
            JournalEntryLine.objects.create(entry=entry, **line)
        return entry


class OpenItemSerializer(serializers.ModelSerializer[OpenItem]):
    outstanding_amount = serializers.SerializerMethodField()

    class Meta:
        model = OpenItem
        fields = "__all__"
        read_only_fields = ["allocated_amount", "allocated_base_amount", "status", "row_version"]

    def get_outstanding_amount(self, obj: OpenItem) -> Decimal:
        return obj.original_amount - obj.allocated_amount

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        party = attrs.get("party", getattr(self.instance, "party", None))
        journal = attrs.get("journal", getattr(self.instance, "journal", None))
        if party.company_id != company.pk or journal.company_id != company.pk:
            raise serializers.ValidationError("往来单位、凭证和未结项必须属于同一公司。")
        return attrs


class SettlementSerializer(serializers.ModelSerializer[Settlement]):
    available_amount = serializers.SerializerMethodField()

    class Meta:
        model = Settlement
        fields = "__all__"
        read_only_fields = ["allocated_amount", "row_version"]

    def get_available_amount(self, obj: Settlement) -> Decimal:
        return obj.amount - obj.allocated_amount

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        party = attrs.get("party", getattr(self.instance, "party", None))
        journal = attrs.get("journal", getattr(self.instance, "journal", None))
        if party.company_id != company.pk or journal.company_id != company.pk:
            raise serializers.ValidationError("往来单位、凭证和收付款必须属于同一公司。")
        return attrs


class AllocationSerializer(serializers.ModelSerializer[Allocation]):
    class Meta:
        model = Allocation
        fields = "__all__"
        read_only_fields = ["reversal_of", "row_version"]


class ThreeWayMatchSerializer(serializers.ModelSerializer[ThreeWayMatch]):
    class Meta:
        model = ThreeWayMatch
        fields = "__all__"


class ReverseJournalSerializer(serializers.Serializer[dict[str, object]]):
    target_period_id = serializers.IntegerField()
    voucher_no = serializers.CharField(max_length=64)
    entry_date = serializers.DateField()


class ReopenPeriodSerializer(serializers.Serializer[dict[str, object]]):
    approval_reference = serializers.CharField()


class AllocateSerializer(serializers.Serializer[dict[str, object]]):
    open_item_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=6)
    base_amount = serializers.DecimalField(max_digits=20, decimal_places=6)

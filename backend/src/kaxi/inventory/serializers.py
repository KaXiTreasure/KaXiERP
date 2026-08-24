from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from kaxi.inventory.models import (
    InventoryBalance,
    StockCount,
    StockCountLine,
    StockTransfer,
    StockTransferLine,
)


class InventoryBalanceSerializer(serializers.ModelSerializer[InventoryBalance]):
    physical_free_qty = serializers.DecimalField(max_digits=20, decimal_places=6, read_only=True)

    class Meta:
        model = InventoryBalance
        fields = [
            "id",
            "company",
            "sku",
            "warehouse",
            "location",
            "inventory_status",
            "lot",
            "on_hand_qty",
            "reserved_qty",
            "locked_qty",
            "physical_free_qty",
            "row_version",
            "updated_at",
        ]


class StockTransferLineSerializer(serializers.ModelSerializer[StockTransferLine]):
    class Meta:
        model = StockTransferLine
        fields = [
            "id",
            "line_no",
            "sku",
            "source_balance",
            "destination_balance",
            "requested_qty",
            "dispatched_qty",
            "received_qty",
            "difference_qty",
            "row_version",
        ]
        read_only_fields = ["dispatched_qty", "received_qty", "difference_qty", "row_version"]


class StockTransferSerializer(serializers.ModelSerializer[StockTransfer]):
    lines = StockTransferLineSerializer(many=True)

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "company",
            "transfer_no",
            "source_warehouse",
            "destination_warehouse",
            "status",
            "version_no",
            "dispatched_at",
            "received_at",
            "lines",
        ]
        read_only_fields = ["status", "version_no", "dispatched_at", "received_at"]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        company = attrs["company"]
        source = attrs["source_warehouse"]
        destination = attrs["destination_warehouse"]
        lines = attrs.get("lines", [])
        if source.company_id != company.pk or destination.company_id != company.pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("调出仓和调入仓必须属于调拨公司。")
        if source.pk == destination.pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("调出仓和调入仓不能相同。")
        if not lines:
            raise serializers.ValidationError("调拨单至少需要一个明细行。")
        line_numbers = [line["line_no"] for line in lines]  # type: ignore[index]
        if len(line_numbers) != len(set(line_numbers)):
            raise serializers.ValidationError("调拨行号不能重复。")
        for line in lines:  # type: ignore[assignment]
            sku = line["sku"]
            source_balance = line["source_balance"]
            destination_balance = line["destination_balance"]
            if (
                sku.company_id != company.pk
                or source_balance.company_id != company.pk
                or destination_balance.company_id != company.pk
                or source_balance.warehouse_id != source.pk
                or destination_balance.warehouse_id != destination.pk
                or source_balance.sku_id != sku.pk
                or destination_balance.sku_id != sku.pk
            ):
                raise serializers.ValidationError("调拨行的公司、仓库、SKU或库存余额不一致。")
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict[str, object]) -> StockTransfer:
        lines = validated_data.pop("lines")
        transfer = StockTransfer.objects.create(**validated_data)
        for line in lines:  # type: ignore[assignment]
            StockTransferLine.objects.create(transfer=transfer, **line)
        return transfer


class StockCountLineSerializer(serializers.ModelSerializer[StockCountLine]):
    class Meta:
        model = StockCountLine
        fields = [
            "id",
            "line_no",
            "balance",
            "book_qty",
            "counted_qty",
            "difference_qty",
            "remarks",
            "row_version",
        ]


class StockCountSerializer(serializers.ModelSerializer[StockCount]):
    lines = StockCountLineSerializer(many=True, read_only=True)

    class Meta:
        model = StockCount
        fields = [
            "id",
            "company",
            "count_no",
            "warehouse",
            "status",
            "version_no",
            "started_at",
            "submitted_at",
            "posted_at",
            "posted_by",
            "lines",
        ]
        read_only_fields = [
            "status",
            "version_no",
            "started_at",
            "submitted_at",
            "posted_at",
            "posted_by",
        ]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs["warehouse"].company_id != attrs["company"].pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("盘点仓必须属于盘点公司。")
        return attrs


class VersionSerializer(serializers.Serializer[dict[str, object]]):
    expected_version = serializers.IntegerField(min_value=1)


class TransferOperationSerializer(serializers.Serializer[dict[str, object]]):
    idempotency_key = serializers.CharField(max_length=200)
    occurred_at = serializers.DateTimeField()


class TransferReceiptLineSerializer(serializers.Serializer[dict[str, object]]):
    line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal(0))


class TransferReceiptSerializer(TransferOperationSerializer):
    lines = TransferReceiptLineSerializer(many=True, allow_empty=False)


class StartCountSerializer(VersionSerializer):
    balance_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )
    started_at = serializers.DateTimeField()


class CountedLineSerializer(serializers.Serializer[dict[str, object]]):
    line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal(0))


class SubmitCountSerializer(serializers.Serializer[dict[str, object]]):
    submitted_at = serializers.DateTimeField()
    lines = CountedLineSerializer(many=True, allow_empty=False)

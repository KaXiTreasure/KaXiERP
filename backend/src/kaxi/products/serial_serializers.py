from rest_framework import serializers

from kaxi.products.models import (
    LimitedEditionPool,
    ProductSerial,
    SerialProductionAttempt,
    SerialReservation,
    SerialShipmentAssignment,
    SerialStatusHistory,
)


class LimitedEditionPoolSerializer(serializers.ModelSerializer[LimitedEditionPool]):
    class Meta:
        model = LimitedEditionPool
        fields = [
            "id",
            "company",
            "sku",
            "edition_code",
            "total_limit",
            "numbering_rule",
            "allocated_count",
            "produced_good_count",
            "next_sort_value",
            "status",
            "row_version",
        ]
        read_only_fields = [
            "allocated_count",
            "produced_good_count",
            "next_sort_value",
            "status",
            "row_version",
        ]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if attrs["sku"].company_id != attrs["company"].pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("限量池SKU必须属于限量池公司。")
        return attrs


class SerialAttemptSerializer(serializers.ModelSerializer[SerialProductionAttempt]):
    class Meta:
        model = SerialProductionAttempt
        fields = [
            "id",
            "production_order",
            "attempt_no",
            "started_at",
            "completed_at",
            "result",
            "ng_reason",
            "previous_attempt",
            "inspection_reference",
            "row_version",
        ]


class SerialHistorySerializer(serializers.ModelSerializer[SerialStatusHistory]):
    class Meta:
        model = SerialStatusHistory
        fields = [
            "id",
            "from_status",
            "to_status",
            "reason",
            "reference_type",
            "reference_id",
            "actor",
            "occurred_at",
        ]


class ProductSerialSerializer(serializers.ModelSerializer[ProductSerial]):
    production_attempts = SerialAttemptSerializer(many=True, read_only=True)
    status_history = SerialHistorySerializer(many=True, read_only=True)

    class Meta:
        model = ProductSerial
        fields = [
            "id",
            "company",
            "limited_pool",
            "sku",
            "serial_no",
            "serial_sort_value",
            "status",
            "warehouse",
            "location",
            "current_customer",
            "current_sales_order",
            "current_production_order",
            "row_version",
            "production_attempts",
            "status_history",
        ]


class SerialReservationSerializer(serializers.ModelSerializer[SerialReservation]):
    class Meta:
        model = SerialReservation
        fields = [
            "id",
            "serial",
            "sales_order_line",
            "allocation_type",
            "status",
            "expires_at",
            "released_reason",
            "idempotency_key",
            "row_version",
        ]


class SerialShipmentAssignmentSerializer(serializers.ModelSerializer[SerialShipmentAssignment]):
    class Meta:
        model = SerialShipmentAssignment
        fields = ["id", "serial", "reservation", "shipment_line", "status", "row_version"]


class GenerateSerialsSerializer(serializers.Serializer[dict[str, object]]):
    quantity = serializers.IntegerField(min_value=1, max_value=10000)


class StartProductionSerializer(serializers.Serializer[dict[str, object]]):
    production_order_id = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(max_length=200)
    started_at = serializers.DateTimeField()


class CompleteAttemptSerializer(serializers.Serializer[dict[str, object]]):
    result = serializers.ChoiceField(choices=["good", "ng"])
    completed_at = serializers.DateTimeField()
    warehouse_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    location_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    ng_reason = serializers.CharField(required=False, allow_blank=True, default="")
    inspection_reference = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )


class DisposeSerialSerializer(serializers.Serializer[dict[str, object]]):
    action = serializers.ChoiceField(choices=["rework", "reproduce", "scrap", "void"])
    reason = serializers.CharField(max_length=1000)


class ReserveSerialSerializer(serializers.Serializer[dict[str, object]]):
    order_line_id = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(max_length=200)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class ReleaseSerialSerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField(max_length=1000)


class AssignShipmentSerializer(serializers.Serializer[dict[str, object]]):
    shipment_line_id = serializers.IntegerField(min_value=1)

from rest_framework import serializers

from kaxi.manufacturing.models import (
    OperationReport,
    ProductionSuggestion,
    Routing,
    RoutingOperation,
    SubcontractMaterial,
    SubcontractOrder,
    WorkCenter,
)


class WorkCenterSerializer(serializers.ModelSerializer[WorkCenter]):
    class Meta:
        model = WorkCenter
        fields = "__all__"


class OperationSerializer(serializers.ModelSerializer[RoutingOperation]):
    class Meta:
        model = RoutingOperation
        fields = "__all__"
        read_only_fields = ["routing", "row_version"]


class RoutingSerializer(serializers.ModelSerializer[Routing]):
    operations = OperationSerializer(many=True)

    class Meta:
        model = Routing
        fields = "__all__"
        read_only_fields = ["status", "approval_reference", "row_version"]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        operations = validated_data.pop("operations")
        routing = Routing.objects.create(**validated_data)
        for operation in operations:
            RoutingOperation.objects.create(routing=routing, **operation)
        return routing


class ReportSerializer(serializers.ModelSerializer[OperationReport]):
    class Meta:
        model = OperationReport
        fields = "__all__"
        read_only_fields = ["operator", "row_version"]


class SuggestionSerializer(serializers.ModelSerializer[ProductionSuggestion]):
    class Meta:
        model = ProductionSuggestion
        fields = "__all__"
        read_only_fields = ["status", "production_order", "row_version"]


class MaterialSerializer(serializers.ModelSerializer[SubcontractMaterial]):
    class Meta:
        model = SubcontractMaterial
        fields = "__all__"
        read_only_fields = [
            "subcontract_order",
            "sent_qty",
            "consumed_qty",
            "returned_qty",
            "row_version",
        ]


class SubcontractSerializer(serializers.ModelSerializer[SubcontractOrder]):
    materials = MaterialSerializer(many=True)

    class Meta:
        model = SubcontractOrder
        fields = "__all__"
        read_only_fields = [
            "received_qty",
            "accepted_qty",
            "rejected_qty",
            "status",
            "requested_by",
            "approved_by",
            "sent_at",
            "received_at",
            "version_no",
            "row_version",
        ]

    def create(self, validated_data):  # type: ignore[no-untyped-def]
        materials = validated_data.pop("materials")
        order = SubcontractOrder.objects.create(**validated_data)
        for material in materials:
            SubcontractMaterial.objects.create(subcontract_order=order, **material)
        return order


class ActivateSerializer(serializers.Serializer[dict[str, object]]):
    approval_reference = serializers.CharField(max_length=200)


class ConvertSerializer(serializers.Serializer[dict[str, object]]):
    production_order_no = serializers.CharField(max_length=100)
    bom_id = serializers.IntegerField()
    routing_id = serializers.IntegerField(required=False, allow_null=True)
    warehouse_id = serializers.IntegerField()


class IdempotencySerializer(serializers.Serializer[dict[str, object]]):
    idempotency_key = serializers.CharField(max_length=100)


class ReceiveSerializer(IdempotencySerializer):
    accepted_qty = serializers.DecimalField(max_digits=20, decimal_places=6)
    rejected_qty = serializers.DecimalField(max_digits=20, decimal_places=6)
    accepted_balance_id = serializers.IntegerField(required=False, allow_null=True)
    rejected_balance_id = serializers.IntegerField(required=False, allow_null=True)

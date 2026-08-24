from rest_framework import serializers

from kaxi.sales.models import PresaleAllocation, PresaleCampaign, SupplyAllocation, SupplyDemand


class SupplyAllocationSerializer(serializers.ModelSerializer[SupplyAllocation]):
    class Meta:
        model = SupplyAllocation
        fields = "__all__"
        read_only_fields = ["demand", "received_qty", "status", "row_version"]


class SupplyDemandSerializer(serializers.ModelSerializer[SupplyDemand]):
    allocations = SupplyAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = SupplyDemand
        fields = "__all__"
        read_only_fields = [
            "company",
            "shortage_qty",
            "supplied_qty",
            "promised_date",
            "status",
            "row_version",
        ]


class PresaleAllocationSerializer(serializers.ModelSerializer[PresaleAllocation]):
    class Meta:
        model = PresaleAllocation
        fields = "__all__"
        read_only_fields = ["promised_delivery_date", "status", "row_version"]


class PresaleCampaignSerializer(serializers.ModelSerializer[PresaleCampaign]):
    allocations = PresaleAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = PresaleCampaign
        fields = "__all__"
        read_only_fields = ["allocated_qty", "status", "row_version"]


class LinkSupplySerializer(serializers.Serializer[dict[str, object]]):
    source_type = serializers.ChoiceField(
        choices=["purchase_order", "production_order", "prepack_order", "stock_transfer"]
    )
    source_id = serializers.CharField(max_length=100)
    planned_qty = serializers.DecimalField(max_digits=20, decimal_places=6)
    expected_date = serializers.DateField(required=False, allow_null=True)


class ReceiveSupplySerializer(serializers.Serializer[dict[str, object]]):
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)

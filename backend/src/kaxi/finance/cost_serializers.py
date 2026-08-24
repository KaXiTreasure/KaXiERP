from rest_framework import serializers

from kaxi.finance.models import CostRecord, InventoryCostBalance, SerialCost


class CostBalanceSerializer(serializers.ModelSerializer[InventoryCostBalance]):
    class Meta:
        model = InventoryCostBalance
        fields = "__all__"


class CostRecordSerializer(serializers.ModelSerializer[CostRecord]):
    class Meta:
        model = CostRecord
        fields = "__all__"


class SerialCostSerializer(serializers.ModelSerializer[SerialCost]):
    class Meta:
        model = SerialCost
        fields = "__all__"


class ReceiveCostSerializer(serializers.Serializer[dict[str, object]]):
    company_id = serializers.IntegerField()
    sku_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    original_total_cost = serializers.DecimalField(max_digits=20, decimal_places=6)
    currency_id = serializers.IntegerField()
    exchange_rate = serializers.DecimalField(max_digits=20, decimal_places=10)
    source_type = serializers.CharField(max_length=50)
    source_id = serializers.CharField(max_length=100)
    cost_record_no = serializers.CharField(max_length=100)
    idempotency_key = serializers.CharField(max_length=100)
    effective_date = serializers.DateField()
    category = serializers.ChoiceField(choices=CostRecord.Category, default="purchase")


class IssueCostSerializer(serializers.Serializer[dict[str, object]]):
    company_id = serializers.IntegerField()
    sku_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    source_type = serializers.CharField(max_length=50)
    source_id = serializers.CharField(max_length=100)
    cost_record_no = serializers.CharField(max_length=100)
    idempotency_key = serializers.CharField(max_length=100)
    effective_date = serializers.DateField()


class AssignSerialCostSerializer(serializers.Serializer[dict[str, object]]):
    serial_id = serializers.IntegerField()
    currency_id = serializers.IntegerField()
    original_cost = serializers.DecimalField(max_digits=20, decimal_places=6)
    exchange_rate = serializers.DecimalField(max_digits=20, decimal_places=10)
    source_type = serializers.CharField(max_length=50)
    source_id = serializers.CharField(max_length=100)


class ReverseCostSerializer(serializers.Serializer[dict[str, object]]):
    cost_record_no = serializers.CharField(max_length=100)
    idempotency_key = serializers.CharField(max_length=100)
    effective_date = serializers.DateField()

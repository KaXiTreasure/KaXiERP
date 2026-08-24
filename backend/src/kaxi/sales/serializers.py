from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from kaxi.inventory.models import InventoryReservation
from kaxi.sales.models import SalesOrder, SalesOrderLine, SalesShipment, SalesShipmentLine


class SalesOrderLineSerializer(serializers.ModelSerializer[SalesOrderLine]):
    class Meta:
        model = SalesOrderLine
        fields = [
            "id",
            "line_no",
            "sku",
            "ordered_qty",
            "reserved_qty",
            "shipped_qty",
            "cancelled_qty",
            "unit_price",
            "line_total",
            "price_source",
            "price_snapshot",
            "row_version",
        ]
        read_only_fields = [
            "reserved_qty",
            "shipped_qty",
            "cancelled_qty",
            "unit_price",
            "line_total",
            "price_source",
            "price_snapshot",
            "row_version",
        ]


class SalesOrderSerializer(serializers.ModelSerializer[SalesOrder]):
    lines = SalesOrderLineSerializer(many=True)

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "company",
            "order_no",
            "customer",
            "channel",
            "shipping_address",
            "currency",
            "order_date",
            "status",
            "version_no",
            "lines",
        ]
        read_only_fields = ["status", "version_no"]

    def create(self, validated_data: dict[str, object]) -> SalesOrder:
        lines = validated_data.pop("lines")
        order = SalesOrder.objects.create(**validated_data)
        for line in lines:
            SalesOrderLine.objects.create(order=order, **line)
        return order


class LinePriceInputSerializer(serializers.Serializer[dict[str, object]]):
    line_id = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=20, decimal_places=6, min_value=Decimal(0))
    price_source = serializers.CharField(max_length=50)
    snapshot = serializers.JSONField()


class AllocationInputSerializer(serializers.Serializer[dict[str, object]]):
    line_id = serializers.IntegerField(min_value=1)
    balance_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )
    reservation_no = serializers.CharField(max_length=100)


class CreditInputSerializer(serializers.Serializer[dict[str, object]]):
    account_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(
        max_digits=20, decimal_places=6, min_value=Decimal("0.000001")
    )
    at = serializers.DateTimeField()
    approval_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class ConfirmOrderSerializer(serializers.Serializer[dict[str, object]]):
    expected_version = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(max_length=200)
    prices = LinePriceInputSerializer(many=True)
    allocations = AllocationInputSerializer(many=True, required=False, default=list)
    credit = CreditInputSerializer(required=False, allow_null=True)


class CancelOrderSerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField(max_length=1000)


class SalesShipmentLineSerializer(serializers.ModelSerializer[SalesShipmentLine]):
    class Meta:
        model = SalesShipmentLine
        fields = [
            "id",
            "line_no",
            "order_line",
            "reservation",
            "quantity",
            "picked_qty",
            "shipped_qty",
            "row_version",
        ]
        read_only_fields = ["picked_qty", "shipped_qty", "row_version"]


class SalesShipmentSerializer(serializers.ModelSerializer[SalesShipment]):
    lines = SalesShipmentLineSerializer(many=True)

    class Meta:
        model = SalesShipment
        fields = [
            "id",
            "company",
            "shipment_no",
            "order",
            "warehouse",
            "status",
            "version_no",
            "carrier_code",
            "tracking_no",
            "shipped_at",
            "shipped_by",
            "lines",
        ]
        read_only_fields = ["status", "version_no", "shipped_at", "shipped_by"]

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        company = attrs["company"]
        order = attrs["order"]
        warehouse = attrs["warehouse"]
        lines = attrs.get("lines", [])
        if order.company_id != company.pk or warehouse.company_id != company.pk:  # type: ignore[attr-defined]
            raise serializers.ValidationError("销售订单和发货仓必须属于发货公司。")
        if not lines:
            raise serializers.ValidationError("发货单至少需要一个明细行。")
        reservation_ids = [line["reservation"].pk for line in lines]  # type: ignore[index,union-attr]
        if len(reservation_ids) != len(set(reservation_ids)):
            raise serializers.ValidationError("同一库存预留不能在发货单中重复。")
        for line in lines:  # type: ignore[assignment]
            reservation: InventoryReservation = line["reservation"]
            order_line = line["order_line"]
            quantity = line["quantity"]
            if (
                reservation.company_id != company.pk
                or reservation.sales_order_line_id != order_line.pk
                or order_line.order_id != order.pk
                or reservation.balance.warehouse_id != warehouse.pk
            ):
                raise serializers.ValidationError("发货行的订单、预留、公司或仓库不一致。")
            pending = SalesShipmentLine.objects.filter(reservation=reservation).exclude(
                shipment__status__in=[SalesShipment.Status.SHIPPED, SalesShipment.Status.CANCELLED]
            ).aggregate(total=Sum("quantity"))["total"] or Decimal(0)
            if quantity > reservation.remaining_qty - pending:
                raise serializers.ValidationError("发货数量超过预留可分配数量。")
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict[str, object]) -> SalesShipment:
        lines = validated_data.pop("lines")
        shipment = SalesShipment.objects.create(**validated_data)
        for line in lines:  # type: ignore[assignment]
            SalesShipmentLine.objects.create(shipment=shipment, **line)
        return shipment


class ShipmentTransitionSerializer(serializers.Serializer[dict[str, object]]):
    expected_version = serializers.IntegerField(min_value=1)


class ShipShipmentSerializer(serializers.Serializer[dict[str, object]]):
    idempotency_key = serializers.CharField(max_length=200)
    shipped_at = serializers.DateTimeField()

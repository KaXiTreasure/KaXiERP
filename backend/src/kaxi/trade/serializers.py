from rest_framework import serializers

from kaxi.trade.models import (
    CustomsDeclaration,
    ForwarderSettlement,
    OverseasWarehouseProfile,
    Package,
    PackageItem,
    SalesOrderTradeDetail,
    Shipment,
    ShipmentClaim,
    ShipmentMilestone,
    ShipmentOrder,
    TradeContract,
    TradeCost,
    TradeDocument,
)


class ContractSerializer(serializers.ModelSerializer[TradeContract]):
    class Meta:
        model = TradeContract
        fields = "__all__"
        read_only_fields = [
            "status",
            "created_by",
            "approved_by",
            "approved_at",
            "row_version",
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        if customer and customer.company_id != getattr(company, "pk", None):
            raise serializers.ValidationError({"customer": "客户必须属于合同公司。"})
        return attrs


class TradeDetailSerializer(serializers.ModelSerializer[SalesOrderTradeDetail]):
    class Meta:
        model = SalesOrderTradeDetail
        fields = "__all__"

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        order = attrs.get("sales_order", getattr(self.instance, "sales_order", None))
        contract = attrs.get("contract", getattr(self.instance, "contract", None))
        forwarder = attrs.get(
            "freight_forwarder", getattr(self.instance, "freight_forwarder", None)
        )
        if contract and contract.company_id != order.company_id:
            raise serializers.ValidationError({"contract": "合同必须与销售订单属于同一公司。"})
        if forwarder and forwarder.company_id != order.company_id:
            raise serializers.ValidationError({"freight_forwarder": "货代必须属于订单公司。"})
        return attrs


class PackageItemSerializer(serializers.ModelSerializer[PackageItem]):
    class Meta:
        model = PackageItem
        fields = "__all__"
        read_only_fields = ["package", "sku", "row_version"]


class PackageSerializer(serializers.ModelSerializer[Package]):
    items = PackageItemSerializer(many=True, read_only=True)

    class Meta:
        model = Package
        fields = "__all__"
        read_only_fields = ["status", "sealed_at", "reviewed_by", "row_version"]


class ShipmentOrderSerializer(serializers.ModelSerializer[ShipmentOrder]):
    class Meta:
        model = ShipmentOrder
        fields = "__all__"
        read_only_fields = ["shipment", "row_version"]


class MilestoneSerializer(serializers.ModelSerializer[ShipmentMilestone]):
    class Meta:
        model = ShipmentMilestone
        fields = "__all__"


class ClaimSerializer(serializers.ModelSerializer[ShipmentClaim]):
    class Meta:
        model = ShipmentClaim
        fields = "__all__"


class ShipmentSerializer(serializers.ModelSerializer[Shipment]):
    packages = PackageSerializer(many=True, read_only=True)
    orders = ShipmentOrderSerializer(many=True, read_only=True)
    milestones = MilestoneSerializer(many=True, read_only=True)
    claims = ClaimSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = "__all__"
        read_only_fields = [
            "package_count",
            "gross_weight",
            "net_weight",
            "volume",
            "status",
            "actual_ship_at",
            "actual_arrival_at",
            "exception_type",
            "exception_detail",
            "version_no",
            "row_version",
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        forwarder = attrs.get("forwarder", getattr(self.instance, "forwarder", None))
        if forwarder and forwarder.company_id != getattr(company, "pk", None):
            raise serializers.ValidationError({"forwarder": "货代必须属于出运公司。"})
        return attrs


class AddOrderSerializer(serializers.Serializer[dict[str, object]]):
    sales_order_id = serializers.IntegerField()


class PackItemInputSerializer(serializers.Serializer[dict[str, object]]):
    sales_order_line_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6)
    product_serial_id = serializers.IntegerField(required=False, allow_null=True)


class PackSerializer(serializers.Serializer[dict[str, object]]):
    items = PackItemInputSerializer(many=True, allow_empty=False)


class ReviewSerializer(serializers.Serializer[dict[str, object]]):
    approved = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ReasonSerializer(serializers.Serializer[dict[str, object]]):
    reason = serializers.CharField()


class ExceptionSerializer(serializers.Serializer[dict[str, object]]):
    exception_type = serializers.CharField(max_length=50)
    detail = serializers.CharField()


class CompanyRelationSerializer(serializers.ModelSerializer):
    relation_fields: tuple[str, ...] = ()

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        company = attrs.get("company", getattr(self.instance, "company", None))
        for field in self.relation_fields:
            related = attrs.get(field, getattr(self.instance, field, None))
            related_company_id = getattr(related, "company_id", None)
            if related is not None and related_company_id != getattr(company, "pk", None):
                raise serializers.ValidationError({field: "关联对象必须属于同一公司。"})
        return attrs


class TradeDocumentSerializer(CompanyRelationSerializer):
    relation_fields = ("shipment",)

    class Meta:
        model = TradeDocument
        fields = "__all__"
        read_only_fields = [
            "status",
            "content_sha256",
            "created_by",
            "issued_by",
            "issued_at",
            "row_version",
        ]


class CustomsDeclarationSerializer(CompanyRelationSerializer):
    relation_fields = ("shipment",)

    class Meta:
        model = CustomsDeclaration
        fields = "__all__"
        read_only_fields = ["status", "row_version"]


class TradeCostSerializer(CompanyRelationSerializer):
    relation_fields = ("shipment", "service_party")

    class Meta:
        model = TradeCost
        fields = "__all__"
        read_only_fields = ["status", "row_version"]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        attrs = super().validate(attrs)
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        rate = attrs.get("exchange_rate", getattr(self.instance, "exchange_rate", None))
        base_amount = attrs.get("base_amount", getattr(self.instance, "base_amount", None))
        if amount is not None and rate is not None and base_amount != amount * rate:
            raise serializers.ValidationError({"base_amount": "本位币金额必须等于原币金额乘汇率。"})
        return attrs


class ForwarderSettlementSerializer(CompanyRelationSerializer):
    relation_fields = ("forwarder",)

    class Meta:
        model = ForwarderSettlement
        fields = "__all__"
        read_only_fields = ["status", "difference_amount", "row_version"]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        attrs = super().validate(attrs)
        receivable = attrs.get("receivable_amount", getattr(self.instance, "receivable_amount", 0))
        fees = attrs.get("fee_amount", getattr(self.instance, "fee_amount", 0))
        received = attrs.get("received_amount", getattr(self.instance, "received_amount", 0))
        attrs["difference_amount"] = receivable - fees - received
        return attrs


class OverseasWarehouseSerializer(CompanyRelationSerializer):
    relation_fields = ("warehouse", "operator")

    class Meta:
        model = OverseasWarehouseProfile
        fields = "__all__"
        read_only_fields = ["row_version"]

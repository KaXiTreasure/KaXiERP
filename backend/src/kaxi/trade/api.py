import hashlib
import json

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.shared.crud import ScopedCrudViewSet
from kaxi.trade.models import (
    CustomsDeclaration,
    ForwarderSettlement,
    OverseasWarehouseProfile,
    Package,
    SalesOrderTradeDetail,
    Shipment,
    TradeContract,
    TradeCost,
    TradeDocument,
)
from kaxi.trade.serializers import (
    AddOrderSerializer,
    ContractSerializer,
    CustomsDeclarationSerializer,
    ExceptionSerializer,
    ForwarderSettlementSerializer,
    OverseasWarehouseSerializer,
    PackageSerializer,
    PackSerializer,
    ReasonSerializer,
    ReviewSerializer,
    ShipmentSerializer,
    TradeCostSerializer,
    TradeDetailSerializer,
    TradeDocumentSerializer,
)
from kaxi.trade.services import (
    PackageItemInput,
    add_order,
    approve_contract,
    dispatch_shipment,
    open_package,
    pack_items,
    record_exception,
    review_package,
    submit_package,
    transition_shipment,
)


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class CompanyViewSet(ScopedCrudViewSet):
    permission_classes = [AtomicPermissionRequired]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)


class ContractViewSet(CompanyViewSet):
    queryset = TradeContract.objects.select_related("company", "customer", "currency")
    serializer_class = ContractSerializer
    atomic_permissions = {
        name: "trade.contract.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy", "approve"]
    }

    def perform_create(self, serializer: ContractSerializer) -> None:
        instance = serializer.save(created_by=_user(self.request))
        self._assert_company(instance)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        contract = approve_contract(contract_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(contract).data)


class TradeDetailViewSet(viewsets.ModelViewSet[SalesOrderTradeDetail]):
    queryset = SalesOrderTradeDetail.objects.select_related("sales_order", "contract")
    serializer_class = TradeDetailSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "trade.order.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return (
            queryset if company_id is None else queryset.filter(sales_order__company_id=company_id)
        )

    def _assert_company(self, instance: SalesOrderTradeDetail) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and instance.sales_order.company_id != company_id:
            raise PermissionDenied("不能写入其他公司的贸易订单扩展。")

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())


class ShipmentViewSet(CompanyViewSet):
    queryset = Shipment.objects.select_related("company", "forwarder").prefetch_related(
        "orders", "packages__items", "milestones", "claims"
    )
    serializer_class = ShipmentSerializer
    atomic_permissions = {
        "list": "trade.shipment.manage",
        "retrieve": "trade.shipment.manage",
        "create": "trade.shipment.manage",
        "update": "trade.shipment.manage",
        "partial_update": "trade.shipment.manage",
        "destroy": "trade.shipment.manage",
        "add_order": "trade.shipment.manage",
        "transition": "trade.shipment.manage",
        "dispatch": "trade.shipment.dispatch",
        "exception": "trade.shipment.manage",
    }

    @action(detail=True, methods=["post"], url_path="orders")
    def add_order(self, request: Request, pk: str | None = None) -> Response:
        serializer = AddOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        link = add_order(shipment_id=self.get_object().pk, **serializer.validated_data)
        return Response({"shipment_order_id": link.pk}, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "transition_action",
                str,
                OpenApiParameter.PATH,
                enum=["documents_ready", "handover", "in_transit", "arrive", "sign", "complete"],
            )
        ]
    )
    @action(detail=True, methods=["post"], url_path=r"transition/(?P<transition_action>[^/.]+)")
    def transition(
        self, request: Request, pk: str | None = None, transition_action: str = ""
    ) -> Response:
        shipment = transition_shipment(shipment_id=self.get_object().pk, action=transition_action)
        return Response(self.get_serializer(shipment).data)

    @action(detail=True, methods=["post"])
    def dispatch(self, request: Request, pk: str | None = None) -> Response:
        shipment = dispatch_shipment(
            shipment_id=self.get_object().pk, actual_ship_at=timezone.now()
        )
        return Response(self.get_serializer(shipment).data)

    @action(detail=True, methods=["post"])
    def exception(self, request: Request, pk: str | None = None) -> Response:
        serializer = ExceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shipment = record_exception(shipment_id=self.get_object().pk, **serializer.validated_data)
        return Response(self.get_serializer(shipment).data)


class PackageViewSet(viewsets.ModelViewSet[Package]):
    queryset = Package.objects.select_related("shipment").prefetch_related("items")
    serializer_class = PackageSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "trade.packing.process",
        "retrieve": "trade.packing.process",
        "create": "trade.packing.process",
        "update": "trade.packing.process",
        "partial_update": "trade.packing.process",
        "destroy": "trade.packing.process",
        "pack": "trade.packing.process",
        "submit": "trade.packing.process",
        "review": "trade.packing.process",
        "open": "trade.packing.process",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(shipment__company_id=company_id)

    def _assert_company(self, instance: Package) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and instance.shipment.company_id != company_id:
            raise PermissionDenied("不能写入其他公司的装箱数据。")

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())

    @action(detail=True, methods=["post"])
    def pack(self, request: Request, pk: str | None = None) -> Response:
        serializer = PackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        package = pack_items(
            package_id=self.get_object().pk,
            items=[PackageItemInput(**item) for item in serializer.validated_data["items"]],
        )
        return Response(self.get_serializer(package).data)

    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: str | None = None) -> Response:
        package = submit_package(package_id=self.get_object().pk)
        return Response(self.get_serializer(package).data)

    @action(detail=True, methods=["post"])
    def review(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        package = review_package(
            package_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(self.get_serializer(package).data)

    @action(detail=True, methods=["post"])
    def open(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        package = open_package(package_id=self.get_object().pk, **serializer.validated_data)
        return Response(self.get_serializer(package).data)


class TradeDocumentViewSet(CompanyViewSet):
    queryset = TradeDocument.objects.select_related(
        "company", "shipment", "created_by", "issued_by"
    )
    serializer_class = TradeDocumentSerializer
    atomic_permissions = {
        name: "trade.document.generate"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "generate",
            "issue",
            "void",
        ]
    }

    def perform_create(self, serializer: TradeDocumentSerializer) -> None:
        instance = serializer.save(created_by=_user(self.request))
        self._assert_company(instance)

    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        if serializer.instance.status != TradeDocument.Status.DRAFT:
            raise PermissionDenied("已生成或签发的单证快照不可覆盖。")
        super().perform_update(serializer)

    def perform_destroy(self, instance):  # type: ignore[no-untyped-def]
        if instance.status != TradeDocument.Status.DRAFT:
            raise PermissionDenied("已生成或签发的单证不可删除，只能作废。")
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def generate(self, request: Request, pk: str | None = None) -> Response:
        document = TradeDocument.objects.select_for_update().get(pk=self.get_object().pk)
        if document.status != TradeDocument.Status.DRAFT:
            raise PermissionDenied("只有草稿单证可以生成。")
        canonical = json.dumps(document.snapshot, sort_keys=True, ensure_ascii=False).encode()
        document.content_sha256 = hashlib.sha256(canonical).hexdigest()
        document.status = TradeDocument.Status.GENERATED
        document.row_version += 1
        document.save()
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def issue(self, request: Request, pk: str | None = None) -> Response:
        document = TradeDocument.objects.select_for_update().get(pk=self.get_object().pk)
        actor = _user(request)
        if document.status != TradeDocument.Status.GENERATED:
            raise PermissionDenied("只有已生成单证可以签发。")
        if document.created_by_id == actor.pk:
            raise PermissionDenied("单证创建人与签发人必须分离。")
        document.status = TradeDocument.Status.ISSUED
        document.issued_by = actor
        document.issued_at = timezone.now()
        document.row_version += 1
        document.save()
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def void(self, request: Request, pk: str | None = None) -> Response:
        document = TradeDocument.objects.select_for_update().get(pk=self.get_object().pk)
        if document.status != TradeDocument.Status.VOID:
            document.status = TradeDocument.Status.VOID
            document.row_version += 1
            document.save()
        return Response(self.get_serializer(document).data)


class StateControlledViewSet(CompanyViewSet):
    transitions: dict[str, tuple[str, ...]] = {}
    editable_statuses: tuple[str, ...] = ("draft",)

    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        if str(serializer.instance.status) not in self.editable_statuses:
            raise PermissionDenied("当前状态的记录不可覆盖修改。")
        super().perform_update(serializer)

    def perform_destroy(self, instance):  # type: ignore[no-untyped-def]
        if str(instance.status) not in self.editable_statuses:
            raise PermissionDenied("当前状态的记录不可删除。")
        super().perform_destroy(instance)

    @extend_schema(parameters=[OpenApiParameter("target", str, OpenApiParameter.PATH)])
    @action(detail=True, methods=["post"], url_path=r"transition/(?P<target>[^/.]+)")
    @transaction.atomic
    def transition(self, request: Request, pk: str | None = None, target: str = "") -> Response:
        instance = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
        if target not in self.transitions.get(str(instance.status), ()):
            raise PermissionDenied(f"不能从 {instance.status} 转换到 {target}。")
        instance.status = target
        instance.row_version += 1
        instance.save(update_fields=["status", "row_version", "updated_at"])
        return Response(self.get_serializer(instance).data)


class CustomsDeclarationViewSet(StateControlledViewSet):
    queryset = CustomsDeclaration.objects.select_related(
        "company", "shipment", "declaration_currency"
    )
    serializer_class = CustomsDeclarationSerializer
    transitions = {
        "draft": ("submitted", "cancelled"),
        "submitted": ("cleared", "rejected", "cancelled"),
        "rejected": ("draft", "cancelled"),
    }
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy", "transition"],
        "trade.customs.manage",
    )


class TradeCostViewSet(StateControlledViewSet):
    queryset = TradeCost.objects.select_related("company", "shipment", "service_party", "currency")
    serializer_class = TradeCostSerializer
    transitions = {
        "estimated": ("confirmed", "reversed"),
        "confirmed": ("settled", "reversed"),
        "settled": ("reversed",),
    }
    editable_statuses = ("estimated",)
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy", "transition"],
        "trade.cost.manage",
    )


class ForwarderSettlementViewSet(StateControlledViewSet):
    queryset = ForwarderSettlement.objects.select_related("company", "forwarder", "currency")
    serializer_class = ForwarderSettlementSerializer
    transitions = {"draft": ("confirmed",), "confirmed": ("paid",), "paid": ("reconciled",)}
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy", "transition"],
        "trade.forwarder_settlement.manage",
    )


class OverseasWarehouseViewSet(CompanyViewSet):
    queryset = OverseasWarehouseProfile.objects.select_related(
        "company", "warehouse", "country_region", "operator"
    )
    serializer_class = OverseasWarehouseSerializer
    atomic_permissions = dict.fromkeys(
        ["list", "retrieve", "create", "update", "partial_update", "destroy"],
        "trade.overseas_warehouse.manage",
    )

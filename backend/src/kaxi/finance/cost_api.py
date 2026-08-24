from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.finance.cost_serializers import (
    AssignSerialCostSerializer,
    CostBalanceSerializer,
    CostRecordSerializer,
    IssueCostSerializer,
    ReceiveCostSerializer,
    ReverseCostSerializer,
    SerialCostSerializer,
)
from kaxi.finance.cost_services import (
    assign_serial_cost,
    issue_weighted_cost,
    receive_weighted_cost,
    reverse_cost_record,
)
from kaxi.finance.models import CostRecord, InventoryCostBalance, SerialCost
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.products.models import ProductSerial


class CostBalanceViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[InventoryCostBalance]
):
    queryset = InventoryCostBalance.objects.select_related("company", "sku", "warehouse")
    serializer_class = CostBalanceSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {"list": "inventory.cost.read", "retrieve": "inventory.cost.read"}

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)


class CostRecordViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[CostRecord]
):
    queryset = CostRecord.objects.select_related("company", "currency")
    serializer_class = CostRecordSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "finance.cost.read",
        "retrieve": "finance.cost.read",
        "receive": "finance.cost.manage",
        "issue": "finance.cost.manage",
        "reverse": "finance.cost.reverse",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def _check_company(self, request: Request, company_id: int) -> None:
        scoped = company_id_for_request(request)
        if scoped is not None and scoped != company_id:
            raise PermissionDenied("不能处理其他公司的成本。")

    @action(detail=False, methods=["post"])
    def receive(self, request: Request) -> Response:
        serializer = ReceiveCostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._check_company(request, serializer.validated_data["company_id"])
        result = receive_weighted_cost(**serializer.validated_data)
        return Response(result.__dict__, status=201)

    @action(detail=False, methods=["post"])
    def issue(self, request: Request) -> Response:
        serializer = IssueCostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._check_company(request, serializer.validated_data["company_id"])
        result = issue_weighted_cost(**serializer.validated_data)
        return Response(result.__dict__, status=201)

    @action(detail=True, methods=["post"])
    def reverse(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReverseCostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = reverse_cost_record(record_id=self.get_object().pk, **serializer.validated_data)
        return Response(self.get_serializer(result).data, status=201)


class SerialCostViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[SerialCost]
):
    queryset = SerialCost.objects.select_related("serial", "company", "currency")
    serializer_class = SerialCostSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "inventory.cost.read",
        "retrieve": "inventory.cost.read",
        "assign": "finance.cost.manage",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=False, methods=["post"])
    def assign(self, request: Request) -> Response:
        serializer = AssignSerialCostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scoped = company_id_for_request(request)
        if (
            scoped is not None
            and not ProductSerial.objects.filter(
                pk=serializer.validated_data["serial_id"], company_id=scoped
            ).exists()
        ):
            raise PermissionDenied("不能处理其他公司的单件成本。")
        item = assign_serial_cost(**serializer.validated_data)
        return Response(self.get_serializer(item).data, status=201)

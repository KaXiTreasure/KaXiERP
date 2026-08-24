from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.inventory.models import InventoryBalance, StockCount, StockTransfer
from kaxi.inventory.operation_services import (
    approve_stock_transfer,
    dispatch_stock_transfer,
    post_stock_count,
    receive_stock_transfer,
    start_stock_count,
    submit_stock_count,
)
from kaxi.inventory.serializers import (
    InventoryBalanceSerializer,
    StartCountSerializer,
    StockCountSerializer,
    StockTransferSerializer,
    SubmitCountSerializer,
    TransferOperationSerializer,
    TransferReceiptSerializer,
    VersionSerializer,
)


class CompanyScopedMixin:
    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()  # type: ignore[misc]
        company_id = company_id_for_request(self.request)  # type: ignore[attr-defined]
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def validate_company_create(self, serializer) -> None:  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)  # type: ignore[attr-defined]
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能为其他公司创建库存单据。")


class InventoryBalanceViewSet(
    CompanyScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[InventoryBalance],
):
    queryset = InventoryBalance.objects.select_related(
        "company", "sku", "warehouse", "location", "inventory_status", "lot"
    )
    serializer_class = InventoryBalanceSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {"list": "inventory.balance.read", "retrieve": "inventory.balance.read"}


class StockTransferViewSet(
    CompanyScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[StockTransfer],
):
    queryset = StockTransfer.objects.select_related(
        "company", "source_warehouse", "destination_warehouse"
    ).prefetch_related("lines")
    serializer_class = StockTransferSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "inventory.transfer.manage",
        "retrieve": "inventory.transfer.manage",
        "create": "inventory.transfer.manage",
        "approve": "inventory.transfer.manage",
        "dispatch": "inventory.transfer.manage",
        "receive": "inventory.transfer.manage",
    }

    def perform_create(self, serializer: StockTransferSerializer) -> None:
        self.validate_company_create(serializer)
        serializer.save()

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        transfer = self.get_object()
        serializer = VersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = approve_stock_transfer(
            transfer_id=transfer.pk, expected_version=serializer.validated_data["expected_version"]
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def dispatch(self, request: Request, pk: str | None = None) -> Response:
        transfer = self.get_object()
        serializer = TransferOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = dispatch_stock_transfer(
            transfer_id=transfer.pk,
            idempotency_key=serializer.validated_data["idempotency_key"],
            operator=user,
            occurred_at=serializer.validated_data["occurred_at"],
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str | None = None) -> Response:
        transfer = self.get_object()
        serializer = TransferReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        lines = serializer.validated_data["lines"]
        result = receive_stock_transfer(
            transfer_id=transfer.pk,
            received_quantities={line["line_id"]: line["quantity"] for line in lines},
            idempotency_key=serializer.validated_data["idempotency_key"],
            operator=user,
            occurred_at=serializer.validated_data["occurred_at"],
        )
        return Response(result.__dict__)


class StockCountViewSet(
    CompanyScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[StockCount],
):
    queryset = StockCount.objects.select_related(
        "company", "warehouse", "posted_by"
    ).prefetch_related("lines")
    serializer_class = StockCountSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "inventory.count.manage",
        "retrieve": "inventory.count.manage",
        "create": "inventory.count.manage",
        "start": "inventory.count.manage",
        "submit": "inventory.count.manage",
        "post": "inventory.count.approve",
    }

    def perform_create(self, serializer: StockCountSerializer) -> None:
        self.validate_company_create(serializer)
        serializer.save()

    @action(detail=True, methods=["post"])
    def start(self, request: Request, pk: str | None = None) -> Response:
        count = self.get_object()
        serializer = StartCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = start_stock_count(
            count_id=count.pk,
            balance_ids=data["balance_ids"],
            expected_version=data["expected_version"],
            started_at=data["started_at"],
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: str | None = None) -> Response:
        count = self.get_object()
        serializer = SubmitCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = submit_stock_count(
            count_id=count.pk,
            counted_quantities={line["line_id"]: line["quantity"] for line in data["lines"]},
            submitted_at=data["submitted_at"],
        )
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def post(self, request: Request, pk: str | None = None) -> Response:
        count = self.get_object()
        serializer = TransferOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = post_stock_count(
            count_id=count.pk,
            idempotency_key=serializer.validated_data["idempotency_key"],
            operator=user,
            occurred_at=serializer.validated_data["occurred_at"],
        )
        return Response(result.__dict__, status=status.HTTP_200_OK)

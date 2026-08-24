from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.purchasing.models import GoodsReceipt, PurchaseOrder
from kaxi.purchasing.serializers import (
    CompleteInspectionSerializer,
    GoodsReceiptSerializer,
    PurchaseOrderSerializer,
    PurchaseOrderTransitionSerializer,
    ReceivePurchaseOrderSerializer,
)
from kaxi.purchasing.services import (
    InspectionLineInput,
    ReceiptLineInput,
    complete_purchase_inspection,
    receive_purchase_order,
    transition_purchase_order,
)


class PurchaseOrderViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet[PurchaseOrder],
):
    queryset = PurchaseOrder.objects.select_related(
        "company", "supplier", "currency", "warehouse"
    ).prefetch_related("lines")
    serializer_class = PurchaseOrderSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "purchase.order.manage",
        "retrieve": "purchase.order.manage",
        "create": "purchase.order.manage",
        "receive": "purchase.receipt.inspect",
        "approve": "purchase.order.approve",
        "issue": "purchase.order.manage",
        "cancel": "purchase.order.manage",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: PurchaseOrderSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能为其他公司创建采购订单。")
        serializer.save()

    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str | None = None) -> Response:
        order = self.get_object()
        serializer = ReceivePurchaseOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = receive_purchase_order(
            order_id=order.pk,
            receipt_no=data["receipt_no"],
            received_at=data["received_at"],
            received_by=user,
            supplier_delivery_no=data["supplier_delivery_no"],
            lines=[ReceiptLineInput(**line) for line in data["lines"]],
        )
        return Response(result.__dict__, status=status.HTTP_200_OK)

    def _transition(self, request: Request, pk: str | None, action_name: str) -> Response:
        order = self.get_object()
        serializer = PurchaseOrderTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = transition_purchase_order(
            order_id=order.pk,
            expected_version=serializer.validated_data["expected_version"],
            action=action_name,
        )
        return Response(result.__dict__, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, pk, "approve")

    @action(detail=True, methods=["post"])
    def issue(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, pk, "issue")

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        return self._transition(request, pk, "cancel")


class GoodsReceiptViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[GoodsReceipt]
):
    queryset = GoodsReceipt.objects.select_related(
        "company", "purchase_order", "supplier", "warehouse", "received_by"
    ).prefetch_related("lines")
    serializer_class = GoodsReceiptSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "purchase.receipt.inspect",
        "retrieve": "purchase.receipt.inspect",
        "complete_inspection": "purchase.receipt.inspect",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=True, methods=["post"], url_path="complete-inspection")
    def complete_inspection(self, request: Request, pk: str | None = None) -> Response:
        receipt = self.get_object()
        serializer = CompleteInspectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        if not isinstance(user, User):
            raise PermissionDenied("需要有效业务用户。")
        result = complete_purchase_inspection(
            receipt_id=receipt.pk,
            inspection_no=data["inspection_no"],
            inspector=user,
            completed_at=data["completed_at"],
            lines=[InspectionLineInput(**line) for line in data["lines"]],
        )
        return Response(result.__dict__, status=status.HTTP_200_OK)

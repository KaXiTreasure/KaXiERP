from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.purchasing.extended_serializers import (
    ApprovalSerializer,
    AwardSerializer,
    DispatchSerializer,
    PerformanceSerializer,
    PurchaseReturnSerializer,
    QuoteSerializer,
    RequisitionSerializer,
    RfqSerializer,
)
from kaxi.purchasing.models import (
    PurchaseRequisition,
    PurchaseReturn,
    RequestForQuotation,
    SupplierPerformanceSnapshot,
    SupplierQuote,
)
from kaxi.purchasing.serializers import PurchaseOrderSerializer
from kaxi.purchasing.services import (
    approve_purchase_return,
    approve_requisition,
    award_quote,
    dispatch_purchase_return,
    issue_rfq,
    submit_requisition,
)


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class CompanyViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)


class RequisitionViewSet(CompanyViewSet):
    queryset = PurchaseRequisition.objects.select_related("company", "warehouse").prefetch_related(
        "lines"
    )
    serializer_class = RequisitionSerializer
    atomic_permissions = {
        "list": "purchase.requisition.manage",
        "retrieve": "purchase.requisition.manage",
        "create": "purchase.requisition.manage",
        "update": "purchase.requisition.manage",
        "partial_update": "purchase.requisition.manage",
        "destroy": "purchase.requisition.manage",
        "submit": "purchase.requisition.manage",
        "approve": "purchase.order.approve",
    }

    def perform_create(self, serializer: RequisitionSerializer) -> None:
        serializer.save(requested_by=_user(self.request))

    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: str | None = None) -> Response:
        item = submit_requisition(requisition_id=self.get_object().pk)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        serializer = ApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = approve_requisition(
            requisition_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(self.get_serializer(item).data)


class RfqViewSet(CompanyViewSet):
    queryset = RequestForQuotation.objects.select_related(
        "company", "requisition"
    ).prefetch_related("suppliers", "quotes")
    serializer_class = RfqSerializer
    atomic_permissions = {
        "list": "purchase.rfq.manage",
        "retrieve": "purchase.rfq.manage",
        "create": "purchase.rfq.manage",
        "update": "purchase.rfq.manage",
        "partial_update": "purchase.rfq.manage",
        "destroy": "purchase.rfq.manage",
        "issue": "purchase.rfq.manage",
        "award": "purchase.order.approve",
    }

    @action(detail=True, methods=["post"])
    def issue(self, request: Request, pk: str | None = None) -> Response:
        item = issue_rfq(rfq_id=self.get_object().pk)
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def award(self, request: Request, pk: str | None = None) -> Response:
        serializer = AwardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = award_quote(rfq_id=self.get_object().pk, **serializer.validated_data)
        return Response(PurchaseOrderSerializer(order).data)


class QuoteViewSet(viewsets.ModelViewSet[SupplierQuote]):
    queryset = SupplierQuote.objects.select_related(
        "rfq__company", "supplier", "currency"
    ).prefetch_related("lines")
    serializer_class = QuoteSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "purchase.rfq.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(rfq__company_id=company_id)


class ReturnViewSet(CompanyViewSet):
    queryset = PurchaseReturn.objects.select_related(
        "company", "purchase_order", "supplier"
    ).prefetch_related("lines")
    serializer_class = PurchaseReturnSerializer
    atomic_permissions = {
        "list": "purchase.return.manage",
        "retrieve": "purchase.return.manage",
        "create": "purchase.return.manage",
        "update": "purchase.return.manage",
        "partial_update": "purchase.return.manage",
        "destroy": "purchase.return.manage",
        "approve": "purchase.return.manage",
        "dispatch": "purchase.return.manage",
    }

    def perform_create(self, serializer: PurchaseReturnSerializer) -> None:
        serializer.save(requested_by=_user(self.request))

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        item = approve_purchase_return(return_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"])
    def dispatch(self, request: Request, pk: str | None = None) -> Response:
        serializer = DispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = dispatch_purchase_return(
            return_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(self.get_serializer(item).data)


class PerformanceViewSet(CompanyViewSet):
    queryset = SupplierPerformanceSnapshot.objects.select_related("company", "supplier")
    serializer_class = PerformanceSerializer
    atomic_permissions = {
        name: "purchase.supplier_performance.read"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.aftersales.models import AfterSalesCase, Refund, ReturnReceipt
from kaxi.aftersales.serializers import (
    ApprovalSerializer,
    CaseSerializer,
    PaidSerializer,
    ReceiptSerializer,
    ReceiveSerializer,
    RefundSerializer,
)
from kaxi.aftersales.services import (
    ReturnLineInput,
    approve_case,
    approve_refund,
    complete_case,
    mark_refund_paid,
    receive_return,
    submit_case,
)
from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class CaseViewSet(viewsets.ModelViewSet[AfterSalesCase]):
    queryset = AfterSalesCase.objects.select_related(
        "company", "sales_order", "customer", "requested_by"
    ).prefetch_related("lines", "refunds", "replacements")
    serializer_class = CaseSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "sales.aftersales.create",
        "retrieve": "sales.aftersales.create",
        "create": "sales.aftersales.create",
        "update": "sales.aftersales.process",
        "partial_update": "sales.aftersales.process",
        "destroy": "sales.aftersales.process",
        "submit": "sales.aftersales.process",
        "approve": "sales.aftersales.approve",
        "receive": "sales.aftersales.process",
        "complete": "sales.aftersales.process",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def perform_create(self, serializer: CaseSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能为其他公司创建售后单。")
        serializer.save(requested_by=_user(self.request))

    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: str | None = None) -> Response:
        case = submit_case(case_id=self.get_object().pk)
        return Response(self.get_serializer(case).data)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        serializer = ApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        case = approve_case(
            case_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(self.get_serializer(case).data)

    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        receipt = receive_return(
            case_id=self.get_object().pk,
            actor=_user(request),
            receipt_no=data["receipt_no"],
            idempotency_key=data["idempotency_key"],
            lines=[ReturnLineInput(**item) for item in data["lines"]],
        )
        return Response(ReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: str | None = None) -> Response:
        case = complete_case(case_id=self.get_object().pk)
        return Response(self.get_serializer(case).data)


class ReceiptViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[ReturnReceipt]
):
    queryset = ReturnReceipt.objects.select_related("case", "received_by").prefetch_related("lines")
    serializer_class = ReceiptSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "sales.aftersales.process",
        "retrieve": "sales.aftersales.process",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(case__company_id=company_id)


class RefundViewSet(viewsets.ModelViewSet[Refund]):
    queryset = Refund.objects.select_related("case", "currency")
    serializer_class = RefundSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "list": "sales.aftersales.process",
        "retrieve": "sales.aftersales.process",
        "create": "sales.aftersales.process",
        "update": "sales.aftersales.approve",
        "partial_update": "sales.aftersales.approve",
        "destroy": "sales.aftersales.approve",
        "mark_paid": "sales.aftersales.approve",
        "approve": "sales.aftersales.approve",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(case__company_id=company_id)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request: Request, pk: str | None = None) -> Response:
        serializer = PaidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund = mark_refund_paid(refund_id=self.get_object().pk, **serializer.validated_data)
        return Response(self.get_serializer(refund).data)

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        refund = approve_refund(refund_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(refund).data)

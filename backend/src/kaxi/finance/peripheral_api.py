from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.finance.api import CompanyScopedViewSet, _user
from kaxi.finance.models import DepreciationEntry, ExpenseClaim, FixedAsset, PayrollRun, TaxInvoice
from kaxi.finance.peripheral_serializers import (
    DepreciateSerializer,
    DepreciationSerializer,
    DisposeSerializer,
    ExpenseClaimSerializer,
    FixedAssetSerializer,
    PayrollSerializer,
    TaxInvoiceSerializer,
    TransitionSerializer,
)
from kaxi.finance.peripheral_services import (
    activate_asset,
    calculate_payroll,
    depreciate_asset,
    dispose_asset,
    transition_expense,
    transition_payroll,
    transition_tax_invoice,
)


class ExpenseClaimViewSet(CompanyScopedViewSet):
    queryset = ExpenseClaim.objects.select_related("company", "claimant", "currency", "journal")
    serializer_class = ExpenseClaimSerializer
    atomic_permissions = {
        name: "expense.claim.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "transition",
        ]
    }

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: str | None = None) -> Response:
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        claim = transition_expense(
            claim_id=self.get_object().pk,
            target=serializer.validated_data["target"],
            actor=_user(request),
        )
        return Response(self.get_serializer(claim).data)


class FixedAssetViewSet(CompanyScopedViewSet):
    queryset = FixedAsset.objects.select_related("company", "custodian")
    serializer_class = FixedAssetSerializer
    atomic_permissions = {
        name: "asset.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "activate",
            "depreciate",
            "dispose",
        ]
    }

    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        return Response(self.get_serializer(activate_asset(asset_id=self.get_object().pk)).data)

    @action(detail=True, methods=["post"])
    def depreciate(self, request: Request, pk: str | None = None) -> Response:
        serializer = DepreciateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = depreciate_asset(asset_id=self.get_object().pk, **serializer.validated_data)
        return Response(DepreciationSerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def dispose(self, request: Request, pk: str | None = None) -> Response:
        serializer = DisposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asset = dispose_asset(asset_id=self.get_object().pk, **serializer.validated_data)
        return Response(self.get_serializer(asset).data)


class DepreciationViewSet(viewsets.ReadOnlyModelViewSet[DepreciationEntry]):
    queryset = DepreciationEntry.objects.select_related("asset", "period", "journal")
    serializer_class = DepreciationSerializer
    permission_classes = FixedAssetViewSet.permission_classes
    atomic_permissions = {"list": "asset.manage", "retrieve": "asset.manage"}

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = getattr(self.request.user, "company_id", None)
        return queryset if company_id is None else queryset.filter(asset__company_id=company_id)


class PayrollViewSet(CompanyScopedViewSet):
    queryset = PayrollRun.objects.select_related("company", "period", "journal").prefetch_related(
        "lines"
    )
    serializer_class = PayrollSerializer
    atomic_permissions = {
        name: "payroll.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "calculate",
            "transition",
        ]
    }

    def perform_create(self, serializer: PayrollSerializer) -> None:
        serializer.save(calculated_by=_user(self.request))

    @action(detail=True, methods=["post"])
    def calculate(self, request: Request, pk: str | None = None) -> Response:
        payroll = calculate_payroll(payroll_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(payroll).data)

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: str | None = None) -> Response:
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payroll = transition_payroll(
            payroll_id=self.get_object().pk,
            target=serializer.validated_data["target"],
            actor=_user(request),
        )
        return Response(self.get_serializer(payroll).data)


class TaxInvoiceViewSet(CompanyScopedViewSet):
    queryset = TaxInvoice.objects.select_related("company", "party", "currency", "journal")
    serializer_class = TaxInvoiceSerializer
    atomic_permissions = {
        name: "tax.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "transition",
        ]
    }

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: str | None = None) -> Response:
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = transition_tax_invoice(
            invoice_id=self.get_object().pk,
            target=serializer.validated_data["target"],
            actor=_user(request),
        )
        return Response(self.get_serializer(invoice).data)

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.sales.models import PresaleCampaign, SupplyAllocation, SupplyDemand
from kaxi.sales.penetration_serializers import (
    LinkSupplySerializer,
    PresaleAllocationSerializer,
    PresaleCampaignSerializer,
    ReceiveSupplySerializer,
    SupplyAllocationSerializer,
    SupplyDemandSerializer,
)
from kaxi.sales.penetration_services import (
    activate_presale,
    allocate_presale,
    create_supply_demand,
    link_supply,
    receive_supply,
)


class SupplyDemandViewSet(viewsets.ModelViewSet[SupplyDemand]):
    queryset = SupplyDemand.objects.select_related("company", "sales_order_line").prefetch_related(
        "allocations"
    )
    serializer_class = SupplyDemandSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "sales.penetration.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy", "link"]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def create(self, request: Request, *args, **kwargs) -> Response:  # type: ignore[no-untyped-def]
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        demand = create_supply_demand(
            sales_order_line_id=data["sales_order_line"].pk,
            demand_no=data["demand_no"],
            strategy=data["strategy"],
            required_date=data["required_date"],
            idempotency_key=data["idempotency_key"],
        )
        return Response(self.get_serializer(demand).data, status=201)

    @action(detail=True, methods=["post"])
    def link(self, request: Request, pk: str | None = None) -> Response:
        serializer = LinkSupplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allocation = link_supply(demand_id=self.get_object().pk, **serializer.validated_data)
        return Response(SupplyAllocationSerializer(allocation).data, status=201)


class SupplyAllocationViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet[SupplyAllocation]):
    queryset = SupplyAllocation.objects.select_related("demand")
    serializer_class = SupplyAllocationSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        "retrieve": "sales.penetration.manage",
        "receive": "sales.penetration.manage",
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(demand__company_id=company_id)

    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReceiveSupplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        demand = receive_supply(allocation_id=self.get_object().pk, **serializer.validated_data)
        return Response(SupplyDemandSerializer(demand).data)


class PresaleCampaignViewSet(viewsets.ModelViewSet[PresaleCampaign]):
    queryset = PresaleCampaign.objects.select_related(
        "company", "sku", "sales_channel"
    ).prefetch_related("allocations")
    serializer_class = PresaleCampaignSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {
        name: "sales.penetration.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "activate",
            "allocate",
        ]
    }

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        campaign = activate_presale(campaign_id=self.get_object().pk)
        return Response(self.get_serializer(campaign).data)

    @action(detail=True, methods=["post"])
    def allocate(self, request: Request, pk: str | None = None) -> Response:
        serializer = PresaleAllocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        allocation = allocate_presale(
            campaign_id=self.get_object().pk,
            sales_order_line_id=data["sales_order_line"].pk,
            quantity=data["quantity"],
        )
        return Response(PresaleAllocationSerializer(allocation).data, status=201)

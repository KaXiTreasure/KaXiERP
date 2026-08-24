from django.db import transaction
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.finance.models import (
    Account,
    ChartOfAccounts,
    FiscalPeriod,
    JournalEntry,
    Ledger,
    OpenItem,
    Settlement,
    ThreeWayMatch,
)
from kaxi.finance.serializers import (
    AccountSerializer,
    AllocateSerializer,
    ChartSerializer,
    JournalSerializer,
    LedgerSerializer,
    OpenItemSerializer,
    PeriodSerializer,
    ReopenPeriodSerializer,
    ReverseJournalSerializer,
    SettlementSerializer,
    ThreeWayMatchSerializer,
)
from kaxi.finance.services import (
    account_ledger,
    allocate,
    approve_journal,
    balance_sheet,
    cash_flow_statement,
    close_period,
    income_statement,
    post_journal,
    reopen_period,
    reverse_journal,
    trial_balance,
)
from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class CompanyScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        if company_id is None:
            return queryset
        if "company" in {field.name for field in queryset.model._meta.fields}:
            return queryset.filter(company_id=company_id)
        if queryset.model is Ledger:
            return queryset.filter(company_id=company_id)
        if queryset.model is ChartOfAccounts:
            return queryset.filter(ledger__company_id=company_id)
        if queryset.model is Account:
            return queryset.filter(chart__ledger__company_id=company_id)
        if queryset.model is FiscalPeriod:
            return queryset.filter(ledger__company_id=company_id)
        return queryset.none()

    def _instance_company_id(self, instance) -> int:  # type: ignore[no-untyped-def]
        if hasattr(instance, "company_id"):
            return instance.company_id
        if isinstance(instance, (ChartOfAccounts, FiscalPeriod)):
            return instance.ledger.company_id
        if isinstance(instance, Account):
            return instance.chart.ledger.company_id
        raise PermissionDenied("无法判定财务对象的公司归属。")

    def _assert_company(self, instance) -> None:  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        if company_id is not None and self._instance_company_id(instance) != company_id:
            raise PermissionDenied("不能写入其他公司的财务数据。")

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())


class LedgerViewSet(CompanyScopedViewSet):
    queryset = Ledger.objects.all()
    serializer_class = LedgerSerializer
    atomic_permissions = {
        name: "finance.account.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "trial_balance",
        ]
    }
    atomic_permissions.update(
        {
            "balance_sheet": "finance.statement.read",
            "income_statement": "finance.statement.read",
            "cash_flow": "finance.statement.read",
            "account_ledger": "finance.ledger.read",
        }
    )

    @action(detail=True, methods=["get"], url_path="trial-balance")
    def trial_balance(self, request: Request, pk: str | None = None) -> Response:
        ledger = self.get_object()
        start_date = parse_date(request.query_params.get("start_date", ""))
        end_date = parse_date(request.query_params.get("end_date", ""))
        if start_date is None or end_date is None:
            return Response(
                {"detail": "start_date 和 end_date 必须为 YYYY-MM-DD。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rows = trial_balance(
            ledger_id=ledger.pk,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(list(rows))

    @action(detail=True, methods=["get"], url_path="account-ledger")
    def account_ledger(self, request: Request, pk: str | None = None) -> Response:
        start_date = parse_date(request.query_params.get("start_date", ""))
        end_date = parse_date(request.query_params.get("end_date", ""))
        account_raw = request.query_params.get("account_id", "")
        party_raw = request.query_params.get("party_id", "")
        if (
            start_date is None
            or end_date is None
            or start_date > end_date
            or not account_raw.isdigit()
            or (party_raw and not party_raw.isdigit())
        ):
            return Response(
                {"detail": "必须提供有效的 account_id、start_date、end_date；party_id 可选。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = account_ledger(
                ledger_id=self.get_object().pk,
                account_id=int(account_raw),
                start_date=start_date,
                end_date=end_date,
                party_id=int(party_raw) if party_raw else None,
            )
        except Account.DoesNotExist:
            return Response({"detail": "科目不属于当前账簿。"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=True, methods=["get"], url_path="balance-sheet")
    def balance_sheet(self, request: Request, pk: str | None = None) -> Response:
        as_of = parse_date(request.query_params.get("as_of", ""))
        if as_of is None:
            return Response({"detail": "as_of 必须为 YYYY-MM-DD。"}, status=400)
        return Response(balance_sheet(ledger_id=self.get_object().pk, as_of=as_of))

    def _statement_dates(self, request: Request):  # type: ignore[no-untyped-def]
        start_date = parse_date(request.query_params.get("start_date", ""))
        end_date = parse_date(request.query_params.get("end_date", ""))
        if start_date is None or end_date is None or start_date > end_date:
            return None
        return start_date, end_date

    @action(detail=True, methods=["get"], url_path="income-statement")
    def income_statement(self, request: Request, pk: str | None = None) -> Response:
        dates = self._statement_dates(request)
        if dates is None:
            return Response({"detail": "报表日期范围无效。"}, status=400)
        return Response(
            income_statement(ledger_id=self.get_object().pk, start_date=dates[0], end_date=dates[1])
        )

    @action(detail=True, methods=["get"], url_path="cash-flow")
    def cash_flow(self, request: Request, pk: str | None = None) -> Response:
        dates = self._statement_dates(request)
        if dates is None:
            return Response({"detail": "报表日期范围无效。"}, status=400)
        return Response(
            cash_flow_statement(
                ledger_id=self.get_object().pk, start_date=dates[0], end_date=dates[1]
            )
        )


class ChartViewSet(CompanyScopedViewSet):
    queryset = ChartOfAccounts.objects.select_related("ledger")
    serializer_class = ChartSerializer
    atomic_permissions = {
        name: "finance.account.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class AccountViewSet(CompanyScopedViewSet):
    queryset = Account.objects.select_related("chart__ledger")
    serializer_class = AccountSerializer
    atomic_permissions = {
        name: "finance.account.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class PeriodViewSet(CompanyScopedViewSet):
    queryset = FiscalPeriod.objects.select_related("ledger")
    serializer_class = PeriodSerializer
    atomic_permissions = {
        name: "finance.period.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "close",
            "reopen",
        ]
    }

    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str | None = None) -> Response:
        period = close_period(period_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReopenPeriodSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        period = reopen_period(
            period_id=self.get_object().pk,
            actor=_user(request),
            approval_reference=serializer.validated_data["approval_reference"],
        )
        return Response(self.get_serializer(period).data)


class JournalViewSet(CompanyScopedViewSet):
    queryset = JournalEntry.objects.select_related("company", "ledger", "period").prefetch_related(
        "lines"
    )
    serializer_class = JournalSerializer
    atomic_permissions = {
        name: "finance.journal.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "approve",
            "post",
            "reverse",
        ]
    }

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        entry = approve_journal(journal_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(entry).data)

    @action(detail=True, methods=["post"])
    def post(self, request: Request, pk: str | None = None) -> Response:
        result = post_journal(journal_id=self.get_object().pk, actor=_user(request))
        return Response(result.__dict__)

    @action(detail=True, methods=["post"])
    def reverse(self, request: Request, pk: str | None = None) -> Response:
        serializer = ReverseJournalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = reverse_journal(
            journal_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(result.__dict__)


class OpenItemViewSet(CompanyScopedViewSet):
    queryset = OpenItem.objects.select_related("company", "party", "currency", "journal")
    serializer_class = OpenItemSerializer
    atomic_permissions = {
        name: "finance.arap.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class SettlementViewSet(CompanyScopedViewSet):
    queryset = Settlement.objects.select_related("company", "party", "currency", "journal")
    serializer_class = SettlementSerializer
    atomic_permissions = {
        name: "finance.treasury.manage"
        for name in [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "allocate",
        ]
    }

    @action(detail=True, methods=["post"])
    def allocate(self, request: Request, pk: str | None = None) -> Response:
        serializer = AllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = allocate(settlement_id=self.get_object().pk, **serializer.validated_data)
        return Response({"allocation_id": item.pk}, status=status.HTTP_201_CREATED)


class ThreeWayMatchViewSet(CompanyScopedViewSet):
    queryset = ThreeWayMatch.objects.select_related("company", "purchase_order", "goods_receipt")
    serializer_class = ThreeWayMatchSerializer
    atomic_permissions = {
        name: "finance.ap.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }

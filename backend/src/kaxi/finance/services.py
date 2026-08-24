from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from kaxi.finance.models import (
    Account,
    Allocation,
    FiscalPeriod,
    JournalEntry,
    OpenItem,
    Settlement,
)
from kaxi.identity.models import User
from kaxi.shared.outbox_service import append_outbox_event


@dataclass(frozen=True)
class PostingResult:
    journal_id: int
    status: str
    total: Decimal


def _emit(entry: JournalEntry, event_type: str) -> None:
    append_outbox_event(
        company=entry.company,
        aggregate_type="finance.journal",
        aggregate_id=str(entry.pk),
        aggregate_version=entry.row_version,
        event_type=event_type,
        payload={"journal_id": entry.pk, "voucher_no": entry.voucher_no},
    )


@transaction.atomic
def approve_journal(*, journal_id: int, actor: User) -> JournalEntry:
    entry = JournalEntry.objects.select_for_update().get(pk=journal_id)
    if entry.status != JournalEntry.Status.DRAFT:
        raise ValidationError("只有草稿凭证可以审核。")
    if entry.approved_by_id == actor.pk:
        raise ValidationError("凭证审核人与制单控制应由组织权限进一步分离。")
    JournalEntry.objects.filter(pk=entry.pk).update(
        status=JournalEntry.Status.APPROVED,
        approved_by=actor,
        approved_at=timezone.now(),
        row_version=entry.row_version + 1,
    )
    entry.refresh_from_db()
    return entry


@transaction.atomic
def post_journal(*, journal_id: int, actor: User) -> PostingResult:
    entry = (
        JournalEntry.objects.select_for_update()
        .select_related("ledger", "period")
        .get(pk=journal_id)
    )
    if entry.status == JournalEntry.Status.POSTED:
        return PostingResult(entry.pk, entry.status, entry.total_debit_base)
    if entry.status != JournalEntry.Status.APPROVED:
        raise ValidationError("凭证必须先审核再过账。")
    period = FiscalPeriod.objects.select_for_update().get(pk=entry.period_id)
    if period.status not in {FiscalPeriod.Status.OPEN, FiscalPeriod.Status.REOPENED}:
        raise ValidationError("会计期间已关闭。")
    if not period.start_date <= entry.entry_date <= period.end_date:
        raise ValidationError("凭证日期不在会计期间内。")
    lines = list(entry.lines.select_related("account__chart", "currency"))
    if len(lines) < 2:
        raise ValidationError("凭证至少需要两条分录。")
    for line in lines:
        account = line.account
        if (
            account.chart.ledger_id != entry.ledger_id
            or not account.active
            or not account.allow_posting
        ):
            raise ValidationError("凭证包含不可过账或不属于当前账簿的科目。")
        if account.requires_party and line.party_id is None:
            raise ValidationError("该科目要求填写往来单位。")
        if line.currency_id == entry.ledger.base_currency_id and (
            line.debit_original != line.debit_base or line.credit_original != line.credit_base
        ):
            raise ValidationError("本位币分录原币金额必须等于本位币金额。")
    debit = sum((line.debit_base for line in lines), Decimal(0))
    credit = sum((line.credit_base for line in lines), Decimal(0))
    if debit <= 0 or debit != credit:
        raise ValidationError("凭证借贷必须平衡且金额大于零。")
    JournalEntry.objects.filter(pk=entry.pk).update(
        status=JournalEntry.Status.POSTED,
        total_debit_base=debit,
        total_credit_base=credit,
        posted_by=actor,
        posted_at=timezone.now(),
        row_version=entry.row_version + 1,
    )
    entry.refresh_from_db()
    _emit(entry, "finance.journal.posted")
    return PostingResult(entry.pk, entry.status, debit)


@transaction.atomic
def reverse_journal(
    *, journal_id: int, target_period_id: int, voucher_no: str, entry_date: date, actor: User
) -> PostingResult:
    original = JournalEntry.objects.select_for_update().prefetch_related("lines").get(pk=journal_id)
    if original.status == JournalEntry.Status.REVERSED and hasattr(original, "reversal"):
        reversal = original.reversal
        return PostingResult(reversal.pk, reversal.status, reversal.total_debit_base)
    if original.status != JournalEntry.Status.POSTED:
        raise ValidationError("只有已过账凭证可以冲销。")
    period = FiscalPeriod.objects.get(pk=target_period_id, ledger=original.ledger)
    reversal = JournalEntry.objects.create(
        company=original.company,
        ledger=original.ledger,
        period=period,
        voucher_no=voucher_no,
        entry_type="reversal",
        entry_date=entry_date,
        description=f"冲销 {original.voucher_no}",
        source_type="journal_reversal",
        source_id=str(original.pk),
        reversal_of=original,
        status=JournalEntry.Status.APPROVED,
        approved_by=actor,
        approved_at=timezone.now(),
    )
    for line in original.lines.all():
        reversal.lines.create(
            line_no=line.line_no,
            account=line.account,
            summary=f"冲销：{line.summary}",
            currency=line.currency,
            exchange_rate=line.exchange_rate,
            debit_original=line.credit_original,
            credit_original=line.debit_original,
            debit_base=line.credit_base,
            credit_base=line.debit_base,
            party=line.party,
        )
    result = post_journal(journal_id=reversal.pk, actor=actor)
    JournalEntry.objects.filter(pk=original.pk).update(
        status=JournalEntry.Status.REVERSED, row_version=original.row_version + 1
    )
    return result


@transaction.atomic
def close_period(*, period_id: int, actor: User) -> FiscalPeriod:
    period = FiscalPeriod.objects.select_for_update().get(pk=period_id)
    if period.status == FiscalPeriod.Status.CLOSED:
        return period
    if period.journals.exclude(
        status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED]
    ).exists():
        raise ValidationError("期间仍有未过账凭证。")
    period.status = FiscalPeriod.Status.CLOSED
    period.closed_at = timezone.now()
    period.closed_by = actor
    period.row_version += 1
    period.save()
    return period


@transaction.atomic
def reopen_period(*, period_id: int, actor: User, approval_reference: str) -> FiscalPeriod:
    if not approval_reference.strip():
        raise ValidationError("重开期间必须提供审批依据。")
    period = FiscalPeriod.objects.select_for_update().get(pk=period_id)
    if period.status != FiscalPeriod.Status.CLOSED:
        raise ValidationError("只有已关闭期间可以重开。")
    period.status = FiscalPeriod.Status.REOPENED
    period.reopen_reason = approval_reference
    period.closed_at = None
    period.closed_by = actor
    period.row_version += 1
    period.save()
    return period


@transaction.atomic
def allocate(
    *, settlement_id: int, open_item_id: int, amount: Decimal, base_amount: Decimal
) -> Allocation:
    settlement = Settlement.objects.select_for_update().get(pk=settlement_id)
    item = OpenItem.objects.select_for_update().get(pk=open_item_id)
    if settlement.company_id != item.company_id or settlement.party_id != item.party_id:
        raise ValidationError("收付款与应收应付必须属于同一公司和往来单位。")
    expected = (Settlement.Kind.RECEIPT, OpenItem.Kind.RECEIVABLE)
    actual = (settlement.kind, item.kind)
    if actual not in {expected, (Settlement.Kind.PAYMENT, OpenItem.Kind.PAYABLE)}:
        raise ValidationError("收款只能核销应收，付款只能核销应付。")
    if amount <= 0 or base_amount <= 0:
        raise ValidationError("核销金额必须大于零。")
    if settlement.allocated_amount + amount > settlement.amount:
        raise ValidationError("核销金额超过收付款余额。")
    if item.allocated_amount + amount > item.original_amount:
        raise ValidationError("核销金额超过应收应付余额。")
    allocation = Allocation.objects.create(
        settlement=settlement, open_item=item, amount=amount, base_amount=base_amount
    )
    settlement.allocated_amount += amount
    settlement.row_version += 1
    settlement.save(update_fields=["allocated_amount", "row_version", "updated_at"])
    item.allocated_amount += amount
    item.allocated_base_amount += base_amount
    item.status = (
        OpenItem.Status.SETTLED
        if item.allocated_amount == item.original_amount
        else OpenItem.Status.PARTIAL
    )
    item.row_version += 1
    item.save(
        update_fields=[
            "allocated_amount",
            "allocated_base_amount",
            "status",
            "row_version",
            "updated_at",
        ]
    )
    return allocation


@transaction.atomic
def reverse_allocation(*, allocation_id: int) -> Allocation:
    original = (
        Allocation.objects.select_for_update()
        .select_related("settlement", "open_item")
        .get(pk=allocation_id)
    )
    if hasattr(original, "reversal"):
        return original.reversal
    settlement = Settlement.objects.select_for_update().get(pk=original.settlement_id)
    item = OpenItem.objects.select_for_update().get(pk=original.open_item_id)
    reversal = Allocation.objects.create(
        settlement=settlement,
        open_item=item,
        amount=-original.amount,
        base_amount=-original.base_amount,
        reversal_of=original,
    )
    settlement.allocated_amount -= original.amount
    settlement.row_version += 1
    settlement.save(update_fields=["allocated_amount", "row_version", "updated_at"])
    item.allocated_amount -= original.amount
    item.allocated_base_amount -= original.base_amount
    item.status = OpenItem.Status.OPEN if item.allocated_amount == 0 else OpenItem.Status.PARTIAL
    item.row_version += 1
    item.save(
        update_fields=[
            "allocated_amount",
            "allocated_base_amount",
            "status",
            "row_version",
            "updated_at",
        ]
    )
    return reversal


def trial_balance(*, ledger_id: int, start_date: date, end_date: date):  # type: ignore[no-untyped-def]
    from kaxi.finance.models import JournalEntryLine

    return (
        JournalEntryLine.objects.filter(
            entry__ledger_id=ledger_id,
            entry__status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED],
            entry__entry_date__range=(start_date, end_date),
        )
        .values("account_id", "account__code", "account__name")
        .annotate(debit=Sum("debit_base"), credit=Sum("credit_base"))
        .order_by("account__code")
    )


def account_ledger(
    *,
    ledger_id: int,
    account_id: int,
    start_date: date,
    end_date: date,
    party_id: int | None = None,
) -> dict[str, object]:
    from kaxi.finance.models import JournalEntryLine

    account = Account.objects.select_related("chart__ledger").get(
        pk=account_id, chart__ledger_id=ledger_id
    )
    base_filters = {
        "entry__ledger_id": ledger_id,
        "entry__status__in": [JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED],
        "account_id": account_id,
    }
    if party_id is not None:
        base_filters["party_id"] = party_id
    opening = JournalEntryLine.objects.filter(
        **base_filters, entry__entry_date__lt=start_date
    ).aggregate(
        debit=Coalesce(Sum("debit_base"), Value(0), output_field=MONEY),
        credit=Coalesce(Sum("credit_base"), Value(0), output_field=MONEY),
    )

    def signed(debit: Decimal, credit: Decimal) -> Decimal:
        return debit - credit if account.normal_balance == Account.Balance.DEBIT else credit - debit

    running = signed(opening["debit"], opening["credit"])
    rows = []
    lines = (
        JournalEntryLine.objects.filter(
            **base_filters, entry__entry_date__range=(start_date, end_date)
        )
        .select_related("entry", "currency", "party")
        .order_by("entry__entry_date", "entry__voucher_no", "line_no", "id")
    )
    period_debit = Decimal(0)
    period_credit = Decimal(0)
    for line in lines:
        period_debit += line.debit_base
        period_credit += line.credit_base
        running += signed(line.debit_base, line.credit_base)
        rows.append(
            {
                "line_id": line.pk,
                "entry_id": line.entry_id,
                "entry_date": line.entry.entry_date,
                "voucher_no": line.entry.voucher_no,
                "summary": line.summary or line.entry.description,
                "source_type": line.entry.source_type,
                "source_id": line.entry.source_id,
                "party_id": line.party_id,
                "party_name": line.party.display_name if line.party else "",
                "currency": line.currency.code,
                "exchange_rate": line.exchange_rate,
                "debit_original": line.debit_original,
                "credit_original": line.credit_original,
                "debit_base": line.debit_base,
                "credit_base": line.credit_base,
                "running_balance_base": running,
            }
        )
    return {
        "ledger_id": ledger_id,
        "account_id": account.pk,
        "account_code": account.code,
        "account_name": account.name,
        "normal_balance": account.normal_balance,
        "party_id": party_id,
        "start_date": start_date,
        "end_date": end_date,
        "opening_debit_base": opening["debit"],
        "opening_credit_base": opening["credit"],
        "opening_balance_base": signed(opening["debit"], opening["credit"]),
        "period_debit_base": period_debit,
        "period_credit_base": period_credit,
        "closing_balance_base": running,
        "rows": rows,
    }


MONEY = DecimalField(max_digits=20, decimal_places=6)


def _posted_lines(*, ledger_id: int, start_date: date | None = None, end_date: date):  # type: ignore[no-untyped-def]
    from kaxi.finance.models import JournalEntryLine

    filters = {
        "entry__ledger_id": ledger_id,
        "entry__status__in": [JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED],
        "entry__entry_date__lte": end_date,
    }
    if start_date is not None:
        filters["entry__entry_date__gte"] = start_date
    return JournalEntryLine.objects.filter(**filters)


def balance_sheet(*, ledger_id: int, as_of: date) -> dict[str, object]:
    rows = list(
        _posted_lines(ledger_id=ledger_id, end_date=as_of)
        .filter(
            account__account_type__in=[
                Account.Type.ASSET,
                Account.Type.LIABILITY,
                Account.Type.EQUITY,
            ]
        )
        .values(
            "account__account_type", "account__code", "account__name", "account__normal_balance"
        )
        .annotate(
            debit=Coalesce(Sum("debit_base"), Value(0), output_field=MONEY),
            credit=Coalesce(Sum("credit_base"), Value(0), output_field=MONEY),
        )
        .order_by("account__code")
    )
    totals = {"asset": Decimal(0), "liability": Decimal(0), "equity": Decimal(0)}
    for row in rows:
        row["balance"] = (
            row["debit"] - row["credit"]
            if row["account__normal_balance"] == Account.Balance.DEBIT
            else row["credit"] - row["debit"]
        )
        totals[row["account__account_type"]] += row["balance"]
    profit_values = (
        _posted_lines(ledger_id=ledger_id, end_date=as_of)
        .filter(account__account_type__in=[Account.Type.REVENUE, Account.Type.EXPENSE])
        .aggregate(
            revenue_credit=Coalesce(
                Sum("credit_base", filter=Q(account__account_type=Account.Type.REVENUE)),
                Value(0),
                output_field=MONEY,
            ),
            revenue_debit=Coalesce(
                Sum("debit_base", filter=Q(account__account_type=Account.Type.REVENUE)),
                Value(0),
                output_field=MONEY,
            ),
            expense_debit=Coalesce(
                Sum("debit_base", filter=Q(account__account_type=Account.Type.EXPENSE)),
                Value(0),
                output_field=MONEY,
            ),
            expense_credit=Coalesce(
                Sum("credit_base", filter=Q(account__account_type=Account.Type.EXPENSE)),
                Value(0),
                output_field=MONEY,
            ),
        )
    )
    current_profit = (
        profit_values["revenue_credit"]
        - profit_values["revenue_debit"]
        - profit_values["expense_debit"]
        + profit_values["expense_credit"]
    )
    totals["equity"] += current_profit
    return {
        "as_of": as_of,
        "rows": rows,
        "totals": totals,
        "current_profit": current_profit,
        "balanced": totals["asset"] == totals["liability"] + totals["equity"],
    }


def income_statement(*, ledger_id: int, start_date: date, end_date: date) -> dict[str, object]:
    rows = list(
        _posted_lines(ledger_id=ledger_id, start_date=start_date, end_date=end_date)
        .filter(account__account_type__in=[Account.Type.REVENUE, Account.Type.EXPENSE])
        .values("account__account_type", "account__code", "account__name")
        .annotate(
            debit=Coalesce(Sum("debit_base"), Value(0), output_field=MONEY),
            credit=Coalesce(Sum("credit_base"), Value(0), output_field=MONEY),
        )
        .order_by("account__code")
    )
    revenue = Decimal(0)
    expense = Decimal(0)
    for row in rows:
        if row["account__account_type"] == Account.Type.REVENUE:
            row["amount"] = row["credit"] - row["debit"]
            revenue += row["amount"]
        else:
            row["amount"] = row["debit"] - row["credit"]
            expense += row["amount"]
    return {
        "start_date": start_date,
        "end_date": end_date,
        "rows": rows,
        "revenue": revenue,
        "expense": expense,
        "profit": revenue - expense,
    }


def cash_flow_statement(*, ledger_id: int, start_date: date, end_date: date) -> dict[str, object]:
    categories = [
        Account.CashFlow.OPERATING,
        Account.CashFlow.INVESTING,
        Account.CashFlow.FINANCING,
    ]
    rows = list(
        _posted_lines(ledger_id=ledger_id, start_date=start_date, end_date=end_date)
        .filter(account__cash_flow_category__in=categories)
        .values("account__cash_flow_category")
        .annotate(
            inflow=Coalesce(Sum("credit_base"), Value(0), output_field=MONEY),
            outflow=Coalesce(Sum("debit_base"), Value(0), output_field=MONEY),
        )
        .annotate(net=F("inflow") - F("outflow"))
        .order_by("account__cash_flow_category")
    )
    by_category = {row["account__cash_flow_category"]: row["net"] for row in rows}
    return {
        "start_date": start_date,
        "end_date": end_date,
        "rows": rows,
        "net_cash_change": sum(by_category.values(), Decimal(0)),
    }

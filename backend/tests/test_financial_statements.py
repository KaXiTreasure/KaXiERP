from datetime import date
from decimal import Decimal

import pytest

from kaxi.finance.models import (
    Account,
    ChartOfAccounts,
    FiscalPeriod,
    JournalEntry,
    JournalEntryLine,
    Ledger,
)
from kaxi.finance.services import (
    account_ledger,
    approve_journal,
    balance_sheet,
    cash_flow_statement,
    income_statement,
    post_journal,
)
from kaxi.identity.models import User
from kaxi.master_data.models import Company, Currency

pytestmark = pytest.mark.django_db(transaction=True)


def test_three_financial_statements_derive_from_posted_entries():
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="STM", legal_name="报表测试", display_name="报表测试", base_currency=currency
    )
    actor = User.objects.create_user(username="statement", password="test", company=company)
    ledger = Ledger.objects.create(
        company=company, code="MAIN", name="主账簿", base_currency=currency
    )
    chart = ChartOfAccounts.objects.create(
        ledger=ledger, code="CAS", name="会计准则", version=1, effective_from=date(2026, 1, 1)
    )
    cash = Account.objects.create(
        chart=chart,
        code="1002",
        name="银行存款",
        account_type=Account.Type.ASSET,
        normal_balance=Account.Balance.DEBIT,
        cash_flow_category=Account.CashFlow.CASH,
    )
    revenue = Account.objects.create(
        chart=chart,
        code="6001",
        name="主营业务收入",
        account_type=Account.Type.REVENUE,
        normal_balance=Account.Balance.CREDIT,
        cash_flow_category=Account.CashFlow.OPERATING,
    )
    expense = Account.objects.create(
        chart=chart,
        code="6601",
        name="经营费用",
        account_type=Account.Type.EXPENSE,
        normal_balance=Account.Balance.DEBIT,
        cash_flow_category=Account.CashFlow.OPERATING,
    )
    period = FiscalPeriod.objects.create(
        ledger=ledger, year=2026, month=8, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )

    def post(voucher: str, debit: Account, credit: Account, amount: Decimal) -> None:
        entry = JournalEntry.objects.create(
            company=company,
            ledger=ledger,
            period=period,
            voucher_no=voucher,
            entry_date=date(2026, 8, 23),
        )
        JournalEntryLine.objects.create(
            entry=entry,
            line_no=1,
            account=debit,
            currency=currency,
            exchange_rate=1,
            debit_original=amount,
            debit_base=amount,
        )
        JournalEntryLine.objects.create(
            entry=entry,
            line_no=2,
            account=credit,
            currency=currency,
            exchange_rate=1,
            credit_original=amount,
            credit_base=amount,
        )
        approve_journal(journal_id=entry.pk, actor=actor)
        post_journal(journal_id=entry.pk, actor=actor)

    post("记-收入", cash, revenue, Decimal("100"))
    post("记-费用", expense, cash, Decimal("30"))

    income = income_statement(
        ledger_id=ledger.pk, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )
    balance = balance_sheet(ledger_id=ledger.pk, as_of=date(2026, 8, 31))
    cash_flow = cash_flow_statement(
        ledger_id=ledger.pk, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )
    detail = account_ledger(
        ledger_id=ledger.pk,
        account_id=cash.pk,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )

    assert income["revenue"] == Decimal("100")
    assert income["expense"] == Decimal("30")
    assert income["profit"] == Decimal("70")
    assert balance["totals"]["asset"] == Decimal("70")
    assert balance["current_profit"] == Decimal("70")
    assert balance["balanced"] is True
    assert cash_flow["net_cash_change"] == Decimal("70")
    assert detail["opening_balance_base"] == 0
    assert detail["period_debit_base"] == Decimal("100")
    assert detail["period_credit_base"] == Decimal("30")
    assert detail["closing_balance_base"] == Decimal("70")
    assert [row["running_balance_base"] for row in detail["rows"]] == [
        Decimal("100"),
        Decimal("70"),
    ]

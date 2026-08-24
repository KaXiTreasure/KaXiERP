from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from kaxi.finance.models import (
    Account,
    ChartOfAccounts,
    FiscalPeriod,
    JournalEntry,
    JournalEntryLine,
    Ledger,
    OpenItem,
    Settlement,
)
from kaxi.finance.services import allocate, approve_journal, post_journal, reverse_allocation
from kaxi.identity.models import User
from kaxi.master_data.models import Company, Currency, Party

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def company() -> Company:
    currency = Currency.objects.create(code="CNY", name="人民币")
    return Company.objects.create(
        company_code="FIN",
        legal_name="财务测试公司",
        display_name="财务测试",
        base_currency=currency,
    )


@pytest.fixture
def currency(company: Company) -> Currency:
    return company.base_currency


def test_posting_and_allocation_are_controlled(company: Company, currency: Currency) -> None:
    actor = User.objects.create_user(username="finance-test", password="test", company=company)
    ledger = Ledger.objects.create(
        company=company, code="MAIN", name="主账簿", base_currency=currency
    )
    chart = ChartOfAccounts.objects.create(
        ledger=ledger, code="CAS", name="企业会计准则", version=1, effective_from=date(2026, 1, 1)
    )
    cash = Account.objects.create(
        chart=chart, code="1002", name="银行存款", account_type="asset", normal_balance="debit"
    )
    ar = Account.objects.create(
        chart=chart,
        code="1122",
        name="应收账款",
        account_type="asset",
        normal_balance="debit",
        requires_party=True,
    )
    period = FiscalPeriod.objects.create(
        ledger=ledger, year=2026, month=8, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )
    entry = JournalEntry.objects.create(
        company=company,
        ledger=ledger,
        period=period,
        voucher_no="记-0001",
        entry_date=date(2026, 8, 23),
    )
    JournalEntryLine.objects.create(
        entry=entry,
        line_no=1,
        account=cash,
        currency=currency,
        exchange_rate=1,
        debit_original=100,
        debit_base=100,
    )
    party = Party.objects.create(
        company=company,
        party_no="C001",
        party_type=Party.PartyType.ORGANIZATION,
        legal_name="测试客户",
        display_name="测试客户",
        default_currency=currency,
    )
    JournalEntryLine.objects.create(
        entry=entry,
        line_no=2,
        account=ar,
        currency=currency,
        exchange_rate=1,
        credit_original=100,
        credit_base=100,
        party=party,
    )
    approve_journal(journal_id=entry.pk, actor=actor)
    result = post_journal(journal_id=entry.pk, actor=actor)
    assert result.total == Decimal("100")
    entry.refresh_from_db()
    entry.description = "tamper"
    with pytest.raises(ValidationError):
        entry.save()
    open_item = OpenItem.objects.create(
        company=company,
        kind=OpenItem.Kind.RECEIVABLE,
        item_no="AR-001",
        party=party,
        source_type="sales_order",
        source_id="1",
        currency=currency,
        exchange_rate=1,
        original_amount=100,
        base_amount=100,
        due_date=date(2026, 9, 23),
        journal=entry,
    )
    settlement = Settlement.objects.create(
        company=company,
        kind=Settlement.Kind.RECEIPT,
        settlement_no="RC-001",
        party=party,
        settlement_date=date(2026, 8, 23),
        currency=currency,
        exchange_rate=1,
        amount=100,
        base_amount=100,
        journal=entry,
    )
    allocation = allocate(
        settlement_id=settlement.pk,
        open_item_id=open_item.pk,
        amount=Decimal("40"),
        base_amount=Decimal("40"),
    )
    with pytest.raises(ValidationError):
        allocate(
            settlement_id=settlement.pk,
            open_item_id=open_item.pk,
            amount=Decimal("70"),
            base_amount=Decimal("70"),
        )
    reverse_allocation(allocation_id=allocation.pk)
    open_item.refresh_from_db()
    settlement.refresh_from_db()
    assert open_item.allocated_amount == 0
    assert settlement.allocated_amount == 0

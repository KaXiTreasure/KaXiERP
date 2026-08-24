from decimal import Decimal

from kaxi.sales.credit_services import _effective_limit
from kaxi.sales.models import CreditAccount, CreditCommitment, SalesOrderStatusHistory


def test_credit_scope_is_unique() -> None:
    names = {constraint.name for constraint in CreditAccount._meta.constraints}
    assert "sal_credit_account_scope_uniq" in names


def test_credit_commitment_is_tied_to_order() -> None:
    names = {constraint.name for constraint in CreditCommitment._meta.constraints}
    assert "sal_credit_order_uniq" in names


def test_order_status_history_is_append_only_fact_shape() -> None:
    assert SalesOrderStatusHistory._meta.db_table == "sal_order_status_history"


def test_expired_temporary_limit_is_not_counted() -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    account = CreditAccount(
        permanent_limit=Decimal("100"),
        temporary_limit=Decimal("50"),
        temporary_valid_to=now - timedelta(seconds=1),
    )
    assert _effective_limit(account, now) == Decimal("100")

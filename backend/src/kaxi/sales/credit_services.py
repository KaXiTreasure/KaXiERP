from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from kaxi.sales.models import CreditAccount, CreditCommitment, SalesOrder
from kaxi.shared.outbox_service import append_outbox_event


class CreditLimitExceededError(ValueError):
    pass


@dataclass(frozen=True)
class CreditResult:
    commitment_id: int
    amount: Decimal
    repeated: bool


def _effective_limit(account: CreditAccount, at: datetime) -> Decimal:
    temporary = (
        account.temporary_limit
        if account.temporary_valid_to is not None and account.temporary_valid_to > at
        else Decimal(0)
    )
    return account.permanent_limit + temporary


@transaction.atomic
def commit_credit(
    *,
    account_id: int,
    order: SalesOrder,
    amount: Decimal,
    at: datetime,
    approval_id: int | None = None,
) -> CreditResult:
    if amount <= 0:
        raise ValueError("授信占用金额必须大于零")
    account = CreditAccount.objects.select_for_update().select_related("company").get(pk=account_id)
    existing = CreditCommitment.objects.filter(account=account, order=order).first()
    if existing is not None:
        return CreditResult(existing.pk, existing.amount, True)
    if (
        account.company_id != order.company_id
        or account.customer_id != order.customer_id
        or account.currency_id != order.currency_id
    ):
        raise ValueError("授信账户与订单主体、客户或币种不一致")
    if account.status != CreditAccount.Status.ACTIVE:
        raise CreditLimitExceededError("授信账户不可用")
    exposure = account.committed_amount + account.receivable_amount + amount
    if exposure > _effective_limit(account, at) and approval_id is None:
        raise CreditLimitExceededError("可用授信不足且没有批准例外")
    account.committed_amount += amount
    account.row_version += 1
    account.save(update_fields=["committed_amount", "row_version", "updated_at"])
    commitment = CreditCommitment.objects.create(
        account=account, order=order, amount=amount, approval_id=approval_id
    )
    append_outbox_event(
        company=account.company,
        aggregate_type="credit_account",
        aggregate_id=str(account.pk),
        aggregate_version=account.row_version,
        event_type="CREDIT_COMMITTED",
        payload={"order_id": order.pk, "amount": str(amount)},
    )
    return CreditResult(commitment.pk, amount, False)


@transaction.atomic
def release_credit(*, commitment_id: int, amount: Decimal) -> CreditResult:
    if amount <= 0:
        raise ValueError("授信释放金额必须大于零")
    commitment = (
        CreditCommitment.objects.select_for_update()
        .select_related("account__company")
        .get(pk=commitment_id)
    )
    account = CreditAccount.objects.select_for_update().get(pk=commitment.account_id)
    remaining = commitment.amount - commitment.released_amount - commitment.converted_amount
    if amount > remaining:
        raise ValueError("授信释放金额超过有效占用")
    commitment.released_amount += amount
    if commitment.released_amount + commitment.converted_amount == commitment.amount:
        commitment.status = CreditCommitment.Status.RELEASED
    commitment.row_version += 1
    commitment.save(update_fields=["released_amount", "status", "row_version", "updated_at"])
    account.committed_amount -= amount
    account.row_version += 1
    account.save(update_fields=["committed_amount", "row_version", "updated_at"])
    append_outbox_event(
        company=commitment.account.company,
        aggregate_type="credit_account",
        aggregate_id=str(account.pk),
        aggregate_version=account.row_version,
        event_type="CREDIT_RELEASED",
        payload={"order_id": commitment.order_id, "amount": str(amount)},
    )
    return CreditResult(commitment.pk, amount, False)

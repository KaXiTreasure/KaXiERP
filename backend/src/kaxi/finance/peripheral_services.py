from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum

from kaxi.finance.models import (
    DepreciationEntry,
    ExpenseClaim,
    FiscalPeriod,
    FixedAsset,
    JournalEntry,
    PayrollRun,
    TaxInvoice,
)
from kaxi.identity.models import User


def _posted(journal: JournalEntry | None) -> bool:
    return journal is not None and journal.status == JournalEntry.Status.POSTED


@transaction.atomic
def transition_expense(*, claim_id: int, target: str, actor: User) -> ExpenseClaim:
    claim = ExpenseClaim.objects.select_for_update().get(pk=claim_id)
    allowed = {
        (ExpenseClaim.Status.DRAFT, ExpenseClaim.Status.SUBMITTED),
        (ExpenseClaim.Status.SUBMITTED, ExpenseClaim.Status.APPROVED),
        (ExpenseClaim.Status.SUBMITTED, ExpenseClaim.Status.REJECTED),
        (ExpenseClaim.Status.APPROVED, ExpenseClaim.Status.POSTED),
        (ExpenseClaim.Status.POSTED, ExpenseClaim.Status.PAID),
    }
    if (claim.status, target) not in allowed:
        raise ValidationError("费用报销状态转换无效。")
    if target in {ExpenseClaim.Status.APPROVED, ExpenseClaim.Status.REJECTED}:
        if claim.claimant_id == actor.pk:
            raise PermissionDenied("报销申请人与审批人必须分离。")
        claim.approved_by = actor
    if target in {ExpenseClaim.Status.POSTED, ExpenseClaim.Status.PAID} and not _posted(
        claim.journal
    ):
        raise ValidationError("报销入账或支付前必须关联已过账凭证。")
    claim.status = target
    claim.row_version += 1
    claim.save()
    return claim


@transaction.atomic
def activate_asset(*, asset_id: int) -> FixedAsset:
    asset = FixedAsset.objects.select_for_update().get(pk=asset_id)
    if asset.status != FixedAsset.Status.DRAFT:
        raise ValidationError("只有草稿资产可以启用。")
    asset.status = FixedAsset.Status.ACTIVE
    asset.row_version += 1
    asset.save()
    return asset


@transaction.atomic
def depreciate_asset(
    *, asset_id: int, period_id: int, amount: Decimal, journal_id: int
) -> DepreciationEntry:
    asset = FixedAsset.objects.select_for_update().get(pk=asset_id)
    period = FiscalPeriod.objects.get(pk=period_id, ledger__company=asset.company)
    journal = JournalEntry.objects.get(pk=journal_id, company=asset.company, period=period)
    depreciable = asset.original_cost - asset.residual_value - asset.accumulated_depreciation
    if asset.status != FixedAsset.Status.ACTIVE or amount <= 0 or amount > depreciable:
        raise ValidationError("折旧金额或资产状态无效。")
    if not _posted(journal):
        raise ValidationError("折旧必须关联已过账凭证。")
    entry = DepreciationEntry.objects.create(
        asset=asset, period=period, amount=amount, journal=journal
    )
    asset.accumulated_depreciation += amount
    if asset.accumulated_depreciation == asset.original_cost - asset.residual_value:
        asset.status = FixedAsset.Status.FULLY_DEPRECIATED
    asset.row_version += 1
    asset.save()
    return entry


@transaction.atomic
def dispose_asset(*, asset_id: int, disposal_date: date, proceeds: Decimal) -> FixedAsset:
    asset = FixedAsset.objects.select_for_update().get(pk=asset_id)
    if asset.status not in {FixedAsset.Status.ACTIVE, FixedAsset.Status.FULLY_DEPRECIATED}:
        raise ValidationError("当前资产不可处置。")
    if proceeds < 0:
        raise ValidationError("处置收入不能为负数。")
    asset.status = FixedAsset.Status.DISPOSED
    asset.disposal_date = disposal_date
    asset.disposal_proceeds = proceeds
    asset.row_version += 1
    asset.save()
    return asset


@transaction.atomic
def calculate_payroll(*, payroll_id: int, actor: User) -> PayrollRun:
    payroll = PayrollRun.objects.select_for_update().get(pk=payroll_id)
    if payroll.status != PayrollRun.Status.DRAFT or not payroll.lines.exists():
        raise ValidationError("工资批次必须为草稿且包含明细。")
    totals = payroll.lines.aggregate(
        gross=Sum("gross_amount"), deductions=Sum("deduction_amount"), net=Sum("net_amount")
    )
    payroll.gross_amount = totals["gross"] or Decimal(0)
    payroll.deduction_amount = totals["deductions"] or Decimal(0)
    payroll.net_amount = totals["net"] or Decimal(0)
    payroll.calculated_by = actor
    payroll.status = PayrollRun.Status.CALCULATED
    payroll.row_version += 1
    payroll.save()
    return payroll


@transaction.atomic
def transition_payroll(*, payroll_id: int, target: str, actor: User) -> PayrollRun:
    payroll = PayrollRun.objects.select_for_update().get(pk=payroll_id)
    allowed = {
        (PayrollRun.Status.CALCULATED, PayrollRun.Status.APPROVED),
        (PayrollRun.Status.APPROVED, PayrollRun.Status.POSTED),
        (PayrollRun.Status.POSTED, PayrollRun.Status.PAID),
    }
    if (payroll.status, target) not in allowed:
        raise ValidationError("工资批次状态转换无效。")
    if target == PayrollRun.Status.APPROVED:
        if payroll.calculated_by_id == actor.pk:
            raise PermissionDenied("工资计算人与审批人必须分离。")
        payroll.approved_by = actor
    if target in {PayrollRun.Status.POSTED, PayrollRun.Status.PAID} and not _posted(
        payroll.journal
    ):
        raise ValidationError("工资计提或发放前必须关联已过账凭证。")
    payroll.status = target
    payroll.row_version += 1
    payroll.save()
    return payroll


@transaction.atomic
def transition_tax_invoice(*, invoice_id: int, target: str, actor: User) -> TaxInvoice:
    invoice = TaxInvoice.objects.select_for_update().get(pk=invoice_id)
    allowed = {
        (TaxInvoice.Status.DRAFT, TaxInvoice.Status.VERIFIED),
        (TaxInvoice.Status.DRAFT, TaxInvoice.Status.VOID),
        (TaxInvoice.Status.VERIFIED, TaxInvoice.Status.POSTED),
        (TaxInvoice.Status.VERIFIED, TaxInvoice.Status.VOID),
    }
    if (invoice.status, target) not in allowed:
        raise ValidationError("税务发票状态转换无效。")
    if target == TaxInvoice.Status.VERIFIED:
        invoice.verified_by = actor
    if target == TaxInvoice.Status.POSTED and not _posted(invoice.journal):
        raise ValidationError("税务发票入账必须关联已过账凭证。")
    invoice.status = target
    invoice.row_version += 1
    invoice.save()
    return invoice

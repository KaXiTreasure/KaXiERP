from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from kaxi.aftersales.models import (
    AfterSalesCase,
    AfterSalesLine,
    Refund,
    ReturnReceipt,
    ReturnReceiptLine,
)
from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance
from kaxi.inventory.services import adjust_on_hand
from kaxi.sales.models import SalesOrderLine
from kaxi.shared.outbox_service import append_outbox_event


@dataclass(frozen=True)
class ReturnLineInput:
    aftersales_line_id: int
    received_qty: Decimal
    accepted_qty: Decimal
    rejected_qty: Decimal
    accepted_balance_id: int | None = None
    exception_balance_id: int | None = None


def _emit(case: AfterSalesCase, event_type: str) -> None:
    append_outbox_event(
        company=case.company,
        aggregate_type="sales.aftersales",
        aggregate_id=str(case.pk),
        aggregate_version=case.version_no,
        event_type=event_type,
        payload={"case_id": case.pk, "case_no": case.case_no, "case_type": case.case_type},
    )


@transaction.atomic
def submit_case(*, case_id: int) -> AfterSalesCase:
    case = AfterSalesCase.objects.select_for_update().prefetch_related("lines").get(pk=case_id)
    if case.status != AfterSalesCase.Status.DRAFT or not case.lines.exists():
        raise ValidationError("只有包含明细的草稿售后单可以提交。")
    for line in case.lines.select_related("sales_order_line"):
        if line.sales_order_line.order_id != case.sales_order_id:
            raise ValidationError("售后行不属于原销售订单。")
        available = line.sales_order_line.shipped_qty - line.sales_order_line.returned_qty
        if line.requested_qty > available:
            raise ValidationError("售后申请数量超过已发货未退数量。")
    case.status = AfterSalesCase.Status.PENDING_APPROVAL
    case.version_no += 1
    case.row_version += 1
    case.save()
    _emit(case, "sales.aftersales.submitted")
    return case


@transaction.atomic
def approve_case(*, case_id: int, actor: User, approved: bool, reason: str = "") -> AfterSalesCase:
    case = AfterSalesCase.objects.select_for_update().get(pk=case_id)
    if case.status != AfterSalesCase.Status.PENDING_APPROVAL:
        raise ValidationError("售后单不在待审批状态。")
    if case.requested_by_id == actor.pk:
        raise ValidationError("售后申请人与审批人必须分离。")
    if not approved and not reason.strip():
        raise ValidationError("拒绝售后必须填写原因。")
    case.status = AfterSalesCase.Status.APPROVED if approved else AfterSalesCase.Status.REJECTED
    case.approved_by = actor
    case.approved_at = timezone.now()
    case.version_no += 1
    case.row_version += 1
    case.save()
    _emit(case, f"sales.aftersales.{case.status}")
    return case


def _validate_balance(balance: InventoryBalance, line: AfterSalesLine) -> None:
    if balance.company_id != line.case.company_id or balance.sku_id != line.sales_order_line.sku_id:
        raise ValidationError("退货库存余额与公司或 SKU 不匹配。")


@transaction.atomic
def receive_return(
    *,
    case_id: int,
    receipt_no: str,
    idempotency_key: str,
    actor: User,
    lines: list[ReturnLineInput],
) -> ReturnReceipt:
    existing = ReturnReceipt.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    case = AfterSalesCase.objects.select_for_update().get(pk=case_id)
    if case.status != AfterSalesCase.Status.APPROVED or case.case_type not in {
        AfterSalesCase.Type.RETURN,
        AfterSalesCase.Type.EXCHANGE,
    }:
        raise ValidationError("当前售后单不能接收退货。")
    receipt = ReturnReceipt.objects.create(
        case=case,
        receipt_no=receipt_no,
        received_at=timezone.now(),
        received_by=actor,
        idempotency_key=idempotency_key,
    )
    expected_ids = set(case.lines.values_list("id", flat=True))
    if {item.aftersales_line_id for item in lines} != expected_ids:
        raise ValidationError("退货验收必须一次提交全部售后行。")
    for item in lines:
        line = (
            AfterSalesLine.objects.select_for_update()
            .select_related("case", "sales_order_line")
            .get(pk=item.aftersales_line_id)
        )
        if (
            item.received_qty <= 0
            or item.received_qty > line.requested_qty
            or item.accepted_qty + item.rejected_qty != item.received_qty
        ):
            raise ValidationError("退货收货、合格与异常数量不平衡。")
        accepted_balance = None
        exception_balance = None
        if item.accepted_qty:
            if not item.accepted_balance_id:
                raise ValidationError("合格退货必须指定可售库存余额。")
            accepted_balance = InventoryBalance.objects.select_for_update().get(
                pk=item.accepted_balance_id
            )
            _validate_balance(accepted_balance, line)
            adjust_on_hand(
                balance_id=accepted_balance.pk,
                quantity_delta=item.accepted_qty,
                transaction_type="sales_return_accepted",
                reference_type="aftersales_case",
                reference_id=case.pk,
                reference_no=case.case_no,
                idempotency_key=f"{idempotency_key}:accepted:{line.pk}",
                operator=actor,
                occurred_at=receipt.received_at,
            )
        if item.rejected_qty:
            if not item.exception_balance_id:
                raise ValidationError("异常退货必须指定异常库存余额。")
            exception_balance = InventoryBalance.objects.select_for_update().get(
                pk=item.exception_balance_id
            )
            _validate_balance(exception_balance, line)
            adjust_on_hand(
                balance_id=exception_balance.pk,
                quantity_delta=item.rejected_qty,
                transaction_type="sales_return_exception",
                reference_type="aftersales_case",
                reference_id=case.pk,
                reference_no=case.case_no,
                idempotency_key=f"{idempotency_key}:exception:{line.pk}",
                operator=actor,
                occurred_at=receipt.received_at,
            )
        ReturnReceiptLine.objects.create(
            receipt=receipt,
            aftersales_line=line,
            received_qty=item.received_qty,
            accepted_qty=item.accepted_qty,
            rejected_qty=item.rejected_qty,
            accepted_balance=accepted_balance,
            exception_balance=exception_balance,
        )
        line.received_qty = item.received_qty
        line.accepted_qty = item.accepted_qty
        line.rejected_qty = item.rejected_qty
        line.row_version += 1
        line.save()
        sales_line = SalesOrderLine.objects.select_for_update().get(pk=line.sales_order_line_id)
        sales_line.returned_qty += item.received_qty
        sales_line.row_version += 1
        sales_line.save(update_fields=["returned_qty", "row_version", "updated_at"])
    case.status = AfterSalesCase.Status.PROCESSING
    case.version_no += 1
    case.row_version += 1
    case.save()
    _emit(case, "sales.aftersales.return_received")
    return receipt


@transaction.atomic
def mark_refund_paid(*, refund_id: int, external_refund_id: str) -> Refund:
    refund = Refund.objects.select_for_update().select_related("case__company").get(pk=refund_id)
    if refund.status != Refund.Status.APPROVED or not external_refund_id.strip():
        raise ValidationError("退款未批准或缺少外部退款流水号。")
    if Refund.objects.exclude(pk=refund.pk).filter(external_refund_id=external_refund_id).exists():
        raise ValidationError("外部退款流水号已使用。")
    refund.status = Refund.Status.PAID
    refund.external_refund_id = external_refund_id
    refund.row_version += 1
    refund.save()
    _emit(refund.case, "sales.aftersales.refund_paid")
    return refund


@transaction.atomic
def approve_refund(*, refund_id: int, actor: User) -> Refund:
    refund = Refund.objects.select_for_update().select_related("case").get(pk=refund_id)
    if refund.status != Refund.Status.PENDING:
        raise ValidationError("只有待退款记录可以批准。")
    if refund.case.requested_by_id == actor.pk:
        raise ValidationError("退款申请人与批准人必须分离。")
    if refund.case.status not in {
        AfterSalesCase.Status.APPROVED,
        AfterSalesCase.Status.PROCESSING,
    }:
        raise ValidationError("关联售后单尚未批准。")
    refund.status = Refund.Status.APPROVED
    refund.row_version += 1
    refund.save(update_fields=["status", "row_version", "updated_at"])
    _emit(refund.case, "sales.aftersales.refund_approved")
    return refund


@transaction.atomic
def complete_case(*, case_id: int) -> AfterSalesCase:
    case = AfterSalesCase.objects.select_for_update().get(pk=case_id)
    if case.status not in {AfterSalesCase.Status.APPROVED, AfterSalesCase.Status.PROCESSING}:
        raise ValidationError("售后单尚不能完成。")
    if case.refunds.exclude(status=Refund.Status.PAID).exists():
        raise ValidationError("仍有未完成退款。")
    case.status = AfterSalesCase.Status.COMPLETED
    case.completed_at = timezone.now()
    case.version_no += 1
    case.row_version += 1
    case.save()
    _emit(case, "sales.aftersales.completed")
    return case

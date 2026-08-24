from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from kaxi.finance.models import CostRecord, InventoryCostBalance, SerialCost
from kaxi.master_data.models import Company, Currency
from kaxi.products.models import ProductSerial, ProductSku
from kaxi.warehouse.models import Warehouse


@dataclass(frozen=True)
class CostingResult:
    record_id: int
    quantity_after: Decimal
    total_cost_after: Decimal
    average_unit_cost: Decimal


def _locked_balance(
    *, company: Company, sku: ProductSku, warehouse: Warehouse
) -> InventoryCostBalance:
    with suppress(IntegrityError):
        InventoryCostBalance.objects.get_or_create(company=company, sku=sku, warehouse=warehouse)
    return InventoryCostBalance.objects.select_for_update().get(
        company=company, sku=sku, warehouse=warehouse
    )


@transaction.atomic
def receive_weighted_cost(
    *,
    company_id: int,
    sku_id: int,
    warehouse_id: int,
    quantity: Decimal,
    original_total_cost: Decimal,
    currency_id: int,
    exchange_rate: Decimal,
    source_type: str,
    source_id: str,
    cost_record_no: str,
    idempotency_key: str,
    effective_date: date,
    category: str = CostRecord.Category.PURCHASE,
) -> CostingResult:
    existing = CostRecord.objects.filter(
        company_id=company_id, idempotency_key=idempotency_key
    ).first()
    if existing:
        balance = InventoryCostBalance.objects.get(
            company_id=company_id, sku_id=sku_id, warehouse_id=warehouse_id
        )
        return CostingResult(
            existing.pk, balance.quantity, balance.total_cost_base, balance.average_unit_cost_base
        )
    if quantity <= 0 or original_total_cost <= 0 or exchange_rate <= 0:
        raise ValidationError("入库成本数量、金额或汇率无效。")
    company = Company.objects.get(pk=company_id)
    sku = ProductSku.objects.get(pk=sku_id)
    warehouse = Warehouse.objects.get(pk=warehouse_id)
    currency = Currency.objects.get(pk=currency_id)
    if sku.company_id != company.pk or warehouse.company_id != company.pk:
        raise ValidationError("成本对象不属于当前公司。")
    base_cost = original_total_cost * exchange_rate
    balance = _locked_balance(company=company, sku=sku, warehouse=warehouse)
    balance.quantity += quantity
    balance.total_cost_base += base_cost
    balance.average_unit_cost_base = balance.total_cost_base / balance.quantity
    balance.row_version += 1
    balance.save()
    record = CostRecord.objects.create(
        company=company,
        cost_record_no=cost_record_no,
        object_type="inventory",
        object_id=f"{sku_id}:{warehouse_id}",
        category=category,
        quantity=quantity,
        unit_cost=original_total_cost / quantity,
        total_cost=original_total_cost,
        currency=currency,
        exchange_rate=exchange_rate,
        base_total_cost=base_cost,
        source_type=source_type,
        source_id=source_id,
        effective_date=effective_date,
        idempotency_key=idempotency_key,
    )
    return CostingResult(
        record.pk, balance.quantity, balance.total_cost_base, balance.average_unit_cost_base
    )


@transaction.atomic
def issue_weighted_cost(
    *,
    company_id: int,
    sku_id: int,
    warehouse_id: int,
    quantity: Decimal,
    source_type: str,
    source_id: str,
    cost_record_no: str,
    idempotency_key: str,
    effective_date: date,
) -> CostingResult:
    existing = CostRecord.objects.filter(
        company_id=company_id, idempotency_key=idempotency_key
    ).first()
    balance = InventoryCostBalance.objects.select_for_update().get(
        company_id=company_id, sku_id=sku_id, warehouse_id=warehouse_id
    )
    if existing:
        return CostingResult(
            existing.pk, balance.quantity, balance.total_cost_base, balance.average_unit_cost_base
        )
    if quantity <= 0 or quantity > balance.quantity:
        raise ValidationError("出库成本数量超过成本库存。")
    unit_cost = balance.average_unit_cost_base
    base_cost = unit_cost * quantity
    balance.quantity -= quantity
    balance.total_cost_base -= base_cost
    if balance.quantity == 0:
        balance.total_cost_base = Decimal(0)
        balance.average_unit_cost_base = Decimal(0)
    balance.row_version += 1
    balance.save()
    company = Company.objects.get(pk=company_id)
    record = CostRecord.objects.create(
        company=company,
        cost_record_no=cost_record_no,
        object_type="inventory",
        object_id=f"{sku_id}:{warehouse_id}",
        category=CostRecord.Category.COGS,
        quantity=-quantity,
        unit_cost=unit_cost,
        total_cost=-base_cost,
        currency=company.base_currency,
        exchange_rate=1,
        base_total_cost=-base_cost,
        source_type=source_type,
        source_id=source_id,
        effective_date=effective_date,
        idempotency_key=idempotency_key,
    )
    return CostingResult(
        record.pk, balance.quantity, balance.total_cost_base, balance.average_unit_cost_base
    )


@transaction.atomic
def assign_serial_cost(
    *,
    serial_id: int,
    currency_id: int,
    original_cost: Decimal,
    exchange_rate: Decimal,
    source_type: str,
    source_id: str,
) -> SerialCost:
    serial = ProductSerial.objects.select_for_update().get(pk=serial_id)
    if hasattr(serial, "cost"):
        raise ValidationError("单件编号已经具有个别成本，不得覆盖。")
    if original_cost < 0 or exchange_rate <= 0:
        raise ValidationError("单件成本或汇率无效。")
    return SerialCost.objects.create(
        serial=serial,
        company=serial.company,
        currency_id=currency_id,
        original_cost=original_cost,
        exchange_rate=exchange_rate,
        base_cost=original_cost * exchange_rate,
        source_type=source_type,
        source_id=source_id,
    )


@transaction.atomic
def reverse_cost_record(
    *, record_id: int, cost_record_no: str, idempotency_key: str, effective_date: date
) -> CostRecord:
    original = CostRecord.objects.select_for_update().get(pk=record_id)
    if hasattr(original, "reversal"):
        return original.reversal
    return CostRecord.objects.create(
        company=original.company,
        cost_record_no=cost_record_no,
        object_type=original.object_type,
        object_id=original.object_id,
        category=original.category,
        quantity=-original.quantity,
        unit_cost=original.unit_cost,
        total_cost=-original.total_cost,
        currency=original.currency,
        exchange_rate=original.exchange_rate,
        base_total_cost=-original.base_total_cost,
        source_type="cost_reversal",
        source_id=str(original.pk),
        effective_date=effective_date,
        idempotency_key=idempotency_key,
        reversal_of=original,
    )

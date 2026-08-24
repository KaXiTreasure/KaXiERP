import csv
import hashlib
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from kaxi.identity.models import User
from kaxi.inventory.models import InventoryBalance, InventoryLot, InventoryStatus
from kaxi.inventory.services import adjust_on_hand
from kaxi.master_data.models import Currency, Party, Region, UnitOfMeasure
from kaxi.products.models import ProductSku, ProductSpu
from kaxi.system.models import DataImportBatch, DataImportRow
from kaxi.warehouse.models import Warehouse, WarehouseLocation

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000
REQUIRED_HEADERS = {
    DataImportBatch.Entity.PARTY: {"party_no", "party_type", "legal_name", "display_name"},
    DataImportBatch.Entity.SKU: {"sku_code", "spu_code", "name_zh", "base_uom_code"},
    DataImportBatch.Entity.OPENING_INVENTORY: {
        "reference_no",
        "sku_code",
        "warehouse_code",
        "location_code",
        "status_code",
        "quantity",
        "occurred_at",
    },
}


@transaction.atomic
def stage_csv(
    *, company_id: int, entity_type: str, filename: str, content: bytes, actor: User
) -> DataImportBatch:
    if entity_type not in DataImportBatch.Entity.values:
        raise ValidationError("不支持的导入实体类型。")
    if not content or len(content) > MAX_IMPORT_BYTES:
        raise ValidationError("导入文件为空或超过 5 MiB。")
    digest = hashlib.sha256(content).hexdigest()
    existing = DataImportBatch.objects.filter(
        company_id=company_id, entity_type=entity_type, source_sha256=digest
    ).first()
    if existing is not None:
        return existing
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV 必须使用 UTF-8 编码。") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_HEADERS[entity_type] - headers
    if missing:
        raise ValidationError(f"CSV 缺少字段：{', '.join(sorted(missing))}")
    rows = list(reader)
    if not rows or len(rows) > MAX_IMPORT_ROWS:
        raise ValidationError("导入行数必须为 1 至 10000。")
    batch = DataImportBatch.objects.create(
        company_id=company_id,
        batch_no=f"IMP-{timezone.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
        entity_type=entity_type,
        source_filename=filename,
        source_sha256=digest,
        total_rows=len(rows),
        requested_by=actor,
    )
    DataImportRow.objects.bulk_create(
        [
            DataImportRow(batch=batch, row_number=index, source_data=dict(row))
            for index, row in enumerate(rows, start=2)
        ]
    )
    return batch


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "是"}:
        return True
    if normalized in {"0", "false", "no", "n", "否", ""}:
        return False
    raise ValueError("布尔值无效")


def _validate_party(batch: DataImportBatch, source: dict[str, str]) -> dict[str, object]:
    party_type = source["party_type"].strip().lower()
    if party_type not in Party.PartyType.values:
        raise ValueError("party_type 必须为 organization 或 person")
    currency_code = source.get("default_currency_code", "").strip()
    region_code = source.get("country_region_code", "").strip()
    return {
        "party_no": source["party_no"].strip(),
        "party_type": party_type,
        "legal_name": source["legal_name"].strip(),
        "display_name": source["display_name"].strip(),
        "country_region_id": Region.objects.get(region_code=region_code).pk
        if region_code
        else None,
        "default_language": source.get("default_language", "").strip(),
        "default_currency_id": Currency.objects.get(code=currency_code).pk
        if currency_code
        else None,
        "status": source.get("status", Party.Status.DRAFT).strip() or Party.Status.DRAFT,
        "risk_level": source.get("risk_level", "").strip(),
    }


def _validate_sku(batch: DataImportBatch, source: dict[str, str]) -> dict[str, object]:
    spu = ProductSpu.objects.get(company=batch.company, spu_code=source["spu_code"].strip())
    uom = UnitOfMeasure.objects.get(uom_code=source["base_uom_code"].strip())
    serialized = _boolean(source.get("is_serialized", ""))
    limited = _boolean(source.get("is_limited_edition", ""))
    if limited and not serialized:
        raise ValueError("限量 SKU 必须启用单件追踪")
    return {
        "sku_code": source["sku_code"].strip(),
        "spu_id": spu.pk,
        "name_zh": source["name_zh"].strip(),
        "name_en": source.get("name_en", "").strip(),
        "base_uom_id": uom.pk,
        "is_serialized": serialized,
        "is_limited_edition": limited,
        "is_lot_tracked": _boolean(source.get("is_lot_tracked", "")),
        "allow_oversell": _boolean(source.get("allow_oversell", "")),
        "status": source.get("status", ProductSku.Status.DRAFT).strip() or ProductSku.Status.DRAFT,
    }


def _validate_inventory(batch: DataImportBatch, source: dict[str, str]) -> dict[str, object]:
    sku = ProductSku.objects.get(company=batch.company, sku_code=source["sku_code"].strip())
    warehouse = Warehouse.objects.get(
        company=batch.company, warehouse_code=source["warehouse_code"].strip()
    )
    location = WarehouseLocation.objects.get(
        warehouse=warehouse, location_code=source["location_code"].strip()
    )
    inventory_status = InventoryStatus.objects.get(
        company=batch.company, status_code=source["status_code"].strip()
    )
    quantity = Decimal(source["quantity"])
    occurred_at = parse_datetime(source["occurred_at"])
    if quantity < 0 or occurred_at is None:
        raise ValueError("期初数量不能为负，occurred_at 必须为 ISO 8601 时间")
    return {
        "reference_no": source["reference_no"].strip(),
        "sku_id": sku.pk,
        "warehouse_id": warehouse.pk,
        "location_id": location.pk,
        "inventory_status_id": inventory_status.pk,
        "quantity": str(quantity),
        "occurred_at": occurred_at.isoformat(),
    }


@transaction.atomic
def validate_batch(*, batch_id: int) -> DataImportBatch:
    batch = DataImportBatch.objects.select_for_update().get(pk=batch_id)
    if batch.status == DataImportBatch.Status.COMMITTED:
        return batch
    validators = {
        DataImportBatch.Entity.PARTY: _validate_party,
        DataImportBatch.Entity.SKU: _validate_sku,
        DataImportBatch.Entity.OPENING_INVENTORY: _validate_inventory,
    }
    valid = 0
    for row in batch.rows.order_by("row_number"):
        try:
            normalized = validators[batch.entity_type](batch, row.source_data)
            if not all(
                str(normalized.get(key, "")).strip()
                for key in REQUIRED_HEADERS[batch.entity_type]
                if key in normalized
            ):
                raise ValueError("必填字段不能为空")
            row.normalized_data = normalized
            row.status = DataImportRow.Status.VALID
            row.errors = []
            valid += 1
        except (
            ValueError,
            InvalidOperation,
            Currency.DoesNotExist,
            Region.DoesNotExist,
            UnitOfMeasure.DoesNotExist,
            ProductSpu.DoesNotExist,
            ProductSku.DoesNotExist,
            Warehouse.DoesNotExist,
            WarehouseLocation.DoesNotExist,
            InventoryStatus.DoesNotExist,
        ) as exc:
            row.normalized_data = {}
            row.status = DataImportRow.Status.INVALID
            row.errors = [str(exc)]
        row.save()
    batch.valid_rows = valid
    batch.invalid_rows = batch.total_rows - valid
    batch.status = (
        DataImportBatch.Status.VALIDATED
        if batch.invalid_rows == 0
        else DataImportBatch.Status.INVALID
    )
    batch.row_version += 1
    batch.save()
    return batch


@transaction.atomic
def commit_batch(*, batch_id: int, actor: User) -> DataImportBatch:
    batch = DataImportBatch.objects.select_for_update().get(pk=batch_id)
    if batch.status == DataImportBatch.Status.COMMITTED:
        return batch
    if batch.status != DataImportBatch.Status.VALIDATED or batch.invalid_rows:
        raise ValidationError("导入批次必须全部校验通过后才能提交。")
    for row in batch.rows.select_for_update().order_by("row_number"):
        data = row.normalized_data
        if batch.entity_type == DataImportBatch.Entity.PARTY:
            target = Party.objects.create(company=batch.company, **data)
        elif batch.entity_type == DataImportBatch.Entity.SKU:
            target = ProductSku.objects.create(company=batch.company, **data)
        else:
            lot, _ = InventoryLot.objects.get_or_create(
                company=batch.company,
                sku_id=data["sku_id"],
                lot_no="NO-LOT",
                defaults={"is_no_lot_sentinel": True},
            )
            balance, _ = InventoryBalance.objects.get_or_create(
                company=batch.company,
                sku_id=data["sku_id"],
                warehouse_id=data["warehouse_id"],
                location_id=data["location_id"],
                inventory_status_id=data["inventory_status_id"],
                lot=lot,
            )
            adjust_on_hand(
                balance_id=balance.pk,
                quantity_delta=Decimal(data["quantity"]),
                transaction_type="opening",
                reference_type="data_import_row",
                reference_id=row.pk,
                reference_no=data["reference_no"],
                idempotency_key=f"import:{batch.pk}:{row.row_number}",
                operator=actor,
                occurred_at=datetime.fromisoformat(data["occurred_at"]),
            )
            target = balance
        row.target_id = target.pk
        row.status = DataImportRow.Status.COMMITTED
        row.save()
    batch.status = DataImportBatch.Status.COMMITTED
    batch.committed_at = timezone.now()
    batch.row_version += 1
    batch.save()
    return batch

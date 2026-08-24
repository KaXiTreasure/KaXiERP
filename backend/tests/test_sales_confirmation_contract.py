from decimal import Decimal

from kaxi.sales.models import SalesOrder, SalesOrderConfirmation, SalesOrderLine
from kaxi.sales.services import _target_status


def test_confirmation_has_idempotency_constraint() -> None:
    names = {constraint.name for constraint in SalesOrderConfirmation._meta.constraints}
    assert "sal_confirmation_company_idem_uniq" in names


def test_confirmation_status_reflects_allocation_progress() -> None:
    lines = [
        SalesOrderLine(ordered_qty=Decimal("2"), reserved_qty=Decimal("2")),
        SalesOrderLine(ordered_qty=Decimal("1"), reserved_qty=Decimal("1")),
    ]
    assert _target_status(lines) == SalesOrder.Status.ALLOCATED
    lines[1].reserved_qty = Decimal("0")
    assert _target_status(lines) == SalesOrder.Status.ALLOCATING


def test_line_contains_frozen_price_snapshot_fields() -> None:
    names = {field.name for field in SalesOrderLine._meta.fields}
    assert {"unit_price", "line_total", "price_source", "price_snapshot"} <= names

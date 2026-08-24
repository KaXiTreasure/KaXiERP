from decimal import Decimal

import pytest

from kaxi.inventory.models import InventoryBalance, InventoryLedger


def test_inventory_balance_has_complete_unique_dimension() -> None:
    names = {constraint.name for constraint in InventoryBalance._meta.constraints}
    assert "inv_balance_dimension_uniq" in names


def test_physical_free_quantity_is_derived() -> None:
    balance = InventoryBalance(
        on_hand_qty=Decimal("10"), reserved_qty=Decimal("3"), locked_qty=Decimal("2")
    )
    assert balance.physical_free_qty == Decimal("5")


def test_inventory_ledger_is_immutable_after_creation() -> None:
    ledger = InventoryLedger(id=1)
    with pytest.raises(RuntimeError, match="只允许追加"):
        ledger.save()
    with pytest.raises(RuntimeError, match="只允许追加"):
        ledger.delete()

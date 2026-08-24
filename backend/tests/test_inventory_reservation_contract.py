from decimal import Decimal

from kaxi.inventory.models import InventoryReservation
from kaxi.sales.models import SalesOrderLine


def test_reservation_has_sales_order_line_relation() -> None:
    relation = InventoryReservation._meta.get_field("sales_order_line")
    assert relation.remote_field.model is SalesOrderLine


def test_reservation_remaining_quantity_is_derived() -> None:
    reservation = InventoryReservation(
        reserved_qty=Decimal("10"), consumed_qty=Decimal("3"), released_qty=Decimal("2")
    )
    assert reservation.remaining_qty == Decimal("5")


def test_reservation_quantities_have_database_constraints() -> None:
    names = {constraint.name for constraint in InventoryReservation._meta.constraints}
    assert "inv_reservation_used_lte_reserved_ck" in names

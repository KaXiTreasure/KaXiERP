from kaxi.pricing.models import CustomerSpecialPrice, PriceListItem, PricingPolicy


def test_pricing_policy_makes_source_precedence_configurable() -> None:
    names = {field.name for field in PricingPolicy._meta.fields}
    assert {
        "customer_special_priority",
        "agent_sku_priority",
        "agent_category_priority",
        "channel_priority",
        "standard_priority",
    } <= names


def test_price_item_has_floor_and_quantity_tier() -> None:
    names = {field.name for field in PriceListItem._meta.fields}
    assert {"minimum_price", "minimum_discount_rate", "min_qty", "max_qty"} <= names


def test_floor_break_requires_approval_constraint() -> None:
    names = {constraint.name for constraint in CustomerSpecialPrice._meta.constraints}
    assert "prc_special_floor_approval_ck" in names

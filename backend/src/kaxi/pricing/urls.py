from rest_framework.routers import DefaultRouter

from kaxi.pricing.models import (
    AgentDiscountRule,
    AgentLevel,
    AgentProfile,
    CustomerSpecialPrice,
    PriceList,
    PriceListItem,
    PricingPolicy,
)
from kaxi.shared.crud import crud_for

router = DefaultRouter()
router.register("policies", crud_for(PricingPolicy, "pricing.manage"), basename="pricing-policy")
router.register("price-lists", crud_for(PriceList, "pricing.manage"), basename="price-list")
router.register(
    "price-items",
    crud_for(PriceListItem, "pricing.manage", "price_list__company_id"),
    basename="price-item",
)
router.register("agent-levels", crud_for(AgentLevel, "pricing.manage"), basename="agent-level")
router.register(
    "agent-profiles",
    crud_for(AgentProfile, "pricing.manage", "party__company_id"),
    basename="agent-profile",
)
router.register(
    "agent-rules",
    crud_for(AgentDiscountRule, "pricing.manage", "agent_level__company_id"),
    basename="agent-rule",
)
router.register(
    "special-prices",
    crud_for(CustomerSpecialPrice, "pricing.override.manage", "customer__company_id"),
    basename="special-price",
)
urlpatterns = router.urls

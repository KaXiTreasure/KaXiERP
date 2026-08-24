from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db.models import Q

from kaxi.master_data.models import Currency, Party, UnitOfMeasure
from kaxi.pricing.models import (
    AgentDiscountRule,
    AgentLevel,
    CustomerSpecialPrice,
    PriceListItem,
    PricingPolicy,
)
from kaxi.products.models import ProductSku
from kaxi.sales.models import SalesChannel, SalesOrder
from kaxi.sales.services import LinePriceInput


class PriceNotFoundError(ValueError):
    pass


class PriceFloorViolationError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedPrice:
    unit_price: Decimal
    source_type: str
    source_id: int
    minimum_price: Decimal | None
    snapshot: dict[str, object]


def price_sales_order(
    *,
    order: SalesOrder,
    policy: PricingPolicy,
    at: datetime,
    agent_level: AgentLevel | None = None,
) -> list[LinePriceInput]:
    results: list[LinePriceInput] = []
    for line in order.lines.select_related("sku__spu__category", "sku__base_uom").order_by("id"):
        resolved = resolve_price(
            policy=policy,
            customer=order.customer,
            sku=line.sku,
            currency=order.currency,
            uom=line.sku.base_uom,
            quantity=line.ordered_qty,
            at=at,
            channel=order.channel,
            agent_level=agent_level,
        )
        results.append(
            LinePriceInput(
                line_id=line.pk,
                unit_price=resolved.unit_price,
                price_source=resolved.source_type,
                snapshot=resolved.snapshot,
            )
        )
    return results


def resolve_price(
    *,
    policy: PricingPolicy,
    customer: Party,
    sku: ProductSku,
    currency: Currency,
    uom: UnitOfMeasure,
    quantity: Decimal,
    at: datetime,
    channel: SalesChannel | None = None,
    agent_level: AgentLevel | None = None,
) -> ResolvedPrice:
    base = (
        PriceListItem.objects.select_related("price_list")
        .filter(
            price_list__company=policy.company,
            price_list__currency=currency,
            price_list__status="active",
            price_list__valid_from__lte=at,
            sku=sku,
            uom=uom,
            min_qty__lte=quantity,
            is_active=True,
        )
        .filter(Q(price_list__valid_to__isnull=True) | Q(price_list__valid_to__gt=at))
        .filter(Q(max_qty__isnull=True) | Q(max_qty__gt=quantity))
        .filter(Q(price_list__channel__isnull=True) | Q(price_list__channel=channel))
        .order_by("-price_list__priority", "-min_qty", "-id")
        .first()
    )
    if base is None:
        raise PriceNotFoundError("没有匹配的有效基础价格")

    candidates: list[tuple[int, int, str, Decimal, bool, int | None]] = []
    base_priority = (
        policy.channel_priority if base.price_list.channel_id else policy.standard_priority
    )
    candidates.append((base_priority, base.pk, "price_list", base.unit_price, False, None))

    special = (
        CustomerSpecialPrice.objects.filter(
            customer=customer,
            sku=sku,
            currency=currency,
            valid_from__lte=at,
            is_active=True,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=at))
        .order_by("-priority", "-valid_from", "-id")
        .first()
    )
    if special is not None:
        price = special.special_price
        if price is None:
            price = base.unit_price * special.special_discount_rate
        candidates.append(
            (
                policy.customer_special_priority + special.priority,
                special.pk,
                "customer_special",
                price,
                special.can_break_floor,
                special.approval_id,
            )
        )

    if agent_level is not None:
        discount = (
            AgentDiscountRule.objects.filter(
                agent_level=agent_level, valid_from__lte=at, is_active=True
            )
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=at))
            .filter(Q(sku=sku) | Q(product_category=sku.spu.category))
            .order_by("-priority", "-id")
            .first()
        )
        if discount is not None:
            source_priority = (
                policy.agent_sku_priority if discount.sku_id else policy.agent_category_priority
            )
            candidates.append(
                (
                    source_priority + discount.priority,
                    discount.pk,
                    "agent_discount",
                    base.unit_price * discount.discount_rate,
                    False,
                    None,
                )
            )

    _, source_id, source_type, final_price, can_break_floor, approval_id = max(
        candidates, key=lambda item: (item[0], item[1])
    )
    if (
        base.minimum_price is not None
        and final_price < base.minimum_price
        and (not can_break_floor or approval_id is None)
    ):
        raise PriceFloorViolationError("解析价格低于底价且没有有效批准例外")
    return ResolvedPrice(
        unit_price=final_price,
        source_type=source_type,
        source_id=source_id,
        minimum_price=base.minimum_price,
        snapshot={
            "policy_id": policy.pk,
            "base_price_item_id": base.pk,
            "source_type": source_type,
            "source_id": source_id,
            "currency": currency.code,
            "uom": uom.uom_code,
            "quantity": str(quantity),
            "unit_price": str(final_price),
            "minimum_price": str(base.minimum_price) if base.minimum_price is not None else None,
            "approval_id": approval_id,
            "resolved_at": at.isoformat(),
        },
    )

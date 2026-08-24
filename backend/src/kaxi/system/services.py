from dataclasses import dataclass
from datetime import date

from django.db import transaction

from kaxi.system.models import NumberRule, NumberSequence


@dataclass(frozen=True)
class AllocatedNumber:
    value: str
    sequence_value: int
    period_key: str


def _period_key(rule: NumberRule, business_date: date) -> str:
    match rule.reset_period:
        case NumberRule.ResetPeriod.YEAR:
            return business_date.strftime("%Y")
        case NumberRule.ResetPeriod.MONTH:
            return business_date.strftime("%Y%m")
        case NumberRule.ResetPeriod.DAY:
            return business_date.strftime("%Y%m%d")
        case _:
            return "all"


@transaction.atomic
def allocate_business_number(
    *, rule: NumberRule, business_date: date, context: dict[str, str] | None = None
) -> AllocatedNumber:
    """Allocate one number while locking its company/rule/period sequence row."""
    rule = NumberRule.objects.select_for_update().select_related("company").get(pk=rule.pk)
    if not rule.is_active:
        raise ValueError("编号规则未启用")

    period_key = _period_key(rule, business_date)
    sequence, created = NumberSequence.objects.select_for_update().get_or_create(
        rule=rule,
        period_key=period_key,
        defaults={"last_value": rule.starts_from - 1},
    )
    if not created and sequence.last_value < rule.starts_from - 1:
        sequence.last_value = rule.starts_from - 1
    sequence.last_value += 1
    sequence.save(update_fields=["last_value", "updated_at"])

    template_context = {"company": rule.company.company_code, **(context or {})}
    prefix = rule.prefix_template.format_map(template_context) if rule.prefix_template else ""
    date_part = business_date.strftime(rule.date_format) if rule.date_format else ""
    parts = [part for part in (prefix, date_part) if part]
    parts.append(str(sequence.last_value).zfill(rule.sequence_length))
    return AllocatedNumber(rule.separator.join(parts), sequence.last_value, period_key)

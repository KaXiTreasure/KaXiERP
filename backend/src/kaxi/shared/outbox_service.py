from collections.abc import Iterable
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from kaxi.master_data.models import Company
from kaxi.shared.outbox import OutboxEvent


def append_outbox_event(
    *,
    company: Company,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
    event_type: str,
    payload: dict[str, object],
    trace_id: str = "",
) -> OutboxEvent:
    """Persist an event; callers must invoke this inside their business transaction."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Outbox事件必须在数据库事务中写入")
    return OutboxEvent.objects.create(
        company=company,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        event_type=event_type,
        payload=payload,
        trace_id=trace_id,
    )


@transaction.atomic
def claim_outbox_events(
    *, worker_id: str, batch_size: int = 100, lease_seconds: int = 60
) -> Iterable[OutboxEvent]:
    now = timezone.now()
    events = list(
        OutboxEvent.objects.select_for_update(skip_locked=True)
        .filter(status=OutboxEvent.Status.PENDING, next_attempt_at__lte=now)
        .order_by("-priority", "id")[:batch_size]
    )
    lease_until = now + timedelta(seconds=lease_seconds)
    for event in events:
        event.status = OutboxEvent.Status.PROCESSING
        event.worker_id = worker_id
        event.lease_until = lease_until
        event.attempts += 1
    OutboxEvent.objects.bulk_update(events, ["status", "worker_id", "lease_until", "attempts"])
    return events

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from kaxi.integrations.models import IntegrationAccount, IntegrationEvent


@transaction.atomic
def enqueue_event(
    *,
    account_id: int,
    direction: str,
    event_type: str,
    idempotency_key: str,
    payload_reference: str,
    payload_sha256: str,
    signature_verified: bool = False,
    external_id: str = "",
) -> IntegrationEvent:
    existing = IntegrationEvent.objects.filter(
        account_id=account_id, direction=direction, idempotency_key=idempotency_key
    ).first()
    if existing:
        return existing
    account = IntegrationAccount.objects.get(pk=account_id)
    if account.status != IntegrationAccount.Status.ACTIVE:
        raise ValidationError("集成账号当前不可用。")
    if direction == "in" and not signature_verified:
        raise ValidationError("入站事件必须先通过签名验证。")
    return IntegrationEvent.objects.create(
        account=account,
        direction=direction,
        event_type=event_type,
        external_id=external_id,
        idempotency_key=idempotency_key,
        payload_reference=payload_reference,
        payload_sha256=payload_sha256.lower(),
        signature_verified=signature_verified,
        next_attempt_at=timezone.now(),
    )


@transaction.atomic
def claim_events(*, worker_id: str, batch_size: int = 100) -> list[IntegrationEvent]:
    now = timezone.now()
    events = list(
        IntegrationEvent.objects.select_for_update(skip_locked=True)
        .filter(
            Q(status=IntegrationEvent.Status.PENDING)
            | Q(status=IntegrationEvent.Status.PROCESSING, lease_until__lte=now),
            next_attempt_at__lte=now,
        )
        .order_by("next_attempt_at", "id")[:batch_size]
    )
    for event in events:
        event.status = IntegrationEvent.Status.PROCESSING
        event.worker_id = worker_id
        event.lease_until = now + timedelta(minutes=2)
        event.attempts += 1
    IntegrationEvent.objects.bulk_update(
        events, ["status", "worker_id", "lease_until", "attempts", "updated_at"]
    )
    return events


@transaction.atomic
def complete_event(
    *,
    event_id: int,
    worker_id: str,
    succeeded: bool,
    error_code: str = "",
    error_message: str = "",
) -> IntegrationEvent:
    event = IntegrationEvent.objects.select_for_update().get(pk=event_id)
    if event.status != IntegrationEvent.Status.PROCESSING or event.worker_id != worker_id:
        raise ValidationError("事件租约无效。")
    if succeeded:
        event.status = IntegrationEvent.Status.SUCCEEDED
    elif event.attempts >= event.max_attempts:
        event.status = IntegrationEvent.Status.DEAD
    else:
        event.status = IntegrationEvent.Status.PENDING
        delay = min(3600, 2 ** min(event.attempts, 10) * 5)
        event.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    event.error_code = error_code
    event.error_message = error_message[:4000]
    event.lease_until = None
    event.worker_id = ""
    event.row_version += 1
    event.save()
    return event

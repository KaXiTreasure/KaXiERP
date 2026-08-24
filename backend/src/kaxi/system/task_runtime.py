from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from kaxi.system.models import BackgroundTaskExecution


@contextmanager
def recorded_task(
    *,
    task_name: str,
    idempotency_key: str,
    queue: str,
    company_id: int | None = None,
    source_type: str = "",
    source_id: str = "",
) -> Iterator[BackgroundTaskExecution | None]:
    with transaction.atomic():
        execution, _ = BackgroundTaskExecution.objects.select_for_update().get_or_create(
            company_id=company_id,
            task_name=task_name,
            task_version=1,
            idempotency_key=idempotency_key,
            defaults={
                "queue": queue,
                "scheduled_at": timezone.now(),
                "trace_id": uuid4().hex,
                "source_type": source_type,
                "source_id": source_id,
            },
        )
        if execution.status == BackgroundTaskExecution.Status.SUCCEEDED:
            yield None
            return
        execution.status = BackgroundTaskExecution.Status.PROCESSING
        execution.attempts += 1
        execution.started_at = timezone.now()
        execution.heartbeat_at = execution.started_at
        execution.error_code = ""
        execution.error_summary = ""
        execution.save()
    try:
        yield execution
    except Exception as exc:
        execution.status = (
            BackgroundTaskExecution.Status.DEAD
            if execution.attempts >= execution.max_attempts
            else BackgroundTaskExecution.Status.FAILED
        )
        execution.finished_at = timezone.now()
        execution.next_retry_at = timezone.now() + timedelta(
            seconds=min(3600, 30 * 2 ** (execution.attempts - 1))
        )
        execution.error_code = type(exc).__name__
        execution.error_summary = str(exc)[:2000]
        execution.save()
        raise
    else:
        execution.status = BackgroundTaskExecution.Status.SUCCEEDED
        execution.finished_at = timezone.now()
        execution.heartbeat_at = execution.finished_at
        execution.save()

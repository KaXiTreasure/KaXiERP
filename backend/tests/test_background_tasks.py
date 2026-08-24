import pytest
from config.celery import app

from kaxi.system.models import BackgroundTaskExecution
from kaxi.system.task_runtime import recorded_task


@pytest.mark.django_db(transaction=True)
def test_recorded_task_is_idempotent_after_success():
    with recorded_task(
        task_name="test.once",
        idempotency_key="company-1-window-1",
        queue="maintenance",
    ) as execution:
        assert execution is not None

    with recorded_task(
        task_name="test.once",
        idempotency_key="company-1-window-1",
        queue="maintenance",
    ) as repeated:
        assert repeated is None

    saved = BackgroundTaskExecution.objects.get(task_name="test.once")
    assert saved.status == BackgroundTaskExecution.Status.SUCCEEDED
    assert saved.attempts == 1
    assert saved.finished_at is not None


@pytest.mark.django_db(transaction=True)
def test_recorded_task_failure_is_retryable_and_audited():
    with (
        pytest.raises(RuntimeError, match="temporary"),
        recorded_task(
            task_name="test.retry",
            idempotency_key="source-7",
            queue="critical",
        ),
    ):
        raise RuntimeError("temporary")

    failed = BackgroundTaskExecution.objects.get(task_name="test.retry")
    assert failed.status == BackgroundTaskExecution.Status.FAILED
    assert failed.attempts == 1
    assert failed.next_retry_at is not None
    assert failed.error_code == "RuntimeError"

    with recorded_task(
        task_name="test.retry",
        idempotency_key="source-7",
        queue="critical",
    ) as retried:
        assert retried is not None

    failed.refresh_from_db()
    assert failed.status == BackgroundTaskExecution.Status.SUCCEEDED
    assert failed.attempts == 2


def test_required_periodic_tasks_are_registered():
    required = {
        "auth.expire_user_overrides",
        "document.expire_shares",
        "inventory.release_expired_reservations",
        "workflow.escalate_overdue_tasks",
        "pricing.activate_versions",
    }
    app.autodiscover_tasks(force=True)
    assert required <= set(app.tasks)

from celery import shared_task

from kaxi.analytics.export_services import execute_export
from kaxi.system.task_runtime import recorded_task


@shared_task(name="analytics.execute_export")
def execute_export_task(job_id: int) -> int:
    with recorded_task(
        task_name="analytics.execute_export",
        idempotency_key=str(job_id),
        source_type="analytics_export",
        source_id=str(job_id),
        queue="analytics",
    ) as execution:
        if execution is None:
            return job_id
        execute_export(job_id=job_id)
        return job_id

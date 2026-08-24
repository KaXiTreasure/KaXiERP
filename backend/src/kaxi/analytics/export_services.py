import csv
import hashlib
import io
import json
from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook

from kaxi.analytics.models import ExportJob, ReportSnapshot
from kaxi.analytics.services import result_digest, run_report
from kaxi.documents.models import FileCategory, FileObject, FileVersion
from kaxi.documents.storage import put_bytes
from kaxi.identity.models import User


def _rows(result: object) -> tuple[list[str], list[list[object]]]:
    values = result if isinstance(result, list) else [result]
    dictionaries = [value for value in values if isinstance(value, dict)]
    columns = sorted({str(key) for value in dictionaries for key in value})
    rows = [
        [
            json.dumps(value.get(column), ensure_ascii=False, default=str)
            if isinstance(value.get(column), (dict, list))
            else value.get(column, "")
            for column in columns
        ]
        for value in dictionaries
    ]
    return columns, rows


def _render(result: object, output_format: str) -> tuple[bytes, str, str]:
    columns, rows = _rows(result)
    if output_format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8-sig"), "text/csv", "csv"
    if output_format != "xlsx":
        raise ValueError("仅支持 CSV 或 XLSX 导出。")
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("KAXI ERP")
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return (
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    )


@transaction.atomic
def create_snapshot(
    *, definition_id: int, company_id: int, filters: dict[str, object], actor: User
) -> ReportSnapshot:
    from kaxi.analytics.models import ReportDefinition

    definition = ReportDefinition.objects.get(pk=definition_id, active=True)
    if definition.company_id not in {None, company_id}:
        raise ValueError("报表定义不属于当前公司。")
    if set(filters) - set(definition.allowed_filters):
        raise ValueError("报表筛选条件不在定义允许范围内。")
    result = run_report(report_type=definition.report_type, company_id=company_id, filters=filters)
    return ReportSnapshot.objects.create(
        company_id=company_id,
        definition=definition,
        snapshot_no=f"SNAP-{timezone.now():%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
        as_of=timezone.now(),
        filters=filters,
        result=result,
        result_sha256=result_digest(result),
        generated_by=actor,
    )


def execute_export(*, job_id: int) -> ExportJob:
    with transaction.atomic():
        job = (
            ExportJob.objects.select_for_update()
            .select_related("definition", "company", "requested_by")
            .get(pk=job_id)
        )
        if job.status == ExportJob.Status.COMPLETED:
            return job
        job.status = ExportJob.Status.PROCESSING
        job.error_message = ""
        job.save()
    try:
        result = run_report(
            report_type=job.definition.report_type,
            company_id=job.company_id,
            filters=job.filters,
        )
        body, mime_type, extension = _render(result, job.format)
        digest = hashlib.sha256(body).hexdigest()
        token = uuid4().hex
        storage_key = f"companies/{job.company_id}/exports/{token}.{extension}"
        put_bytes(storage_key=storage_key, body=body, mime_type=mime_type, sha256=digest)
        with transaction.atomic():
            category, _ = FileCategory.objects.get_or_create(
                company=job.company,
                code="SYSTEM_EXPORT",
                defaults={"name": "系统报表导出"},
            )
            file_object = FileObject.objects.create(
                company=job.company,
                file_no=f"EXP-{token[:20]}",
                title=f"{job.definition.name}.{extension}",
                category=category,
                owner=job.requested_by,
                status=FileObject.Status.ACTIVE,
            )
            version = FileVersion.objects.create(
                file_object=file_object,
                version_no=1,
                original_filename=f"{job.definition.report_code}.{extension}",
                storage_key=storage_key,
                mime_type=mime_type,
                extension=extension,
                size_bytes=len(body),
                sha256=digest,
                scan_status=FileVersion.ScanStatus.CLEAN,
                source_type="report_export",
                business_snapshot={"definition_id": job.definition_id, "filters": job.filters},
                created_by=job.requested_by,
            )
            file_object.current_version = version
            file_object.save()
            job.file_object = file_object
            job.status = ExportJob.Status.COMPLETED
            job.save()
    except Exception as exc:
        ExportJob.objects.filter(pk=job_id).update(
            status=ExportJob.Status.FAILED, error_message=str(exc)[:2000]
        )
        raise
    job.refresh_from_db()
    return job

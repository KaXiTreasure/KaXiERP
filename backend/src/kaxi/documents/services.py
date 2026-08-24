import hashlib
import re
import secrets
from dataclasses import dataclass

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from kaxi.documents.models import (
    DisposalBatch,
    FileAuditLog,
    FileObject,
    FileVersion,
    ShareLink,
)
from kaxi.identity.models import User
from kaxi.shared.outbox_service import append_outbox_event

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def audit(file_object: FileObject, actor: User | None, action: str, detail=None) -> None:  # type: ignore[no-untyped-def]
    FileAuditLog.objects.create(
        company=file_object.company,
        file_object=file_object,
        actor=actor,
        action=action,
        detail=detail or {},
    )


@transaction.atomic
def add_file_version(
    *,
    file_id: int,
    actor: User,
    original_filename: str,
    storage_key: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    scan_status: str = FileVersion.ScanStatus.PENDING,
    change_reason: str = "",
) -> FileVersion:
    file_object = FileObject.objects.select_for_update().get(pk=file_id)
    if actor.company_id != file_object.company_id:
        raise PermissionDenied("不能为其他公司上传文件版本。")
    if file_object.status in {FileObject.Status.VOID, FileObject.Status.DISPOSED}:
        raise ValidationError("作废或已销毁文件不能增加版本。")
    digest = sha256.lower()
    if not SHA256_PATTERN.fullmatch(digest) or size_bytes <= 0:
        raise ValidationError("文件大小或 SHA-256 无效。")
    last = file_object.versions.order_by("-version_no").first()
    version = FileVersion.objects.create(
        file_object=file_object,
        version_no=1 if last is None else last.version_no + 1,
        original_filename=original_filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=digest,
        scan_status=scan_status,
        change_reason=change_reason,
        created_by=actor,
    )
    file_object.current_version = version
    if scan_status == FileVersion.ScanStatus.CLEAN:
        file_object.status = FileObject.Status.ACTIVE
    file_object.row_version += 1
    file_object.save(update_fields=["current_version", "status", "row_version", "updated_at"])
    audit(file_object, actor, "version.upload", {"version": version.version_no, "sha256": digest})
    return version


@transaction.atomic
def set_scan_result(*, version_id: int, status: str, actor: User | None = None) -> FileVersion:
    version = (
        FileVersion.objects.select_for_update().select_related("file_object").get(pk=version_id)
    )
    if status not in FileVersion.ScanStatus.values or status == FileVersion.ScanStatus.PENDING:
        raise ValidationError("扫描结果无效。")
    version.scan_status = status
    version.row_version += 1
    version.save(update_fields=["scan_status", "row_version", "updated_at"])
    file_object = FileObject.objects.select_for_update().get(pk=version.file_object_id)
    if file_object.current_version_id == version.pk:
        file_object.status = (
            FileObject.Status.ACTIVE
            if status == FileVersion.ScanStatus.CLEAN
            else FileObject.Status.DRAFT
        )
        file_object.row_version += 1
        file_object.save(update_fields=["status", "row_version", "updated_at"])
    audit(file_object, actor, f"scan.{status}", {"version": version.version_no})
    return version


@dataclass(frozen=True)
class ShareCreation:
    share_id: int
    token: str


@transaction.atomic
def create_share(
    *,
    file_id: int,
    actor: User,
    expires_at,
    max_downloads: int,
    password: str = "",
    watermark: str = "",
) -> ShareCreation:
    file_object = FileObject.objects.select_for_update().get(pk=file_id)
    if file_object.company_id != actor.company_id or file_object.status != FileObject.Status.ACTIVE:
        raise PermissionDenied("当前文件不可分享。")
    if file_object.security_level == FileObject.Security.L4:
        raise PermissionDenied("L4 文件不得创建匿名外部分享。")
    if expires_at <= timezone.now() or max_downloads < 1:
        raise ValidationError("分享期限和下载次数无效。")
    token = secrets.token_urlsafe(32)
    share = ShareLink.objects.create(
        file_object=file_object,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        password_hash=make_password(password) if password else "",
        expires_at=expires_at,
        max_downloads=max_downloads,
        watermark=watermark,
        created_by=actor,
    )
    audit(file_object, actor, "share.create", {"share_id": share.pk})
    return ShareCreation(share.pk, token)


@transaction.atomic
def consume_share(*, token: str, password: str = "") -> FileVersion:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    share = (
        ShareLink.objects.select_for_update()
        .select_related("file_object__current_version")
        .get(token_hash=token_hash)
    )
    if share.revoked_at or share.expires_at <= timezone.now():
        raise PermissionDenied("分享已撤销或过期。")
    if share.download_count >= share.max_downloads:
        raise PermissionDenied("分享下载次数已用尽。")
    if share.password_hash and not check_password(password, share.password_hash):
        raise PermissionDenied("分享密码错误。")
    version = share.file_object.current_version
    if version is None or version.scan_status != FileVersion.ScanStatus.CLEAN:
        raise PermissionDenied("文件当前版本尚未通过安全扫描。")
    ShareLink.objects.filter(pk=share.pk).update(download_count=F("download_count") + 1)
    audit(share.file_object, None, "share.download", {"share_id": share.pk})
    return version


@transaction.atomic
def approve_disposal(*, batch_id: int, actor: User) -> DisposalBatch:
    batch = (
        DisposalBatch.objects.select_for_update()
        .prefetch_related("items__file_object")
        .get(pk=batch_id)
    )
    if batch.status != DisposalBatch.Status.DRAFT or batch.requested_by_id == actor.pk:
        raise PermissionDenied("销毁必须由第二人批准。")
    if any(item.file_object.legal_hold for item in batch.items.all()):
        raise ValidationError("法律冻结文件不得进入销毁批次。")
    batch.status = DisposalBatch.Status.APPROVED
    batch.approved_by = actor
    batch.approved_at = timezone.now()
    batch.row_version += 1
    batch.save()
    return batch


@transaction.atomic
def execute_disposal(*, batch_id: int, actor: User) -> DisposalBatch:
    batch = (
        DisposalBatch.objects.select_for_update()
        .prefetch_related("items__file_object")
        .get(pk=batch_id)
    )
    if batch.status != DisposalBatch.Status.APPROVED:
        raise ValidationError("销毁批次尚未批准。")
    for item in batch.items.all():
        file_object = FileObject.objects.select_for_update().get(pk=item.file_object_id)
        if file_object.legal_hold:
            raise ValidationError("法律冻结文件不得销毁。")
        file_object.status = FileObject.Status.DISPOSED
        file_object.row_version += 1
        file_object.save(update_fields=["status", "row_version", "updated_at"])
        audit(file_object, actor, "disposal.execute", {"batch_id": batch.pk})
        append_outbox_event(
            company=file_object.company,
            aggregate_type="document.file",
            aggregate_id=str(file_object.pk),
            aggregate_version=file_object.row_version,
            event_type="document.storage.deletion_requested",
            payload={"file_id": file_object.pk, "batch_id": batch.pk},
        )
    batch.status = DisposalBatch.Status.EXECUTED
    batch.executed_at = timezone.now()
    batch.row_version += 1
    batch.save()
    return batch

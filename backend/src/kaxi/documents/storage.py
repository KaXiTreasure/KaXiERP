import re
import uuid
from pathlib import PurePath

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError


def _client():  # type: ignore[no-untyped-def]
    if not settings.KAXI_S3_ACCESS_KEY or not settings.KAXI_S3_SECRET_KEY:
        raise ImproperlyConfigured("对象存储凭据尚未配置。")
    return boto3.client(
        "s3",
        endpoint_url=settings.KAXI_S3_ENDPOINT,
        aws_access_key_id=settings.KAXI_S3_ACCESS_KEY,
        aws_secret_access_key=settings.KAXI_S3_SECRET_KEY,
        region_name=settings.KAXI_S3_REGION,
        config=Config(signature_version="s3v4"),
    )


def create_upload(*, company_id: int, file_id: int, filename: str, mime_type: str, sha256: str):  # type: ignore[no-untyped-def]
    digest = sha256.lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValidationError("SHA-256 无效。")
    suffix = PurePath(filename).suffix.lower()[:20]
    key = f"companies/{company_id}/files/{file_id}/{uuid.uuid4().hex}{suffix}"
    params = {
        "Bucket": settings.KAXI_S3_BUCKET,
        "Key": key,
        "ContentType": mime_type,
        "Metadata": {"sha256": digest},
    }
    url = _client().generate_presigned_url(
        "put_object", Params=params, ExpiresIn=settings.KAXI_S3_PRESIGN_TTL
    )
    return {
        "storage_key": key,
        "upload_url": url,
        "headers": {"Content-Type": mime_type, "x-amz-meta-sha256": digest},
        "expires_in": settings.KAXI_S3_PRESIGN_TTL,
    }


def verify_upload(
    *, company_id: int, file_id: int, storage_key: str, size_bytes: int, sha256: str
) -> None:
    prefix = f"companies/{company_id}/files/{file_id}/"
    if not storage_key.startswith(prefix) or ".." in storage_key:
        raise ValidationError("对象存储路径不属于当前文件。")
    try:
        result = _client().head_object(Bucket=settings.KAXI_S3_BUCKET, Key=storage_key)
    except Exception as exc:
        raise ValidationError("对象存储中未找到待登记文件。") from exc
    remote_hash = str(result.get("Metadata", {}).get("sha256", "")).lower()
    if int(result.get("ContentLength", -1)) != size_bytes or remote_hash != sha256.lower():
        raise ValidationError("对象大小或 SHA-256 元数据核验失败。")


def create_download(*, storage_key: str, filename: str) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.KAXI_S3_BUCKET,
            "Key": storage_key,
            "ResponseContentDisposition": f'attachment; filename="{PurePath(filename).name}"',
        },
        ExpiresIn=settings.KAXI_S3_PRESIGN_TTL,
    )


def create_preview(*, storage_key: str, filename: str, mime_type: str) -> str:
    previewable = (
        mime_type.startswith("image/")
        or mime_type.startswith("text/")
        or mime_type.startswith("video/")
        or mime_type == "application/pdf"
    )
    if not previewable:
        raise ValidationError("该文件格式不支持浏览器直接预览，请使用受控下载。")
    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.KAXI_S3_BUCKET,
            "Key": storage_key,
            "ResponseContentType": mime_type,
            "ResponseContentDisposition": f'inline; filename="{PurePath(filename).name}"',
        },
        ExpiresIn=settings.KAXI_S3_PRESIGN_TTL,
    )


def put_bytes(*, storage_key: str, body: bytes, mime_type: str, sha256: str) -> None:
    _client().put_object(
        Bucket=settings.KAXI_S3_BUCKET,
        Key=storage_key,
        Body=body,
        ContentType=mime_type,
        Metadata={"sha256": sha256},
    )


def put_branding_asset(*, kind: str, filename: str, body, mime_type: str) -> str:  # type: ignore[no-untyped-def]
    if kind not in {"logo", "background"} or not mime_type.startswith("image/"):
        raise ValidationError("品牌资产必须是有效图片。")
    suffix = PurePath(filename).suffix.lower()[:20]
    key = f"system/branding/{kind}/{uuid.uuid4().hex}{suffix}"
    _client().upload_fileobj(
        body,
        settings.KAXI_S3_BUCKET,
        key,
        ExtraArgs={"ContentType": mime_type},
    )
    return key


def put_font_asset(*, filename: str, body, mime_type: str) -> str:  # type: ignore[no-untyped-def]
    suffix = PurePath(filename).suffix.lower()
    if suffix not in {".ttf", ".otf", ".woff", ".woff2"}:
        raise ValidationError("仅支持 TTF、OTF、WOFF 和 WOFF2 字体。")
    key = f"system/fonts/{uuid.uuid4().hex}{suffix}"
    _client().upload_fileobj(
        body,
        settings.KAXI_S3_BUCKET,
        key,
        ExtraArgs={"ContentType": mime_type or "application/octet-stream"},
    )
    return key


def create_asset_view(*, storage_key: str, mime_type: str) -> str:
    if not storage_key:
        return ""
    return _client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.KAXI_S3_BUCKET,
            "Key": storage_key,
            "ResponseContentType": mime_type,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=settings.KAXI_S3_PRESIGN_TTL,
    )


def delete_storage_object(storage_key: str) -> None:
    if storage_key:
        _client().delete_object(Bucket=settings.KAXI_S3_BUCKET, Key=storage_key)

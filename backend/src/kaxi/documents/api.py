from django.conf import settings
from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.documents.models import (
    DisposalBatch,
    FileAuditLog,
    FileBusinessLink,
    FileCategory,
    FileObject,
    FilePermission,
    RetentionPolicy,
)
from kaxi.documents.serializers import (
    AuditSerializer,
    CategorySerializer,
    CreateShareSerializer,
    DisposalSerializer,
    FileSerializer,
    LinkSerializer,
    PermissionSerializer,
    PrepareUploadSerializer,
    RetentionSerializer,
    UploadVersionSerializer,
    VersionSerializer,
)
from kaxi.documents.services import (
    add_file_version,
    approve_disposal,
    audit,
    create_share,
    execute_disposal,
)
from kaxi.documents.storage import create_download, create_preview, create_upload, verify_upload
from kaxi.identity.models import User
from kaxi.identity.permissions import AtomicPermissionRequired, company_id_for_request
from kaxi.identity.services import user_has_atomic_permission


def _user(request: Request) -> User:
    if not isinstance(request.user, User):
        raise PermissionDenied("需要有效业务用户。")
    return request.user


class CompanyViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

    def _assert_company(self, instance) -> None:  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        if company_id is not None and instance.company_id != company_id:
            raise PermissionDenied("不能写入其他公司的文件数据。")

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())


class CategoryViewSet(CompanyViewSet):
    queryset = FileCategory.objects.all()
    serializer_class = CategorySerializer
    atomic_permissions = {
        name: "document.version.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class RetentionViewSet(CompanyViewSet):
    queryset = RetentionPolicy.objects.all()
    serializer_class = RetentionSerializer
    atomic_permissions = {
        name: "document.retention.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class FileViewSet(CompanyViewSet):
    queryset = FileObject.objects.select_related(
        "category", "owner", "current_version"
    ).prefetch_related("versions")
    serializer_class = FileSerializer
    atomic_permissions = {
        "list": "document.file.read",
        "retrieve": "document.file.read",
        "create": "document.file.upload",
        "update": "document.version.manage",
        "partial_update": "document.version.manage",
        "destroy": "document.retention.manage",
        "add_version": "document.version.manage",
        "prepare_upload": "document.file.upload",
        "download": "document.file.read",
        "preview": "document.file.read",
        "create_share": "document.share.manage",
        "legal_hold": "document.retention.manage",
        "archive": "document.retention.manage",
        "recycle": "document.retention.manage",
        "restore": "document.retention.manage",
    }

    @transaction.atomic
    def perform_create(self, serializer: FileSerializer) -> None:
        company_id = company_id_for_request(self.request)
        if company_id is not None and serializer.validated_data["company"].pk != company_id:
            raise PermissionDenied("不能为其他公司创建文件。")
        self._assert_company(serializer.save(owner=_user(self.request)))

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        if not user_has_atomic_permission(_user(self.request), "document.sensitive.read"):
            queryset = queryset.exclude(security_level=FileObject.Security.L4)
        return queryset

    def destroy(self, request: Request, *args, **kwargs) -> Response:  # type: ignore[no-untyped-def]
        raise MethodNotAllowed("DELETE", "文件只能通过双人审批的销毁批次处置。")

    @action(detail=True, methods=["post"], url_path="versions")
    def add_version(self, request: Request, pk: str | None = None) -> Response:
        serializer = UploadVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_object = self.get_object()
        verify_upload(
            company_id=file_object.company_id,
            file_id=file_object.pk,
            storage_key=serializer.validated_data["storage_key"],
            size_bytes=serializer.validated_data["size_bytes"],
            sha256=serializer.validated_data["sha256"],
        )
        version = add_file_version(
            file_id=file_object.pk, actor=_user(request), **serializer.validated_data
        )
        return Response(VersionSerializer(version).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="prepare-upload")
    def prepare_upload(self, request: Request, pk: str | None = None) -> Response:
        serializer = PrepareUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_object = self.get_object()
        return Response(
            create_upload(
                company_id=file_object.company_id,
                file_id=file_object.pk,
                filename=serializer.validated_data["original_filename"],
                mime_type=serializer.validated_data["mime_type"],
                sha256=serializer.validated_data["sha256"],
            )
        )

    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> Response:
        file_object = self.get_object()
        version = file_object.current_version
        if version is None or version.scan_status != version.ScanStatus.CLEAN:
            raise PermissionDenied("文件当前版本尚未通过安全扫描。")
        audit(file_object, _user(request), "version.download", {"version": version.version_no})
        return Response(
            {
                "download_url": create_download(
                    storage_key=version.storage_key, filename=version.original_filename
                )
            }
        )

    @action(detail=True, methods=["get"])
    def preview(self, request: Request, pk: str | None = None) -> Response:
        file_object = self.get_object()
        version = file_object.current_version
        if version is None or version.scan_status != version.ScanStatus.CLEAN:
            raise PermissionDenied("文件当前版本尚未通过安全扫描。")
        audit(file_object, _user(request), "version.preview", {"version": version.version_no})
        return Response(
            {
                "preview_url": create_preview(
                    storage_key=version.storage_key,
                    filename=version.original_filename,
                    mime_type=version.mime_type,
                ),
                "mime_type": version.mime_type,
                "expires_in": settings.KAXI_S3_PRESIGN_TTL,
            }
        )

    def _status_change(self, request: Request, target: str, allowed: set[str]) -> Response:
        file_object = self.get_object()
        if file_object.status not in allowed:
            return Response({"detail": "当前文件状态不允许此操作。"}, status=409)
        if target == FileObject.Status.RECYCLED and file_object.legal_hold:
            raise PermissionDenied("法律冻结文件不能移入回收站。")
        previous = file_object.status
        file_object.status = target
        file_object.row_version += 1
        file_object.save(update_fields=["status", "row_version", "updated_at"])
        audit(file_object, _user(request), f"file.{target}", {"from": previous, "to": target})
        return Response(self.get_serializer(file_object).data)

    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: str | None = None) -> Response:
        return self._status_change(request, FileObject.Status.ARCHIVED, {FileObject.Status.ACTIVE})

    @action(detail=True, methods=["post"])
    def recycle(self, request: Request, pk: str | None = None) -> Response:
        return self._status_change(
            request,
            FileObject.Status.RECYCLED,
            {
                FileObject.Status.DRAFT,
                FileObject.Status.ACTIVE,
                FileObject.Status.VOID,
                FileObject.Status.ARCHIVED,
            },
        )

    @action(detail=True, methods=["post"])
    def restore(self, request: Request, pk: str | None = None) -> Response:
        return self._status_change(request, FileObject.Status.ACTIVE, {FileObject.Status.RECYCLED})

    @action(detail=True, methods=["post"], url_path="shares")
    def create_share(self, request: Request, pk: str | None = None) -> Response:
        serializer = CreateShareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_share(
            file_id=self.get_object().pk, actor=_user(request), **serializer.validated_data
        )
        return Response(result.__dict__, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="legal-hold")
    def legal_hold(self, request: Request, pk: str | None = None) -> Response:
        file_object = self.get_object()
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response({"detail": "法律冻结必须填写原因。"}, status=400)
        file_object.legal_hold = True
        file_object.legal_hold_reason = reason
        file_object.row_version += 1
        file_object.save()
        return Response(self.get_serializer(file_object).data)


class FileRelatedViewSet(viewsets.ModelViewSet):
    permission_classes = [AtomicPermissionRequired]

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = super().get_queryset()
        company_id = company_id_for_request(self.request)
        return (
            queryset if company_id is None else queryset.filter(file_object__company_id=company_id)
        )

    def _assert_company(self, instance) -> None:  # type: ignore[no-untyped-def]
        company_id = company_id_for_request(self.request)
        if company_id is not None and instance.file_object.company_id != company_id:
            raise PermissionDenied("不能写入其他公司的文件关联数据。")

    @transaction.atomic
    def perform_create(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())

    @transaction.atomic
    def perform_update(self, serializer):  # type: ignore[no-untyped-def]
        self._assert_company(serializer.save())


class LinkViewSet(FileRelatedViewSet):
    queryset = FileBusinessLink.objects.select_related("file_object")
    serializer_class = LinkSerializer
    atomic_permissions = {
        name: "document.link.manage"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class PermissionViewSet(FileRelatedViewSet):
    queryset = FilePermission.objects.select_related("file_object", "user")
    serializer_class = PermissionSerializer
    atomic_permissions = {
        name: "document.sensitive.approve"
        for name in ["list", "retrieve", "create", "update", "partial_update", "destroy"]
    }


class DisposalViewSet(CompanyViewSet):
    queryset = DisposalBatch.objects.prefetch_related("items")
    serializer_class = DisposalSerializer
    atomic_permissions = {
        "list": "document.retention.manage",
        "retrieve": "document.retention.manage",
        "create": "document.retention.manage",
        "approve": "document.disposal.approve",
        "execute": "document.disposal.approve",
    }

    @transaction.atomic
    def perform_create(self, serializer: DisposalSerializer) -> None:
        self._assert_company(serializer.save(requested_by=_user(self.request)))

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        batch = approve_disposal(batch_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"])
    def execute(self, request: Request, pk: str | None = None) -> Response:
        batch = execute_disposal(batch_id=self.get_object().pk, actor=_user(request))
        return Response(self.get_serializer(batch).data)


class AuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet[FileAuditLog]):
    serializer_class = AuditSerializer
    permission_classes = [AtomicPermissionRequired]
    atomic_permissions = {"list": "document.audit.read"}

    def get_queryset(self):  # type: ignore[no-untyped-def]
        queryset = FileAuditLog.objects.order_by("-occurred_at")
        company_id = company_id_for_request(self.request)
        return queryset if company_id is None else queryset.filter(company_id=company_id)

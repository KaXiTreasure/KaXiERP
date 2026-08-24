from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from kaxi.documents.models import FileAuditLog, FileCategory, FileObject, FileVersion
from kaxi.identity.models import AtomicPermission, Role, RolePermission, User, UserRole
from kaxi.integrations.models import (
    Connector,
    ExternalObjectMapping,
    IntegrationAccount,
    IntegrationEvent,
)
from kaxi.master_data.models import Company, Currency

pytestmark = pytest.mark.django_db(transaction=True)


def _company(code: str) -> Company:
    currency, _ = Currency.objects.get_or_create(code="CNY", defaults={"name": "人民币"})
    return Company.objects.create(
        company_code=code,
        legal_name=f"{code}测试公司",
        display_name=f"{code}测试公司",
        base_currency=currency,
    )


def _admin() -> User:
    return User.objects.create_superuser(
        username="management-root", password="StrongPass123!", display_name="系统管理员"
    )


def test_file_preview_archive_recycle_restore_and_legal_hold(monkeypatch, settings):
    company = _company("DOC")
    admin = _admin()
    category = FileCategory.objects.create(company=company, code="CONTRACT", name="合同")
    file_object = FileObject.objects.create(
        company=company,
        file_no="DOC-001",
        title="销售合同",
        category=category,
        owner=admin,
        status=FileObject.Status.ACTIVE,
    )
    version = FileVersion.objects.create(
        file_object=file_object,
        version_no=1,
        original_filename="contract.pdf",
        storage_key="companies/1/files/1/contract.pdf",
        mime_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        scan_status=FileVersion.ScanStatus.CLEAN,
        created_by=admin,
    )
    file_object.current_version = version
    file_object.save(update_fields=["current_version", "updated_at"])
    monkeypatch.setattr(
        "kaxi.documents.api.create_preview", lambda **kwargs: "https://storage.example/preview"
    )
    settings.KAXI_S3_PRESIGN_TTL = 600
    client = APIClient()
    client.force_authenticate(admin)

    preview = client.get(f"/api/v1/documents/files/{file_object.pk}/preview/")
    assert preview.status_code == 200, preview.data
    assert preview.data == {
        "preview_url": "https://storage.example/preview",
        "mime_type": "application/pdf",
        "expires_in": 600,
    }
    assert client.post(f"/api/v1/documents/files/{file_object.pk}/archive/").status_code == 200
    assert client.post(f"/api/v1/documents/files/{file_object.pk}/recycle/").status_code == 200
    restored = client.post(f"/api/v1/documents/files/{file_object.pk}/restore/")
    assert restored.status_code == 200
    assert restored.data["status"] == FileObject.Status.ACTIVE
    assert set(
        FileAuditLog.objects.filter(file_object=file_object).values_list("action", flat=True)
    ) >= {"version.preview", "file.archived", "file.recycled", "file.active"}

    file_object.legal_hold = True
    file_object.save(update_fields=["legal_hold", "updated_at"])
    denied = client.post(f"/api/v1/documents/files/{file_object.pk}/recycle/")
    assert denied.status_code == 403
    file_object.refresh_from_db()
    assert file_object.status == FileObject.Status.ACTIVE


def test_integration_monitor_and_cross_company_update_rollback():
    first = _company("INT1")
    second = _company("INT2")
    connector = Connector.objects.create(
        code="SHOP", name="商城", connector_type="marketplace", capabilities=[]
    )
    first_account = IntegrationAccount.objects.create(
        company=first,
        connector=connector,
        account_code="A1",
        display_name="一号店",
        credential_reference="secret://a1",
    )
    second_account = IntegrationAccount.objects.create(
        company=second,
        connector=connector,
        account_code="A2",
        display_name="二号店",
        credential_reference="secret://a2",
    )
    now = timezone.now()
    for index, status in enumerate(
        [IntegrationEvent.Status.SUCCEEDED, IntegrationEvent.Status.FAILED]
    ):
        IntegrationEvent.objects.create(
            account=first_account,
            direction="in",
            event_type="order.sync",
            idempotency_key=f"event-{index}",
            payload_reference=f"object://event-{index}",
            payload_sha256=str(index) * 64,
            status=status,
            next_attempt_at=now + timedelta(minutes=5),
        )
    admin = _admin()
    client = APIClient()
    client.force_authenticate(admin)

    monitor = client.get("/api/v1/integrations/events/monitor/?hours=24")
    assert monitor.status_code == 200, monitor.data
    assert monitor.data["total"] == 2
    assert monitor.data["status_counts"]["succeeded"] == 1
    assert monitor.data["status_counts"]["failed"] == 1
    assert monitor.data["success_rate"] == 0.5
    assert monitor.data["by_event_type"]["order.sync"] == {
        "total": 2,
        "succeeded": 1,
        "failed": 1,
    }

    scoped = User.objects.create_user(
        username="integration-user",
        password="StrongPass123!",
        display_name="集成管理员",
        company=first,
        status=User.Status.ACTIVE,
    )
    role = Role.objects.create(company=first, role_code="INTEGRATION", name="集成管理员")
    permission = AtomicPermission.objects.create(
        permission_code="integration.product_mapping.manage", name="映射管理"
    )
    RolePermission.objects.create(role=role, permission=permission)
    UserRole.objects.create(user=scoped, role=role, starts_at=now)
    mapping = ExternalObjectMapping.objects.create(
        account=first_account,
        object_type="product",
        internal_id="SKU-1",
        external_id="EXT-1",
    )
    client.force_authenticate(scoped)
    moved = client.patch(
        f"/api/v1/integrations/mappings/{mapping.pk}/",
        {"account": second_account.pk},
        format="json",
    )
    assert moved.status_code == 403, moved.data
    mapping.refresh_from_db()
    assert mapping.account_id == first_account.pk

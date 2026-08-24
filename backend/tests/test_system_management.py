import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from kaxi.identity.models import AtomicPermission, Role, RolePermission, User, UserRole
from kaxi.master_data.models import Company, Currency
from kaxi.shared.outbox import OutboxEvent
from kaxi.system.models import BackgroundTaskExecution, DictionaryType

pytestmark = pytest.mark.django_db(transaction=True)


def _context():  # type: ignore[no-untyped-def]
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="SYS", legal_name="系统测试", display_name="系统测试", base_currency=currency
    )
    user = User.objects.create_user(
        username="system-admin",
        password="StrongPass123!",
        display_name="系统管理员",
        company=company,
        status=User.Status.ACTIVE,
    )
    role = Role.objects.create(company=company, role_code="SYS_ADMIN", name="系统管理员")
    now = timezone.now()
    UserRole.objects.create(user=user, role=role, starts_at=now)
    for code in ("system.config.manage", "system.job.manage"):
        permission = AtomicPermission.objects.create(permission_code=code, name=code)
        RolePermission.objects.create(role=role, permission=permission)
    return company, user


def test_dictionary_management_is_company_scoped():
    company, user = _context()
    other = Company.objects.create(
        company_code="OTHER",
        legal_name="其他公司",
        display_name="其他公司",
        base_currency=company.base_currency,
    )
    DictionaryType.objects.create(company=other, dictionary_code="hidden", name="不可见")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        "/api/v1/system/dictionary-types/",
        {"company": company.pk, "dictionary_code": "order_source", "name": "订单来源"},
        format="json",
    )
    assert response.status_code == 201, response.data
    dictionary_id = response.data["id"]
    moved = client.patch(
        f"/api/v1/system/dictionary-types/{dictionary_id}/",
        {"company": other.pk},
        format="json",
    )
    assert moved.status_code == 403, moved.data
    assert DictionaryType.objects.get(pk=dictionary_id).company_id == company.pk
    listed = client.get("/api/v1/system/dictionary-types/")
    assert listed.status_code == 200
    assert [row["dictionary_code"] for row in listed.data["results"]] == ["order_source"]


def test_failed_job_and_outbox_can_be_requeued(monkeypatch):
    company, user = _context()
    job = BackgroundTaskExecution.objects.create(
        company=company,
        task_name="test.retry",
        idempotency_key="retry-1",
        queue="maintenance",
        scheduled_at=timezone.now(),
        status=BackgroundTaskExecution.Status.FAILED,
    )
    event = OutboxEvent.objects.create(
        company=company,
        aggregate_type="test",
        aggregate_id="1",
        aggregate_version=1,
        event_type="test.created",
        payload={},
        status=OutboxEvent.Status.DEAD,
    )
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "kaxi.system.management_api.current_app.send_task",
        lambda name, queue: sent.append((name, queue)),
    )
    client = APIClient()
    client.force_authenticate(user)
    assert client.post(f"/api/v1/system/jobs/{job.pk}/retry/").status_code == 202
    assert client.post(f"/api/v1/system/outbox-events/{event.pk}/retry/").status_code == 202
    job.refresh_from_db()
    event.refresh_from_db()
    assert job.status == BackgroundTaskExecution.Status.PENDING
    assert event.status == OutboxEvent.Status.PENDING
    assert sent == [("test.retry", "maintenance")]

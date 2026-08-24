from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from kaxi.identity.models import AtomicPermission, User, UserPermissionOverride
from kaxi.identity.services import user_has_atomic_permission
from kaxi.master_data.models import Company, Currency

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def identity_context():  # type: ignore[no-untyped-def]
    currency = Currency.objects.create(code="CNY", name="人民币")
    company = Company.objects.create(
        company_code="IAM", legal_name="权限测试", display_name="权限测试", base_currency=currency
    )
    requester = User.objects.create_superuser(
        username="iam-requester", password="StrongPass123!", display_name="申请管理员"
    )
    approver = User.objects.create_superuser(
        username="iam-approver", password="StrongPass123!", display_name="审批管理员"
    )
    target = User.objects.create_user(
        username="iam-target",
        password="StrongPass123!",
        display_name="目标用户",
        company=company,
        status=User.Status.ACTIVE,
    )
    permission = AtomicPermission.objects.create(
        permission_code="sales.order.view", name="查看订单"
    )
    return company, requester, approver, target, permission


def test_override_requires_second_person_approval(identity_context):  # type: ignore[no-untyped-def]
    _, requester, approver, target, permission = identity_context
    client = APIClient()
    client.force_authenticate(requester)
    response = client.post(
        "/api/v1/auth/overrides/",
        {
            "user": target.pk,
            "permission": permission.pk,
            "effect": UserPermissionOverride.Effect.ALLOW,
            "starts_at": timezone.now().isoformat(),
            "expires_at": (timezone.now() + timedelta(days=2)).isoformat(),
            "reason": "临时负责订单复核",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    override_id = response.data["id"]
    assert client.post(f"/api/v1/auth/overrides/{override_id}/approve/").status_code == 403
    client.force_authenticate(approver)
    assert client.post(f"/api/v1/auth/overrides/{override_id}/approve/").status_code == 200
    target.refresh_from_db()
    assert user_has_atomic_permission(target, "sales.order.view")


def test_user_management_hashes_initial_password(identity_context):  # type: ignore[no-untyped-def]
    company, requester, _, _, _ = identity_context
    client = APIClient()
    client.force_authenticate(requester)
    response = client.post(
        "/api/v1/auth/users/",
        {
            "username": "new-employee",
            "password": "AnotherStrong123!",
            "display_name": "新员工",
            "company": company.pk,
            "status": User.Status.ACTIVE,
            "is_active": True,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    created = User.objects.get(username="new-employee")
    assert created.password != "AnotherStrong123!"
    assert created.check_password("AnotherStrong123!")


def test_authenticated_user_can_change_password(identity_context):  # type: ignore[no-untyped-def]
    _, requester, _, _, _ = identity_context
    client = APIClient()
    client.force_authenticate(requester)
    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": "StrongPass123!", "new_password": "ChangedPass456!"},
        format="json",
    )
    assert response.status_code == 204, getattr(response, "data", None)
    requester.refresh_from_db()
    assert requester.check_password("ChangedPass456!")

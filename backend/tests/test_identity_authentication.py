import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from kaxi.identity.models import (
    AtomicPermission,
    AuditLog,
    Role,
    RolePermission,
    User,
    UserPermissionOverride,
    UserRole,
)
from kaxi.identity.services import get_effective_permissions
from kaxi.master_data.models import Company, Currency


@pytest.fixture
def company() -> Company:
    currency = Currency.objects.create(code="CNY", name="人民币")
    return Company.objects.create(
        company_code="KAXI",
        legal_name="KAXI测试公司",
        display_name="KAXI",
        base_currency=currency,
    )


@pytest.mark.django_db
def test_session_login_me_and_logout_are_csrf_protected(company: Company) -> None:
    user = User.objects.create_user(
        username="operator",
        password="correct-password",
        display_name="业务员",
        company=company,
        status=User.Status.ACTIVE,
    )
    client = APIClient(enforce_csrf_checks=True)

    assert client.post("/api/v1/auth/login/", {"username": user.username}).status_code == 403
    bootstrap = client.get("/api/v1/auth/session/")
    csrf_token = bootstrap.json()["csrf_token"]
    login_response = client.post(
        "/api/v1/auth/login/",
        {"username": user.username, "password": "correct-password"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["company_id"] == company.pk
    assert client.get("/api/v1/auth/me/").status_code == 200
    assert AuditLog.objects.filter(actor=user, action="session.login").exists()

    csrf_token = client.cookies["csrftoken"].value
    logout_response = client.post("/api/v1/auth/logout/", HTTP_X_CSRFTOKEN=csrf_token)
    assert logout_response.status_code == 204
    assert client.get("/api/v1/auth/me/").status_code == 403


@pytest.mark.django_db
def test_approved_user_deny_override_wins_over_role_allow(company: Company) -> None:
    user = User.objects.create_user(
        username="restricted",
        display_name="受限用户",
        company=company,
        status=User.Status.ACTIVE,
    )
    permission = AtomicPermission.objects.create(
        permission_code="sales.order.view", name="查看销售订单"
    )
    role = Role.objects.create(company=company, role_code="sales", name="销售")
    RolePermission.objects.create(role=role, permission=permission)
    UserRole.objects.create(user=user, role=role, starts_at=timezone.now())
    UserPermissionOverride.objects.create(
        user=user,
        permission=permission,
        effect=UserPermissionOverride.Effect.DENY,
        starts_at=timezone.now(),
        reason="临时限制",
        approval_status="approved",
        approved_by=user,
        approved_at=timezone.now(),
    )

    effective = get_effective_permissions(user)
    assert "sales.order.view" in effective.denied
    assert not effective.has("sales.order.view")


@pytest.mark.django_db
def test_initial_admin_is_created_once_and_must_change_password() -> None:
    call_command("bootstrap_initial_admin")
    call_command("bootstrap_initial_admin")
    admin = User.objects.get(username="admin")
    assert User.objects.filter(is_superuser=True).count() == 1
    assert admin.check_password("12345678")
    assert admin.must_change_password is True

    client = APIClient()
    login_response = client.post(
        "/api/v1/auth/login/",
        {"username": "admin", "password": "12345678"},
        format="json",
    )
    assert login_response.status_code == 200
    assert login_response.data["user"]["must_change_password"] is True
    assert client.get("/api/v1/system/dictionary-types/").status_code == 403

    changed = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": "12345678", "new_password": "NewPass88!"},
        format="json",
    )
    assert changed.status_code == 204, changed.data
    admin.refresh_from_db()
    assert admin.must_change_password is False
    assert admin.check_password("NewPass88!")
    assert client.get("/api/v1/system/dictionary-types/").status_code == 200


@pytest.mark.django_db
def test_captcha_is_required_after_first_failed_password(company: Company) -> None:
    user = User.objects.create_user(
        username="captcha-user",
        password="CorrectPass88!",
        display_name="验证码用户",
        company=company,
        status=User.Status.ACTIVE,
    )
    client = APIClient()

    first = client.post(
        "/api/v1/auth/login/",
        {"username": user.username, "password": "wrong-password"},
        format="json",
    )
    assert first.status_code == 401
    assert first.data["captcha_required"] is True

    missing_captcha = client.post(
        "/api/v1/auth/login/",
        {"username": user.username, "password": "CorrectPass88!"},
        format="json",
    )
    assert missing_captcha.status_code == 400
    assert missing_captcha.data["code"] == "captcha_required"

    captcha = client.get("/api/v1/auth/captcha/")
    assert captcha.status_code == 200
    assert captcha["Content-Type"] == "image/svg+xml"
    answer = client.session["login_captcha_answer"]
    logged_in = client.post(
        "/api/v1/auth/login/",
        {"username": user.username, "password": "CorrectPass88!", "captcha": answer},
        format="json",
    )
    assert logged_in.status_code == 200
    user.refresh_from_db()
    assert user.failed_login_attempts == 0


@pytest.mark.django_db
def test_six_failed_passwords_lock_user_until_admin_unlocks(company: Company) -> None:
    user = User.objects.create_user(
        username="lock-user",
        password="CorrectPass88!",
        display_name="锁定用户",
        company=company,
        status=User.Status.ACTIVE,
    )
    client = APIClient()

    for attempt in range(6):
        payload = {"username": user.username, "password": "wrong-password"}
        if attempt:
            client.get("/api/v1/auth/captcha/")
            payload["captcha"] = client.session["login_captcha_answer"]
        response = client.post("/api/v1/auth/login/", payload, format="json")

    assert response.status_code == 403
    assert response.data["code"] == "account_locked"
    user.refresh_from_db()
    assert user.status == User.Status.LOCKED
    assert user.failed_login_attempts == 6
    assert user.locked_at is not None

    admin = User.objects.create_superuser(
        username="unlock-admin", password="AdminPass88!", display_name="解锁管理员"
    )
    admin_client = APIClient()
    admin_client.force_authenticate(admin)
    unlocked = admin_client.patch(
        f"/api/v1/auth/users/{user.pk}/", {"status": User.Status.ACTIVE}, format="json"
    )
    assert unlocked.status_code == 200
    user.refresh_from_db()
    assert user.status == User.Status.ACTIVE
    assert user.failed_login_attempts == 0
    assert user.locked_at is None
    assert user.locked_reason == ""

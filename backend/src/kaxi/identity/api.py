import html
import secrets

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from kaxi.identity.models import AuditLog, User
from kaxi.identity.serializers import LoginSerializer, PasswordChangeSerializer
from kaxi.identity.services import get_effective_permissions

MAX_FAILED_LOGINS = 6
CAPTCHA_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CAPTCHA_SESSION_KEY = "login_captcha_answer"
CAPTCHA_ISSUED_AT_SESSION_KEY = "login_captcha_issued_at"
CAPTCHA_MAX_AGE_SECONDS = 300
UNKNOWN_FAILURE_SESSION_KEY = "unknown_login_failures"


def _client_ip(request: Request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    value = forwarded.split(",", 1)[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return value or None


def _user_payload(user: User) -> dict[str, object]:
    effective = get_effective_permissions(user)
    return {
        "id": user.pk,
        "username": user.username,
        "display_name": user.display_name,
        "company_id": user.company_id,
        "department_id": user.department_id,
        "status": user.status,
        "is_superuser": user.is_superuser,
        "must_change_password": user.must_change_password,
        "permissions": ["*"] if "*" in effective.allowed else sorted(effective.allowed),
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionBootstrapView(APIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request)})


class LoginCaptchaView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> HttpResponse:
        answer = "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(5))
        request.session[CAPTCHA_SESSION_KEY] = answer
        request.session[CAPTCHA_ISSUED_AT_SESSION_KEY] = timezone.now().timestamp()
        offsets = [secrets.randbelow(13) - 6 for _ in answer]
        glyphs = "".join(
            f'<text x="{24 + index * 30}" y="{43 + offsets[index]}" '
            f'transform="rotate({secrets.randbelow(25) - 12} {24 + index * 30} 38)">'
            f"{html.escape(char)}</text>"
            for index, char in enumerate(answer)
        )
        lines = "".join(
            f'<path d="M0 {secrets.randbelow(55)} L180 {secrets.randbelow(55)}" />'
            for _ in range(4)
        )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="60" viewBox="0 0 180 60">'
            '<rect width="180" height="60" rx="8" fill="#eef3ef"/>'
            f'<g stroke="#8aa096" stroke-width="1.5" opacity=".65">{lines}</g>'
            '<g fill="#173d2d" font-family="monospace" font-size="28" font-weight="700">'
            f"{glyphs}</g>"
            "</svg>"
        )
        response = HttpResponse(svg, content_type="image/svg+xml")
        response["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response["X-Content-Type-Options"] = "nosniff"
        return response


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.validated_data
        candidate = User.objects.filter(username__iexact=credentials["username"]).first()
        captcha_required = bool(
            (candidate and candidate.failed_login_attempts >= 1)
            or request.session.get(UNKNOWN_FAILURE_SESSION_KEY, 0) >= 1
        )
        if captcha_required:
            supplied = credentials.get("captcha", "").upper()
            expected = request.session.pop(CAPTCHA_SESSION_KEY, "")
            issued_at = float(request.session.pop(CAPTCHA_ISSUED_AT_SESSION_KEY, 0))
            captcha_expired = timezone.now().timestamp() - issued_at > CAPTCHA_MAX_AGE_SECONDS
            if captcha_expired or not expected or not secrets.compare_digest(supplied, expected):
                return Response(
                    {
                        "code": "captcha_required",
                        "detail": "请输入正确的图片验证码。",
                        "captcha_required": True,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        user = authenticate(
            request,
            username=candidate.username if candidate else credentials["username"],
            password=credentials["password"],
        )
        if not isinstance(user, User):
            locked = False
            if candidate and candidate.status == User.Status.ACTIVE:
                with transaction.atomic():
                    target = User.objects.select_for_update().get(pk=candidate.pk)
                    target.failed_login_attempts += 1
                    if target.failed_login_attempts >= MAX_FAILED_LOGINS:
                        target.status = User.Status.LOCKED
                        target.locked_at = timezone.now()
                        target.locked_reason = "连续登录密码错误 6 次"
                        locked = True
                    target.save(
                        update_fields=[
                            "failed_login_attempts",
                            "status",
                            "locked_at",
                            "locked_reason",
                        ]
                    )
                    AuditLog.objects.create(
                        company=target.company,
                        actor=None,
                        action="session.login_failed",
                        object_type="user",
                        object_id=str(target.pk),
                        source_ip=_client_ip(request),
                        changes={"attempt": target.failed_login_attempts, "locked": locked},
                    )
            else:
                request.session[UNKNOWN_FAILURE_SESSION_KEY] = min(
                    int(request.session.get(UNKNOWN_FAILURE_SESSION_KEY, 0)) + 1,
                    MAX_FAILED_LOGINS,
                )
            if locked:
                return Response(
                    {"code": "account_locked", "detail": "账号已锁定，请联系管理员解锁。"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response(
                {
                    "code": "invalid_credentials",
                    "detail": "用户名或密码错误。",
                    "captcha_required": True,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if user.status != User.Status.ACTIVE:
            return Response(
                {"code": "account_unavailable", "detail": "账号不可用，请联系管理员。"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if user.failed_login_attempts:
            user.failed_login_attempts = 0
            user.locked_at = None
            user.locked_reason = ""
            user.save(update_fields=["failed_login_attempts", "locked_at", "locked_reason"])
        request.session.pop(UNKNOWN_FAILURE_SESSION_KEY, None)
        login(request, user)
        AuditLog.objects.create(
            company=user.company,
            actor=user,
            action="session.login",
            object_type="user",
            object_id=str(user.pk),
            source_ip=_client_ip(request),
        )
        return Response({"user": _user_payload(user)})


class CurrentUserView(APIView):
    serializer_class = LoginSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user = request.user
        if not isinstance(user, User) or user.status != User.Status.ACTIVE:
            return Response(
                {"code": "account_unavailable", "detail": "账户不可用。"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response({"user": _user_payload(user)})


class LogoutView(APIView):
    serializer_class = LoginSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        user = request.user
        if isinstance(user, User):
            AuditLog.objects.create(
                company=user.company,
                actor=user,
                action="session.logout",
                object_type="user",
                object_id=str(user.pk),
                source_ip=_client_ip(request),
            )
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class PasswordChangeView(APIView):
    serializer_class = PasswordChangeSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not isinstance(user, User) or not user.check_password(
            serializer.validated_data["current_password"]
        ):
            return Response(
                {"code": "invalid_current_password", "detail": "当前密码不正确。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        new_password = serializer.validated_data["new_password"]
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response(
                {"code": "weak_password", "details": {"new_password": exc.messages}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, user)
        AuditLog.objects.create(
            company=user.company,
            actor=user,
            action="session.password_change",
            object_type="user",
            object_id=str(user.pk),
            source_ip=_client_ip(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

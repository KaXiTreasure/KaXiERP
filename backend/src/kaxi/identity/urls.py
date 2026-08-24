from django.urls import include, path
from rest_framework.routers import DefaultRouter

from kaxi.identity.api import (
    CurrentUserView,
    LoginCaptchaView,
    LoginView,
    LogoutView,
    PasswordChangeView,
    SessionBootstrapView,
)
from kaxi.identity.management_api import (
    AuditViewSet,
    DepartmentViewSet,
    OverrideViewSet,
    PermissionViewSet,
    PositionViewSet,
    RoleViewSet,
    UserRoleViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register("departments", DepartmentViewSet)
router.register("positions", PositionViewSet)
router.register("users", UserViewSet)
router.register("permissions", PermissionViewSet)
router.register("roles", RoleViewSet)
router.register("user-roles", UserRoleViewSet)
router.register("overrides", OverrideViewSet)
router.register("audit-events", AuditViewSet, basename="identity-audit")

urlpatterns = [
    path("session/", SessionBootstrapView.as_view(), name="session-bootstrap"),
    path("captcha/", LoginCaptchaView.as_view(), name="login-captcha"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path("", include(router.urls)),
]

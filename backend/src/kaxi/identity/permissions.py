from collections.abc import Mapping
from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from kaxi.identity.models import User
from kaxi.identity.services import user_has_atomic_permission


class AtomicPermissionRequired(BasePermission):
    message = "当前用户没有执行此操作的权限。"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not isinstance(user, User):
            return False
        if user.must_change_password:
            return False
        permission_map: Mapping[str, str] = getattr(view, "atomic_permissions", {})
        action = getattr(view, "action", request.method.lower())
        permission_code = permission_map.get(action)
        if permission_code is None:
            return False
        return user_has_atomic_permission(user, permission_code)


def company_id_for_request(request: Request) -> int | None:
    user: Any = request.user
    if not isinstance(user, User) or user.is_superuser:
        return None
    return user.company_id

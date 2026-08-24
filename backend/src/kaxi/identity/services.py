from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from kaxi.identity.models import User, UserPermissionOverride


@dataclass(frozen=True)
class EffectivePermissions:
    allowed: frozenset[str]
    denied: frozenset[str]

    def has(self, permission_code: str) -> bool:
        return permission_code in self.allowed and permission_code not in self.denied


def get_effective_permissions(user: User) -> EffectivePermissions:
    if not user.is_authenticated or not user.is_active or user.status != User.Status.ACTIVE:
        return EffectivePermissions(frozenset(), frozenset())
    if user.is_superuser:
        return EffectivePermissions(frozenset({"*"}), frozenset())

    now = timezone.now()
    role_permissions = user.role_set.filter(
        is_active=True,
        userrole__starts_at__lte=now,
    ).filter(Q(userrole__expires_at__isnull=True) | Q(userrole__expires_at__gt=now))
    if user.company_id:
        role_permissions = role_permissions.filter(Q(company_id=user.company_id) | Q(company=None))
    allowed = set(
        role_permissions.filter(permissions__is_active=True).values_list(
            "permissions__permission_code", flat=True
        )
    )

    overrides = UserPermissionOverride.objects.filter(
        user=user,
        permission__is_active=True,
        approval_status="approved",
        revoked_at__isnull=True,
        starts_at__lte=now,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    denied: set[str] = set()
    for permission_code, effect in overrides.values_list("permission__permission_code", "effect"):
        if effect == UserPermissionOverride.Effect.DENY:
            denied.add(permission_code)
        else:
            allowed.add(permission_code)
    allowed.difference_update(denied)
    return EffectivePermissions(frozenset(allowed), frozenset(denied))


def user_has_atomic_permission(user: User, permission_code: str) -> bool:
    permissions = get_effective_permissions(user)
    return "*" in permissions.allowed or permissions.has(permission_code)

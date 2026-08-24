from django.core.management.base import BaseCommand
from django.urls import URLResolver, get_resolver

from kaxi.identity.models import AtomicPermission

EXTRA_PERMISSIONS = {
    "document.sensitive.read",
}


def permission_codes() -> set[str]:
    result = set(EXTRA_PERMISSIONS)

    def walk(patterns):  # type: ignore[no-untyped-def]
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns)
                continue
            view_class = getattr(pattern.callback, "cls", None)
            mapping = getattr(view_class, "atomic_permissions", {})
            result.update(code for code in mapping.values() if code)

    walk(get_resolver().url_patterns)
    return result


class Command(BaseCommand):
    help = "幂等初始化全部 API 原子权限目录"

    def handle(self, *args, **options):  # type: ignore[no-untyped-def]
        created = 0
        for code in sorted(permission_codes()):
            _, was_created = AtomicPermission.objects.update_or_create(
                permission_code=code,
                defaults={"name": code, "is_active": True},
            )
            created += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(f"权限目录已同步：{len(permission_codes())} 项，新增 {created} 项。")
        )

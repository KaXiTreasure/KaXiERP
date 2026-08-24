from django.core.management.base import BaseCommand

from kaxi.identity.models import User


class Command(BaseCommand):
    help = "仅在系统没有超级管理员时创建一次性初始管理员 admin/12345678"

    def handle(self, *args, **options):  # type: ignore[no-untyped-def]
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("超级管理员已存在，跳过初始管理员创建。")
            return
        user = User.objects.create_superuser(
            username="admin",
            password="12345678",
            display_name="初始系统管理员",
            must_change_password=True,
        )
        self.stdout.write(
            self.style.WARNING(
                f"已创建一次性初始管理员：{user.username} / 12345678；首次登录必须修改密码。"
            )
        )

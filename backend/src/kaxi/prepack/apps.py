from django.apps import AppConfig


class PrepackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kaxi.prepack"
    verbose_name = "预包装管理"

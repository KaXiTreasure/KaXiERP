from django.apps import AppConfig


class SharedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kaxi.shared"

    def import_models(self) -> None:
        super().import_models()
        from kaxi.shared import outbox  # noqa: F401

from django.conf import settings
from django.db.models import BigAutoField

from kaxi.identity.models import User, UserPermissionOverride
from kaxi.master_data.models import Company, Currency


def test_custom_user_model_is_enabled() -> None:
    assert settings.AUTH_USER_MODEL == "identity.User"
    assert User._meta.db_table == "sys_user"


def test_db01_models_use_bigint_primary_keys() -> None:
    for model in (Currency, Company, User, UserPermissionOverride):
        assert isinstance(model._meta.pk, BigAutoField)


def test_user_permission_override_has_required_audit_fields() -> None:
    field_names = {field.name for field in UserPermissionOverride._meta.fields}
    assert {"starts_at", "expires_at", "reason", "approved_by", "revoked_by"} <= field_names

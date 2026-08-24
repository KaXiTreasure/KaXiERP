from pathlib import Path


def test_project_has_no_sqlite_runtime_configuration() -> None:
    settings = Path("backend/config/settings/base.py").read_text(encoding="utf-8")
    assert "django.db.backends.postgresql" in settings
    assert "django.db.backends.sqlite3" not in settings


def test_required_domain_packages_are_declared() -> None:
    manifest = Path("backend/src/kaxi/domain_modules.txt").read_text(encoding="utf-8").splitlines()
    assert "sales" in manifest
    assert "inventory" in manifest
    assert "finance" in manifest

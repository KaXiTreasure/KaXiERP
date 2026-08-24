import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from kaxi.identity.models import User
from kaxi.system.models import BrandingConfiguration

pytestmark = pytest.mark.django_db(transaction=True)


def test_branding_is_public_but_only_admin_can_change(monkeypatch):
    monkeypatch.setattr(
        "kaxi.system.branding_api.create_asset_view",
        lambda storage_key, mime_type: (
            f"https://assets.example/{storage_key}" if storage_key else ""
        ),
    )
    client = APIClient()
    initial = client.get("/api/v1/system/branding/")
    assert initial.status_code == 200
    assert initial.data["app_name"] == "KAXI ERP"
    assert initial.data["login_card_opacity"] == 92
    assert initial.data["login_footer_text"]
    assert initial.data["login_footer_links"] == []
    assert initial.data["login_slogan"] == "Slogan"
    assert client.patch("/api/v1/system/branding/", {"app_name": "Denied"}).status_code == 403

    admin = User.objects.create_superuser(
        username="branding-root", password="StrongPass123!", display_name="品牌管理员"
    )
    client.force_authenticate(admin)
    updated = client.patch(
        "/api/v1/system/branding/",
        {
            "app_name": "KAXI Global",
            "version_name": "2026.1",
            "theme": "ocean",
            "login_card_opacity": 78,
            "login_footer_text": "© KAXI · ICP 备案信息",
            "login_footer_links": [
                {"label": "帮助", "url": "https://example.com/help"}
            ],
            "login_slogan": "连接业务",
            "login_slogan_1": "驱动增长",
            "login_slogan_2": "统一、可信、可追溯。",
        },
        format="json",
    )
    assert updated.status_code == 200, updated.data
    assert updated.data["app_name"] == "KAXI Global"
    assert updated.data["login_card_opacity"] == 78
    assert updated.data["login_footer_text"] == "© KAXI · ICP 备案信息"
    assert updated.data["login_footer_links"] == [
        {"label": "帮助", "url": "https://example.com/help"}
    ]
    assert updated.data["login_slogan_1"] == "驱动增长"

    rejected = client.patch(
        "/api/v1/system/branding/", {"login_card_opacity": 20}, format="json"
    )
    assert rejected.status_code == 400


def test_branding_asset_has_no_application_size_limit(monkeypatch):
    admin = User.objects.create_superuser(
        username="asset-root", password="StrongPass123!", display_name="资产管理员"
    )
    captured = {}

    def fake_upload(*, kind, filename, body, mime_type):  # type: ignore[no-untyped-def]
        captured.update(kind=kind, filename=filename, size=body.size, mime_type=mime_type)
        return "system/branding/logo/large.png"

    monkeypatch.setattr("kaxi.system.branding_api.put_branding_asset", fake_upload)
    monkeypatch.setattr(
        "kaxi.system.branding_api.create_asset_view",
        lambda storage_key, mime_type: (
            f"https://assets.example/{storage_key}" if storage_key else ""
        ),
    )
    image = SimpleUploadedFile("large.png", b"x" * 2_000_000, content_type="image/png")
    client = APIClient()
    client.force_authenticate(admin)
    response = client.post(
        "/api/v1/system/branding/assets/logo/", {"file": image}, format="multipart"
    )
    assert response.status_code == 201, response.data
    assert captured["size"] == 2_000_000
    assert response.data["background_source"] == "local"
    assert BrandingConfiguration.objects.get().logo_storage_key.endswith("large.png")
    assert response.data["logo_url"].endswith("system/branding/logo/large.png")


def test_admin_can_refresh_and_persist_bing_background(monkeypatch):
    admin = User.objects.create_superuser(
        username="bing-root", password="StrongPass123!", display_name="背景管理员"
    )
    configuration = BrandingConfiguration.objects.create(
        background_source=BrandingConfiguration.BackgroundSource.BING,
        background_storage_key="system/branding/background/bing.jpg",
        background_mime_type="image/jpeg",
        bing_image_title="每日图片",
        bing_image_copyright="Bing 图片版权说明",
        bing_image_date="20260825",
    )
    monkeypatch.setattr(
        "kaxi.system.branding_api.refresh_bing_background", lambda: configuration
    )
    monkeypatch.setattr(
        "kaxi.system.branding_api.create_asset_view",
        lambda storage_key, mime_type: f"https://assets.example/{storage_key}",
    )
    client = APIClient()
    client.force_authenticate(admin)

    response = client.post("/api/v1/system/branding/background/bing/refresh/")

    assert response.status_code == 200, response.data
    assert response.data["background_source"] == "bing"
    assert response.data["bing_image_title"] == "每日图片"


def test_replacing_branding_asset_deletes_previous_object(monkeypatch):
    admin = User.objects.create_superuser(
        username="replace-root", password="StrongPass123!", display_name="品牌管理员"
    )
    configuration = BrandingConfiguration.objects.create(
        logo_storage_key="system/branding/logo/old.png", logo_mime_type="image/png"
    )
    deleted = []
    monkeypatch.setattr(
        "kaxi.system.branding_api.put_branding_asset",
        lambda **kwargs: "system/branding/logo/new.png",
    )
    monkeypatch.setattr(
        "kaxi.system.branding_api.delete_storage_object", lambda key: deleted.append(key)
    )
    monkeypatch.setattr(
        "kaxi.system.branding_api.create_asset_view",
        lambda storage_key, mime_type: storage_key,
    )
    client = APIClient()
    client.force_authenticate(admin)
    response = client.post(
        "/api/v1/system/branding/assets/logo/",
        {"file": SimpleUploadedFile("new.png", b"new", content_type="image/png")},
        format="multipart",
    )
    assert response.status_code == 201, response.data
    configuration.refresh_from_db()
    assert configuration.logo_storage_key.endswith("new.png")
    assert deleted == ["system/branding/logo/old.png"]


def test_font_import_classifies_and_persists_in_object_storage(monkeypatch):
    admin = User.objects.create_superuser(
        username="font-root", password="StrongPass123!", display_name="字体管理员"
    )
    monkeypatch.setattr(
        "kaxi.system.branding_api._font_metadata",
        lambda uploaded: ("FangSong_GB2312", True, 6763, "combined"),
    )
    monkeypatch.setattr(
        "kaxi.system.branding_api.put_font_asset", lambda **kwargs: "system/fonts/fangsong.ttf"
    )
    monkeypatch.setattr(
        "kaxi.system.branding_api.create_asset_view",
        lambda storage_key, mime_type: (
            f"https://assets.example/{storage_key}" if storage_key else ""
        ),
    )
    client = APIClient()
    client.force_authenticate(admin)
    response = client.post(
        "/api/v1/system/branding/fonts/",
        {"file": SimpleUploadedFile("仿宋_GB2312.ttf", b"font", content_type="font/ttf")},
        format="multipart",
    )
    assert response.status_code == 201, response.data
    assert response.data["font_library"][0]["coverage"] == "combined"
    assert response.data["font_library"][0]["cjk_glyph_count"] == 6763

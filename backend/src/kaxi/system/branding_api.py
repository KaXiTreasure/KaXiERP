from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_field
from fontTools.ttLib import TTFont
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from kaxi.documents.storage import (
    create_asset_view,
    delete_storage_object,
    put_branding_asset,
    put_font_asset,
)
from kaxi.identity.models import User
from kaxi.identity.services import user_has_atomic_permission
from kaxi.system.branding_services import refresh_bing_background
from kaxi.system.models import BrandingConfiguration, FontAsset

THEMES = {"forest", "ocean", "indigo", "coral", "graphite"}


class AssetUploadSerializer(serializers.Serializer[dict[str, object]]):
    file = serializers.FileField()


class FontUploadSerializer(AssetUploadSerializer):
    display_name = serializers.CharField(required=False, allow_blank=True)


class FontChoiceSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.IntegerField()
    family_name = serializers.CharField()
    display_name = serializers.CharField()
    coverage = serializers.CharField()
    latin_supported = serializers.BooleanField()
    cjk_glyph_count = serializers.IntegerField()
    font_url = serializers.URLField()


class BrandingSerializer(serializers.ModelSerializer[BrandingConfiguration]):
    logo_url = serializers.SerializerMethodField()
    login_background = serializers.SerializerMethodField()
    font_library = serializers.SerializerMethodField()

    class Meta:
        model = BrandingConfiguration
        fields = [
            "app_name",
            "version_name",
            "theme",
            "login_card_opacity",
            "login_footer_text",
            "login_footer_links",
            "login_slogan",
            "login_slogan_1",
            "login_slogan_2",
            "logo_url",
            "login_background",
            "background_source",
            "bing_image_title",
            "bing_image_copyright",
            "bing_image_date",
            "bing_last_synced_at",
            "primary_font",
            "western_font",
            "font_library",
        ]

    def get_logo_url(self, obj: BrandingConfiguration) -> str:
        return create_asset_view(storage_key=obj.logo_storage_key, mime_type=obj.logo_mime_type)

    def get_login_background(self, obj: BrandingConfiguration) -> str:
        return create_asset_view(
            storage_key=obj.background_storage_key, mime_type=obj.background_mime_type
        )

    def validate_theme(self, value: str) -> str:
        if value not in THEMES:
            raise serializers.ValidationError("未知界面风格。")
        return value

    def validate_login_card_opacity(self, value: int) -> int:
        if not 55 <= value <= 100:
            raise serializers.ValidationError("登录框透明度必须在 55% 到 100% 之间。")
        return value

    def validate_login_footer_links(self, value: object) -> list[dict[str, str]]:
        if not isinstance(value, list) or len(value) > 20:
            raise serializers.ValidationError("底部链接必须是最多 20 项的列表。")
        cleaned: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("底部链接格式不正确。")
            label = str(item.get("label", "")).strip()
            url = str(item.get("url", "")).strip()
            if not label or len(label) > 80:
                raise serializers.ValidationError("链接名称不能为空且最多 80 个字符。")
            valid_url = url.startswith(("http://", "https://")) or (
                url.startswith("/") and not url.startswith("//")
            )
            if len(url) > 1000 or not valid_url:
                raise serializers.ValidationError("链接地址必须使用 http、https 或站内路径。")
            cleaned.append({"label": label, "url": url})
        return cleaned

    @extend_schema_field(FontChoiceSerializer(many=True))
    def get_font_library(self, obj: BrandingConfiguration) -> list[dict[str, object]]:
        return [
            {
                "id": font.pk,
                "family_name": font.family_name,
                "display_name": font.display_name,
                "coverage": font.coverage,
                "latin_supported": font.latin_supported,
                "cjk_glyph_count": font.cjk_glyph_count,
                "font_url": create_asset_view(
                    storage_key=font.storage_key, mime_type=font.mime_type
                ),
            }
            for font in FontAsset.objects.order_by("display_name")
        ]

    def validate(self, attrs):  # type: ignore[no-untyped-def]
        primary = attrs.get("primary_font", getattr(self.instance, "primary_font", None))
        western = attrs.get("western_font", getattr(self.instance, "western_font", None))
        if primary and primary.coverage == FontAsset.Coverage.LATIN_ONLY:
            raise serializers.ValidationError("仅西文字体不能作为主字体。")
        if western and not western.latin_supported:
            raise serializers.ValidationError("西文字体槽必须选择包含西文字形的字体。")
        return attrs


def _configuration() -> BrandingConfiguration:
    configuration, _ = BrandingConfiguration.objects.get_or_create(singleton_key="global")
    return configuration


def _require_manage(request: Request) -> None:
    user = request.user
    if not isinstance(user, User) or not user_has_atomic_permission(user, "system.config.manage"):
        raise PermissionDenied("只有系统配置管理员可以修改品牌设置。")


@extend_schema(methods=["GET"], responses=BrandingSerializer)
@extend_schema(methods=["PATCH"], request=BrandingSerializer, responses=BrandingSerializer)
@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
def branding(request: Request) -> Response:
    configuration = _configuration()
    if request.method == "GET":
        return Response(BrandingSerializer(configuration).data)
    _require_manage(request)
    serializer = BrandingSerializer(configuration, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(BrandingSerializer(configuration).data)


@extend_schema(methods=["POST"], request=AssetUploadSerializer, responses=BrandingSerializer)
@extend_schema(methods=["DELETE"], responses=BrandingSerializer)
@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_branding_asset(request: Request, kind: str) -> Response:
    _require_manage(request)
    if kind not in {"logo", "background"}:
        raise ValidationError("未知品牌资产类型。")
    configuration = _configuration()
    if request.method == "DELETE":
        if kind == "logo":
            old_key = configuration.logo_storage_key
            delete_storage_object(old_key)
            configuration.logo_storage_key = ""
            configuration.logo_mime_type = ""
            fields = ["logo_storage_key", "logo_mime_type", "updated_at"]
        else:
            old_key = configuration.background_storage_key
            delete_storage_object(old_key)
            configuration.background_storage_key = ""
            configuration.background_mime_type = ""
            configuration.background_source = BrandingConfiguration.BackgroundSource.LOCAL
            fields = [
                "background_storage_key",
                "background_mime_type",
                "background_source",
                "updated_at",
            ]
        configuration.save(update_fields=fields)
        return Response(BrandingSerializer(configuration).data)
    uploaded = request.FILES.get("file")
    if uploaded is None:
        raise ValidationError("请选择图片文件。")
    mime_type = str(uploaded.content_type or "")
    storage_key = put_branding_asset(
        kind=kind,
        filename=uploaded.name,
        body=uploaded,
        mime_type=mime_type,
    )
    old_key = (
        configuration.logo_storage_key if kind == "logo" else configuration.background_storage_key
    )
    if kind == "logo":
        configuration.logo_storage_key = storage_key
        configuration.logo_mime_type = mime_type
        fields = ["logo_storage_key", "logo_mime_type", "updated_at"]
    else:
        configuration.background_storage_key = storage_key
        configuration.background_mime_type = mime_type
        configuration.background_source = BrandingConfiguration.BackgroundSource.LOCAL
        fields = [
            "background_storage_key",
            "background_mime_type",
            "background_source",
            "updated_at",
        ]
    configuration.save(update_fields=fields)
    if old_key and old_key != storage_key:
        delete_storage_object(old_key)
    return Response(BrandingSerializer(configuration).data, status=status.HTTP_201_CREATED)


@extend_schema(methods=["POST"], responses=BrandingSerializer)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def refresh_bing_branding_background(request: Request) -> Response:
    _require_manage(request)
    try:
        configuration = refresh_bing_background()
    except (OSError, ValueError, KeyError) as exc:
        raise ValidationError(f"Bing 背景更新失败：{exc}") from exc
    return Response(BrandingSerializer(configuration).data)


def _font_metadata(uploaded) -> tuple[str, bool, int, str]:  # type: ignore[no-untyped-def]
    try:
        font = TTFont(uploaded)
        names = font["name"].names
        family = next(
            (name.toUnicode() for name in names if name.nameID == 1 and name.toUnicode().strip()),
            uploaded.name.rsplit(".", 1)[0],
        )
        characters: set[int] = set()
        for table in font["cmap"].tables:
            characters.update(table.cmap)
        latin = all(ord(char) in characters for char in "AZaz09")
        cjk_count = sum(codepoint in characters for codepoint in range(0x4E00, 0xA000))
        coverage = (
            FontAsset.Coverage.COMBINED
            if latin and cjk_count
            else FontAsset.Coverage.CJK_ONLY
            if cjk_count
            else FontAsset.Coverage.LATIN_ONLY
        )
        uploaded.seek(0)
        return family, latin, cjk_count, coverage
    except Exception as exc:
        raise ValidationError("无法读取字体字符表，文件可能损坏或格式不受支持。") from exc


@extend_schema(request=FontUploadSerializer, responses=BrandingSerializer)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_font(request: Request) -> Response:
    _require_manage(request)
    uploaded = request.FILES.get("file")
    if uploaded is None:
        raise ValidationError("请选择字体文件。")
    family, latin, cjk_count, coverage = _font_metadata(uploaded)
    mime_type = str(uploaded.content_type or "application/octet-stream")
    storage_key = put_font_asset(filename=uploaded.name, body=uploaded, mime_type=mime_type)
    FontAsset.objects.create(
        family_name=family,
        display_name=str(request.data.get("display_name", "")).strip() or family,
        storage_key=storage_key,
        mime_type=mime_type,
        original_filename=uploaded.name,
        coverage=coverage,
        latin_supported=latin,
        cjk_glyph_count=cjk_count,
    )
    return Response(BrandingSerializer(_configuration()).data, status=status.HTTP_201_CREATED)


@extend_schema(responses=BrandingSerializer)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_font(request: Request, pk: int) -> Response:
    _require_manage(request)
    asset = FontAsset.objects.get(pk=pk)
    if BrandingConfiguration.objects.filter(Q(primary_font=asset) | Q(western_font=asset)).exists():
        raise ValidationError("正在使用的字体不能删除，请先切换字体。")
    delete_storage_object(asset.storage_key)
    asset.delete()
    return Response(BrandingSerializer(_configuration()).data)

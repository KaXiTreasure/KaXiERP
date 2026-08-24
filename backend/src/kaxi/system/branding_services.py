import io
import json
import mimetypes
import urllib.parse
import urllib.request

from django.db import transaction
from django.utils import timezone

from kaxi.documents.storage import delete_storage_object, put_branding_asset
from kaxi.system.models import BrandingConfiguration

BING_ARCHIVE_URL = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=zh-CN"


def refresh_bing_background() -> BrandingConfiguration:
    with urllib.request.urlopen(BING_ARCHIVE_URL, timeout=20) as response:  # noqa: S310
        payload = json.load(response)
    image = payload["images"][0]
    image_url = urllib.parse.urljoin("https://www.bing.com", str(image["url"]))
    parsed = urllib.parse.urlparse(image_url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.bing.com", "bing.com"}:
        raise ValueError("Bing 返回了不受信任的图片地址。")
    with urllib.request.urlopen(image_url, timeout=45) as response:  # noqa: S310
        body = response.read()
        mime_type = response.headers.get_content_type()
    if not body or not mime_type.startswith("image/"):
        raise ValueError("Bing 图片下载失败或格式不正确。")
    suffix = mimetypes.guess_extension(mime_type) or ".jpg"
    storage_key = put_branding_asset(
        kind="background",
        filename=f"bing-{image.get('enddate', 'daily')}{suffix}",
        body=io.BytesIO(body),
        mime_type=mime_type,
    )
    with transaction.atomic():
        configuration, _ = BrandingConfiguration.objects.select_for_update().get_or_create(
            singleton_key="global"
        )
        old_key = configuration.background_storage_key
        configuration.background_source = BrandingConfiguration.BackgroundSource.BING
        configuration.background_storage_key = storage_key
        configuration.background_mime_type = mime_type
        configuration.bing_image_title = str(image.get("title", ""))[:300]
        configuration.bing_image_copyright = str(image.get("copyright", ""))[:1000]
        configuration.bing_image_date = str(image.get("enddate", ""))[:8]
        configuration.bing_last_synced_at = timezone.now()
        configuration.save(
            update_fields=[
                "background_source",
                "background_storage_key",
                "background_mime_type",
                "bing_image_title",
                "bing_image_copyright",
                "bing_image_date",
                "bing_last_synced_at",
                "updated_at",
            ]
        )
    if old_key != storage_key:
        delete_storage_object(old_key)
    return configuration

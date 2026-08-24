import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("KAXI_SECRET_KEY", "unsafe-local-placeholder")
DEBUG = False
ALLOWED_HOSTS = [host for host in os.environ.get("KAXI_ALLOWED_HOSTS", "").split(",") if host]
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.environ.get("KAXI_CSRF_TRUSTED_ORIGINS", "").split(",") if origin
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "kaxi.shared",
    "kaxi.system",
    "kaxi.master_data",
    "kaxi.identity",
    "kaxi.products",
    "kaxi.warehouse",
    "kaxi.inventory",
    "kaxi.sales",
    "kaxi.pricing",
    "kaxi.purchasing",
    "kaxi.manufacturing",
    "kaxi.prepack",
    "kaxi.finance",
    "kaxi.workflow",
    "kaxi.documents",
    "kaxi.integrations",
    "kaxi.trade",
    "kaxi.aftersales",
    "kaxi.analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("KAXI_DB_NAME", "kaxi_erp"),
        "USER": os.environ.get("KAXI_DB_USER", "kaxi_app"),
        "PASSWORD": os.environ.get("KAXI_DB_PASSWORD", ""),
        "HOST": os.environ.get("KAXI_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("KAXI_DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"options": "-c search_path=erp,public"},
    }
}

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "identity.User"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "kaxi.shared.pagination.StableCursorPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "kaxi.shared.api_exceptions.kaxi_exception_handler",
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 28800
SESSION_SAVE_EVERY_REQUEST = True

SPECTACULAR_SETTINGS = {
    "TITLE": "KAXI ERP API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "ActiveInactiveStatusEnum": [
            ("active", "启用"),
            ("inactive", "停用"),
        ],
    },
}

CELERY_BROKER_URL = os.environ.get("KAXI_REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("KAXI_REDIS_URL", "redis://127.0.0.1:6379/1")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_DEFAULT_QUEUE = "maintenance"
CELERY_TASK_ROUTES = {
    "auth.*": {"queue": "critical"},
    "inventory.*": {"queue": "critical"},
    "document.*": {"queue": "documents"},
    "integration.*": {"queue": "integration"},
    "finance.*": {"queue": "finance"},
    "asset.*": {"queue": "finance"},
    "payroll.*": {"queue": "finance"},
    "tax.*": {"queue": "finance"},
    "analytics.*": {"queue": "analytics"},
    "branding.*": {"queue": "maintenance"},
}
CELERY_BEAT_SCHEDULE = {
    "expire-user-overrides": {
        "task": "auth.expire_user_overrides",
        "schedule": 60.0,
    },
    "release-expired-reservations": {
        "task": "inventory.release_expired_reservations",
        "schedule": 60.0,
    },
    "expire-document-shares": {"task": "document.expire_shares", "schedule": 60.0},
    "activate-price-versions": {"task": "pricing.activate_versions", "schedule": 60.0},
    "escalate-overdue-approvals": {
        "task": "workflow.escalate_overdue_tasks",
        "schedule": 900.0,
    },
    "refresh-bing-login-background": {
        "task": "branding.refresh_bing_background",
        "schedule": 86400.0,
    },
}

KAXI_S3_ENDPOINT = os.environ.get("KAXI_S3_ENDPOINT", "http://127.0.0.1:9000")
KAXI_S3_ACCESS_KEY = os.environ.get("KAXI_S3_ACCESS_KEY", "")
KAXI_S3_SECRET_KEY = os.environ.get("KAXI_S3_SECRET_KEY", "")
KAXI_S3_BUCKET = os.environ.get("KAXI_S3_BUCKET", "kaxi-documents")
KAXI_S3_REGION = os.environ.get("KAXI_S3_REGION", "us-east-1")
KAXI_S3_PRESIGN_TTL = int(os.environ.get("KAXI_S3_PRESIGN_TTL", "900"))

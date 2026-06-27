"""
Django settings for openbook.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-only-change-in-production",
)

DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "corsheaders",
    "accounts",
    "books",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.FirstRunSetupMiddleware",
    "accounts.middleware_timezone.UserTimezoneMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "openbook.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "openbook.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "openbook.context_processors.app_version",
            ],
        },
    },
]

WSGI_APPLICATION = "openbook.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _database_from_url(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
    }


if DATABASE_URL:
    DATABASES = {"default": _database_from_url(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Tashkent")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "openbook_cache",
    }
}

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

def _parse_throttle_rates() -> dict[str, str]:
    rates = {
        "user": "1000/day",
        "auth": "5/min",
    }
    env_rates = os.environ.get("API_THROTTLE_RATES", "")
    if env_rates:
        for part in env_rates.split(","):
            part = part.strip()
            if "=" in part:
                scope, rate = part.split("=", 1)
                rates[scope.strip()] = rate.strip()
    return rates


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "openbook.api.renderers.EnvelopeJSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "openbook.api.pagination.EnvelopePagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "openbook.api.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "openbook.api.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": _parse_throttle_rates(),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "openbook API",
    "DESCRIPTION": "Self-hosted book tracker REST API",
    "VERSION": "0.1.0",
}

OPENLIBRARY_BASE_URL = os.environ.get(
    "OPENLIBRARY_BASE_URL", "https://openlibrary.org"
)
GOOGLE_BOOKS_BASE_URL = os.environ.get(
    "GOOGLE_BOOKS_BASE_URL", "https://www.googleapis.com/books/v1"
)
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "").strip()
OPENLIBRARY_CONTACT_EMAIL = os.environ.get("OPENLIBRARY_CONTACT_EMAIL", "").strip()
APP_VERSION = os.environ.get("APP_VERSION", "0.1.0")

METADATA_CONNECT_TIMEOUT = float(os.environ.get("METADATA_CONNECT_TIMEOUT", "5"))
METADATA_READ_TIMEOUT = float(os.environ.get("METADATA_READ_TIMEOUT", "10"))
METADATA_RETRY_COUNT = int(os.environ.get("METADATA_RETRY_COUNT", "1"))
METADATA_RETRY_BACKOFF = float(os.environ.get("METADATA_RETRY_BACKOFF", "1"))
METADATA_IMPORT_DELAY_SECONDS = float(os.environ.get("METADATA_IMPORT_DELAY_SECONDS", "0"))
IMPORT_GOODREADS_ENRICH_METADATA = os.environ.get(
    "IMPORT_GOODREADS_ENRICH_METADATA", "true"
).lower() in ("true", "1", "yes")
METADATA_WIKIDATA_ENABLED = os.environ.get("METADATA_WIKIDATA_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
METADATA_WIKIDATA_DELAY_SECONDS = float(os.environ.get("METADATA_WIKIDATA_DELAY_SECONDS", "1.0"))
METADATA_AUTO_APPLY_THRESHOLD = float(os.environ.get("METADATA_AUTO_APPLY_THRESHOLD", "0.82"))
METADATA_REVIEW_GAP_THRESHOLD = float(os.environ.get("METADATA_REVIEW_GAP_THRESHOLD", "0.08"))
METADATA_LOOKUP_STRATEGY = os.environ.get("METADATA_LOOKUP_STRATEGY", "chain").lower()
METADATA_HARDCOVER_ENABLED = os.environ.get("METADATA_HARDCOVER_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
HARDCOVER_API_TOKEN = os.environ.get("HARDCOVER_API_TOKEN", "").strip()
HARDCOVER_API_URL = os.environ.get(
    "HARDCOVER_API_URL", "https://api.hardcover.app/v1/graphql"
)
ISBNDB_API_KEY = os.environ.get("ISBNDB_API_KEY", "").strip()
ISBNDB_API_URL = os.environ.get("ISBNDB_API_URL", "https://api2.isbndb.com")

IMPORT_JOB_AUTO_PROCESS = os.environ.get("IMPORT_JOB_AUTO_PROCESS", "true").lower() in (
    "true",
    "1",
    "yes",
)
IMPORT_JOB_STALE_MINUTES = int(os.environ.get("IMPORT_JOB_STALE_MINUTES", "30"))
IMPORT_JOB_DEBUG_STALE_MINUTES = int(os.environ.get("IMPORT_JOB_DEBUG_STALE_MINUTES", "5"))
IMPORT_JOB_CANCEL_FINALIZE_SECONDS = int(os.environ.get("IMPORT_JOB_CANCEL_FINALIZE_SECONDS", "120"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
}

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

GITHUB_REPO_URL = os.environ.get(
    "GITHUB_REPO_URL",
    "https://github.com/JavohirMX/openbook",
)

# Production security (enabled when DEBUG=False)
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() in ("true", "1", "yes")
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_REFERRER_POLICY = "same-origin"

"""Settings for TubePulse CRM.

The defaults are safe for local development. Production deployments must set
DJANGO_SECRET_KEY, DJANGO_DEBUG=0, and DJANGO_ALLOWED_HOSTS.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-tubepulse-change-me-before-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG=0")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "trends.apps.TrendsConfig",
    "ai_studio.apps.AiStudioConfig",
    "dashboard.apps.DashboardConfig",
    "publishing.apps.PublishingConfig",
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

ROOT_URLCONF = "tubepulse.urls"

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
            ],
        },
    }
]

WSGI_APPLICATION = "tubepulse.wsgi.application"
ASGI_APPLICATION = "tubepulse.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.getenv("SQLITE_PATH", BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": int(os.getenv("SQLITE_TIMEOUT", "20"))},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "core.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard:overview"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Provider and media pipeline configuration.
TUBEPULSE_ENCRYPTION_KEY = os.getenv("TUBEPULSE_ENCRYPTION_KEY", "")
PUBLISHING_CREDENTIAL_KEY = (
    os.getenv("PUBLISHING_CREDENTIAL_KEY", "").strip()
    or TUBEPULSE_ENCRYPTION_KEY
)
TUBEPULSE_HTTP_TIMEOUT = int(os.getenv("TUBEPULSE_HTTP_TIMEOUT", "20"))
TUBEPULSE_MAX_DOWNLOAD_MB = int(os.getenv("TUBEPULSE_MAX_DOWNLOAD_MB", "250"))
TUBEPULSE_FFMPEG_THREADS = int(os.getenv("TUBEPULSE_FFMPEG_THREADS", "2"))
TUBEPULSE_RENDER_STALE_MINUTES = int(
    os.getenv("TUBEPULSE_RENDER_STALE_MINUTES", "90")
)
TUBEPULSE_SIMULATE_PUBLISHING = env_bool("TUBEPULSE_SIMULATE_PUBLISHING", DEBUG)
TUBEPULSE_AI_PIPELINE_CLASS = os.getenv(
    "TUBEPULSE_AI_PIPELINE_CLASS", "ai_studio.generation.TrendGenerationPipeline"
)
YOUTUBE_CLIENT_SECRETS_FILE = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "")
YOUTUBE_OAUTH_REDIRECT_URI = os.getenv("YOUTUBE_OAUTH_REDIRECT_URI", "")
PUBLISHING_SIMULATION_MODE = env_bool(
    "PUBLISHING_SIMULATION_MODE", TUBEPULSE_SIMULATE_PUBLISHING
)
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
YOUTUBE_OAUTH_STATE_MAX_AGE = int(os.getenv("YOUTUBE_OAUTH_STATE_MAX_AGE", "600"))
YOUTUBE_CATEGORY_ID = os.getenv("YOUTUBE_CATEGORY_ID", "22")
YOUTUBE_UPLOAD_CHUNK_SIZE = int(os.getenv("YOUTUBE_UPLOAD_CHUNK_SIZE", str(8 * 1024 * 1024)))
YOUTUBE_UPLOAD_MAX_CHUNKS = int(os.getenv("YOUTUBE_UPLOAD_MAX_CHUNKS", "10000"))
PUBLISHING_MAX_ATTEMPTS = int(os.getenv("PUBLISHING_MAX_ATTEMPTS", "3"))
PUBLISHING_STALE_MINUTES = int(os.getenv("PUBLISHING_STALE_MINUTES", "90"))

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{levelname} {asctime} {name}: {message}", "style": "{"}
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.server": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "tubepulse": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

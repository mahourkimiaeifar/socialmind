"""تنظیمات پروژهٔ Socia Mind — نسخهٔ Django."""
import os
import warnings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    """بارگذاری سادهٔ فایل .env بدون وابستگی بیرونی.

    مقادیر موجود در محیط سیستم همیشه بر .env اولویت دارند.
    هیچ‌گاه محتوای این فایل چاپ نمی‌شود.
    """
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    SECRET_KEY = "dev-only-insecure-key-change-me-before-production"
    warnings.warn(
        "DJANGO_SECRET_KEY تنظیم نشده است؛ از کلید موقت توسعه استفاده می‌شود.",
        RuntimeWarning,
    )

DEBUG = _bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [
    item.strip()
    for item in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if item.strip()
]

CSRF_TRUSTED_ORIGINS = [
    item.strip()
    for item in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if item.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "knowledge",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "sociamind.urls"

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
                "core.context_processors.site_context",
            ],
        },
    },
]

WSGI_APPLICATION = "sociamind.wsgi.application"
ASGI_APPLICATION = "sociamind.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "core.views.csrf_failure"

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# --- تنظیمات خصوصی مدل (فقط سمت سرور؛ هرگز به قالب یا جاوااسکریپت پاس داده نمی‌شود) ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_API_STYLE = os.environ.get("OPENAI_API_STYLE", "responses").strip().lower()
try:
    OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", "90") or "90")
except ValueError:
    OPENAI_TIMEOUT = 90


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default) or default)
    except (TypeError, ValueError):
        return default


# --- محدودیت‌های ایمنی و تجربهٔ کاربری ---
MESSAGE_MAX_LENGTH = _int("MESSAGE_MAX_LENGTH", 1500)
MAX_USER_MESSAGES_PER_CONVERSATION = _int("MAX_USER_MESSAGES_PER_CONVERSATION", 40)
MAX_MESSAGES_PER_CONVERSATION = _int("MAX_MESSAGES_PER_CONVERSATION", 100)
MAX_CONVERSATIONS_PER_SESSION = _int("MAX_CONVERSATIONS_PER_SESSION", 20)
MESSAGE_COOLDOWN_SECONDS = _int("MESSAGE_COOLDOWN_SECONDS", 2)
SCENARIO_MAX_SOURCES = _int("SCENARIO_MAX_SOURCES", 8)

# --- جزوه‌ها و بازیابی روشی ---
# پوشهٔ پیش‌فرض ورود جزوه‌ها؛ دستور import_handouts بدون آرگومان از همین استفاده می‌کند.
HANDOUTS_DIR = os.environ.get("HANDOUTS_DIR", str(Path.home() / "Documents" / "جزوه ها"))
# در هر نوبت گفتگو، جزوه‌ها بررسی می‌شوند تا سؤال تکمیلی هدفمند انتخاب شود.
HANDOUT_RETRIEVAL_PER_TURN = _bool("HANDOUT_RETRIEVAL_PER_TURN", True)
HANDOUT_TURN_SOURCES = _int("HANDOUT_TURN_SOURCES", 5)

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "core.services.llm": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

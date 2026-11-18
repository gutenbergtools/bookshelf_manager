import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(key, default=""):
    return os.environ.get(key, default)


def env_first(*keys, default=""):
    """Prefer the first non-empty env var (CATALOG_* over legacy BSM_*)."""
    for key in keys:
        value = os.environ.get(key)
        if value not in (None, ""):
            return value
    return default


def env_list_first(*keys, default=""):
    return [item.strip() for item in env_first(*keys, default=default).split(",") if item.strip()]


def env_list(key, default=""):
    return env_list_first(key, default=default)


LOG_DIR = Path(env("DJANGO_LOG_DIR", str(BASE_DIR / "logs")))
_DEFAULT_KEY = "insecure-development-key-do-not-use-in-production"
SECRET_KEY = env("DJANGO_SECRET_KEY", _DEFAULT_KEY)
DEBUG = env("DJANGO_DEBUG", "1") == "1"
if not DEBUG and SECRET_KEY == _DEFAULT_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DEBUG=0.")
CATALOG_APP = env_first("CATALOG_APP", "BSM_APP", default="catalog").strip().lower()
if CATALOG_APP not in ("catalog", "shelves"):
    raise ImproperlyConfigured("CATALOG_APP must be catalog or shelves.")
BSM_APP = CATALOG_APP  # legacy alias
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
for _key, _default in (
    ("PGHOST", "127.0.0.1"),
    ("PGPORT", "5432"),
    ("PGDATABASE", "gutenberg"),
    ("PGUSER", "gutenberg"),
):
    os.environ.setdefault(_key, env(_key, _default))
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "catalog.apps.CatalogConfig",
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
    "catalog.middleware.SecurityHeadersMiddleware",
]
ROOT_URLCONF = "catalog.urls_shelves" if CATALOG_APP == "shelves" else "catalog.urls"
WSGI_APPLICATION = "catalog.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "catalog" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "catalog.middleware.brand",
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env("DJANGO_DB_PATH", str(BASE_DIR / "auth.sqlite3")),
    },
    # Unmanaged mirrors / robot blocks (libgutenberg catalog). Auth + Change stay on SQLite.
    "gutenberg": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("PGDATABASE", "gutenberg"),
        "USER": env("PGUSER", "gutenberg"),
        "PASSWORD": env("PGPASSWORD", ""),
        "HOST": env("PGHOST", "127.0.0.1"),
        "PORT": env("PGPORT", "5432"),
        "OPTIONS": {"options": "-c search_path=public,robots"},
        # Avoid creating a second Postgres test DB; unmanaged models are not migrated.
        "TEST": {"MIRROR": "default"},
    },
}
DATABASE_ROUTERS = ["catalog.db.GutenbergRouter"]
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": env("DJANGO_CACHE_DIR", str(BASE_DIR / "cache")),
        "OPTIONS": {"MAX_ENTRIES": 2000},
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "catalog_manager.log"),
            "maxBytes": 5000000,
            "backupCount": 5,
            "formatter": "plain",
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["console", "file"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "shelves" if CATALOG_APP == "shelves" else "books"
LOGOUT_REDIRECT_URL = "login"
ADMIN_URL = env("DJANGO_ADMIN_URL", "admin").strip("/")
SESSION_COOKIE_NAME = "catalog_shelf" if CATALOG_APP == "shelves" else "catalog_cat"
CSRF_COOKIE_NAME = "catalog_shelf_csrf" if CATALOG_APP == "shelves" else "catalog_cat_csrf"
CSRF_COOKIE_HTTPONLY = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 1048576
SESSION_COOKIE_AGE = int(env("DJANGO_SESSION_AGE", "43200"))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if env("DJANGO_SECURE_COOKIES", "0") == "1":
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
PAGE_SIZE = int(env_first("CATALOG_PAGE_SIZE", "BSM_PAGE_SIZE", default="50"))
HIT_PAGE_SIZE = int(env_first("CATALOG_HIT_PAGE_SIZE", "BSM_HIT_PAGE_SIZE", default="8"))
RATE_LOGIN = env_first("CATALOG_RATE_LOGIN", "BSM_RATE_LOGIN", default="10/m")
RATE_POST = env_first("CATALOG_RATE_POST", "BSM_RATE_POST", default="60/m")
CATALOG_TRUSTED_PROXIES = env_list_first("CATALOG_TRUSTED_PROXIES", "BSM_TRUSTED_PROXIES", default="127.0.0.1,::1")
BSM_TRUSTED_PROXIES = CATALOG_TRUSTED_PROXIES  # legacy alias
RATELIMIT_IP_META_KEY = "catalog.proxy.client_ip"
CATALOG_REVIEWERS = env_list_first("CATALOG_REVIEWERS", "BSM_REVIEWERS")
CATALOG_CATALOGERS = env_list_first("CATALOG_CATALOGERS", "BSM_CATALOGERS")
CATALOG_SHELF_USERS = env_list_first("CATALOG_SHELF_USERS", "BSM_SHELF_USERS")
CATALOG_ROLLBACKERS = env_list_first("CATALOG_ROLLBACKERS", "BSM_ROLLBACKERS")
CATALOG_INFRA_ADMINS = env_list_first("CATALOG_INFRA_ADMINS", "BSM_INFRA_ADMINS")
BSM_REVIEWERS = CATALOG_REVIEWERS
BSM_CATALOGERS = CATALOG_CATALOGERS
BSM_SHELF_USERS = CATALOG_SHELF_USERS
BSM_ROLLBACKERS = CATALOG_ROLLBACKERS
BSM_INFRA_ADMINS = CATALOG_INFRA_ADMINS
os.makedirs(LOG_DIR, exist_ok=True)

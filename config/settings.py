"""
Nexora — Django settings.

Secure-by-default. Every secret, host and hardening flag is driven by
environment variables (a .env file is read automatically if present).
See docs/SECURITY.md for the full hardening checklist and README.md for the
quickstart.
"""
from pathlib import Path
import os
import secrets
import warnings

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or not raw.strip().isdigit():
        return default
    return int(raw)


# ---------------------------------------------------------------- secrets
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if env_bool("DJANGO_DEBUG", True):
        SECRET_KEY = "dev-only-" + secrets.token_hex(48)
        warnings.warn(
            "DJANGO_SECRET_KEY is not set -> using a random development key. "
            "Always set a real secret in production.",
            stacklevel=2,
        )
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
ALLOWED_HOSTS.append("testserver")  # required by the test client

CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS").split(",") if o.strip()]

# ---------------------------------------------------------------- apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "core.middleware.SecurityHeadersMiddleware",          # CSP + nonce + extra headers
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.LoginThrottleMiddleware",            # brute-force protection
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "core.middleware.site_processor",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------- database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
# PostgreSQL in production?  pip install "psycopg[binary]>=3.2" then replace
# the block above with the engine + host/user/password read from environment
# variables — everything else in this file is database-agnostic.

# ---------------------------------------------------------------- passwords
# Argon2id first = state of the art; PBKDF2 kept as a fallback for legacy hashes.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------- i18n / tz
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------- static/media
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------- transport security
# Flip these on when deploying behind HTTPS (see .env.example).
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
_cookies_secure = env_bool("DJANGO_COOKIE_SECURE", SECURE_SSL_REDIRECT)
_hsts = env_bool("DJANGO_HSTS", False)
SECURE_HSTS_SECONDS = 31536000 if _hsts else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _hsts
SECURE_HSTS_PRELOAD = _hsts
SESSION_COOKIE_SECURE = _cookies_secure
CSRF_COOKIE_SECURE = _cookies_secure
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if env_bool("DJANGO_BEHIND_PROXY", False) else None

# ---------------------------------------------------------------- cookie hardening
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"                       # clickjacking
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7          # 7-day sessions
SESSION_SAVE_EVERY_REQUEST = False

# ---------------------------------------------------------------- auth routing
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"
CSRF_FAILURE_VIEW = "core.views_errors.csrf_failure"

# ---------------------------------------------------------------- email
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DJANGO_FROM_EMAIL", "noreply@example.com")
# Production: switch EMAIL_BACKEND to smtp and read host/user/password from env.

# ---------------------------------------------------------------- app metadata
APP_NAME = "Nexora"
APP_TAGLINE = "Retail operating system — POS, stock, purchase, accounts, warranty, installment"

# ---------------------------------------------------------------- brute-force protection
AUTH_LOGIN_MAX_ATTEMPTS = env_int("DJANGO_LOGIN_MAX_ATTEMPTS", 5)
AUTH_LOGIN_WINDOW_SECONDS = env_int("DJANGO_LOGIN_WINDOW_SECONDS", 60)

# ---------------------------------------------------------------- misc hardening
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_500_000          # 2.5 MB request bodies
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

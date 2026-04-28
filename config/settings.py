from decimal import Decimal
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "SECRET_KEY",
    default="dev-only-secret-key-change-me",
)
DEBUG = env("DEBUG")
if not DEBUG and SECRET_KEY in {"", "change-me", "dev-only-secret-key-change-me"}:
    raise RuntimeError("SECRET_KEY must be set to a secure value when DEBUG is False.")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
USE_X_FORWARDED_HOST = env.bool("USE_X_FORWARDED_HOST", default=not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=not DEBUG)
SECURE_REFERRER_POLICY = env("SECURE_REFERRER_POLICY", default="same-origin")
SECURE_CONTENT_TYPE_NOSNIFF = env.bool("SECURE_CONTENT_TYPE_NOSNIFF", default=not DEBUG)

INSTALLED_APPS = [
    "daphne",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "pages",
    "analytics_dashboard",
    "products",
    "orders",
    "payments",
    "transactions",
    "shipping",
    "support_chat",
    "after_sales",
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

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site_config",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DB_ENGINE = env("DB_ENGINE", default="sqlite").lower()

if DB_ENGINE == "mysql":
    db_name = env("DB_NAME", default="xuanor")
    test_db_name = env("DB_TEST_NAME", default=db_name)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": db_name,
            "USER": env("DB_USER", default="xuanor"),
            "PASSWORD": env("DB_PASSWORD", default=""),
            "HOST": env("DB_HOST", default="127.0.0.1"),
            "PORT": env("DB_PORT", default="3306"),
            "OPTIONS": {"charset": "utf8mb4"},
            "TEST": {"NAME": test_db_name},
        }
    }
else:
    SQLITE_PATH = env("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3"))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": SQLITE_PATH,
        }
    }

CACHE_BACKEND = env("CACHE_BACKEND", default="filebased").lower()
CACHE_LOCATION = env("CACHE_LOCATION", default="/tmp/xuanor-cache")
CACHE_KEY_PREFIX = env("CACHE_KEY_PREFIX", default="xuanor")
CACHE_TABLE = env("CACHE_TABLE", default="django_cache")

if CACHE_BACKEND in {"locmem", "localmemory", "local-memory"}:
    DEFAULT_CACHE = {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "xuanor-default",
    }
elif CACHE_BACKEND in {"filebased", "filebasedcache", "file", "filesystem"}:
    DEFAULT_CACHE = {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": CACHE_LOCATION,
    }
elif CACHE_BACKEND in {"database", "db"}:
    DEFAULT_CACHE = {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": CACHE_TABLE,
    }
elif CACHE_BACKEND == "dummy":
    DEFAULT_CACHE = {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
else:
    DEFAULT_CACHE = {
        "BACKEND": env("CACHE_BACKEND"),
        "LOCATION": CACHE_LOCATION,
    }

DEFAULT_CACHE["KEY_PREFIX"] = CACHE_KEY_PREFIX
CACHES = {"default": DEFAULT_CACHE}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

if not DEBUG:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SITE_NAME = "XUANOR"
SITE_TITLE = "XUANOR | Quiet symbols for modern life"
SITE_DESCRIPTION = "XUANOR 是一个以东方象征与仪式美学为灵感的品牌展示与产品目录站。"
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000")
DEFAULT_CURRENCY = env("DEFAULT_CURRENCY", default="USD")
DEFAULT_SHIPPING_AMOUNT = Decimal(env("DEFAULT_SHIPPING_AMOUNT", default="15.00"))

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
PAYPAL_CLIENT_ID = env("PAYPAL_CLIENT_ID", default="")
PAYPAL_CLIENT_SECRET = env("PAYPAL_CLIENT_SECRET", default="")
PAYPAL_BASE_URL = env("PAYPAL_BASE_URL", default="https://api-m.sandbox.paypal.com")
EASYPOST_API_KEY = env("EASYPOST_API_KEY", default="")
CHAT_WIDGET_ENABLED = env.bool("CHAT_WIDGET_ENABLED", default=True)
CHAT_DEFAULT_OPERATOR_LANGUAGE = env("CHAT_DEFAULT_OPERATOR_LANGUAGE", default="zh-hans")
CHAT_POLL_INTERVAL_MS = env.int("CHAT_POLL_INTERVAL_MS", default=3000)
CHAT_TRANSLATION_PROVIDER = env("CHAT_TRANSLATION_PROVIDER", default="mock")
CHAT_TRANSLATION_API_KEY = env("CHAT_TRANSLATION_API_KEY", default="")
OPENCLAW_ENABLED = env.bool("OPENCLAW_ENABLED", default=False)
OPENCLAW_COMMAND = env("OPENCLAW_COMMAND", default="openclaw")
OPENCLAW_AGENT_ID = env("OPENCLAW_AGENT_ID", default="")
OPENCLAW_TIMEOUT_SECONDS = env.int("OPENCLAW_TIMEOUT_SECONDS", default=60)
OPENCLAW_AUTO_REPLY_ENABLED = env.bool("OPENCLAW_AUTO_REPLY_ENABLED", default=True)
OPENCLAW_DRAFT_ENABLED = env.bool("OPENCLAW_DRAFT_ENABLED", default=True)
OPENCLAW_SYSTEM_LABEL = env("OPENCLAW_SYSTEM_LABEL", default="OpenClaw")
CHAT_COOKIE_SECURE = env.bool("CHAT_COOKIE_SECURE", default=not DEBUG)
CHAT_COOKIE_HTTPONLY = env.bool("CHAT_COOKIE_HTTPONLY", default=True)
CHAT_RATE_LIMIT_WINDOW_SECONDS = env.int("CHAT_RATE_LIMIT_WINDOW_SECONDS", default=60)
CHAT_SESSION_RATE_LIMIT = env.int("CHAT_SESSION_RATE_LIMIT", default=20)
CHAT_SEND_RATE_LIMIT = env.int("CHAT_SEND_RATE_LIMIT", default=60)
CHAT_POLL_RATE_LIMIT = env.int("CHAT_POLL_RATE_LIMIT", default=240)
CHAT_REALTIME_ENABLED = env.bool("CHAT_REALTIME_ENABLED", default=False)
CHANNEL_LAYER_BACKEND = env("CHANNEL_LAYER_BACKEND", default="memory").lower()
REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/1")

if not CHAT_REALTIME_ENABLED or CHANNEL_LAYER_BACKEND in {"memory", "inmemory", "in_memory", "locmem"}:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
            },
        }
    }

SHIP_FROM_ADDRESS_LINE1 = env("SHIP_FROM_ADDRESS_LINE1", default="")
SHIP_FROM_ADDRESS_LINE2 = env("SHIP_FROM_ADDRESS_LINE2", default="")
SHIP_FROM_CITY = env("SHIP_FROM_CITY", default="")
SHIP_FROM_STATE = env("SHIP_FROM_STATE", default="")
SHIP_FROM_POSTAL_CODE = env("SHIP_FROM_POSTAL_CODE", default="")
SHIP_FROM_COUNTRY = env("SHIP_FROM_COUNTRY", default="US")

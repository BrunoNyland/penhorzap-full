"""
Django settings for penhorzap project.
"""

import os
from pathlib import Path

import dotenv
from django.core.exceptions import ImproperlyConfigured

# BASE_DIR = .../pwa.brunonyland.com/www
BASE_DIR = Path(__file__).resolve().parent.parent
# PROJECT_ROOT = .../pwa.brunonyland.com  (where .env, venv, staticfiles, media live)
PROJECT_ROOT = BASE_DIR.parent

dotenv.load_dotenv(PROJECT_ROOT / ".env")

DJANGO_IS_PRODUCTION = int(os.environ.get("DJANGO_IS_PRODUCTION", 0))

if DJANGO_IS_PRODUCTION:
    SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
    if not SECRET_KEY:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY não está definida no ambiente. Em produção "
            "(DJANGO_IS_PRODUCTION=1) essa variável é obrigatória — defina-a "
            "no .env antes de subir o serviço."
        )
else:
    SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")

DEBUG = not DJANGO_IS_PRODUCTION

ALLOWED_HOSTS = ["pwa.brunonyland.com", "www.pwa.brunonyland.com", "127.0.0.1", "localhost"]

CSRF_TRUSTED_ORIGINS = ["https://pwa.brunonyland.com"]

# Application definition

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
    "django_q",
    "core",
    "whatsapp",
    "ia",
    "api",
    "painel",
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

ROOT_URLCONF = "penhorzap.urls"

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
    },
]

WSGI_APPLICATION = "wsgi.application"

# Database

DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite3")

if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DB_NAME", ""),
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET collation_connection = utf8mb4_unicode_ci, sql_mode='STRICT_TRANS_TABLES'",
                "use_unicode": True,
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": PROJECT_ROOT / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = str(PROJECT_ROOT / "staticfiles")

MEDIA_URL = "/media/"
MEDIA_ROOT = str(PROJECT_ROOT / "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Production hardening -------------------------------------------------

if DJANGO_IS_PRODUCTION:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_REFERRER_POLICY = "same-origin"

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "django.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10MB
            "backupCount": 5,
            "formatter": "verbose",
            "delay": True,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        # Loggers dedicados usados pelos apps whatsapp/ia (ver AGENTS.md);
        # sem handlers próprios — propagam para os handlers do root
        # (console + arquivo) evitando duplicar linhas de log.
        "whatsapp": {
            "level": "INFO",
            "propagate": True,
        },
        "ia": {
            "level": "INFO",
            "propagate": True,
        },
    },
}

# --- Cache ------------------------------------------------------------------
# LocMemCache explícito: documenta a intenção (cache em memória por processo,
# não compartilhado entre workers do gunicorn). Trocar por Redis/Memcached se
# for necessário cache compartilhado entre processos.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "penhorzap-locmem",
    }
}

# --- Third-party integrations ----------------------------------------------

EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "http://127.0.0.1:8080")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.environ.get("EVOLUTION_INSTANCE", "penhorzap")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "")

# --- django-q2 (async task queue, ORM broker on the same MySQL database) --

Q_CLUSTER = {
    "name": "penhorzap",
    "orm": "default",
    "workers": 2,
    "timeout": 120,
    "retry": 300,
    "queue_limit": 50,
    "bulk": 10,
    "catch_up": False,
}

# --- Django REST Framework --------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "api.views.custom_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "penhorzap API",
    "DESCRIPTION": "API de backoffice para operadores humanos: consultar solicitações geradas pela IA, atualizar status e enviar boletos aos clientes.",
    "VERSION": "1.0.0",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
    "SCHEMA_PATH_PREFIX": "/api/",
}

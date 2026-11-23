"""Configuración de Novera. Todo lo sensible se lee de variables de entorno (.env)."""

import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"


def env_bool(nombre, defecto=False):
    return os.environ.get(nombre, str(defecto)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def env_list(nombre, defecto=""):
    return [v.strip() for v in os.environ.get(nombre, defecto).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "solo-para-desarrollo-no-usar-en-produccion"
    else:
        raise ImproperlyConfigured("Define DJANGO_SECRET_KEY (o DJANGO_DEBUG=1 en desarrollo).")

# localhost siempre: lo usa el healthcheck del contenedor (/salud/)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS") + ["localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.clientes",
    "apps.facturas",
    "apps.usuarios",
    "apps.trabajos",
    "apps.configuracion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.usuarios.middleware.RolMiddleware",
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
                "apps.usuarios.context_processors.rol",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Sin DATABASE_URL se usa SQLite (desarrollo). En el VPS docker-compose define PostgreSQL.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Guayaquil"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTHENTICATION_BACKENDS = ["apps.usuarios.backends.UsuarioSinMayusculasBackend"]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

# Detrás de Caddy (HTTPS terminado en el proxy)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", not TESTING)
    SECURE_REDIRECT_EXEMPT = [r"^salud/$"]
    # Activa HSTS (p. ej. 31536000) solo cuando el dominio ya funcione bien con HTTPS.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# --- Novera ---
# Serie SRI (establecimiento-punto de emisión) para numerar facturas: 001-001-000000123
NOVERA_SERIE_FACTURA = os.environ.get("NOVERA_SERIE_FACTURA", "001-001")
NOVERA_IVA_DEFECTO = 15
NOVERA_DIAS_CREDITO_DEFECTO = 30

# Datos del emisor: se editan en Novera → Configuración (base de datos). Estas variables solo son el respaldo
# si todavía no se ha guardado nada allí.
NOVERA_EMPRESA = {
    "razon_social": os.environ.get("NOVERA_EMPRESA_RAZON_SOCIAL", ""),
    "nombre_comercial": os.environ.get("NOVERA_EMPRESA_NOMBRE_COMERCIAL", ""),
    "ruc": os.environ.get("NOVERA_EMPRESA_RUC", ""),
    "direccion": os.environ.get("NOVERA_EMPRESA_DIRECCION", ""),
    "telefono": os.environ.get("NOVERA_EMPRESA_TELEFONO", ""),
    "email": os.environ.get("NOVERA_EMPRESA_EMAIL", ""),
    "web": os.environ.get("NOVERA_EMPRESA_WEB", ""),
}
# Logo de respaldo para los PDF si no se subió uno en Configuración: static/img/logo-empresa.png
NOVERA_LOGO = "img/logo-empresa.png"


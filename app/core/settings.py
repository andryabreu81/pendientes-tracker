import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Sin valor por defecto: una SECRET_KEY conocida permite falsificar
# sesiones de cualquier usuario.
SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")

# Necesario para que el formulario funcione al entrar por IP de red local
# (http://192.168.x.x:8000) y no solo por localhost.
CSRF_TRUSTED_ORIGINS = [
    o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tracker",
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

ROOT_URLCONF = "core.urls"

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

WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "pendientes"),
        "USER": os.getenv("DB_USER", "pendientes"),
        # Sin valor por defecto a proposito: si falta DB_PASSWORD el
        # sistema falla al arrancar y dice que falta, en lugar de correr
        # en silencio con una clave conocida.
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Caracas"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------
# Membrete institucional de los archivos exportados.
#
# Nada de esto esta escrito en el codigo: el nombre de una institucion
# impreso en un reporte que circula a nivel ejecutivo tiene que poder
# corregirse sin tocar Python, y el mismo sistema sirve si manana se
# despliega en otra parte.
# ---------------------------------------------------------------

ORG_NOMBRE = os.getenv("ORG_NOMBRE", "Banco Digital de los Trabajadores")
ORG_SIGLA = os.getenv("ORG_SIGLA", "BDT")
# Gerencia o division. Vacio = el membrete muestra solo el banco.
ORG_UNIDAD = os.getenv("ORG_UNIDAD", "")
ORG_CLASIFICACION = os.getenv("ORG_CLASIFICACION", "Uso interno")

# Azul institucional del logo. Sin el "#": openpyxl lo pide asi.
ORG_COLOR = os.getenv("ORG_COLOR", "203078")

ORG_LOGO = os.getenv("ORG_LOGO", str(BASE_DIR / "tracker" / "marca" / "bdt-logo.png"))

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_SAVE_EVERY_REQUEST = True

# Tamaño maximo del archivo que se sube (25 MB).
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}

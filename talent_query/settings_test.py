"""Settings para testes — usa SQLite (não precisa de PostgreSQL)."""

from .settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Estaticos sem manifesto (R-40): o manifesto so existe depois do collectstatic, e a
# suite renderiza templates com {% static %}. O settings.py ja escolhe o backend simples
# quando DEBUG, mas aqui e explicito para a suite nao depender do valor de DJANGO_DEBUG.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Remove postgres (unaccent) — SQLite não suporta
INSTALLED_APPS = [a for a in INSTALLED_APPS if a != "django.contrib.postgres"]  # noqa: F405

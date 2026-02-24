"""Settings para testes — usa SQLite (não precisa de PostgreSQL)."""

from .settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Remove postgres (unaccent) — SQLite não suporta
INSTALLED_APPS = [a for a in INSTALLED_APPS if a != "django.contrib.postgres"]  # noqa: F405

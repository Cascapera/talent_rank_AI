"""Settings para testes — usa SQLite (não precisa de PostgreSQL)."""

import os

# R-21: fora de DEBUG a aplicação se recusa a subir sem DJANGO_SECRET_KEY. Estes dois
# `setdefault` rodam **antes** do import abaixo, que é onde a checagem acontece — sem
# eles, a suíte não coleta nem um teste. `setdefault` e não `=` para o ambiente poder
# sobrescrever, se alguém quiser rodar a suíte simulando produção.
os.environ.setdefault("DJANGO_SECRET_KEY", "somente-para-a-suite-de-testes")
os.environ.setdefault("DJANGO_DEBUG", "True")

from .settings import *  # noqa: E402, F401, F403

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

"""Testes da configuracao de estaticos (R-40).

O bug que estes testes previnem e silencioso: `STATICFILES_STORAGE` foi removido no
Django 5.1, entao a linha continuou no settings sem efeito nenhum e ninguem percebeu por
um upgrade inteiro. Nada quebra quando isso acontece — so para de comprimir e de versionar.
"""

import importlib
import sys

import pytest

MODULO = "talent_query.settings"


def _recarrega_settings(monkeypatch, debug: str):
    """Importa o settings do zero com um DJANGO_DEBUG escolhido.

    Import limpo e não `reload`: o reload reexecuta o módulo no namespace existente, então
    um atributo definido só no ramo `not DEBUG` sobreviveria à carga seguinte com
    DEBUG=True. Hoje nenhuma asserção daqui cairia nessa armadilha; ela ficaria armada
    para a próxima pessoa (foi o que aconteceu no R-21).

    `load_dotenv` é neutralizado porque roda com override=True: um `.env` local decidiria
    o valor de DEBUG no lugar do teste.
    """
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("DJANGO_DEBUG", debug)
    anterior = sys.modules.pop(MODULO, None)
    try:
        return importlib.import_module(MODULO)
    finally:
        if anterior is not None:
            sys.modules[MODULO] = anterior


class TestBackendDeEstaticos:
    def test_fora_de_debug_usa_whitenoise_com_manifesto(self, monkeypatch):
        settings = _recarrega_settings(monkeypatch, "False")
        assert (
            settings.STORAGES["staticfiles"]["BACKEND"]
            == "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )

    def test_em_debug_usa_o_backend_simples(self, monkeypatch):
        """Sem isso o runserver exigiria collectstatic para abrir qualquer pagina."""
        settings = _recarrega_settings(monkeypatch, "True")
        assert (
            settings.STORAGES["staticfiles"]["BACKEND"]
            == "django.contrib.staticfiles.storage.StaticFilesStorage"
        )

    def test_nao_usa_mais_o_setting_removido_no_django_5_1(self, monkeypatch):
        settings = _recarrega_settings(monkeypatch, "False")
        assert not hasattr(settings, "STATICFILES_STORAGE"), (
            "STATICFILES_STORAGE foi removido no Django 5.1 e nao tem efeito nenhum"
        )

    def test_a_classe_do_whitenoise_existe(self):
        """Guarda contra upgrade do whitenoise que renomeie ou remova a classe."""
        from whitenoise.storage import CompressedManifestStaticFilesStorage

        assert CompressedManifestStaticFilesStorage is not None


class TestSuiteNaoDependeDeManifesto:
    def test_settings_test_forca_o_backend_simples(self):
        from django.conf import settings

        assert (
            settings.STORAGES["staticfiles"]["BACKEND"]
            == "django.contrib.staticfiles.storage.StaticFilesStorage"
        )


@pytest.mark.django_db
def test_a_pagina_renderiza_com_o_backend_da_suite(client_logged):
    """Fecha o ciclo: com o backend simples, {% static %} nao precisa de manifesto."""
    resposta = client_logged.get("/dashboard/")
    assert resposta.status_code == 200

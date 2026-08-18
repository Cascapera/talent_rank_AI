"""Testes do endurecimento de settings de produção (R-21).

Nada aqui testa código da aplicação — testa **configuração**, que é onde o D-7 morava. É
o tipo de coisa que ninguém percebe quebrar: um default trocado de volta não faz nenhum
teste de comportamento falhar, e a aplicação continua funcionando perfeitamente, só que
insegura.
"""

import importlib
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

CHAVE = "chave-de-teste-que-nao-e-a-do-repositorio"
MODULO = "talent_query.settings"


def _recarrega(monkeypatch, *, debug: str, chave: str | None = CHAVE):
    """Importa o settings do zero, com DEBUG e SECRET_KEY escolhidos.

    Import limpo e **não** `importlib.reload`: o reload reexecuta o módulo no namespace
    que já existe, então um `SESSION_COOKIE_SECURE` definido numa carga com DEBUG=False
    sobreviveria à carga seguinte com DEBUG=True — e o teste passaria a afirmar o
    contrário do que verifica.

    `load_dotenv` roda com override=True: sem neutralizar, um `.env` local decidiria o
    resultado no lugar do teste.
    """
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("DJANGO_DEBUG", debug)
    if chave is None:
        monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("DJANGO_SECRET_KEY", chave)

    anterior = sys.modules.pop(MODULO, None)
    try:
        return importlib.import_module(MODULO)
    finally:
        if anterior is not None:
            sys.modules[MODULO] = anterior


class TestSecretKey:
    def test_sem_chave_fora_de_debug_a_aplicacao_nao_sobe(self, monkeypatch):
        """Falhar no boot é barulhento e recuperável. Rodar com a chave publicada no Git
        é silencioso e não tem sintoma até alguém abusar."""
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
            _recarrega(monkeypatch, debug="False", chave=None)

    def test_a_mensagem_ensina_a_gerar_a_chave(self, monkeypatch):
        with pytest.raises(ImproperlyConfigured, match="get_random_secret_key"):
            _recarrega(monkeypatch, debug="False", chave=None)

    def test_em_debug_o_fallback_local_continua(self, monkeypatch):
        settings = _recarrega(monkeypatch, debug="True", chave=None)
        assert settings.SECRET_KEY

    def test_a_chave_do_repositorio_nao_e_mais_fallback(self, monkeypatch):
        """A chave antiga está no histórico do Git desde o primeiro commit."""
        settings = _recarrega(monkeypatch, debug="True", chave=None)
        assert "334cxy" not in settings.SECRET_KEY


class TestDebug:
    def test_o_default_e_desligado(self, monkeypatch):
        """Esquecer de configurar passou a ser seguro por omissão."""
        monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
        monkeypatch.delenv("DJANGO_DEBUG", raising=False)
        monkeypatch.setenv("DJANGO_SECRET_KEY", CHAVE)
        anterior = sys.modules.pop(MODULO, None)
        try:
            settings = importlib.import_module(MODULO)
        finally:
            if anterior is not None:
                sys.modules[MODULO] = anterior
        assert settings.DEBUG is False


class TestCookiesEHttps:
    def test_fora_de_debug_tudo_ligado(self, monkeypatch):
        settings = _recarrega(monkeypatch, debug="False")
        assert settings.SESSION_COOKIE_SECURE is True
        assert settings.CSRF_COOKIE_SECURE is True
        assert settings.SECURE_SSL_REDIRECT is True
        assert settings.SECURE_HSTS_SECONDS > 0

    def test_em_debug_nada_disso_vale(self, monkeypatch):
        """Cookie Secure em http://localhost simplesmente não é enviado: sem isso,
        desenvolvimento vira uma tela de login que nunca loga."""
        settings = _recarrega(monkeypatch, debug="True")
        assert getattr(settings, "SESSION_COOKIE_SECURE", False) is False
        assert getattr(settings, "SECURE_SSL_REDIRECT", False) is False

    def test_o_hsts_comeca_curto(self, monkeypatch):
        """O navegador memoriza o prazo. Um ano publicado com o HTTPS quebrado deixaria
        a usuária sem acesso, e o servidor não teria como desfazer."""
        settings = _recarrega(monkeypatch, debug="False")
        assert settings.SECURE_HSTS_SECONDS <= 3600

    def test_hsts_e_configuravel_para_subir_depois(self, monkeypatch):
        monkeypatch.setenv("SECURE_HSTS_SECONDS", "31536000")
        settings = _recarrega(monkeypatch, debug="False")
        assert settings.SECURE_HSTS_SECONDS == 31536000


class TestProxySsl:
    def test_fora_de_debug_o_header_vem_ligado(self, monkeypatch):
        """Não é preferência: o SECURE_SSL_REDIRECT depende dele para saber que a
        requisição já chegou por HTTPS. Sem o header, o site entra em laço de redirect."""
        monkeypatch.delenv("DJANGO_SECURE_PROXY_SSL", raising=False)
        settings = _recarrega(monkeypatch, debug="False")
        assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")

    def test_em_debug_nao_vem(self, monkeypatch):
        """Em desenvolvimento não há proxy nenhum, e confiar num header que qualquer
        cliente pode mandar é de graça."""
        monkeypatch.delenv("DJANGO_SECURE_PROXY_SSL", raising=False)
        settings = _recarrega(monkeypatch, debug="True")
        assert not hasattr(settings, "SECURE_PROXY_SSL_HEADER")

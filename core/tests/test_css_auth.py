"""Guarda da extração de CSS das telas de autenticação (R-28, sub-PR a).

Não há teste de front neste projeto e CSS quebra em silêncio — a validação de verdade é
visual, feita à mão. O que dá para automatizar é o que costuma quebrar sozinho: o
`<link>` sumir, o arquivo não existir, ou alguém devolver CSS para dentro do template.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

CSS_DIR = Path(settings.BASE_DIR) / "static" / "css"


@pytest.mark.parametrize("nome", ["tokens.css", "auth.css"])
def test_o_arquivo_de_css_existe(nome):
    # Com o ManifestStaticFilesStorage (R-40), `{% static %}` para arquivo inexistente
    # vira 500 na renderização — em produção, não aqui. Este teste é o aviso barato.
    assert (CSS_DIR / nome).is_file()


@pytest.mark.parametrize("rota", ["login", "signup"])
def test_a_tela_carrega_os_dois_css(client, rota):
    html = client.get(reverse(rota)).content.decode()

    assert "css/tokens.css" in html
    assert "css/auth.css" in html


def test_login_nao_tem_mais_css_inline(client):
    html = client.get(reverse("login")).content.decode()

    # O login não tem uma regra sequer que o cadastro não tenha: o bloco inteiro saiu.
    assert "<style>" not in html


def test_cadastro_mantem_inline_so_o_que_e_exclusivo(client):
    html = client.get(reverse("signup")).content.decode()

    assert "<style>" in html
    assert "link-primary" in html
    # E o que é compartilhado não voltou junto.
    assert "--primary-2" not in html
    assert "backdrop-filter" not in html


def test_a_imagem_de_fundo_saiu_por_caminho_relativo(client):
    """`{% static %}` não é processado dentro de um .css.

    O `<style>` do login tinha a tag Django dentro. No arquivo estático ela vira caminho
    relativo, e quem repõe o hash é o `collectstatic`. Se alguém colar a tag de volta,
    ela vai literal para o browser e o fundo some.
    """
    css = (CSS_DIR / "auth.css").read_text(encoding="utf-8")

    assert "{% static" not in css
    assert 'url("../img/back.png")' in css

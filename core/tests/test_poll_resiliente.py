"""Guarda do R-44: o poll de status não pode morrer numa falha de rede.

Achado na validação manual de 2026-08-19. Os polls se reagendavam **só** dentro do ramo
`running`; um `fetch` que falhasse caía num `return` ou num `catch` vazio e matava o laço
para sempre. A tela congelava no contador e nunca mais perguntava nada — inclusive depois
de o servidor voltar.

O caso em que isso dói é o mesmo que o R-20b existe para avisar: o deploy reiniciando o
serviço no meio de uma importação. O backend passava a responder "interrompida" e não
havia mais ninguém ouvindo.

Não há teste de front no projeto, então o que dá para travar é a forma do código — que é
exatamente o que uma edição distraída desfaz.
"""

from pathlib import Path

import pytest
from django.conf import settings

JS = Path(settings.BASE_DIR) / "static" / "js" / "job_detail.js"
TEMPLATE_POOL = Path(settings.BASE_DIR) / "templates" / "core" / "talent_pool.html"

ARQUIVOS = {
    "job_detail.js": JS,
    "talent_pool.html": TEMPLATE_POOL,
}


@pytest.mark.parametrize("nome", sorted(ARQUIVOS))
def test_nenhum_poll_desiste_em_resposta_ruim(nome):
    conteudo = ARQUIVOS[nome].read_text(encoding="utf-8")

    assert "if (!resp.ok) return;" not in conteudo, (
        "voltou a desistir sem reagendar — é o bug do R-44"
    )


@pytest.mark.parametrize("nome", sorted(ARQUIVOS))
def test_nenhum_catch_de_poll_engole_a_falha_em_silencio(nome):
    conteudo = ARQUIVOS[nome].read_text(encoding="utf-8")

    assert "// silêncio" not in conteudo, (
        "catch vazio num poll mata o laço; a falha tem que reagendar"
    )


@pytest.mark.parametrize("nome", sorted(ARQUIVOS))
def test_o_reagendamento_existe_e_e_usado(nome):
    conteudo = ARQUIVOS[nome].read_text(encoding="utf-8")

    assert "function reagendarPoll(poll)" in conteudo
    assert conteudo.count("reagendarPoll(poll);") >= 2, (
        "cada poll precisa reagendar nos dois caminhos de falha: resposta ruim e exceção"
    )


def test_os_tres_polls_da_tela_da_vaga_foram_cobertos():
    """Importação, busca disparada pelo botão e busca já em andamento na carga."""
    conteudo = JS.read_text(encoding="utf-8")

    assert conteudo.count("reagendarPoll(poll);") == 6, "3 polls × 2 caminhos de falha"


def test_o_poll_do_parecer_nao_foi_mexido():
    """Ele usa `setInterval`, que sobrevive a uma resposta ruim sozinho.

    Fica registrado para ninguém 'uniformizar' os quatro depois e trocar um laço que
    funciona por outro que precisa de reagendamento manual.
    """
    conteudo = JS.read_text(encoding="utf-8")

    assert "parecerPollInterval = setInterval(" in conteudo
    assert "if (!resp.ok) return null;" in conteudo

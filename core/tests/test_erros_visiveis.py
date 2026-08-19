"""R-42: os detalhes de erro da importação passam a aparecer na tela.

Achado em 2026-08-19: numa importação real de 5 PDFs, o resumo disse `1 erro(s)` e o
detalhe — `0005.pdf: Expecting value: line 1 column 1 (char 0)` — estava gravado no
payload, mas `grep error_details` em `templates/` e `static/js/` não devolvia nada.

Para quem opera, um número sem nome é o mesmo que não avisar: ela não sabe qual currículo
ficou de fora, nem tem como reenviar o certo.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings

from core.models import ImportJob
from core.services.candidate_import import _process_in_batches

pytestmark = pytest.mark.django_db


class TestListaViajaDuranteAExecucao:
    """Antes só o contador viajava; a lista existia apenas no payload final."""

    def test_o_callback_de_progresso_recebe_os_detalhes(self):
        recebidos = []

        def persist_fn(data, item):
            raise RuntimeError("banco recusou")

        _process_in_batches(
            [SimpleNamespace(name="0001.pdf")],
            batch_fn=lambda batch, _label: [{"name": "Ana", "linkedin_url": "x"}],
            single_fn=lambda item, _label: {"name": "Ana", "linkedin_url": "x"},
            persist_fn=persist_fn,
            progress_callback=lambda **kwargs: recebidos.append(kwargs),
        )

        durante = [r for r in recebidos if r.get("status") == "running"]
        assert durante, "nenhum progresso reportado"
        assert any("0001.pdf" in " ".join(r.get("error_details") or []) for r in durante), (
            "o nome do arquivo que falhou não chegou ao callback"
        )


class TestTelaMostraOsDetalhes:
    def _job(self, user, payload):
        return ImportJob.objects.create(
            user=user,
            kind=ImportJob.Kind.TALENT_POOL_IMPORT,
            status=ImportJob.Status.COMPLETED,
            processed=5,
            total=5,
            payload=payload,
        )

    def test_banco_de_talentos_lista_o_arquivo_que_falhou(self, client_logged, user):
        self._job(
            user,
            {
                "status": "completed",
                "result": {
                    "created": 0,
                    "updated": 4,
                    "unchanged": 0,
                    "skipped": 0,
                    "errors": 1,
                    "error_details": ["0005.pdf: o modelo não devolveu conteúdo"],
                },
            },
        )

        html = client_logged.get("/talentos/").content.decode()

        # Procura o <li> renderizado, nao a string solta: o proprio helper do JS mora
        # nesta pagina e conteria o texto do estilo, dando falso positivo.
        assert re.search(r"<li>[^<]*0005\.pdf[^<]*</li>", html), (
            "o número aparecia; o nome do arquivo, não"
        )
        assert "o modelo não devolveu conteúdo" in html

    def test_sem_erro_nao_aparece_lista_nenhuma(self, client_logged, user):
        self._job(
            user,
            {
                "status": "completed",
                "result": {
                    "created": 5,
                    "updated": 0,
                    "unchanged": 0,
                    "skipped": 0,
                    "errors": 0,
                    "error_details": [],
                },
            },
        )

        html = client_logged.get("/talentos/").content.decode()

        assert not re.search(r"<li>[^<]*\.pdf", html), "listou erro onde não houve nenhum"


class TestFront:
    """Sem teste de front no projeto: trava a forma, que é o que some numa edição."""

    ARQUIVOS = {
        "job_detail.js": Path(settings.BASE_DIR) / "static" / "js" / "job_detail.js",
        "talent_pool.html": Path(settings.BASE_DIR) / "templates" / "core" / "talent_pool.html",
    }

    @pytest.mark.parametrize("nome", sorted(ARQUIVOS))
    def test_a_lista_e_montada_e_escapada(self, nome):
        conteudo = self.ARQUIVOS[nome].read_text(encoding="utf-8")

        assert "function listaDeErros(detalhes)" in conteudo
        # Estes textos carregam nome de arquivo e mensagem de excecao, e entram por
        # innerHTML. Sem escape, um nome com `<` viraria HTML.
        assert "function escaparHtml(texto)" in conteudo
        assert "escaparHtml(d)" in conteudo

    @pytest.mark.parametrize("nome", sorted(ARQUIVOS))
    def test_a_lista_entra_nos_dois_momentos(self, nome):
        conteudo = self.ARQUIVOS[nome].read_text(encoding="utf-8")

        assert "listaDeErros(data.error_details)" in conteudo, "durante a importação"
        assert "listaDeErros(result.error_details)" in conteudo, "no resumo final"

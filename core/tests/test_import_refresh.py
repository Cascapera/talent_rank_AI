"""Testes do R-41: dar refresh não pode importar de novo.

O bug apareceu em produção em 2026-08-18, na primeira importação real depois do deploy do
R-20a: a tabela `core_importjob` mostrou **duas linhas** para um upload de 1 PDF. O dono
do projeto tinha dado F5 na página, e a view tratava o POST e renderizava no mesmo request
— então o browser remandava o multipart inteiro.

O custo não é cosmético: o fluxo da vaga manda cada candidato para o LLM, então uma
importação repetida é dinheiro gasto duas vezes e dois upserts correndo sobre o mesmo
candidato.
"""

import io
from unittest.mock import patch

import pytest
from django.urls import reverse

from core.models import Job

pytestmark = pytest.mark.django_db


def _pdf_falso(nome="cv.pdf"):
    return io.BytesIO(b"%PDF-1.4 conteudo qualquer"), nome


def _upload(client, url):
    conteudo, nome = _pdf_falso()
    conteudo.name = nome
    return client.post(url, {"candidates_zip": conteudo})


class TestTelaDaVaga:
    @pytest.fixture
    def url(self, user):
        vaga = Job.objects.create(user=user, title="Dev Python")
        return f"/vagas/{vaga.id}/"

    def test_post_responde_302_e_nao_200(self, client_logged, url):
        """200 no POST é o que permite o refresh reenviar."""
        with patch("core.views.threading.Thread") as thread:
            resposta = _upload(client_logged, url)

        assert resposta.status_code == 302
        assert thread.return_value.start.call_count == 1

    def test_o_refresh_depois_do_post_nao_importa_de_novo(self, client_logged, url):
        """Segue o redirect e recarrega: nenhuma thread nova."""
        with patch("core.views.threading.Thread") as thread:
            resposta = _upload(client_logged, url)
            client_logged.get(resposta["Location"])
            client_logged.get(resposta["Location"])

        assert thread.return_value.start.call_count == 1, (
            "recarregar a pagina depois do POST disparou outra importacao"
        )

    def test_a_mensagem_sobrevive_ao_redirect(self, client_logged, url):
        with patch("core.views.threading.Thread"):
            resposta = _upload(
                client_logged,
                url,
            )
        pagina = client_logged.get(resposta["Location"], follow=True)
        assert "Importação iniciada" in pagina.content.decode()

    def test_upload_sem_pdf_tambem_redireciona(self, client_logged, url):
        arquivo = io.BytesIO(b"nao sou pdf")
        arquivo.name = "notas.txt"
        with patch("core.views.threading.Thread") as thread:
            resposta = client_logged.post(url, {"candidates_zip": arquivo})
        assert resposta.status_code == 302
        thread.return_value.start.assert_not_called()


class TestBancoDeTalentos:
    def test_post_de_upload_responde_302(self, client_logged):
        with patch("core.views.threading.Thread") as thread:
            resposta = _upload(client_logged, reverse("talent_pool"))
        assert resposta.status_code == 302
        assert thread.return_value.start.call_count == 1

    def test_o_refresh_nao_importa_de_novo(self, client_logged):
        with patch("core.views.threading.Thread") as thread:
            resposta = _upload(client_logged, reverse("talent_pool"))
            client_logged.get(resposta["Location"])
        assert thread.return_value.start.call_count == 1

    def test_cadastro_manual_redireciona(self, client_logged):
        resposta = client_logged.post(
            reverse("talent_pool"),
            {"name": "Fulano", "linkedin_url": "https://linkedin.com/in/fulano"},
        )
        assert resposta.status_code == 302

    def test_formulario_invalido_continua_renderizando_com_erro(self, client_logged):
        """Redirect aqui jogaria fora os erros de validação — de propósito não tem."""
        resposta = client_logged.post(reverse("talent_pool"), {"name": ""})
        assert resposta.status_code == 200
        assert "Confira os campos obrigatórios" in resposta.content.decode()

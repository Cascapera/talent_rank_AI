"""Guarda do R-28 sub-PR b: o CSS do formulário de vaga saiu dos templates.

As 9 regras eram idênticas em `job_create.html` e `job_edit.html`. O que dá para travar
sem teste de front é o que uma edição distraída desfaz: o `<link>` sumir, o arquivo não
existir, ou o CSS voltar para dentro do template.

`jobs.html` e `job_detail.html` ficaram de fora **de propósito** — medido antes de
extrair, os dois não compartilham uma regra sequer com estes. Há teste registrando isso,
porque "consolidar tudo" é a tentação óbvia e criaria acoplamento entre telas hoje
independentes.
"""

from pathlib import Path

import pytest
from django.conf import settings

from core.models import Job

pytestmark = pytest.mark.django_db

CSS = Path(settings.BASE_DIR) / "static" / "css" / "formulario.css"
TEMPLATES = Path(settings.BASE_DIR) / "templates" / "core"


def test_o_arquivo_existe():
    assert CSS.is_file()


def test_tem_as_regras_que_sairam_dos_templates():
    conteudo = CSS.read_text(encoding="utf-8")

    for regra in (".form-wrap", ".form-grid", ".form-grid .full", ".field label", ".errorlist"):
        assert regra in conteudo, regra


class TestTelaDeCriar:
    def test_aponta_para_o_css(self, client_logged):
        html = client_logged.get("/vagas/nova/").content.decode()

        assert "css/formulario.css" in html

    def test_nao_sobrou_style_inline(self):
        conteudo = (TEMPLATES / "job_create.html").read_text(encoding="utf-8")

        # Este template tinha exatamente as 9 regras comuns e nada mais.
        assert "<style>" not in conteudo


class TestTelaDeEditar:
    @pytest.fixture
    def vaga(self, user):
        return Job.objects.create(user=user, title="Dev Python")

    def test_aponta_para_o_css(self, client_logged, vaga):
        html = client_logged.get(f"/vagas/{vaga.id}/editar/").content.decode()

        assert "css/formulario.css" in html

    def test_mantem_inline_so_o_que_e_dele(self, client_logged, vaga):
        html = client_logged.get(f"/vagas/{vaga.id}/editar/").content.decode()

        assert ".hint{" in html
        # E o que foi compartilhado não voltou junto.
        assert ".form-grid{" not in html


def test_as_outras_duas_telas_ficaram_de_fora():
    """`jobs.html` e `job_detail.html` não compartilham regra com o formulário.

    Se alguém consolidar os quatro num arquivo só, este teste cai — e é para cair.
    """
    for nome in ("jobs.html", "job_detail.html"):
        conteudo = (TEMPLATES / nome).read_text(encoding="utf-8")
        assert "css/formulario.css" not in conteudo, nome

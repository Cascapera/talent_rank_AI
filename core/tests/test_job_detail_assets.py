"""Testes do R-27: o JS da tela da vaga saiu do template.

Nao ha teste de comportamento de front neste projeto — a validacao do R-27 e manual.
O que da para travar automaticamente e o que uma edicao distraida desfaz sem querer:
o arquivo existir, a pagina apontar para ele, e o JS nao voltar para dentro do HTML.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import get_template

from core.models import Job

CAMINHO_JS = Path(settings.BASE_DIR) / "static" / "js" / "job_detail.js"
TEMPLATE = Path(settings.BASE_DIR) / "templates" / "core" / "job_detail.html"


class TestArquivoEstatico:
    def test_o_arquivo_existe(self):
        assert CAMINHO_JS.is_file()

    def test_tem_o_codigo_que_saiu_do_template(self):
        conteudo = CAMINHO_JS.read_text(encoding="utf-8")
        # Um marco de cada bloco funcional que estava inline.
        assert "data-status-url" in conteudo, "poll da importacao"
        assert "data-candidate-job-id" in conteudo, "troca de status do candidato"
        assert "parecer" in conteudo, "geracao de parecer"


class TestTemplate:
    def test_compila(self):
        get_template("core/job_detail.html")

    def test_nao_tem_mais_script_inline(self):
        conteudo = TEMPLATE.read_text(encoding="utf-8")
        assert "<script>" not in conteudo, "o JS voltou para dentro do template"

    def test_aponta_para_o_arquivo_estatico(self):
        conteudo = TEMPLATE.read_text(encoding="utf-8")
        assert "{% load static %}" in conteudo, "sem o load, o {% static %} nao resolve"
        assert "js/job_detail.js" in conteudo


@pytest.mark.django_db
class TestPaginaRenderizada:
    def test_a_pagina_carrega_o_js_e_nao_traz_codigo_inline(self, client_logged, user):
        vaga = Job.objects.create(user=user, title="Dev Python")

        resposta = client_logged.get(f"/vagas/{vaga.id}/")

        assert resposta.status_code == 200
        html = resposta.content.decode()
        assert '<script src="/static/js/job_detail.js" defer></script>' in html
        assert "document.getElementById('importStatus')" not in html

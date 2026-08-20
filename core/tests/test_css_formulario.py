"""Guarda do R-28 sub-PR b: o CSS do formulário de vaga saiu dos templates.

As 9 regras eram idênticas em `job_create.html` e `job_edit.html`. O que dá para travar
sem teste de front é o que uma edição distraída desfaz: o `<link>` sumir, o arquivo não
existir, ou o CSS voltar para dentro do template.

`jobs.html` e `job_detail.html` ficaram de fora **de propósito** — medido antes de
extrair, os dois não compartilham uma regra sequer com estes. Há teste registrando isso,
porque "consolidar tudo" é a tentação óbvia e criaria acoplamento entre telas hoje
independentes.
"""

import re
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


class TestContrasteDaMensagemDeErro:
    """R-46: o erro do formulário de vaga era ilegível.

    Era `color: #fecaca` — rosa claro de paleta de tema escuro — sobre o `.card` da área
    logada, `rgba(255,255,255,0.92)`. Contraste de ~1,4:1 contra os 4,5:1 mínimos.

    Achado na **validação visual** do R-28, e é o tipo de defeito que nenhum teste de CSS
    pega sozinho: a regra existia, estava na folha certa e tinha o valor que o template
    tinha antes. O que estava errado era o valor, contra um fundo que teste nenhum conhece.
    Por isso este teste calcula o contraste de verdade em vez de comparar strings.
    """

    FUNDO_DO_CARD = (255, 255, 255)  # rgba(255,255,255,0.92) sobre fundo claro
    MINIMO_WCAG_AA = 4.5

    @staticmethod
    def _luminancia(rgb) -> float:
        def canal(v):
            v = v / 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        r, g, b = (canal(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    @classmethod
    def _contraste(cls, a, b) -> float:
        la, lb = cls._luminancia(a), cls._luminancia(b)
        claro, escuro = max(la, lb), min(la, lb)
        return (claro + 0.05) / (escuro + 0.05)

    @staticmethod
    def _cor_do_errorlist() -> tuple[int, int, int]:
        conteudo = CSS.read_text(encoding="utf-8")
        bloco = conteudo.split(".errorlist{")[1].split("}")[0]
        hexa = re.search(r"color:\s*#([0-9a-fA-F]{6})", bloco).group(1)
        return tuple(int(hexa[i : i + 2], 16) for i in (0, 2, 4))

    def test_o_texto_do_erro_e_legivel_sobre_o_card(self):
        contraste = self._contraste(self._cor_do_errorlist(), self.FUNDO_DO_CARD)

        assert contraste >= self.MINIMO_WCAG_AA, (
            f"contraste de {contraste:.2f}:1 — a recrutadora não consegue ler por que a "
            f"vaga não salvou"
        )

    def test_o_rosa_de_tema_escuro_nao_volta(self):
        """`#fecaca` dá 1,44:1 aqui. Guarda contra reintrodução por cópia de paleta.

        Olha a **declaração ativa**, não o arquivo inteiro: o comentário do R-46 cita o
        valor antigo de propósito, para explicar o que foi corrigido. Um teste que
        proibisse a string no arquivo proibiria também documentar o motivo.
        """
        assert self._contraste((0xFE, 0xCA, 0xCA), self.FUNDO_DO_CARD) < self.MINIMO_WCAG_AA
        assert self._cor_do_errorlist() != (0xFE, 0xCA, 0xCA)

    def test_segue_a_mesma_cor_do_auth(self):
        """As duas folhas resolvem o mesmo problema; divergir de novo seria acidente."""
        auth = (Path(settings.BASE_DIR) / "static" / "css" / "auth.css").read_text(encoding="utf-8")
        assert "#7f1d1d" in auth
        assert "#7f1d1d" in CSS.read_text(encoding="utf-8")

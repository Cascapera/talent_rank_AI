"""PDF órfão a cada reimportação (R-31, etapa 1).

O nome do currículo tem uuid (`resume_upload_to`), então regravar **nunca** sobrescreve:
cria arquivo novo e abandona o anterior em disco, sem nenhuma referência no banco.
`_upsert_candidate` regravava sempre — inclusive quando nada mudou —, então reimportar o
mesmo candidato 10 vezes deixava 10 PDFs, 9 inalcançáveis.

Estes testes fixam a etapa 1: **parar de gerar órfão novo**. Limpar os que já existem em
produção é etapa 2, em comando separado, depois de conferência manual — apagar arquivo de
currículo é irreversível.
"""

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from core.models import Candidate
from core.pdf import _resume_path, _save_resume_pdf

pytestmark = pytest.mark.django_db

User = get_user_model()

PDF_A = b"%PDF-1.4 curriculo A"
PDF_B = b"%PDF-1.4 curriculo B, outra versao"


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return Path(settings.MEDIA_ROOT)


@pytest.fixture
def user(db):
    return User.objects.create_user(username="recrutadora", password="x")


@pytest.fixture
def candidate(user):
    return Candidate.objects.create(
        user=user,
        name="Ana Souza",
        linkedin_url="https://linkedin.com/in/ana-souza",
    )


def pdf_file(tmp_path, content=PDF_A, name="0001.pdf"):
    p = tmp_path / name
    p.write_bytes(content)
    return p


def files_on_disk(media_root) -> list[Path]:
    return sorted(p for p in media_root.rglob("*.pdf") if p.is_file())


class TestConteudoIdentico:
    """O caso comum: a recrutadora reimporta o mesmo lote."""

    def test_regravar_o_mesmo_conteudo_nao_cria_arquivo_novo(self, candidate, media, tmp_path):
        origem = pdf_file(tmp_path)
        _save_resume_pdf(candidate, origem)
        primeiro = candidate.resume_pdf.name

        _save_resume_pdf(candidate, origem)

        assert candidate.resume_pdf.name == primeiro
        assert len(files_on_disk(media)) == 1

    def test_dez_reimportacoes_deixam_um_arquivo(self, candidate, media, tmp_path):
        """O número do diagnóstico: 10 reimportações deixavam 10 PDFs, 9 inalcançáveis."""
        origem = pdf_file(tmp_path)
        for _ in range(10):
            _save_resume_pdf(candidate, origem)

        assert len(files_on_disk(media)) == 1
        assert _resume_path(candidate) is not None

    def test_o_arquivo_que_fica_e_legivel(self, candidate, media, tmp_path):
        origem = pdf_file(tmp_path)
        _save_resume_pdf(candidate, origem)
        _save_resume_pdf(candidate, origem)

        assert Path(candidate.resume_pdf.path).read_bytes() == PDF_A


class TestConteudoDiferente:
    """Currículo atualizado: o novo entra, o antigo sai — nesta ordem."""

    def test_conteudo_novo_substitui_e_apaga_o_antigo(self, candidate, media, tmp_path):
        antigo_origem = pdf_file(tmp_path, PDF_A, "antigo.pdf")
        _save_resume_pdf(candidate, antigo_origem)
        antigo = Path(candidate.resume_pdf.path)

        novo_origem = pdf_file(tmp_path, PDF_B, "novo.pdf")
        _save_resume_pdf(candidate, novo_origem)

        assert not antigo.exists()
        assert Path(candidate.resume_pdf.path).read_bytes() == PDF_B
        assert len(files_on_disk(media)) == 1

    def test_mesmo_tamanho_conteudo_diferente_ainda_troca(self, candidate, media, tmp_path):
        """Tamanho igual não é conteúdo igual — a comparação não pode parar no `stat`."""
        a = pdf_file(tmp_path, b"%PDF-1.4 aaaa", "a.pdf")
        _save_resume_pdf(candidate, a)
        antigo = Path(candidate.resume_pdf.path)

        b = pdf_file(tmp_path, b"%PDF-1.4 bbbb", "b.pdf")
        _save_resume_pdf(candidate, b)

        assert not antigo.exists()
        assert Path(candidate.resume_pdf.path).read_bytes() == b"%PDF-1.4 bbbb"


class TestBordas:
    def test_primeiro_curriculo_do_candidato_e_gravado(self, candidate, media, tmp_path):
        assert not candidate.resume_pdf

        _save_resume_pdf(candidate, pdf_file(tmp_path))

        assert candidate.resume_pdf
        assert candidate.resume_pdf.name.startswith(f"resumes/{candidate.user_id}/")
        assert len(files_on_disk(media)) == 1

    def test_registro_no_banco_com_arquivo_sumido_regrava_sem_estourar(
        self, candidate, media, tmp_path
    ):
        """`media/` limpo sem limpar o banco: não há o que apagar, e a gravação segue."""
        origem = pdf_file(tmp_path)
        _save_resume_pdf(candidate, origem)
        Path(candidate.resume_pdf.path).unlink()

        _save_resume_pdf(candidate, origem)

        assert _resume_path(candidate) is not None
        assert len(files_on_disk(media)) == 1

    def test_nao_apaga_arquivo_ainda_referenciado_por_outra_linha(self, user, media, tmp_path):
        """Duas linhas apontando para o mesmo arquivo: o órfão é o mal menor.

        O uuid do nome torna isso improvável por importação, mas linha duplicada existe
        no banco de produção (achado do R-09) e apagar currículo não se desfaz.
        """
        ana = Candidate.objects.create(
            user=user, name="Ana", linkedin_url="https://linkedin.com/in/ana"
        )
        _save_resume_pdf(ana, pdf_file(tmp_path, PDF_A, "ana.pdf"))
        compartilhado = Path(ana.resume_pdf.path)
        copia = Candidate.objects.create(
            user=user,
            name="Ana (duplicata)",
            linkedin_url="https://linkedin.com/in/ana-2",
            resume_pdf=ana.resume_pdf.name,
        )

        _save_resume_pdf(ana, pdf_file(tmp_path, PDF_B, "ana2.pdf"))

        assert compartilhado.exists()
        assert Path(copia.resume_pdf.path) == compartilhado

    def test_nao_apaga_o_pdf_de_outro_candidato(self, user, media, tmp_path):
        """Cada candidato tem o seu arquivo; substituir um não pode encostar no outro."""
        ana = Candidate.objects.create(
            user=user, name="Ana", linkedin_url="https://linkedin.com/in/ana"
        )
        bruno = Candidate.objects.create(
            user=user, name="Bruno", linkedin_url="https://linkedin.com/in/bruno"
        )
        _save_resume_pdf(ana, pdf_file(tmp_path, PDF_A, "ana.pdf"))
        _save_resume_pdf(bruno, pdf_file(tmp_path, PDF_A, "bruno.pdf"))
        pdf_do_bruno = Path(bruno.resume_pdf.path)

        _save_resume_pdf(ana, pdf_file(tmp_path, PDF_B, "ana2.pdf"))

        assert pdf_do_bruno.exists()
        assert len(files_on_disk(media)) == 2

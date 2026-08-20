"""Currículo já importado não vai ao LLM de novo (R-45).

Medido em produção em 2026-08-20: dos 719 PDFs em disco, **231 (32%) eram cópia
byte-a-byte** de outro já presente. Cada um custou uma extração de LLM para chegar
exatamente ao mesmo resultado.

A chave é o SHA-256 do arquivo, e tem de ser: `linkedin_url` só se conhece **depois** de
extrair o PDF, que é justamente a chamada que se quer evitar.

Vale só para o banco de talentos. No fluxo de vaga o LLM extrai **e** avalia contra a
vaga na mesma chamada, e a avaliação é sempre necessária — pular ali não economizaria
nada e custaria a nota de aderência. Há teste fixando essa assimetria.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from core.models import Candidate
from core.pdf import _save_resume_pdf
from core.services.candidate_import import (
    import_candidates_from_folder,
    import_candidates_from_folder_no_ranking,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

PDF_ANA = b"%PDF-1.4 curriculo da Ana"
PDF_BRUNO = b"%PDF-1.4 curriculo do Bruno"


def llm_row(i=0, **overrides) -> dict:
    row = {
        "name": f"Candidato {i}",
        "linkedin_url": f"https://linkedin.com/in/candidato-{i}",
        "location": "São Paulo",
        "current_title": "Dev",
        "current_company": "ACME",
        "skills": ["Python"],
        "technologies": ["Django"],
        "languages": ["Português"],
        "certifications": [],
        "experience_time_years": 3.0,
        "average_tenure_years": 1.5,
        "seniority": "Pleno",
    }
    row.update(overrides)
    return row


@pytest.fixture
def pdf_dir(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    folder = tmp_path / "pdfs"
    folder.mkdir()
    return folder


@pytest.fixture
def user(db):
    return User.objects.create_user(username="recrutadora", password="x")


def escrever(folder, nome, conteudo):
    p = folder / nome
    p.write_bytes(conteudo)
    return p


def importar(folder, batch_results=None, **kwargs):
    with (
        patch("core.services.candidate_import.extract_candidates_batch_no_ranking") as mock_batch,
        patch("core.services.candidate_import.extract_candidate_no_ranking") as mock_single,
    ):
        if batch_results is not None:
            mock_batch.side_effect = batch_results
        result = import_candidates_from_folder_no_ranking(str(folder), **kwargs)
    return result, mock_batch, mock_single


class TestHashGravado:
    def test_salvar_curriculo_grava_o_sha256(self, tmp_path, settings, user):
        settings.MEDIA_ROOT = tmp_path / "media"
        candidate = Candidate.objects.create(user=user, name="Ana", linkedin_url="x")

        _save_resume_pdf(candidate, escrever(tmp_path, "0001.pdf", PDF_ANA))

        candidate.refresh_from_db()
        assert len(candidate.resume_sha256) == 64

    def test_curriculo_diferente_atualiza_o_hash(self, tmp_path, settings, user):
        settings.MEDIA_ROOT = tmp_path / "media"
        candidate = Candidate.objects.create(user=user, name="Ana", linkedin_url="x")

        _save_resume_pdf(candidate, escrever(tmp_path, "0001.pdf", PDF_ANA))
        candidate.refresh_from_db()
        primeiro = candidate.resume_sha256

        _save_resume_pdf(candidate, escrever(tmp_path, "0002.pdf", PDF_BRUNO))
        candidate.refresh_from_db()

        assert candidate.resume_sha256 != primeiro

    def test_candidato_anterior_ao_r45_ganha_hash_ao_reimportar(self, tmp_path, settings, user):
        """Sem isto, quem já estava no banco nunca seria reconhecido.

        O caminho de conteúdo idêntico do R-31 retorna cedo, sem regravar o arquivo —
        e era exatamente por ali que o candidato antigo passava, ficando sem hash para
        sempre.
        """
        settings.MEDIA_ROOT = tmp_path / "media"
        candidate = Candidate.objects.create(user=user, name="Ana", linkedin_url="x")
        _save_resume_pdf(candidate, escrever(tmp_path, "0001.pdf", PDF_ANA))
        Candidate.objects.filter(pk=candidate.pk).update(resume_sha256="")

        candidate.refresh_from_db()
        _save_resume_pdf(candidate, escrever(tmp_path, "0002.pdf", PDF_ANA))

        candidate.refresh_from_db()
        assert len(candidate.resume_sha256) == 64


class TestBancoDeTalentos:
    def test_curriculo_ja_no_banco_nao_vai_ao_llm(self, pdf_dir, user):
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        primeiro, mock_batch, _ = importar(pdf_dir, [[llm_row(0)]], user_id=user.id)
        assert primeiro["created"] == 1
        assert mock_batch.call_count == 1

        segundo, mock_batch2, _ = importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        assert mock_batch2.call_count == 0, "chamou o LLM para um currículo já conhecido"
        assert segundo["already_known"] == 1
        assert segundo["created"] == 0
        assert Candidate.objects.count() == 1

    def test_lote_misto_manda_ao_llm_so_o_que_e_novo(self, pdf_dir, user):
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        escrever(pdf_dir, "0002.pdf", PDF_BRUNO)
        result, mock_batch, _ = importar(pdf_dir, [[llm_row(1)]], user_id=user.id)

        enviados = mock_batch.call_args[0][0]
        assert [p.name for p in enviados] == ["0002.pdf"]
        assert result["already_known"] == 1
        assert result["created"] == 1

    def test_o_mesmo_perfil_duas_vezes_no_mesmo_lote(self, pdf_dir, user):
        """Ela exporta o mesmo candidato em duas buscas e os dois caem na pasta."""
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        escrever(pdf_dir, "0002.pdf", PDF_ANA)

        result, mock_batch, _ = importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        assert len(mock_batch.call_args[0][0]) == 1
        assert result["already_known"] == 1
        assert Candidate.objects.count() == 1

    def test_curriculo_atualizado_volta_ao_llm(self, pdf_dir, user):
        """Candidato mexeu no perfil: bytes diferentes, tem de ser reprocessado."""
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        escrever(pdf_dir, "0001.pdf", PDF_ANA + b" agora com uma certificacao nova")
        result, mock_batch, _ = importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        assert mock_batch.call_count == 1
        assert result["already_known"] == 0

    def test_o_total_continua_sendo_o_que_ela_selecionou(self, pdf_dir, user):
        """A tela mostra `3/5`: o denominador é o que ela escolheu, não o que sobrou."""
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        importar(pdf_dir, [[llm_row(0)]], user_id=user.id)
        escrever(pdf_dir, "0002.pdf", PDF_BRUNO)

        result, _, _ = importar(pdf_dir, [[llm_row(1)]], user_id=user.id)

        assert result["total"] == 2
        soma = (
            result["created"]
            + result["updated"]
            + result["unchanged"]
            + result["skipped"]
            + result["already_known"]
            + result["errors"]
        )
        assert soma == result["total"], "a conta da importação tem de fechar (R-32)"

    def test_progresso_chega_ao_fim_quando_todos_ja_sao_conhecidos(self, pdf_dir, user):
        """Sem isto a tela ficaria em 0/2 para sempre — o R-20b/R-44 de novo."""
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        escrever(pdf_dir, "0002.pdf", PDF_BRUNO)
        importar(pdf_dir, [[llm_row(0), llm_row(1)]], user_id=user.id)

        chamadas = []
        with patch("core.services.candidate_import.extract_candidates_batch_no_ranking"):
            import_candidates_from_folder_no_ranking(
                str(pdf_dir),
                user_id=user.id,
                progress_callback=lambda **kw: chamadas.append(kw),
            )

        final = chamadas[-1]
        assert final["status"] == "completed"
        assert final["processed"] == final["total"] == 2
        assert final["result"]["already_known"] == 2


class TestEscopo:
    def test_hash_de_outro_usuario_nao_conta_fora_do_pool_compartilhado(self, pdf_dir, user):
        outro = User.objects.create_user(username="outro", password="x")
        Candidate.objects.create(user=outro, name="Ana", linkedin_url="y", resume_sha256="a" * 64)
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        importar(pdf_dir, [[llm_row(0)]], user_id=outro.id)

        result, mock_batch, _ = importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        assert mock_batch.call_count == 1, "currículo de outro dono não pode pular o LLM"
        assert result["already_known"] == 0

    def test_pool_compartilhado_reconhece_curriculo_de_qualquer_dono(self, pdf_dir, user):
        outro = User.objects.create_user(username="outro", password="x")
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        importar(pdf_dir, [[llm_row(0)]], user_id=outro.id)

        result, mock_batch, _ = importar(pdf_dir, [[llm_row(0)]], user_id=user.id, shared_pool=True)

        assert mock_batch.call_count == 0
        assert result["already_known"] == 1


class TestFluxoDeVagaNaoDeduplica:
    def test_curriculo_conhecido_ainda_e_avaliado_contra_a_vaga(self, pdf_dir, user):
        """A assimetria decidida em 2026-08-20.

        No fluxo de vaga o LLM extrai **e** calcula a aderência na mesma chamada. Pular
        pouparia a extração e perderia a nota — que é o produto. Então aqui não se
        deduplica, por decisão, não por esquecimento.
        """
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        with patch("core.services.candidate_import.extract_candidates_batch_with_llm") as mock_vaga:
            mock_vaga.side_effect = [[llm_row(0, adherence=80)]]
            import_candidates_from_folder(
                str(pdf_dir),
                job_description="Vaga de Python",
                weights={},
                user_id=user.id,
            )

        assert mock_vaga.call_count == 1


class TestArquivoIlegivel:
    def test_pdf_que_nao_abre_segue_para_o_llm(self, pdf_dir, user, monkeypatch):
        """Errar para o lado caro, nunca para o lado que perde candidato."""
        escrever(pdf_dir, "0001.pdf", PDF_ANA)
        monkeypatch.setattr("core.services.candidate_import._digest", lambda _p: None)

        result, mock_batch, _ = importar(pdf_dir, [[llm_row(0)]], user_id=user.id)

        assert mock_batch.call_count == 1
        assert result["already_known"] == 0


class TestApareceNaTela:
    """O contador só serve se ela puder ver — a lição do R-42.

    Lá, o `error_details` estava no payload e nenhum template o lia: a tela dizia
    "1 erro(s)" sem nunca nomear o arquivo. Um número que não chega à tela não existe
    para quem opera.

    A tela do banco de talentos renderiza o resumo em dois lugares — o bloco do servidor,
    para quem chega com a importação já concluída, e o JS do poll, para quem está com a
    tela aberta. Os dois precisam do contador.
    """

    ARQUIVO = Path(settings.BASE_DIR) / "templates" / "core" / "talent_pool.html"

    def test_o_bloco_do_servidor_mostra_o_contador(self):
        conteudo = self.ARQUIVO.read_text(encoding="utf-8")
        assert "import_status.result.already_known" in conteudo
        assert "já no banco" in conteudo

    def test_o_poll_mostra_o_contador(self):
        conteudo = self.ARQUIVO.read_text(encoding="utf-8")
        assert "result.already_known" in conteudo

    def test_nao_polui_a_tela_quando_nao_ha_nenhum(self):
        """`0 já no banco` em toda importação nova seria ruído."""
        conteudo = self.ARQUIVO.read_text(encoding="utf-8")
        assert "{% if import_status.result.already_known %}" in conteudo
        assert "if (alreadyKnown > 0)" in conteudo

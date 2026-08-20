"""Testes da importação do banco de talentos (sem ranking).

Inclui o teste de regressão do R-09: o fallback individual ignorava o
`shared_pool`, fazendo usuário PREMIUM duplicar candidato quando o lote falhava.
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from core.models import Candidate
from core.services.candidate_import import import_candidates_from_folder_no_ranking

pytestmark = pytest.mark.django_db

User = get_user_model()


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


def make_pdfs(folder, count):
    """Currículos de candidatos **diferentes**, portanto de conteúdo diferente.

    O conteúdo variar por índice não é detalhe: desde o R-45 a importação reconhece pelo
    SHA-256 um currículo que já está no banco e não o manda ao LLM. Este fixture gravava
    os mesmos bytes em todos os arquivos e esperava N candidatos distintos — uma
    combinação que não existe na realidade, e que a partir do R-45 significa outra coisa
    (o mesmo perfil exportado duas vezes). Para esse caso há teste próprio.
    """
    paths = []
    for i in range(count):
        p = folder / f"{i:04d}.pdf"
        p.write_bytes(f"%PDF-1.4 curriculo do candidato {i}".encode())
        paths.append(p)
    return paths


def run(folder, batch_results=None, single_results=None, **kwargs):
    with (
        patch("core.services.candidate_import.time.sleep"),
        patch("core.services.candidate_import.extract_candidates_batch_no_ranking") as mock_batch,
        patch("core.services.candidate_import.extract_candidate_no_ranking") as mock_single,
    ):
        if batch_results is not None:
            mock_batch.side_effect = batch_results
        if single_results is not None:
            mock_single.side_effect = single_results
        result = import_candidates_from_folder_no_ranking(str(folder), **kwargs)
    return result, mock_batch, mock_single


class TestBatchPath:
    def test_creates_candidates_without_any_job_link(self, pdf_dir, user):
        make_pdfs(pdf_dir, 2)
        result, _, _ = run(pdf_dir, [[llm_row(0), llm_row(1)]], user_id=user.id)

        assert result["created"] == 2
        assert Candidate.objects.count() == 2

    def test_shared_pool_updates_candidate_of_another_user(self, pdf_dir, user):
        outro = User.objects.create_user(username="outro", password="x")
        Candidate.objects.create(
            user=outro,
            name="Antigo",
            linkedin_url="https://linkedin.com/in/candidato-0",
        )
        make_pdfs(pdf_dir, 1)
        result, _, _ = run(pdf_dir, [[llm_row(0)]], user_id=user.id, shared_pool=True)

        assert result["created"] == 0
        assert result["updated"] == 1
        assert Candidate.objects.count() == 1

    def test_final_callback_carries_the_result(self, pdf_dir, user):
        """Contrato diferente do import_candidates_from_folder, que NÃO envia `result`."""
        make_pdfs(pdf_dir, 1)
        calls = []
        run(
            pdf_dir,
            [[llm_row(0)]],
            user_id=user.id,
            progress_callback=lambda **kw: calls.append(kw),
        )

        assert calls[-1]["status"] == "completed"
        assert calls[-1]["result"]["created"] == 1


class TestSharedPoolInFallback:
    """Regressão do R-09.

    O fallback individual do banco de talentos ignorava o `shared_pool` e procurava
    o candidato só dentro do usuário que estava importando. Para um usuário PREMIUM,
    isso criava um candidato duplicado em vez de atualizar o do pool compartilhado —
    e só no caminho de erro, o que tornava o bug quase invisível.
    """

    def test_fallback_respects_shared_pool_and_updates_instead_of_duplicating(self, pdf_dir, user):
        outro = User.objects.create_user(username="outro", password="x")
        Candidate.objects.create(
            user=outro,
            name="Antigo",
            linkedin_url="https://linkedin.com/in/candidato-0",
        )
        make_pdfs(pdf_dir, 1)

        result, _, mock_single = run(
            pdf_dir,
            batch_results=[RuntimeError("lote falhou")],
            single_results=[llm_row(0)],
            user_id=user.id,
            shared_pool=True,
        )

        assert mock_single.call_count == 1, "deveria ter caído no fallback individual"
        assert result["created"] == 0, "não pode criar duplicata do candidato do pool"
        assert result["updated"] == 1
        assert Candidate.objects.count() == 1
        # O dono não muda: o update não reatribui o candidato ao importador.
        assert Candidate.objects.get().user_id == outro.id

    def test_fallback_without_shared_pool_still_isolates_users(self, pdf_dir, user):
        """O contrário continua valendo: sem pool compartilhado, cada um tem o seu."""
        outro = User.objects.create_user(username="outro", password="x")
        Candidate.objects.create(
            user=outro,
            name="Antigo",
            linkedin_url="https://linkedin.com/in/candidato-0",
        )
        make_pdfs(pdf_dir, 1)

        result, _, _ = run(
            pdf_dir,
            batch_results=[RuntimeError("lote falhou")],
            single_results=[llm_row(0)],
            user_id=user.id,
            shared_pool=False,
        )

        assert result["created"] == 1
        assert Candidate.objects.count() == 2

    def test_batch_and_fallback_agree_on_shared_pool(self, pdf_dir, user):
        """Os dois caminhos têm que produzir o mesmo resultado para a mesma entrada.

        É essa equivalência que o bug quebrava: o caminho em lote atualizava e o
        fallback duplicava, dependendo apenas de a chamada em lote ter falhado.
        """
        outro = User.objects.create_user(username="outro", password="x")

        def cenario(via_fallback: bool):
            Candidate.objects.all().delete()
            Candidate.objects.create(
                user=outro,
                name="Antigo",
                linkedin_url="https://linkedin.com/in/candidato-0",
            )
            if via_fallback:
                return run(
                    pdf_dir,
                    batch_results=[RuntimeError("falhou")],
                    single_results=[llm_row(0)],
                    user_id=user.id,
                    shared_pool=True,
                )[0]
            return run(pdf_dir, [[llm_row(0)]], user_id=user.id, shared_pool=True)[0]

        make_pdfs(pdf_dir, 1)
        em_lote = cenario(via_fallback=False)
        no_fallback = cenario(via_fallback=True)

        assert em_lote["created"] == no_fallback["created"]
        assert em_lote["updated"] == no_fallback["updated"]

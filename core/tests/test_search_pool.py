"""Characterization tests de `search_and_rank_candidates_from_pool` (R-33 / T-7).

Última função grande sem teste: 309 linhas, o maior bloco do `pdf_extractor.py`. É ela
que a recrutadora dispara em "buscar candidatos do banco para esta vaga".

Como em R-05, R-06 e R-07: estes testes registram o que o sistema faz HOJE, não o que
deveria fazer. O que estiver marcado como QUIRK está fixado de propósito.

**Destrava o 3º laço de lotes**, que ficou de fora do R-10 justamente por não ter teste
— com esta rede, converter para `_process_in_batches` deixa de ser aposta.

Nenhum teste chama a API do Gemini: as 4 funções do `llm_extractor` usadas aqui são
mockadas, e `time.sleep` também (o código dorme 1s entre lotes e 2s por candidato no
fallback).
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile

from core.models import Candidate, CandidateJob, Job
from core.pdf_extractor import search_and_rank_candidates_from_pool

pytestmark = pytest.mark.django_db

User = get_user_model()

WEIGHTS = {"skills": 40, "technologies": 35, "experience": 25}


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def job(user):
    return Job.objects.create(user=user, title="Dev Python")


def make_candidate(user, nome="Ana Souza", *, com_pdf=False, **extra):
    candidate = Candidate.objects.create(
        user=user,
        name=nome,
        linkedin_url=f"https://linkedin.com/in/{nome.lower().replace(' ', '-')}",
        **extra,
    )
    if com_pdf:
        candidate.resume_pdf.save("cv.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    return candidate


def adherence(n=80, texto="aderente"):
    return {"adherence": n, "technical_justification": texto}


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

    @property
    def last(self):
        return self.calls[-1]


def run(job, **kwargs):
    """Roda a busca com as 4 funções do LLM e o `sleep` mockados.

    Por padrão todo candidato recebe aderência 80. Passe `batch_pdf`, `batch_no_pdf`,
    `single_pdf` ou `single_no_pdf` para controlar (valor ou `side_effect`).
    """
    overrides = {
        name: kwargs.pop(name, None)
        for name in ("batch_pdf", "batch_no_pdf", "single_pdf", "single_no_pdf")
    }

    with (
        patch("core.pdf_extractor.time.sleep"),
        patch("core.pdf_extractor.extract_candidates_batch_with_llm") as m_batch_pdf,
        patch("core.pdf_extractor.calculate_adherence_batch_for_candidates") as m_batch_no_pdf,
        patch("core.pdf_extractor.extract_candidate_with_llm") as m_single_pdf,
        patch("core.pdf_extractor.calculate_adherence_for_candidate") as m_single_no_pdf,
    ):
        m_batch_pdf.side_effect = lambda itens, **kw: [adherence() for _ in itens]
        m_batch_no_pdf.side_effect = lambda itens, **kw: [adherence() for _ in itens]
        m_single_pdf.return_value = adherence()
        m_single_no_pdf.return_value = adherence()

        mocks = {
            "batch_pdf": m_batch_pdf,
            "batch_no_pdf": m_batch_no_pdf,
            "single_pdf": m_single_pdf,
            "single_no_pdf": m_single_no_pdf,
        }
        for nome, valor in overrides.items():
            if valor is None:
                continue
            if isinstance(valor, Exception) or callable(valor):
                mocks[nome].side_effect = valor
            else:
                mocks[nome].side_effect = None
                mocks[nome].return_value = valor

        result = search_and_rank_candidates_from_pool(
            job_id=job.id,
            job_description="Vaga de Python",
            weights=WEIGHTS,
            **kwargs,
        )
        return result, mocks


class TestSelection:
    """Quem entra na avaliação."""

    def test_candidate_already_linked_to_the_job_is_skipped(self, job, user):
        ja_vinculado = make_candidate(user, "Ana Souza")
        CandidateJob.objects.create(job=job, candidate=ja_vinculado)
        make_candidate(user, "Bia Lima")

        result, _ = run(job, user_id=user.id)

        assert result["total"] == 1
        assert result["linked"] == 1

    def test_only_own_candidates_when_not_shared_pool(self, job, user):
        make_candidate(user, "Ana Souza")
        outro = User.objects.create_user(username="outro", password="x")
        make_candidate(outro, "Bia Lima")

        result, _ = run(job, user_id=user.id, shared_pool=False)

        assert result["total"] == 1

    def test_shared_pool_reaches_candidates_of_other_users(self, job, user):
        make_candidate(user, "Ana Souza")
        outro = User.objects.create_user(username="outro", password="x")
        make_candidate(outro, "Bia Lima")

        result, _ = run(job, user_id=user.id, shared_pool=True)

        assert result["total"] == 2

    def test_candidate_ids_narrows_the_set(self, job, user):
        ana = make_candidate(user, "Ana Souza")
        make_candidate(user, "Bia Lima")

        result, _ = run(job, user_id=user.id, candidate_ids=[ana.id])

        assert result["total"] == 1
        assert CandidateJob.objects.filter(job=job).get().candidate_id == ana.id


class TestEmpty:
    def test_no_candidates_returns_zeroed_result_without_calling_the_llm(self, job, user):
        rec = Recorder()

        result, mocks = run(job, user_id=user.id, progress_callback=rec)

        assert result == {"linked": 0, "errors": 0, "total": 0, "error_details": []}
        assert mocks["batch_pdf"].call_count == 0
        assert mocks["batch_no_pdf"].call_count == 0
        assert rec.last["status"] == "completed"
        assert rec.last["result"] == result


class TestPdfSplit:
    """A separação com-PDF / sem-PDF, que é a decisão central da função."""

    def test_candidate_with_pdf_goes_through_the_resume(self, job, user):
        make_candidate(user, "Ana Souza", com_pdf=True)

        _, mocks = run(job, user_id=user.id)

        assert mocks["batch_pdf"].call_count == 1
        assert mocks["batch_no_pdf"].call_count == 0

    def test_candidate_without_pdf_goes_through_structured_data(self, job, user):
        make_candidate(user, "Ana Souza", com_pdf=False)

        _, mocks = run(job, user_id=user.id)

        assert mocks["batch_pdf"].call_count == 0
        assert mocks["batch_no_pdf"].call_count == 1

    def test_mixed_batch_calls_both_paths_once(self, job, user):
        make_candidate(user, "Ana Souza", com_pdf=True)
        make_candidate(user, "Bia Lima", com_pdf=False)

        result, mocks = run(job, user_id=user.id)

        assert mocks["batch_pdf"].call_count == 1
        assert mocks["batch_no_pdf"].call_count == 1
        assert result["linked"] == 2

    def test_pdf_registered_but_missing_on_disk_falls_back_to_structured_data(self, job, user):
        """QUIRK útil: o registro no banco não basta — o arquivo tem que existir.

        Um `media/` limpo sem limpar o banco (ou um restore parcial) não quebra a busca:
        o candidato só é avaliado pelos dados estruturados.
        """
        candidate = make_candidate(user, "Ana Souza", com_pdf=True)
        Path(candidate.resume_pdf.path).unlink()

        _, mocks = run(job, user_id=user.id)

        assert mocks["batch_pdf"].call_count == 0
        assert mocks["batch_no_pdf"].call_count == 1

    def test_structured_payload_carries_the_candidate_fields(self, job, user):
        make_candidate(
            user,
            "Ana Souza",
            com_pdf=False,
            current_title="Engenheira",
            skills="Python, Django",
            seniority="Senior",
        )

        _, mocks = run(job, user_id=user.id)

        enviado = mocks["batch_no_pdf"].call_args[0][0][0]
        assert enviado["name"] == "Ana Souza"
        assert enviado["current_title"] == "Engenheira"
        assert enviado["skills"] == "Python, Django"
        assert enviado["seniority"] == "Senior"


class TestPersistence:
    def test_creates_candidate_job_with_the_adherence(self, job, user):
        make_candidate(user, "Ana Souza")

        run(
            job,
            user_id=user.id,
            batch_no_pdf=lambda itens, **kw: [adherence(93, "forte em Python")],
        )

        link = CandidateJob.objects.get(job=job)
        assert link.adherence_score == 93
        assert link.technical_justification == "forte em Python"

    def test_result_counts_the_links(self, job, user):
        make_candidate(user, "Ana Souza")
        make_candidate(user, "Bia Lima")

        result, _ = run(job, user_id=user.id)

        assert result == {"linked": 2, "errors": 0, "total": 2, "error_details": []}


class TestFallback:
    """Quando o lote falha, cada candidato é reprocessado sozinho."""

    def test_batch_failure_falls_back_to_individual_with_pdf(self, job, user):
        make_candidate(user, "Ana Souza", com_pdf=True)

        result, mocks = run(job, user_id=user.id, batch_pdf=RuntimeError("lote falhou"))

        assert mocks["single_pdf"].call_count == 1
        assert result["linked"] == 1
        assert result["errors"] == 0

    def test_batch_failure_falls_back_to_individual_without_pdf(self, job, user):
        make_candidate(user, "Ana Souza", com_pdf=False)

        result, mocks = run(job, user_id=user.id, batch_no_pdf=RuntimeError("lote falhou"))

        assert mocks["single_no_pdf"].call_count == 1
        assert result["linked"] == 1

    def test_individual_failure_is_counted_and_detailed(self, job, user):
        make_candidate(user, "Ana Souza", com_pdf=False)

        result, _ = run(
            job,
            user_id=user.id,
            batch_no_pdf=RuntimeError("lote falhou"),
            single_no_pdf=RuntimeError("individual falhou"),
        )

        assert result["linked"] == 0
        assert result["errors"] == 1
        assert "Ana Souza" in result["error_details"][0]
        assert CandidateJob.objects.count() == 0

    def test_a_failure_does_not_stop_the_others(self, job, user):
        make_candidate(user, "Ana Souza")
        make_candidate(user, "Bia Lima")
        chamadas = {"n": 0}

        def alterna(*args, **kwargs):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise RuntimeError("primeiro falhou")
            return adherence()

        result, _ = run(
            job,
            user_id=user.id,
            batch_no_pdf=RuntimeError("lote falhou"),
            single_no_pdf=alterna,
        )

        assert result["linked"] == 1
        assert result["errors"] == 1
        assert result["total"] == 2


class TestProgress:
    def test_final_callback_carries_the_result(self, job, user):
        make_candidate(user, "Ana Souza")
        rec = Recorder()

        result, _ = run(job, user_id=user.id, progress_callback=rec)

        assert rec.last["status"] == "completed"
        assert rec.last["result"] == result
        assert rec.last["processed"] == 1

    def test_first_callback_announces_the_total(self, job, user):
        make_candidate(user, "Ana Souza")
        rec = Recorder()

        run(job, user_id=user.id, progress_callback=rec)

        assert rec.calls[0] == {
            "total": 1,
            "processed": 0,
            "current": None,
            "status": "running",
        }

    def test_error_details_are_truncated_at_ten(self, job, user):
        for i in range(12):
            make_candidate(user, f"Candidato {i}")

        result, _ = run(
            job,
            user_id=user.id,
            batch_no_pdf=RuntimeError("lote falhou"),
            single_no_pdf=RuntimeError("individual falhou"),
        )

        assert result["errors"] == 12
        assert len(result["error_details"]) == 10

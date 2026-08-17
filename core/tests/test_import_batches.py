"""Characterization tests do loop de lotes e do fallback individual (R-06).

Fixa o comportamento atual do laço de importação antes de R-10 extrair
`_process_in_batches`. Como em R-05: estes testes registram o que o sistema faz hoje,
não o que deveria fazer. Os pontos marcados como QUIRK ficam fixados de propósito.

`time.sleep` é sempre mockado — o código dorme 1s entre lotes e 2s por arquivo no
fallback, o que tornaria a suíte inutilizável.
"""

from unittest.mock import call, patch

import pytest

from core.models import Candidate
from core.services.candidate_import import import_candidates_from_folder

pytestmark = pytest.mark.django_db

WEIGHTS = {"skills": 40, "technologies": 35, "experience": 25}


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
        "adherence": 70,
        "technical_justification": "ok",
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
    paths = []
    for i in range(count):
        p = folder / f"{i:04d}.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        paths.append(p)
    return paths


class Recorder:
    """Captura as chamadas do progress_callback."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)

    @property
    def statuses(self):
        return [c.get("status") for c in self.calls]

    @property
    def last(self):
        return self.calls[-1]


def run(folder, batch_results=None, single_results=None, **kwargs):
    """Roda a importação com LLM e sleep mockados.

    batch_results: lista de retornos por chamada de lote (ou uma Exception para falhar).
    single_results: lista de retornos do caminho individual (ou Exception).
    """
    with (
        patch("core.services.candidate_import.time.sleep") as mock_sleep,
        patch("core.services.candidate_import.extract_candidates_batch_with_llm") as mock_batch,
        patch("core.services.candidate_import.extract_candidate_with_llm") as mock_single,
    ):
        if batch_results is not None:
            mock_batch.side_effect = batch_results
        if single_results is not None:
            mock_single.side_effect = single_results
        result = import_candidates_from_folder(
            str(folder),
            job_description="Vaga",
            weights=WEIGHTS,
            **kwargs,
        )
    return result, mock_batch, mock_single, mock_sleep


class TestBatching:
    def test_splits_into_batches_of_ten(self, pdf_dir, user):
        paths = make_pdfs(pdf_dir, 12)
        batch_results = [
            [llm_row(i) for i in range(10)],
            [llm_row(i) for i in range(10, 12)],
        ]
        result, mock_batch, _, _ = run(pdf_dir, batch_results, user_id=user.id)

        assert mock_batch.call_count == 2
        assert mock_batch.call_args_list[0].args[0] == paths[:10]
        assert mock_batch.call_args_list[1].args[0] == paths[10:]
        assert result["created"] == 12
        assert result["total"] == 12

    def test_single_partial_batch(self, pdf_dir, user):
        paths = make_pdfs(pdf_dir, 3)
        result, mock_batch, _, _ = run(pdf_dir, [[llm_row(i) for i in range(3)]], user_id=user.id)

        assert mock_batch.call_count == 1
        assert mock_batch.call_args.args[0] == paths
        assert result["created"] == 3

    def test_sleeps_one_second_between_batches_but_not_after_the_last(self, pdf_dir, user):
        make_pdfs(pdf_dir, 12)
        batch_results = [
            [llm_row(i) for i in range(10)],
            [llm_row(i) for i in range(10, 12)],
        ]
        _, _, _, mock_sleep = run(pdf_dir, batch_results, user_id=user.id)

        assert mock_sleep.call_args_list == [call(1)]

    def test_no_sleep_with_a_single_batch(self, pdf_dir, user):
        make_pdfs(pdf_dir, 2)
        _, _, _, mock_sleep = run(pdf_dir, [[llm_row(0), llm_row(1)]], user_id=user.id)

        assert mock_sleep.call_count == 0

    def test_batches_are_ordered_by_filename(self, pdf_dir, user):
        make_pdfs(pdf_dir, 3)
        _, mock_batch, _, _ = run(pdf_dir, [[llm_row(i) for i in range(3)]], user_id=user.id)

        names = [p.name for p in mock_batch.call_args.args[0]]
        assert names == sorted(names)


class TestFallbackToIndividual:
    def test_batch_failure_falls_back_to_one_call_per_pdf(self, pdf_dir, user):
        paths = make_pdfs(pdf_dir, 3)
        result, mock_batch, mock_single, _ = run(
            pdf_dir,
            batch_results=[RuntimeError("lote explodiu")],
            single_results=[llm_row(0), llm_row(1), llm_row(2)],
            user_id=user.id,
        )

        assert mock_batch.call_count == 1
        assert mock_single.call_count == 3
        assert [c.args[0] for c in mock_single.call_args_list] == paths
        assert result["created"] == 3
        assert result["errors"] == 0

    def test_fallback_sleeps_two_seconds_per_pdf(self, pdf_dir, user):
        make_pdfs(pdf_dir, 3)
        _, _, _, mock_sleep = run(
            pdf_dir,
            batch_results=[RuntimeError("falhou")],
            single_results=[llm_row(0), llm_row(1), llm_row(2)],
            user_id=user.id,
        )

        assert mock_sleep.call_args_list == [call(2), call(2), call(2)]

    def test_individual_failure_is_counted_and_does_not_stop_the_rest(self, pdf_dir, user):
        make_pdfs(pdf_dir, 3)
        result, _, _, _ = run(
            pdf_dir,
            batch_results=[RuntimeError("falhou")],
            single_results=[llm_row(0), RuntimeError("PDF corrompido"), llm_row(2)],
            user_id=user.id,
        )

        assert result["created"] == 2
        assert result["errors"] == 1
        assert result["total"] == 3
        assert Candidate.objects.count() == 2

    def test_skip_still_applies_inside_the_fallback(self, pdf_dir, user):
        make_pdfs(pdf_dir, 2)
        result, _, _, _ = run(
            pdf_dir,
            batch_results=[RuntimeError("falhou")],
            single_results=[llm_row(0, name=""), llm_row(1)],
            user_id=user.id,
        )

        assert result["skipped"] == 1
        assert result["created"] == 1

    def test_only_the_failing_batch_falls_back(self, pdf_dir, user):
        """QUIRK: o fallback é por lote. Se o segundo lote falha, os 10 do primeiro
        já foram salvos pelo caminho em lote e só os 2 restantes vão individualmente."""
        make_pdfs(pdf_dir, 12)
        result, _, mock_single, _ = run(
            pdf_dir,
            batch_results=[[llm_row(i) for i in range(10)], RuntimeError("segundo lote falhou")],
            single_results=[llm_row(10), llm_row(11)],
            user_id=user.id,
        )

        assert mock_single.call_count == 2
        assert result["created"] == 12


class TestErrorDetails:
    def test_error_details_are_truncated_to_ten(self, pdf_dir, user):
        make_pdfs(pdf_dir, 12)
        result, _, _, _ = run(
            pdf_dir,
            batch_results=[RuntimeError("falhou"), RuntimeError("falhou")],
            single_results=[RuntimeError(f"erro {i}") for i in range(12)],
            user_id=user.id,
        )

        assert result["errors"] == 12
        assert len(result["error_details"]) == 10

    def test_rate_limit_errors_get_a_friendly_message(self, pdf_dir, user):
        make_pdfs(pdf_dir, 1)
        result, _, _, _ = run(
            pdf_dir,
            batch_results=[RuntimeError("falhou")],
            single_results=[RuntimeError("429 RESOURCE_EXHAUSTED quota")],
            user_id=user.id,
        )

        assert result["error_details"] == ["0000.pdf: Limite de uso da API atingido"]

    def test_other_errors_keep_the_original_message(self, pdf_dir, user):
        make_pdfs(pdf_dir, 1)
        result, _, _, _ = run(
            pdf_dir,
            batch_results=[RuntimeError("falhou")],
            single_results=[RuntimeError("PDF ilegivel")],
            user_id=user.id,
        )

        assert result["error_details"] == ["0000.pdf: PDF ilegivel"]


class TestProgressCallback:
    def test_first_call_announces_the_total_before_any_work(self, pdf_dir, user):
        make_pdfs(pdf_dir, 2)
        rec = Recorder()
        run(pdf_dir, [[llm_row(0), llm_row(1)]], user_id=user.id, progress_callback=rec)

        assert rec.calls[0] == {
            "total": 2,
            "processed": 0,
            "current": None,
            "status": "running",
        }

    def test_reports_progress_per_pdf_with_batch_label(self, pdf_dir, user):
        make_pdfs(pdf_dir, 2)
        rec = Recorder()
        run(pdf_dir, [[llm_row(0), llm_row(1)]], user_id=user.id, progress_callback=rec)

        running = [c for c in rec.calls if c["status"] == "running" and c["current"]]
        assert [c["current"] for c in running] == [
            "Lote 1/1: 0000.pdf",
            "Lote 1/1: 0001.pdf",
        ]
        assert [c["processed"] for c in running] == [1, 2]
        assert all(c["errors"] == 0 for c in running)

    def test_skipped_pdf_is_flagged_in_the_message(self, pdf_dir, user):
        make_pdfs(pdf_dir, 1)
        rec = Recorder()
        run(pdf_dir, [[llm_row(0, name="")]], user_id=user.id, progress_callback=rec)

        currents = [c["current"] for c in rec.calls if c["current"]]
        assert any("(pulado)" in c for c in currents)

    def test_errors_counter_is_forwarded_to_the_callback(self, pdf_dir, user):
        make_pdfs(pdf_dir, 2)
        rec = Recorder()
        run(
            pdf_dir,
            batch_results=[RuntimeError("falhou")],
            single_results=[RuntimeError("boom"), llm_row(1)],
            user_id=user.id,
            progress_callback=rec,
        )

        running = [c for c in rec.calls if c["status"] == "running" and c["current"]]
        assert running[-1]["errors"] == 1

    def test_final_call_reports_completed(self, pdf_dir, user):
        make_pdfs(pdf_dir, 2)
        rec = Recorder()
        run(pdf_dir, [[llm_row(0), llm_row(1)]], user_id=user.id, progress_callback=rec)

        assert rec.statuses[-1] == "completed"
        assert rec.last == {
            "total": 2,
            "processed": 2,
            "current": None,
            "status": "completed",
            "result": {
                "created": 2,
                "updated": 0,
                "unchanged": 0,
                "skipped": 0,
                "errors": 0,
                "total": 2,
                "error_details": [],
            },
        }

    def test_final_call_carries_the_errors_when_everything_failed(self, pdf_dir, user):
        """R-30: o callback final agora leva o `result`, então uma importação que
        falhou em tudo termina anunciando `errors=2` em vez de um `completed` mudo.

        `processed=2` NÃO é otimismo, e é por isso que este número não mudou com o
        R-30: `_process_in_batches` conta tentativa, não sucesso — incrementa em todos
        os caminhos, inclusive nos de erro. Os 2 arquivos foram processados; os 2
        falharam, e quem diz isso é o `result`.
        """
        make_pdfs(pdf_dir, 2)
        rec = Recorder()
        run(
            pdf_dir,
            batch_results=[RuntimeError("falhou")],
            single_results=[RuntimeError("boom"), RuntimeError("boom")],
            user_id=user.id,
            progress_callback=rec,
        )

        assert rec.last["status"] == "completed"
        assert rec.last["processed"] == 2
        assert rec.last["total"] == 2
        assert rec.last["result"]["errors"] == 2
        assert rec.last["result"]["created"] == 0

    def test_final_call_carries_the_result(self, pdf_dir, user):
        """R-30: os dois importadores passam a mandar `result` no callback final.

        Antes só o `..._no_ranking` mandava, e quem consumia os dois precisava tratar
        duas formas. Consequência prática do contrato antigo: um poll que caísse entre
        o callback final e a gravação de `views.py:557` via `status="completed"` sem
        `result`, e a tela renderizava "0 criados, 0 atualizados, 0 ignorados".
        """
        make_pdfs(pdf_dir, 1)
        rec = Recorder()
        run(pdf_dir, [[llm_row(0)]], user_id=user.id, progress_callback=rec)

        assert rec.last["result"] == {
            "created": 1,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
            "errors": 0,
            "total": 1,
            "error_details": [],
        }

    def test_works_without_a_callback(self, pdf_dir, user):
        make_pdfs(pdf_dir, 1)
        result, _, _, _ = run(pdf_dir, [[llm_row(0)]], user_id=user.id)

        assert result["created"] == 1

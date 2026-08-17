"""Orquestracao dos jobs de background (R-14).

Estas funcoes moravam em `views.py`, que acumulava HTTP, regra de negocio, threads e
montagem de prompt no mesmo arquivo — o D-5 do diagnostico. Aqui elas ganham lugar
proprio: conhecem o ORM e os casos de uso, nao conhecem `request` nem `response`.

Nada foi reescrito na mudanca. O R-14 e movimentacao pura, de proposito: misturar
recorte-e-cola com alteracao de logica torna o diff impossivel de revisar.

Regra de dependencia (secao 5 do PROJETO_REFATORACAO.md):

    views  ->  services  ->  domain
                         ->  llm
                         ->  models (ORM)
"""

import shutil
from functools import wraps
from pathlib import Path

from django.core.cache import cache
from django.db import close_old_connections

from ..domain.job_description import build_job_description_from
from ..llm_extractor import generate_parecer
from ..metrics import vacancy_candidate_import_failures_total
from ..models import CandidateJob
from ..observability import Timer, ensure_correlation_id, log_event
from .candidate_import import (
    import_candidates_from_folder,
    import_candidates_from_folder_no_ranking,
    search_and_rank_candidates_from_pool,
)


def background_job(fn):
    """Devolve a conexão de banco ao terminar. **Obrigatório em toda função de thread.**

    O Django fecha conexões no sinal `request_finished`, que thread manual não dispara.
    Sem isto, cada importação abre uma conexão Postgres e a deixa aberta para sempre —
    elas acumulam até o banco recusar novas (D-6 do diagnóstico: `close_old_connections`
    não existia em nenhum lugar do projeto).

    Fecha também na **entrada**, porque a thread herda o estado do processo e pode pegar
    uma conexão já expirada pelo `CONN_MAX_AGE`.

    O `finally` garante o fechamento mesmo quando o job estoura — que é justamente o
    caso em que a conexão ficaria pendurada.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        close_old_connections()
        try:
            return fn(*args, **kwargs)
        finally:
            close_old_connections()

    return wrapper


def _import_status_key(job_id: int) -> str:
    return f"import_status_{job_id}"


def _search_status_key(job_id: int) -> str:
    return f"search_status_{job_id}"


def _talent_pool_import_status_key() -> str:
    return "talent_pool_import_status"


def _parecer_status_key(candidate_job_id: int) -> str:
    return f"parecer_status_{candidate_job_id}"


def _set_import_status(job_id: int, payload: dict) -> None:
    cache.set(_import_status_key(job_id), payload, timeout=60 * 60)


def _set_search_status(job_id: int, payload: dict) -> None:
    cache.set(_search_status_key(job_id), payload, timeout=60 * 60)


def _set_talent_pool_import_status(payload: dict) -> None:
    cache.set(_talent_pool_import_status_key(), payload, timeout=60 * 60)


def _set_parecer_status(candidate_job_id: int, payload: dict) -> None:
    cache.set(_parecer_status_key(candidate_job_id), payload, timeout=60 * 30)


@background_job
def _run_import_job(
    job_id: int,
    folder_path: Path,
    job_description: str,
    role_title: str,
    user_id: int,
    shared_pool: bool = False,
    correlation_id: str | None = None,
):
    ensure_correlation_id(correlation_id)
    outer_timer = Timer()
    try:

        def progress_callback(**kwargs):
            _set_import_status(job_id, kwargs)

        result = import_candidates_from_folder(
            str(folder_path),
            job_description=job_description,
            weights={"skills": 40, "technologies": 35, "experience": 25},
            role_title=role_title,
            job_id=job_id,
            user_id=user_id,
            shared_pool=shared_pool,
            progress_callback=progress_callback,
        )
        _set_import_status(job_id, {"status": "completed", "result": result})
    except Exception as exc:
        _set_import_status(job_id, {"status": "error", "message": str(exc)})
        vacancy_candidate_import_failures_total.inc()
        log_event(
            "vacancy_candidate_import_failed",
            status="error",
            vacancy_id=job_id,
            duration_ms=outer_timer.elapsed_ms(),
            error=str(exc),
        )
    finally:
        shutil.rmtree(folder_path, ignore_errors=True)


@background_job
def _run_talent_pool_import(
    folder_path: Path, _is_zip: bool, user_id: int, shared_pool: bool = False
):
    """Executa importação de candidatos no banco de talentos do usuário em background."""
    try:

        def progress_callback(**kwargs):
            _set_talent_pool_import_status(kwargs)

        result = import_candidates_from_folder_no_ranking(
            str(folder_path),
            user_id=user_id,
            shared_pool=shared_pool,
            progress_callback=progress_callback,
        )
        _set_talent_pool_import_status({"status": "completed", "result": result})
    except Exception as exc:
        _set_talent_pool_import_status({"status": "error", "message": str(exc)})
    finally:
        shutil.rmtree(folder_path, ignore_errors=True)


@background_job
def _run_search_in_pool(
    job_id: int,
    job_description: str,
    role_title: str,
    candidate_ids: list[int],
    user_id: int | None = None,
    shared_pool: bool = False,
):
    """Executa rankeamento via LLM dos candidatos pré-aprovados no match, em background."""
    try:

        def progress_callback(**kwargs):
            _set_search_status(job_id, kwargs)

        weights = {"skills": 40, "technologies": 35, "experience": 25}
        result = search_and_rank_candidates_from_pool(
            job_id=job_id,
            job_description=job_description,
            weights=weights,
            role_title=role_title,
            progress_callback=progress_callback,
            candidate_ids=candidate_ids,
            user_id=user_id,
            shared_pool=shared_pool,
        )
        _set_search_status(job_id, {"status": "completed", "result": result})
    except Exception as exc:
        _set_search_status(job_id, {"status": "error", "message": str(exc)})


@background_job
def _run_parecer_generation(candidate_job_id: int, parecer_type: str) -> None:
    """Executa geração de parecer em background."""
    try:
        candidate_job = CandidateJob.objects.select_related("job", "candidate").get(
            id=candidate_job_id
        )
        job = candidate_job.job
        candidate = candidate_job.candidate

        job_description = build_job_description_from(job)
        candidate_data = {
            "name": candidate.name,
            "current_title": candidate.current_title or "",
            "current_company": candidate.current_company or "",
            "location": candidate.location or "",
            "skills": candidate.skills or "",
            "technologies": candidate.technologies or "",
            "languages": candidate.languages or "",
            "certifications": candidate.certifications or "",
            "seniority": candidate.seniority or "",
            "experience_time": str(candidate.experience_time) if candidate.experience_time else "",
            "average_tenure": str(candidate.average_tenure) if candidate.average_tenure else "",
            "summary": candidate.summary or "",
        }
        resume_path = None
        if candidate.resume_pdf:
            try:
                resume_path = candidate.resume_pdf.path
            except (ValueError, NotImplementedError):
                pass

        parecer_text = generate_parecer(
            job_description=job_description,
            candidate_data=candidate_data,
            parecer_type=parecer_type,
            role_title=job.title,
            resume_pdf_path=resume_path,
        )

        candidate_job.parecer = parecer_text
        candidate_job.parecer_type = parecer_type
        candidate_job.save(update_fields=["parecer", "parecer_type", "updated_at"])

        _set_parecer_status(
            candidate_job_id,
            {"status": "completed", "parecer": parecer_text, "parecer_type": parecer_type},
        )
    except Exception as exc:
        _set_parecer_status(
            candidate_job_id,
            {"status": "error", "message": str(exc)},
        )

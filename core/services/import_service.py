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

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from ..domain.job_description import build_job_description_from
from ..llm_extractor import generate_parecer
from ..metrics import vacancy_candidate_import_failures_total
from ..models import CandidateJob, ImportJob
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


def start_import_job(
    *, user_id: int, kind: str, job_id: int | None = None, total: int = 0
) -> int | None:
    """Cria a linha do job e devolve o id. **Chamada pela view, antes da thread.**

    R-20b: nascer na view e não dentro da thread não é detalhe. O primeiro poll acontece
    ~2s depois do POST; se a linha ainda não existisse, o endpoint responderia `idle`, o
    JS pararia de pollar e a barra de progresso nunca apareceria. Era isso que a escrita
    síncrona no cache garantia antes.

    Devolve `None` se a criação falhar — rastreamento não pode derrubar importação.
    """
    try:
        return ImportJob.objects.create(
            user_id=user_id,
            kind=kind,
            job_id=job_id,
            total=total,
            payload={"status": "running", "processed": 0, "total": total},
        ).id
    except Exception:
        return None


def _track_progress(import_job_id: int | None, payload: dict) -> None:
    """Grava o progresso do job na linha do banco.

    Chamado a cada lote pelo `progress_callback`. Escreve o `payload` inteiro além das
    colunas: é ele que a tela recebe no poll. O `heartbeat_at` vai explícito porque
    `.update()` não dispara `auto_now`.
    """
    if import_job_id is None:
        return
    campos = {"payload": {"status": "running", **payload}}
    if payload.get("processed") is not None:
        campos["processed"] = payload["processed"]
    if payload.get("total") is not None:
        campos["total"] = payload["total"]
    try:
        # `.update()` não dispara `auto_now`, então o heartbeat vai explícito — e é ele
        # que o R-20b vai usar para distinguir "trabalhando" de "morreu no meio".
        ImportJob.objects.filter(id=import_job_id).update(heartbeat_at=timezone.now(), **campos)
    except Exception:
        pass


def _finish_import_job(
    import_job_id: int | None, *, status: str, error: str = "", payload: dict | None = None
) -> None:
    if import_job_id is None:
        return
    try:
        ImportJob.objects.filter(id=import_job_id).update(
            status=status,
            error=error[:2000],
            payload=payload or {},
            heartbeat_at=timezone.now(),
        )
    except Exception:
        pass


def job_status_payload(*, user_id: int, kind: str, job_id: int | None = None) -> dict:
    """Estado do job mais recente, no formato que o poll da tela espera (R-20b).

    Porta o contrato do cache sem mudar a forma: o que sai daqui é o mesmo dicionário que
    saía de `cache.get(...)`, para nenhuma linha de JS precisar mudar.

    A diferença que justifica o item: um job `RUNNING` cujo `heartbeat_at` parou de andar
    morreu — quase sempre no `systemctl restart` do deploy, porque as threads são `daemon`
    e não executam o `finally`. Antes ele ficava girando "em andamento" até o cache expirar,
    uma hora depois. Agora vira erro com instrução.
    """
    filtros = {"user_id": user_id, "kind": kind}
    if job_id is not None:
        filtros["job_id"] = job_id
    job = ImportJob.objects.filter(**filtros).order_by("-started_at").first()
    if job is None:
        return {"status": "idle"}

    if job.status == ImportJob.Status.RUNNING and _esta_parado(job):
        return {
            "status": "error",
            "interrupted": True,
            "message": (
                "Importação interrompida — o servidor foi reiniciado no meio. "
                "Os candidatos já processados foram salvos; reinicie a importação "
                "para continuar de onde parou."
            ),
        }

    return job.payload or {"status": job.status.lower()}


def _esta_parado(job: ImportJob) -> bool:
    """Heartbeat velho demais para o job ainda estar vivo.

    O limiar é generoso de propósito. O `heartbeat_at` é escrito **por lote**, não por
    tempo: um lote vai até 10 PDFs numa única chamada ao LLM, com timeout de
    `LLM_TIMEOUT_SECONDS` e até 4 tentativas — pode passar mais de 12 minutos sem sinal e
    estar perfeitamente vivo. Um limiar curto trocaria um problema raro (barra girando à
    toa) por um pior: dizer à recrutadora que uma importação viva morreu, e ela reiniciar
    tudo — pagando o LLM duas vezes.
    """
    limite = getattr(settings, "IMPORT_JOB_STALE_AFTER_SECONDS", 900)
    return (timezone.now() - job.heartbeat_at).total_seconds() > limite


def _parecer_status_key(candidate_job_id: int) -> str:
    return f"parecer_status_{candidate_job_id}"


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
    import_job_id: int | None = None,
):
    ensure_correlation_id(correlation_id)
    outer_timer = Timer()
    try:

        def progress_callback(**kwargs):
            _track_progress(import_job_id, kwargs)

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
        _finish_import_job(
            import_job_id,
            status=ImportJob.Status.COMPLETED,
            payload={"status": "completed", "result": result},
        )
    except Exception as exc:
        _finish_import_job(
            import_job_id,
            status=ImportJob.Status.ERROR,
            error=str(exc),
            payload={"status": "error", "message": str(exc)},
        )
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
    folder_path: Path,
    _is_zip: bool,
    user_id: int,
    shared_pool: bool = False,
    import_job_id: int | None = None,
):
    """Executa importação de candidatos no banco de talentos do usuário em background."""
    try:

        def progress_callback(**kwargs):
            _track_progress(import_job_id, kwargs)

        result = import_candidates_from_folder_no_ranking(
            str(folder_path),
            user_id=user_id,
            shared_pool=shared_pool,
            progress_callback=progress_callback,
        )
        _finish_import_job(
            import_job_id,
            status=ImportJob.Status.COMPLETED,
            payload={"status": "completed", "result": result},
        )
    except Exception as exc:
        _finish_import_job(
            import_job_id,
            status=ImportJob.Status.ERROR,
            error=str(exc),
            payload={"status": "error", "message": str(exc)},
        )
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
    import_job_id: int | None = None,
):
    """Executa rankeamento via LLM dos candidatos pré-aprovados no match, em background."""
    try:

        def progress_callback(**kwargs):
            _track_progress(import_job_id, kwargs)

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
        _finish_import_job(
            import_job_id,
            status=ImportJob.Status.COMPLETED,
            payload={"status": "completed", "result": result},
        )
    except Exception as exc:
        _finish_import_job(
            import_job_id,
            status=ImportJob.Status.ERROR,
            error=str(exc),
            payload={"status": "error", "message": str(exc)},
        )


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

import time
from pathlib import Path

from django.core.files import File

from .llm_extractor import (
    calculate_adherence_batch_for_candidates,
    calculate_adherence_for_candidate,
    extract_candidate_no_ranking,
    extract_candidate_with_llm,
    extract_candidates_batch_no_ranking,
    extract_candidates_batch_with_llm,
)
from .metrics import (
    vacancy_candidate_import_duration_ms,
    vacancy_candidate_imports_total,
    vacancy_candidate_ranking_duration_ms,
    vacancy_candidate_rankings_total,
    vacancy_ranking_persist_duration_ms,
    vacancy_ranking_persist_failures_total,
    vacancy_ranking_persist_total,
)
from .models import Candidate, CandidateJob
from .observability import Timer, log_event


def _save_resume_pdf(candidate: Candidate, pdf_path: Path) -> None:
    """Salva ou substitui o PDF do currículo no candidato."""
    with open(pdf_path, "rb") as f:
        candidate.resume_pdf.save(Path(pdf_path).name, File(f), save=True)


# Campos de texto do candidato: None nunca chega ao banco neles, vira "".
_TEXT_FIELDS = (
    "name",
    "current_title",
    "current_company",
    "location",
    "linkedin_url",
    "summary",
    "skills",
    "technologies",
    "languages",
    "certifications",
    "seniority",
)

# Campos numéricos, que aceitam None no banco.
_NULLABLE_FIELDS = ("experience_time", "average_tenure")


def _candidate_payload(data: dict) -> dict:
    """Traduz o resultado do LLM para os campos do modelo Candidate."""
    return {
        "name": data.get("name") or "",
        "current_title": data.get("current_title") or "",
        "current_company": data.get("current_company") or "",
        "location": data.get("location") or "",
        "linkedin_url": data.get("linkedin_url", ""),
        "summary": "",
        "skills": ", ".join(data.get("skills", [])),
        "technologies": ", ".join(data.get("technologies", [])),
        "languages": ", ".join(data.get("languages", [])),
        "certifications": ", ".join(data.get("certifications", [])),
        "experience_time": data.get("experience_time_years"),
        "average_tenure": data.get("average_tenure_years"),
        "seniority": data.get("seniority") or "",
    }


def _find_candidate(linkedin_url: str, user_id, shared_pool: bool) -> Candidate | None:
    """Procura um candidato já existente pela URL do LinkedIn (case-insensitive).

    shared_pool: procura no banco inteiro, ignorando o dono do registro.
    """
    if shared_pool:
        qs = Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
    elif user_id:
        qs = Candidate.objects.filter(user_id=user_id, linkedin_url__iexact=linkedin_url)
    else:
        qs = Candidate.objects.filter(linkedin_url__iexact=linkedin_url)
    return qs.first()


def _upsert_candidate(
    data: dict, *, user_id, shared_pool: bool, pdf_path: Path
) -> tuple[Candidate, str]:
    """Cria ou atualiza o candidato a partir do resultado do LLM e grava o currículo.

    Único ponto do sistema que persiste candidato vindo de importação. Antes de R-08
    este bloco existia em 4 cópias quase idênticas, uma delas já divergente.

    Devolve `(candidato, resultado)`, onde resultado é "created", "updated" ou
    "unchanged". "unchanged" é o candidato que já existia e no qual nenhum campo mudou:
    hoje ele não entra em nenhum contador do chamador.

    O PDF é sempre (re)gravado, inclusive quando nada mudou.
    """
    payload = _candidate_payload(data)
    candidate = _find_candidate(payload["linkedin_url"], user_id, shared_pool)

    if candidate is None:
        safe_payload = {
            field: ("" if field in _TEXT_FIELDS and value is None else value)
            for field, value in payload.items()
        }
        if user_id:
            safe_payload["user_id"] = user_id
        candidate = Candidate.objects.create(**safe_payload)
        _save_resume_pdf(candidate, pdf_path)
        return candidate, "created"

    changed = False
    for field, value in payload.items():
        if field in _TEXT_FIELDS and value is None:
            value = ""
        if value is None and field not in _NULLABLE_FIELDS:
            continue
        if getattr(candidate, field) != value:
            setattr(candidate, field, value)
            changed = True
    if changed:
        candidate.save()
    _save_resume_pdf(candidate, pdf_path)
    return candidate, "updated" if changed else "unchanged"


def import_candidates_from_folder(
    folder_path: str,
    job_description: str,
    weights: dict[str, int],
    role_title: str | None = None,
    job_id: int | None = None,
    user_id=None,
    shared_pool: bool = False,
    progress_callback=None,
) -> dict:
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Pasta nao encontrada: {folder}")

    pdf_files = [folder] if folder.is_file() else sorted(folder.glob("*.pdf"))
    total_files = len(pdf_files)
    import_timer = Timer()
    if job_id is not None:
        vacancy_candidate_imports_total.inc()
        log_event(
            "vacancy_candidate_import_started",
            status="started",
            vacancy_id=job_id,
            candidate_count=total_files,
        )
    if progress_callback:
        progress_callback(total=total_files, processed=0, current=None, status="running")
    role_titles = []
    if role_title:
        role_titles = [item.strip() for item in role_title.split("/") if item.strip()]
    created = 0
    updated = 0
    skipped = 0
    errors = 0
    error_details = []

    # Processa em lotes de 10 PDFs
    batch_size = 10
    processed_count = 0

    for batch_start in range(0, len(pdf_files), batch_size):
        batch = pdf_files[batch_start : batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(pdf_files) + batch_size - 1) // batch_size
        batch_label = f"{batch_num}/{total_batches}"

        try:
            # Processa o lote inteiro
            results = extract_candidates_batch_with_llm(
                batch,
                job_description=job_description,
                weights=weights,
                role_titles=role_titles,
                vacancy_id=job_id,
                batch_id=batch_label,
            )

            if job_id is not None:
                rank_timer = Timer()
                vacancy_candidate_rankings_total.inc()
                log_event(
                    "vacancy_candidate_ranking_started",
                    status="started",
                    vacancy_id=job_id,
                    batch_id=batch_label,
                    candidate_count=len(batch),
                )

            # Processa cada resultado do lote
            persisted_rankings = 0
            for idx, data in enumerate(results):
                pdf_file = batch[idx]

                linkedin_url = data.get("linkedin_url", "")
                if not data.get("name") or not linkedin_url:
                    skipped += 1
                    processed_count += 1  # Conta como processado mesmo que pulado
                    if progress_callback:
                        progress_callback(
                            total=total_files,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                            status="running",
                            errors=errors,
                        )
                    continue

                try:
                    candidate, outcome = _upsert_candidate(
                        data, user_id=user_id, shared_pool=shared_pool, pdf_path=pdf_file
                    )
                    if outcome == "created":
                        created += 1
                    elif outcome == "updated":
                        updated += 1

                    if job_id:
                        CandidateJob.objects.update_or_create(
                            job_id=job_id,
                            candidate=candidate,
                            defaults={
                                "adherence_score": data.get("adherence"),
                                "technical_justification": data.get("technical_justification", ""),
                            },
                        )
                        persisted_rankings += 1

                    # Incrementa contador apenas após salvar com sucesso
                    processed_count += 1

                except Exception as save_exc:
                    errors += 1
                    error_msg = str(save_exc)
                    if job_id is not None:
                        vacancy_ranking_persist_failures_total.inc()
                        log_event(
                            "vacancy_ranking_persist_fail",
                            status="error",
                            vacancy_id=job_id,
                            batch_id=batch_label,
                            error=error_msg[:500],
                        )
                    if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: Erro ao salvar - {error_msg[:100]}")
                    processed_count += 1  # Conta como processado mesmo com erro

                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )

            if job_id is not None:
                _rank_ms = rank_timer.elapsed_ms()
                vacancy_candidate_ranking_duration_ms.observe(_rank_ms)
                log_event(
                    "vacancy_candidate_ranking_finished",
                    status="success",
                    vacancy_id=job_id,
                    batch_id=batch_label,
                    candidate_count=persisted_rankings,
                    duration_ms=_rank_ms,
                )
                vacancy_ranking_persist_total.inc()
                vacancy_ranking_persist_duration_ms.observe(_rank_ms)
                log_event(
                    "vacancy_ranking_persisted",
                    status="success",
                    vacancy_id=job_id,
                    batch_id=batch_label,
                    candidate_count=persisted_rankings,
                    duration_ms=_rank_ms,
                )

            # Aguarda entre lotes (menos tempo já que processa 10 de uma vez)
            if batch_start + batch_size < len(pdf_files):
                time.sleep(1)

        except Exception as exc:
            # Se o lote falhar, tenta processar individualmente
            error_msg = str(exc)
            for pdf_file in batch:
                try:
                    data = extract_candidate_with_llm(
                        pdf_file,
                        job_description=job_description,
                        weights=weights,
                        role_titles=role_titles,
                        vacancy_id=job_id,
                        batch_id=batch_label,
                    )
                    linkedin_url = data.get("linkedin_url", "")
                    if not data.get("name") or not linkedin_url:
                        skipped += 1
                        processed_count += 1  # Conta como processado mesmo que pulado
                        if progress_callback:
                            progress_callback(
                                total=total_files,
                                processed=processed_count,
                                current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                                status="running",
                                errors=errors,
                            )
                        continue

                    try:
                        candidate, outcome = _upsert_candidate(
                            data, user_id=user_id, shared_pool=shared_pool, pdf_path=pdf_file
                        )
                        if outcome == "created":
                            created += 1
                        elif outcome == "updated":
                            updated += 1

                        if job_id:
                            CandidateJob.objects.update_or_create(
                                job_id=job_id,
                                candidate=candidate,
                                defaults={
                                    "adherence_score": data.get("adherence"),
                                    "technical_justification": data.get(
                                        "technical_justification", ""
                                    ),
                                },
                            )

                        # Incrementa contador apenas após salvar com sucesso
                        processed_count += 1

                    except Exception as save_exc:
                        errors += 1
                        save_error_msg = str(save_exc)
                        if job_id is not None:
                            vacancy_ranking_persist_failures_total.inc()
                            log_event(
                                "vacancy_ranking_persist_fail",
                                status="error",
                                vacancy_id=job_id,
                                batch_id=batch_label,
                                error=save_error_msg[:500],
                            )
                        if "RESOURCE_EXHAUSTED" in save_error_msg or "429" in save_error_msg:
                            error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                        else:
                            error_details.append(
                                f"{pdf_file.name}: Erro ao salvar - {save_error_msg[:100]}"
                            )
                        processed_count += 1  # Conta como processado mesmo com erro

                except Exception as individual_exc:
                    errors += 1
                    individual_error_msg = str(individual_exc)
                    if (
                        "RESOURCE_EXHAUSTED" in individual_error_msg
                        or "429" in individual_error_msg
                    ):
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: {individual_error_msg[:100]}")
                    processed_count += 1  # Conta como processado mesmo com erro

                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )

                time.sleep(2)

    result = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total": total_files,
        "error_details": error_details[:10],
    }
    if job_id is not None:
        _import_ms = import_timer.elapsed_ms()
        vacancy_candidate_import_duration_ms.observe(_import_ms)
        log_event(
            "vacancy_candidate_import_finished",
            status="success",
            vacancy_id=job_id,
            candidate_count=total_files,
            duration_ms=_import_ms,
        )
    if progress_callback:
        progress_callback(
            total=total_files, processed=total_files, current=None, status="completed"
        )
    return result


def import_candidates_from_folder_no_ranking(
    folder_path: str,
    user_id=None,
    shared_pool: bool = False,
    progress_callback=None,
) -> dict:
    """Importa candidatos sem rankeamento (para banco de talentos). Candidatos ficam vinculados ao user_id."""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Pasta não encontrada: {folder}")

    pdf_files = [folder] if folder.is_file() else sorted(folder.glob("*.pdf"))
    total_files = len(pdf_files)
    if progress_callback:
        progress_callback(total=total_files, processed=0, current=None, status="running")

    created = 0
    updated = 0
    skipped = 0
    errors = 0
    error_details = []

    # Processa em lotes de 10 PDFs
    batch_size = 10
    processed_count = 0

    for batch_start in range(0, len(pdf_files), batch_size):
        batch = pdf_files[batch_start : batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(pdf_files) + batch_size - 1) // batch_size

        try:
            # Processa o lote inteiro sem rankeamento
            results = extract_candidates_batch_no_ranking(batch)

            # Processa cada resultado do lote
            for idx, data in enumerate(results):
                pdf_file = batch[idx]

                linkedin_url = data.get("linkedin_url", "")
                if not data.get("name") or not linkedin_url:
                    skipped += 1
                    processed_count += 1
                    if progress_callback:
                        progress_callback(
                            total=total_files,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                            status="running",
                            errors=errors,
                        )
                    continue

                try:
                    candidate, outcome = _upsert_candidate(
                        data, user_id=user_id, shared_pool=shared_pool, pdf_path=pdf_file
                    )
                    if outcome == "created":
                        created += 1
                    elif outcome == "updated":
                        updated += 1

                    # Incrementa contador apenas após salvar com sucesso
                    processed_count += 1

                except Exception as save_exc:
                    errors += 1
                    error_msg = str(save_exc)
                    if "RESOURCE_EXHAUSTED" in error_msg or "429" in error_msg:
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: Erro ao salvar - {error_msg[:100]}")
                    processed_count += 1

                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )

            # Aguarda entre lotes
            if batch_start + batch_size < len(pdf_files):
                time.sleep(1)

        except Exception as exc:
            # Se o lote falhar, tenta processar individualmente
            error_msg = str(exc)
            for pdf_file in batch:
                try:
                    data = extract_candidate_no_ranking(pdf_file)
                    linkedin_url = data.get("linkedin_url", "")
                    if not data.get("name") or not linkedin_url:
                        skipped += 1
                        processed_count += 1
                        if progress_callback:
                            progress_callback(
                                total=total_files,
                                processed=processed_count,
                                current=f"Lote {batch_num}/{total_batches}: {pdf_file.name} (pulado)",
                                status="running",
                                errors=errors,
                            )
                        continue

                    try:
                        # shared_pool nao e considerado aqui: divergencia das outras 3 copias,
                        # preservada de proposito para nao misturar bugfix com refatoracao.
                        # Corrigida em R-09.
                        candidate, outcome = _upsert_candidate(
                            data, user_id=user_id, shared_pool=False, pdf_path=pdf_file
                        )
                        if outcome == "created":
                            created += 1
                        elif outcome == "updated":
                            updated += 1

                        # Incrementa contador apenas após salvar com sucesso
                        processed_count += 1

                    except Exception as save_exc:
                        errors += 1
                        save_error_msg = str(save_exc)
                        if "RESOURCE_EXHAUSTED" in save_error_msg or "429" in save_error_msg:
                            error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                        else:
                            error_details.append(
                                f"{pdf_file.name}: Erro ao salvar - {save_error_msg[:100]}"
                            )
                        processed_count += 1

                except Exception as individual_exc:
                    errors += 1
                    individual_error_msg = str(individual_exc)
                    if (
                        "RESOURCE_EXHAUSTED" in individual_error_msg
                        or "429" in individual_error_msg
                    ):
                        error_details.append(f"{pdf_file.name}: Limite de uso da API atingido")
                    else:
                        error_details.append(f"{pdf_file.name}: {individual_error_msg[:100]}")
                    processed_count += 1

                if progress_callback:
                    progress_callback(
                        total=total_files,
                        processed=processed_count,
                        current=f"Lote {batch_num}/{total_batches}: {pdf_file.name}",
                        status="running",
                        errors=errors,
                    )

                time.sleep(2)

    result = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total": total_files,
        "error_details": error_details[:10],
    }
    if progress_callback:
        progress_callback(
            total=total_files,
            processed=processed_count,
            current=None,
            status="completed",
            result=result,
        )
    return result


def search_and_rank_candidates_from_pool(
    job_id: int,
    job_description: str,
    weights: dict[str, int],
    role_title: str | None = None,
    progress_callback=None,
    candidate_ids: list[int] | None = None,
    user_id=None,
    shared_pool: bool = False,
) -> dict:
    """
    Calcula aderência via LLM dos candidatos do banco para a vaga.

    Quando candidate_ids é fornecido (pré-match feito na view), avalia apenas
    esses candidatos. Candidatos com PDF de currículo são avaliados pelo PDF;
    os demais (cadastro manual ou importações antigas) pelos dados estruturados.
    """
    from .models import Candidate, CandidateJob

    # Busca candidatos do usuário não vinculados à vaga
    linked_candidate_ids = CandidateJob.objects.filter(job_id=job_id).values_list(
        "candidate_id", flat=True
    )
    candidates = Candidate.objects.exclude(id__in=linked_candidate_ids)
    if user_id is not None and not shared_pool:
        candidates = candidates.filter(user_id=user_id)
    if candidate_ids is not None:
        candidates = candidates.filter(id__in=candidate_ids)

    total_candidates = candidates.count()
    if progress_callback:
        progress_callback(total=total_candidates, processed=0, current=None, status="running")

    if total_candidates == 0:
        result = {
            "linked": 0,
            "errors": 0,
            "total": 0,
            "error_details": [],
        }
        if progress_callback:
            progress_callback(total=0, processed=0, current=None, status="completed", result=result)
        return result

    role_titles = []
    if role_title:
        role_titles = [item.strip() for item in role_title.split("/") if item.strip()]

    linked = 0
    errors = 0
    error_details = []

    # Processa em lotes de 10 candidatos
    batch_size = 10
    processed_count = 0

    candidates_list = list(candidates)

    for batch_start in range(0, len(candidates_list), batch_size):
        batch = candidates_list[batch_start : batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(candidates_list) + batch_size - 1) // batch_size

        try:
            # Separa candidatos com PDF (avaliação via currículo completo) dos sem PDF (dados estruturados)
            with_pdf = []
            without_pdf = []
            for candidate in batch:
                if candidate.resume_pdf and hasattr(candidate.resume_pdf, "path"):
                    try:
                        path = Path(candidate.resume_pdf.path)
                        if path.exists():
                            with_pdf.append((candidate, path))
                            continue
                    except (ValueError, OSError):
                        pass
                without_pdf.append(
                    (
                        candidate,
                        {
                            "name": candidate.name or "",
                            "current_title": candidate.current_title or "",
                            "current_company": candidate.current_company or "",
                            "location": candidate.location or "",
                            "skills": candidate.skills or "",
                            "technologies": candidate.technologies or "",
                            "languages": candidate.languages or "",
                            "certifications": candidate.certifications or "",
                            "seniority": candidate.seniority or "",
                            "experience_time": str(candidate.experience_time)
                            if candidate.experience_time
                            else "",
                            "average_tenure": str(candidate.average_tenure)
                            if candidate.average_tenure
                            else "",
                            "summary": candidate.summary or "",
                        },
                    )
                )

            # Mapa candidato -> {adherence, technical_justification}
            results_map = {}

            if with_pdf:
                pdf_paths = [p for _, p in with_pdf]
                pdf_candidates = [c for c, _ in with_pdf]
                llm_results = extract_candidates_batch_with_llm(
                    pdf_paths,
                    job_description=job_description,
                    weights=weights,
                    role_titles=role_titles,
                )
                for candidate, data in zip(pdf_candidates, llm_results, strict=True):
                    results_map[candidate.id] = {
                        "adherence": data.get("adherence"),
                        "technical_justification": data.get("technical_justification", ""),
                    }

            if without_pdf:
                no_pdf_candidates = [c for c, _ in without_pdf]
                no_pdf_data = [d for _, d in without_pdf]
                adherence_results = calculate_adherence_batch_for_candidates(
                    no_pdf_data,
                    job_description=job_description,
                    weights=weights,
                    role_titles=role_titles,
                )
                for candidate, data in zip(no_pdf_candidates, adherence_results, strict=True):
                    results_map[candidate.id] = {
                        "adherence": data.get("adherence"),
                        "technical_justification": data.get("technical_justification", ""),
                    }

            # Cria CandidateJob para cada candidato
            for candidate in batch:
                adherence_data = results_map.get(candidate.id, {})
                if not adherence_data:
                    continue  # Candidato sem resultado (não deveria ocorrer)
                try:
                    CandidateJob.objects.update_or_create(
                        job_id=job_id,
                        candidate=candidate,
                        defaults={
                            "adherence_score": adherence_data.get("adherence"),
                            "technical_justification": adherence_data.get(
                                "technical_justification", ""
                            ),
                        },
                    )
                    linked += 1
                    processed_count += 1

                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name}",
                            status="running",
                            errors=errors,
                        )
                except Exception as save_exc:
                    errors += 1
                    error_msg = str(save_exc)
                    error_details.append(f"{candidate.name}: Erro ao vincular - {error_msg[:100]}")
                    processed_count += 1

                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name} (erro)",
                            status="running",
                            errors=errors,
                        )

            # Aguarda entre lotes
            if batch_start + batch_size < len(candidates_list):
                time.sleep(1)

        except Exception as exc:
            # Se o lote falhar, tenta processar individualmente
            error_msg = str(exc)
            for candidate in batch:
                try:
                    # Candidato com PDF: envia currículo completo para avaliação mais precisa
                    if candidate.resume_pdf and hasattr(candidate.resume_pdf, "path"):
                        try:
                            path = Path(candidate.resume_pdf.path)
                            if path.exists():
                                full_data = extract_candidate_with_llm(
                                    path,
                                    job_description=job_description,
                                    weights=weights,
                                    role_titles=role_titles,
                                )
                                adherence_data = {
                                    "adherence": full_data.get("adherence"),
                                    "technical_justification": full_data.get(
                                        "technical_justification", ""
                                    ),
                                }
                            else:
                                raise FileNotFoundError("PDF não encontrado")
                        except (ValueError, OSError, FileNotFoundError):
                            # Fallback para dados estruturados se PDF inacessível
                            candidate_data = {
                                "name": candidate.name or "",
                                "current_title": candidate.current_title or "",
                                "current_company": candidate.current_company or "",
                                "location": candidate.location or "",
                                "skills": candidate.skills or "",
                                "technologies": candidate.technologies or "",
                                "languages": candidate.languages or "",
                                "certifications": candidate.certifications or "",
                                "seniority": candidate.seniority or "",
                                "experience_time": str(candidate.experience_time)
                                if candidate.experience_time
                                else "",
                                "average_tenure": str(candidate.average_tenure)
                                if candidate.average_tenure
                                else "",
                                "summary": candidate.summary or "",
                            }
                            adherence_data = calculate_adherence_for_candidate(
                                candidate_data,
                                job_description=job_description,
                                weights=weights,
                                role_titles=role_titles,
                            )
                    else:
                        # Candidato sem PDF: usa dados estruturados (comportamento atual)
                        candidate_data = {
                            "name": candidate.name or "",
                            "current_title": candidate.current_title or "",
                            "current_company": candidate.current_company or "",
                            "location": candidate.location or "",
                            "skills": candidate.skills or "",
                            "technologies": candidate.technologies or "",
                            "languages": candidate.languages or "",
                            "certifications": candidate.certifications or "",
                            "seniority": candidate.seniority or "",
                            "experience_time": str(candidate.experience_time)
                            if candidate.experience_time
                            else "",
                            "average_tenure": str(candidate.average_tenure)
                            if candidate.average_tenure
                            else "",
                            "summary": candidate.summary or "",
                        }
                        adherence_data = calculate_adherence_for_candidate(
                            candidate_data,
                            job_description=job_description,
                            weights=weights,
                            role_titles=role_titles,
                        )

                    CandidateJob.objects.update_or_create(
                        job_id=job_id,
                        candidate=candidate,
                        defaults={
                            "adherence_score": adherence_data.get("adherence"),
                            "technical_justification": adherence_data.get(
                                "technical_justification", ""
                            ),
                        },
                    )
                    linked += 1
                    processed_count += 1

                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name}",
                            status="running",
                            errors=errors,
                        )
                except Exception as individual_exc:
                    errors += 1
                    individual_error_msg = str(individual_exc)
                    error_details.append(f"{candidate.name}: {individual_error_msg[:100]}")
                    processed_count += 1

                    if progress_callback:
                        progress_callback(
                            total=total_candidates,
                            processed=processed_count,
                            current=f"Lote {batch_num}/{total_batches}: {candidate.name} (erro)",
                            status="running",
                            errors=errors,
                        )

                time.sleep(2)

    result = {
        "linked": linked,
        "errors": errors,
        "total": total_candidates,
        "error_details": error_details[:10],
    }
    if progress_callback:
        progress_callback(
            total=total_candidates,
            processed=processed_count,
            current=None,
            status="completed",
            result=result,
        )
    return result

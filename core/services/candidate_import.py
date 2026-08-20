"""Importacao de candidatos: orquestracao com persistencia (R-17).

Era `core/pdf_extractor.py`, e o nome mentia. Depois do R-03 (940 linhas de codigo morto)
e do R-37 (3o laco unificado), o que sobrou nao extrai PDF: coordena lotes, chama o LLM,
grava candidato e reporta progresso. O que era de arquivo foi para `core/pdf.py`.

Regra de dependencia (secao 5 do PROJETO_REFATORACAO.md):

    views  ->  services  ->  domain
                         ->  llm
                         ->  models (ORM)
"""

import time
from pathlib import Path

from ..llm_extractor import (
    calculate_adherence_batch_for_candidates,
    calculate_adherence_for_candidate,
    extract_candidate_no_ranking,
    extract_candidate_with_llm,
    extract_candidates_batch_no_ranking,
    extract_candidates_batch_with_llm,
)
from ..metrics import (
    vacancy_candidate_import_duration_ms,
    vacancy_candidate_imports_total,
    vacancy_candidate_ranking_duration_ms,
    vacancy_candidate_rankings_total,
    vacancy_ranking_persist_duration_ms,
    vacancy_ranking_persist_failures_total,
    vacancy_ranking_persist_total,
)
from ..models import Candidate, CandidateJob
from ..observability import Timer, log_event
from ..pdf import _digest, _pdf_files_in, _resume_path, _save_resume_pdf

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


def _separar_ja_importados(
    pdf_files: list[Path], *, user_id, shared_pool: bool
) -> tuple[list[Path], list[Path]]:
    """Divide os PDFs em `(novos, ja_no_banco)` comparando o SHA-256 do arquivo (R-45).

    Roda **antes** de qualquer chamada ao LLM: é o ponto inteiro do item. O hash é a única
    chave utilizável aqui — `linkedin_url` só se conhece depois de extrair, que é a
    chamada que se quer evitar.

    Duas fontes de "já conhecido", nesta ordem:

    1. um candidato do escopo já tem esse hash gravado;
    2. um PDF anterior **do mesmo lote** tinha o mesmo conteúdo — a recrutadora exporta o
       mesmo perfil em buscas diferentes e os dois arquivos caem na mesma pasta.

    Arquivo ilegível volta como novo, nunca como conhecido: seguir o fluxo normal custa
    uma chamada de LLM, enquanto pular por engano perde o candidato em silêncio.
    """
    digests: dict[Path, str] = {}
    for pdf_file in pdf_files:
        digest = _digest(pdf_file)
        if digest is not None:
            digests[pdf_file] = digest

    if shared_pool or not user_id:
        qs = Candidate.objects.all()
    else:
        qs = Candidate.objects.filter(user_id=user_id)
    conhecidos = set(
        qs.filter(resume_sha256__in=set(digests.values()))
        .exclude(resume_sha256="")
        .values_list("resume_sha256", flat=True)
    )

    novos: list[Path] = []
    ja_no_banco: list[Path] = []
    vistos_no_lote: set[str] = set()
    for pdf_file in pdf_files:
        digest = digests.get(pdf_file)
        if digest is None:
            novos.append(pdf_file)
            continue
        if digest in conhecidos or digest in vistos_no_lote:
            ja_no_banco.append(pdf_file)
            continue
        vistos_no_lote.add(digest)
        novos.append(pdf_file)
    return novos, ja_no_banco


def _upsert_candidate(
    data: dict, *, user_id, shared_pool: bool, pdf_path: Path
) -> tuple[Candidate, str]:
    """Cria ou atualiza o candidato a partir do resultado do LLM e grava o currículo.

    Único ponto do sistema que persiste candidato vindo de importação. Antes de R-08
    este bloco existia em 4 cópias quase idênticas, uma delas já divergente.

    Devolve `(candidato, resultado)`, onde resultado é "created", "updated" ou
    "unchanged". "unchanged" é o candidato que já existia e no qual nenhum campo mudou:
    hoje ele não entra em nenhum contador do chamador.

    O PDF só é regravado quando o conteúdo difere do que já está em disco (R-31); em
    qualquer caso o `resume_sha256` é mantido em dia (R-45).
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


def _rate_limited(message: str) -> bool:
    return "RESOURCE_EXHAUSTED" in message or "429" in message


def _process_in_batches(
    items,
    *,
    batch_fn,
    single_fn,
    persist_fn,
    progress_callback=None,
    on_batch_start=None,
    on_batch_end=None,
    on_persist_error=None,
    batch_size=10,
    is_incomplete=None,
    persist_error_label="Erro ao salvar",
    known_items=None,
) -> tuple[dict, int]:
    """Percorre `items` em lotes, caindo para item a item quando o lote falha.

    Único laço de importação do sistema. Antes de R-10 este esqueleto existia em
    3 cópias.

    Contrato dos callbacks obrigatórios:
        batch_fn(batch, batch_label)  -> lista de dados, um por item do lote
        single_fn(item, batch_label)  -> dados de um item só (usado no fallback)
        persist_fn(data, item)        -> "created" | "updated" | "unchanged"

    Hooks opcionais de instrumentação — o fluxo de vaga usa, o banco de talentos não:
        on_batch_start(batch, batch_label)
        on_batch_end(batch_label, persisted)
        on_persist_error(batch_label, error_msg)

    `known_items` (R-45): itens reconhecidos **antes** do laço como já presentes no banco.
    Não vão ao LLM; entram no total e no contador `already_known`, e são reportados de
    saída para a tela não parecer travada enquanto os demais processam.

    Devolve `(resultado, processados)`. O callback final de conclusão fica por conta
    de quem chama: os dois fluxos divergem nele.
    """
    known_items = list(known_items or [])
    # O total é o que a recrutadora selecionou, não o que sobrou depois do filtro: ela
    # escolheu 10 arquivos e o contador tem que terminar em 10.
    total = len(items) + len(known_items)
    created = updated = unchanged = skipped = errors = processed = 0
    already_known = 0
    error_details: list[str] = []

    if progress_callback:
        progress_callback(total=total, processed=0, current=None, status="running")

    total_batches = (len(items) + batch_size - 1) // batch_size

    def report(batch_label, item, suffix=""):
        if progress_callback:
            progress_callback(
                total=total,
                processed=processed,
                current=f"Lote {batch_label}: {item.name}{suffix}",
                status="running",
                errors=errors,
                # R-42: a lista vai junto do contador. Antes so o numero viajava durante a
                # execucao, e o detalhe so existia no payload final — a recrutadora via
                # "2 erro(s)" no meio da importacao sem saber de quais arquivos.
                error_details=list(error_details),
            )

    if is_incomplete is None:
        # Default: o critério da importação de candidato. O ranking do banco de talentos
        # trabalha com dicionários de aderência, que não têm nome nem URL — por isso o
        # critério é injetável desde a conversão do 3º laço.
        def is_incomplete(data) -> bool:
            return not data.get("name") or not data.get("linkedin_url", "")

    for item in known_items:
        already_known += 1
        processed += 1
        if progress_callback:
            progress_callback(
                total=total,
                processed=processed,
                current=f"{item.name} (já no banco)",
                status="running",
                errors=errors,
                error_details=list(error_details),
            )

    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start : batch_start + batch_size]
        batch_label = f"{(batch_start // batch_size) + 1}/{total_batches}"

        try:
            results = batch_fn(batch, batch_label)
            if on_batch_start:
                on_batch_start(batch, batch_label)

            persisted = 0
            for idx, data in enumerate(results):
                item = batch[idx]

                if is_incomplete(data):
                    skipped += 1
                    processed += 1
                    report(batch_label, item, " (pulado)")
                    continue

                suffix = ""
                try:
                    outcome = persist_fn(data, item)
                    if outcome == "created":
                        created += 1
                    elif outcome == "updated":
                        updated += 1
                    elif outcome == "unchanged":
                        unchanged += 1
                    persisted += 1
                    processed += 1
                except Exception as save_exc:
                    errors += 1
                    suffix = " (erro)"
                    msg = str(save_exc)
                    if on_persist_error:
                        on_persist_error(batch_label, msg)
                    error_details.append(
                        f"{item.name}: Limite de uso da API atingido"
                        if _rate_limited(msg)
                        else f"{item.name}: {persist_error_label} - {msg[:100]}"
                    )
                    processed += 1

                report(batch_label, item, suffix)

            if on_batch_end:
                on_batch_end(batch_label, persisted)

            # Aguarda entre lotes (menos tempo já que processa 10 de uma vez)
            if batch_start + batch_size < len(items):
                time.sleep(1)

        except Exception:
            # Se o lote falhar, tenta processar item a item
            for item in batch:
                try:
                    data = single_fn(item, batch_label)

                    if is_incomplete(data):
                        skipped += 1
                        processed += 1
                        report(batch_label, item, " (pulado)")
                        continue

                    try:
                        outcome = persist_fn(data, item)
                        if outcome == "created":
                            created += 1
                        elif outcome == "updated":
                            updated += 1
                        elif outcome == "unchanged":
                            unchanged += 1
                        processed += 1
                    except Exception as save_exc:
                        errors += 1
                        msg = str(save_exc)
                        if on_persist_error:
                            on_persist_error(batch_label, msg)
                        error_details.append(
                            f"{item.name}: Limite de uso da API atingido"
                            if _rate_limited(msg)
                            else f"{item.name}: {persist_error_label} - {msg[:100]}"
                        )
                        processed += 1

                except Exception as individual_exc:
                    errors += 1
                    msg = str(individual_exc)
                    error_details.append(
                        f"{item.name}: Limite de uso da API atingido"
                        if _rate_limited(msg)
                        else f"{item.name}: {msg[:100]}"
                    )
                    processed += 1

                report(batch_label, item)
                time.sleep(2)

    result = {
        "created": created,
        "updated": updated,
        # R-32: "unchanged" e o candidato que ja existia e no qual nenhum campo mudou.
        # Antes ele nao entrava em contador nenhum, e a conta da importacao nao fechava:
        # 10 PDFs podiam virar "3 criados, 2 atualizados" sem explicar os outros 5.
        # Agora created + updated + unchanged + skipped + already_known + errors == total.
        "unchanged": unchanged,
        "skipped": skipped,
        # R-45: currículo idêntico a um que já está no banco. Contador separado de
        # `skipped` de propósito — aquele é "o LLM não devolveu nome nem URL", que a
        # recrutadora precisa investigar; este é trabalho poupado, e não pede nada dela.
        "already_known": already_known,
        "errors": errors,
        "total": total,
        "error_details": error_details[:10],
    }
    return result, processed


def _split_role_titles(role_title: str | None) -> list[str]:
    if not role_title:
        return []
    return [item.strip() for item in role_title.split("/") if item.strip()]


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
    pdf_files = _pdf_files_in(folder_path)
    total_files = len(pdf_files)
    role_titles = _split_role_titles(role_title)
    instrumented = job_id is not None

    import_timer = Timer()
    if instrumented:
        vacancy_candidate_imports_total.inc()
        log_event(
            "vacancy_candidate_import_started",
            status="started",
            vacancy_id=job_id,
            candidate_count=total_files,
        )

    rank_timer: Timer | None = None

    def batch_fn(batch, batch_label):
        return extract_candidates_batch_with_llm(
            batch,
            job_description=job_description,
            weights=weights,
            role_titles=role_titles,
            vacancy_id=job_id,
            batch_id=batch_label,
        )

    def single_fn(pdf_file, batch_label):
        return extract_candidate_with_llm(
            pdf_file,
            job_description=job_description,
            weights=weights,
            role_titles=role_titles,
            vacancy_id=job_id,
            batch_id=batch_label,
        )

    def persist_fn(data, pdf_file):
        candidate, outcome = _upsert_candidate(
            data, user_id=user_id, shared_pool=shared_pool, pdf_path=pdf_file
        )
        if job_id:
            CandidateJob.objects.update_or_create(
                job_id=job_id,
                candidate=candidate,
                defaults={
                    "adherence_score": data.get("adherence"),
                    "technical_justification": data.get("technical_justification", ""),
                },
            )
        return outcome

    def on_batch_start(batch, batch_label):
        nonlocal rank_timer
        rank_timer = Timer()
        vacancy_candidate_rankings_total.inc()
        log_event(
            "vacancy_candidate_ranking_started",
            status="started",
            vacancy_id=job_id,
            batch_id=batch_label,
            candidate_count=len(batch),
        )

    def on_batch_end(batch_label, persisted):
        rank_ms = rank_timer.elapsed_ms()
        vacancy_candidate_ranking_duration_ms.observe(rank_ms)
        log_event(
            "vacancy_candidate_ranking_finished",
            status="success",
            vacancy_id=job_id,
            batch_id=batch_label,
            candidate_count=persisted,
            duration_ms=rank_ms,
        )
        vacancy_ranking_persist_total.inc()
        vacancy_ranking_persist_duration_ms.observe(rank_ms)
        log_event(
            "vacancy_ranking_persisted",
            status="success",
            vacancy_id=job_id,
            batch_id=batch_label,
            candidate_count=persisted,
            duration_ms=rank_ms,
        )

    def on_persist_error(batch_label, error_msg):
        vacancy_ranking_persist_failures_total.inc()
        log_event(
            "vacancy_ranking_persist_fail",
            status="error",
            vacancy_id=job_id,
            batch_id=batch_label,
            error=error_msg[:500],
        )

    result, processed = _process_in_batches(
        pdf_files,
        batch_fn=batch_fn,
        single_fn=single_fn,
        persist_fn=persist_fn,
        progress_callback=progress_callback,
        on_batch_start=on_batch_start if instrumented else None,
        on_batch_end=on_batch_end if instrumented else None,
        on_persist_error=on_persist_error if instrumented else None,
    )

    if instrumented:
        import_ms = import_timer.elapsed_ms()
        vacancy_candidate_import_duration_ms.observe(import_ms)
        log_event(
            "vacancy_candidate_import_finished",
            status="success",
            vacancy_id=job_id,
            candidate_count=total_files,
            duration_ms=import_ms,
        )
    if progress_callback:
        # Mesmo payload final de `..._no_ranking`: contador real e `result` junto.
        # O `result` importa: quem consome sobrescreve este payload logo em seguida
        # (views.py:557), mas um poll que caia na janela entre as duas gravações
        # via `status="completed"` sem `result` e exibia "0 criados, 0 atualizados".
        progress_callback(
            total=result["total"],
            processed=processed,
            current=None,
            status="completed",
            result=result,
        )
    return result


def import_candidates_from_folder_no_ranking(
    folder_path: str,
    user_id=None,
    shared_pool: bool = False,
    progress_callback=None,
) -> dict:
    """Importa candidatos sem rankeamento (banco de talentos), vinculados ao user_id.

    R-45: currículo cujo conteúdo já está no banco não vai ao LLM. Aqui a extração é o
    produto inteiro — não há vaga para avaliar —, então reconhecer o arquivo torna a
    chamada dispensável. O fluxo de vaga não faz isso de propósito: lá o LLM extrai e
    avalia na mesma chamada, e a avaliação contra a vaga é sempre necessária.
    """
    pdf_files = _pdf_files_in(folder_path)
    novos, ja_no_banco = _separar_ja_importados(pdf_files, user_id=user_id, shared_pool=shared_pool)

    def persist_fn(data, pdf_file):
        _candidate, outcome = _upsert_candidate(
            data, user_id=user_id, shared_pool=shared_pool, pdf_path=pdf_file
        )
        return outcome

    result, processed = _process_in_batches(
        novos,
        batch_fn=lambda batch, _label: extract_candidates_batch_no_ranking(batch),
        single_fn=lambda pdf_file, _label: extract_candidate_no_ranking(pdf_file),
        persist_fn=persist_fn,
        progress_callback=progress_callback,
        known_items=ja_no_banco,
    )

    if progress_callback:
        # Diferente do fluxo de vaga: aqui vai o contador real e o result no payload.
        progress_callback(
            total=result["total"],
            processed=processed,
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
    from ..models import Candidate, CandidateJob

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

    if total_candidates == 0:
        result = {
            "linked": 0,
            "errors": 0,
            "total": 0,
            "error_details": [],
        }
        if progress_callback:
            progress_callback(total=0, processed=0, current=None, status="running")
            progress_callback(total=0, processed=0, current=None, status="completed", result=result)
        return result

    role_titles = []
    if role_title:
        role_titles = [item.strip() for item in role_title.split("/") if item.strip()]

    candidates_list = list(candidates)

    def _structured_payload(candidate) -> dict:
        """Dados do candidato para avaliacao sem curriculo em PDF."""
        return {
            "name": candidate.name or "",
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

    def _adherence_of(data: dict) -> dict:
        return {
            "adherence": data.get("adherence"),
            "technical_justification": data.get("technical_justification", ""),
        }

    def batch_fn(batch, batch_label):
        """Avalia o lote e devolve um resultado por candidato, na ordem do lote.

        Candidato com curriculo em disco e avaliado pelo PDF; os demais, pelos dados
        estruturados. Cada grupo vai em uma unica chamada ao LLM.
        """
        with_pdf = []
        without_pdf = []
        for candidate in batch:
            path = _resume_path(candidate)
            if path is not None:
                with_pdf.append((candidate, path))
            else:
                without_pdf.append((candidate, _structured_payload(candidate)))

        results_map = {}

        if with_pdf:
            llm_results = extract_candidates_batch_with_llm(
                [path for _, path in with_pdf],
                job_description=job_description,
                weights=weights,
                role_titles=role_titles,
            )
            for (candidate, _), data in zip(with_pdf, llm_results, strict=True):
                results_map[candidate.id] = _adherence_of(data)

        if without_pdf:
            adherence_results = calculate_adherence_batch_for_candidates(
                [payload for _, payload in without_pdf],
                job_description=job_description,
                weights=weights,
                role_titles=role_titles,
            )
            for (candidate, _), data in zip(without_pdf, adherence_results, strict=True):
                results_map[candidate.id] = _adherence_of(data)

        return [results_map.get(candidate.id, {}) for candidate in batch]

    def single_fn(candidate, batch_label):
        path = _resume_path(candidate)
        if path is not None:
            try:
                return _adherence_of(
                    extract_candidate_with_llm(
                        path,
                        job_description=job_description,
                        weights=weights,
                        role_titles=role_titles,
                    )
                )
            except (ValueError, OSError):
                # PDF ilegivel: cai para os dados estruturados, como antes da conversao.
                pass
        return _adherence_of(
            calculate_adherence_for_candidate(
                _structured_payload(candidate),
                job_description=job_description,
                weights=weights,
                role_titles=role_titles,
            )
        )

    def persist_fn(data, candidate):
        _, created = CandidateJob.objects.update_or_create(
            job_id=job_id,
            candidate=candidate,
            defaults={
                "adherence_score": data.get("adherence"),
                "technical_justification": data.get("technical_justification", ""),
            },
        )
        return "created" if created else "updated"

    batch_result, processed_count = _process_in_batches(
        candidates_list,
        batch_fn=batch_fn,
        single_fn=single_fn,
        persist_fn=persist_fn,
        progress_callback=progress_callback,
        # Dicionario de aderencia nao tem nome nem URL: nada aqui e "incompleto".
        is_incomplete=lambda data: not data,
        persist_error_label="Erro ao vincular",
    )

    result = {
        "linked": batch_result["created"] + batch_result["updated"],
        "errors": batch_result["errors"],
        "total": total_candidates,
        "error_details": batch_result["error_details"],
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

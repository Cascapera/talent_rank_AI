import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlencode

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, F, Func, Q
from django.db.models.functions import Lower
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .domain.normalization import SYNONYMS, normalize
from .filters import collect_filters
from .forms import CandidateForm, JobForm, SignupForm
from .matching import get_min_match_score, job_has_match_criteria, match_candidates_for_job
from .models import Candidate, CandidateJob, Job, Profile
from .observability import new_correlation_id
from .plans import required_plan
from .services.import_service import (
    _import_status_key,
    _parecer_status_key,
    _run_import_job,
    _run_parecer_generation,
    _run_search_in_pool,
    _run_talent_pool_import,
    _search_status_key,
    _set_import_status,
    _set_parecer_status,
    _set_search_status,
    _set_talent_pool_import_status,
    _talent_pool_import_status_key,
)

# Filtro do banco de talentos -> campo do modelo Candidate.
# A ORDEM define a ordem dos parâmetros na URL que a usuária vê e compartilha.
_TALENT_POOL_FILTERS = {
    "name": "name",
    "location": "location",
    "seniority": "seniority",
    "company": "current_company",
    "technologies": "technologies",
    "current_title": "current_title",
    "skills": "skills",
    "certifications": "certifications",
    "languages": "languages",
}

# Filtro da tela da vaga -> (campo do CandidateJob, prefixo do alias do unaccent).
# `pipeline_status` e `min_adherence` ficam de fora: não são `icontains`.
_JOB_CANDIDATE_FILTERS = {
    "candidate_seniority": ("candidate__seniority", "seniority"),
    "candidate_location": ("candidate__location", "location"),
    "candidate_name": ("candidate__name", "name"),
    "candidate_language": ("candidate__languages", "language"),
    "candidate_must_have": ("candidate__skills", "skills"),
    "candidate_technologies": ("candidate__technologies", "technologies"),
}

# Ordem completa dos filtros da vaga na querystring, incluindo os dois especiais.
_JOB_FILTERS = (
    "pipeline_status",
    *_JOB_CANDIDATE_FILTERS,
    "min_adherence",
)


def metrics_view(request):
    """Endpoint Prometheus (texto exposition format)."""
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)


def _prepare_uploaded_files(uploaded_files: list, temp_dir: Path) -> None:
    """
    Processa arquivos enviados (ZIPs e PDFs) e coloca todos os PDFs em temp_dir.
    Suporta: múltiplos ZIPs, múltiplos PDFs, ou combinação.
    """
    pdf_counter = 0
    for f in uploaded_files:
        dest = temp_dir / f.name
        with dest.open("wb") as out:
            for chunk in f.chunks():
                out.write(chunk)
        if zipfile.is_zipfile(dest):
            with zipfile.ZipFile(dest, "r") as zf:
                for member in zf.namelist():
                    if member.lower().endswith(".pdf") and not member.endswith("/"):
                        pdf_counter += 1
                        out_path = temp_dir / f"{pdf_counter:04d}.pdf"
                        with zf.open(member) as src, out_path.open("wb") as dst:
                            dst.write(src.read())
            dest.unlink(missing_ok=True)
        elif dest.suffix.lower() == ".pdf":
            pdf_counter += 1
            new_path = temp_dir / f"{pdf_counter:04d}.pdf"
            if dest != new_path:
                dest.rename(new_path)
        else:
            dest.unlink(missing_ok=True)


def home(request):
    return render(request, "core/home.html")


def _uses_shared_pool(user) -> bool:
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile.plan == Profile.Plan.PREMIUM


def _apply_unaccent_filter(qs, field: str, term: str, alias_prefix: str):
    if not term:
        return qs
    if connection.vendor != "postgresql":
        return qs.filter(**{f"{field}__icontains": term})
    # R-36: era `_normalize_term`, que não aparava as pontas. Filtrar por " python "
    # com espaço sobrando procurava literalmente " python " no campo e não achava nada.
    normalized = normalize(term)
    alias = f"{alias_prefix}_{field.replace('__', '_')}"
    qs = qs.annotate(**{alias: Lower(Func(F(field), function="unaccent"))})
    return qs.filter(Q(**{f"{field}__icontains": term}) | Q(**{f"{alias}__contains": normalized}))


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("login")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})


@login_required
def dashboard(request):
    return render(request, "core/dashboard.html")


@login_required
@required_plan("BASIC")
def jobs(request):
    jobs_qs = Job.objects.filter(user=request.user)
    status = request.GET.get("status", "").strip()
    seniority = request.GET.get("seniority", "").strip()
    location = request.GET.get("location", "").strip()
    department = request.GET.get("department", "").strip()
    title = request.GET.get("title", "").strip()

    if status:
        jobs_qs = jobs_qs.filter(status=status)
    if seniority:
        jobs_qs = jobs_qs.filter(seniority__icontains=seniority)
    if location:
        jobs_qs = jobs_qs.filter(location__icontains=location)
    if department:
        jobs_qs = jobs_qs.filter(department__icontains=department)
    if title:
        jobs_qs = jobs_qs.filter(title__icontains=title)

    context = {
        "jobs": jobs_qs,
        "filters": {
            "status": status,
            "seniority": seniority,
            "location": location,
            "department": department,
            "title": title,
        },
        "status_choices": Job.Status.choices,
    }
    return render(request, "core/jobs.html", context)


@login_required
def search(request):
    return render(request, "core/search.html")


@login_required
@required_plan("BASIC")
def talent_pool(request):
    message = ""
    import_message = ""
    form = CandidateForm()
    shared_pool = _uses_shared_pool(request.user)

    # Processa upload de ZIP/PDF (múltiplos arquivos)
    if request.method == "POST":
        uploads = request.FILES.getlist("candidates_zip")
        if uploads:
            temp_dir = Path(tempfile.mkdtemp(prefix="talent_pool_import_"))
            _prepare_uploaded_files(uploads, temp_dir)
            pdfs = list(temp_dir.glob("*.pdf"))
            if pdfs:
                _set_talent_pool_import_status({"status": "running", "processed": 0, "total": 0})
                thread = threading.Thread(
                    target=_run_talent_pool_import,
                    args=(temp_dir, False, request.user.id, shared_pool),
                    daemon=True,
                )
                thread.start()
                import_message = "Importação iniciada. Acompanhe o progresso abaixo."
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)
                import_message = "Nenhum PDF encontrado nos arquivos enviados."
        else:
            # Processa formulário manual (sem arquivos no POST)
            form = CandidateForm(request.POST)
            if form.is_valid():
                linkedin_url = form.cleaned_data["linkedin_url"].strip()
                candidate = Candidate.objects.filter(
                    user=request.user, linkedin_url__iexact=linkedin_url
                ).first()
                if candidate:
                    changed = False
                    for field, value in form.cleaned_data.items():
                        if value in (None, ""):
                            continue
                        if getattr(candidate, field) != value:
                            setattr(candidate, field, value)
                            changed = True
                    if changed:
                        candidate.save()
                        message = "Candidato atualizado com novos dados."
                    else:
                        message = "Nenhuma alteração detectada para esse candidato."
                else:
                    c = form.save(commit=False)
                    c.user = request.user
                    c.save()
                    message = "Candidato cadastrado com sucesso."
            else:
                message = "Confira os campos obrigatórios."

    filters = collect_filters(request, _TALENT_POOL_FILTERS)

    candidates = (
        Candidate.objects.all() if shared_pool else Candidate.objects.filter(user=request.user)
    )

    for param, campo in _TALENT_POOL_FILTERS.items():
        valor = filters[param]
        if valor:
            candidates = candidates.filter(**{f"{campo}__icontains": valor})

    candidates = candidates.order_by("-updated_at", "-created_at")

    # Paginação: 10 candidatos por página
    paginator = Paginator(candidates, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "form": form,
        "candidates": page_obj,
        "page_obj": page_obj,
        "message": message,
        "import_message": import_message,
        "shared_pool": shared_pool,
        "filters": filters.values,
        "query_string": filters.query_string,
        "import_status": cache.get(_talent_pool_import_status_key()),
    }
    return render(request, "core/talent_pool.html", context)


@login_required
@required_plan("BASIC")
def talent_pool_import_status(request):
    """Endpoint AJAX para status da importação do banco de talentos."""
    payload = cache.get(_talent_pool_import_status_key()) or {"status": "idle"}
    return JsonResponse(payload)


@login_required
@required_plan("PREMIUM")
def reports(request):
    # Resumo geral (apenas dados do usuário)
    jobs_qs = Job.objects.filter(user=request.user)
    total_jobs = jobs_qs.count()
    jobs_by_status = dict(
        jobs_qs.values("status").annotate(cnt=Count("id")).values_list("status", "cnt")
    )
    status_labels = dict(Job.Status.choices)
    jobs_by_status_display = [
        (status_labels.get(s, s), jobs_by_status.get(s, 0))
        for s in [
            Job.Status.OPEN,
            Job.Status.SEARCH_DONE,
            Job.Status.CANDIDATES_SENT,
            Job.Status.CLOSED,
        ]
    ]

    candidates_qs = Candidate.objects.filter(user=request.user)
    total_candidates = candidates_qs.count()
    candidates_ready = candidates_qs.filter(ready_at__isnull=False).count()
    total_links = CandidateJob.objects.filter(job__user=request.user).count()
    candidates_hired = CandidateJob.objects.filter(
        job__user=request.user, pipeline_status=CandidateJob.PipelineStatus.HIRED
    ).count()

    # Vagas com contagem de candidatos e funil
    pipeline_status_order = [
        CandidateJob.PipelineStatus.FIRST_CONTACT,
        CandidateJob.PipelineStatus.RESPONDED,
        CandidateJob.PipelineStatus.INTERVIEW,
        CandidateJob.PipelineStatus.TECH_INTERVIEW,
        CandidateJob.PipelineStatus.SENT_MANAGER,
        CandidateJob.PipelineStatus.CANDIDATE_READY,
        CandidateJob.PipelineStatus.SENT_CLIENT,
        CandidateJob.PipelineStatus.HIRED,
    ]
    pipeline_labels = dict(CandidateJob.PipelineStatus.choices)

    jobs_with_funnel = []
    for job in jobs_qs.order_by("-created_at")[:50]:
        links = job.candidate_links
        total_in_job = links.count()
        funnel = []
        for ps in pipeline_status_order:
            cnt = links.filter(pipeline_status=ps).count()
            funnel.append({"label": pipeline_labels.get(ps, ps), "count": cnt})
        jobs_with_funnel.append(
            {
                "job": job,
                "total_candidates": total_in_job,
                "funnel": funnel,
                "hired": links.filter(pipeline_status=CandidateJob.PipelineStatus.HIRED).count(),
            }
        )

    funnel_headers = [pipeline_labels.get(ps, ps) for ps in pipeline_status_order]

    context = {
        "total_jobs": total_jobs,
        "jobs_by_status_display": jobs_by_status_display,
        "total_candidates": total_candidates,
        "candidates_ready": candidates_ready,
        "total_links": total_links,
        "candidates_hired": candidates_hired,
        "jobs_with_funnel": jobs_with_funnel,
        "funnel_headers": funnel_headers,
    }
    return render(request, "core/reports.html", context)


@login_required
def logout_then_home(request):
    logout(request)
    return redirect("home")


@login_required
@required_plan("BASIC")
def job_create(request):
    if request.method == "POST":
        form = JobForm(request.POST)
        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.save()
            return redirect("jobs")
    else:
        form = JobForm()
    return render(request, "core/job_create.html", {"form": form})


def _build_boolean_search(job: Job) -> str:
    def normalize_list(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def expand_term(term: str) -> list[str]:
        # R-36: a chave passa a sair do mesmo `normalize()` que o pré-match usa. Antes
        # era `strip().lower()`, sem remover acento — os dois consumidores do dicionário
        # procuravam por caminhos diferentes e só concordavam porque todas as chaves de
        # SYNONYMS são ASCII.
        extra = SYNONYMS.get(normalize(term), [])
        return [term] + extra

    def group_terms(terms: list[str]) -> str:
        expanded = []
        for term in terms:
            expanded.extend(expand_term(term))
        expanded = [t for t in expanded if t]
        if not expanded:
            return ""
        if len(expanded) == 1:
            return f'"{expanded[0]}"'
        return "(" + " OR ".join(f'"{t}"' for t in expanded) + ")"

    parts = []
    for base_term in [job.title, job.stack, job.seniority, job.location, job.department]:
        if base_term:
            parts.append(group_terms([base_term]))

    must = normalize_list(job.must_have)
    if must:
        parts.append(" AND ".join(group_terms([item]) for item in must if item))

    nice = normalize_list(job.nice_to_have)
    if nice:
        nice_groups = [group_terms([item]) for item in nice if item]
        nice_groups = [g for g in nice_groups if g]
        if nice_groups:
            parts.append("(" + " OR ".join(nice_groups) + ")")

    undesirable = normalize_list(job.undesirable)
    if undesirable:
        not_groups = [group_terms([item]) for item in undesirable if item]
        not_groups = [g for g in not_groups if g]
        if not_groups:
            parts.append("NOT (" + " OR ".join(not_groups) + ")")

    parts = [p for p in parts if p]
    return " AND ".join(parts).strip()


def _build_job_description(job: Job) -> str:
    parts = [
        f"Título: {job.title}",
        f"Resumo: {job.summary or '-'}",
        f"Senioridade: {job.seniority or '-'}",
        f"Localização: {job.location or '-'}",
        f"Stack: {job.stack or '-'}",
        f"Tipo de contratação: {job.contract_type or '-'}",
        f"Idioma: {job.language or '-'}",
        f"Skills obrigatórias: {job.must_have or '-'}",
        f"Skills desejáveis: {job.nice_to_have or '-'}",
        f"Não desejáveis: {job.undesirable or '-'}",
        f"Observações: {job.notes or '-'}",
    ]
    return "\n".join(parts)


@login_required
@required_plan("BASIC")
def job_detail(request, job_id: int):
    job = get_object_or_404(Job, id=job_id, user=request.user)

    def split_list(value: str):
        return [item.strip() for item in value.split(",") if item.strip()]

    filters_storage_key = f"job_filters_{job.id}"
    if request.GET.get("clear_filters") == "1":
        request.session.pop(filters_storage_key, None)
    else:
        # Era um `set` literal: a ordem dos parâmetros na URL do redirect variava entre
        # reinícios do servidor (hash randomization). Com a tupla, é estável.
        current_params = {k: request.GET.get(k, "").strip() for k in _JOB_FILTERS}
        if any(v for v in current_params.values()):
            request.session[filters_storage_key] = current_params
        else:
            saved_filters = request.session.get(filters_storage_key, {})
            if saved_filters:
                return redirect(f"{request.path}?{urlencode(saved_filters)}")

    filters = collect_filters(request, _JOB_FILTERS)

    import_message = ""
    if request.method == "POST":
        uploads = request.FILES.getlist("candidates_zip")
        if uploads:
            temp_dir = Path(tempfile.mkdtemp(prefix="talent_import_"))
            _prepare_uploaded_files(uploads, temp_dir)
            pdfs = list(temp_dir.glob("*.pdf"))
            if pdfs:
                job_description = _build_job_description(job)
                role_title = job.title
                _set_import_status(job.id, {"status": "running", "processed": 0, "total": 0})
                shared_pool = _uses_shared_pool(request.user)
                header_cid = request.headers.get("X-Correlation-ID", "").strip()
                correlation_id = header_cid or new_correlation_id()
                thread = threading.Thread(
                    target=_run_import_job,
                    args=(
                        job.id,
                        temp_dir,
                        job_description,
                        role_title,
                        request.user.id,
                        shared_pool,
                        correlation_id,
                    ),
                    daemon=True,
                )
                thread.start()
                import_message = "Importação iniciada. Acompanhe o progresso abaixo."
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)
                import_message = "Nenhum PDF encontrado nos arquivos enviados."

    candidate_links = job.candidate_links.select_related("candidate")
    if filters["pipeline_status"]:
        candidate_links = candidate_links.filter(pipeline_status=filters["pipeline_status"])
    for param, (campo, alias) in _JOB_CANDIDATE_FILTERS.items():
        valor = filters[param]
        if valor:
            candidate_links = _apply_unaccent_filter(candidate_links, campo, valor, alias)
    if filters["min_adherence"].isdigit():
        candidate_links = candidate_links.filter(adherence_score__gte=int(filters["min_adherence"]))
    candidate_links = candidate_links.order_by(F("adherence_score").desc(nulls_last=True))

    # Paginação: 10 candidatos por página
    paginator = Paginator(candidate_links, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "job": job,
        "must_have_list": split_list(job.must_have),
        "nice_to_have_list": split_list(job.nice_to_have),
        "undesirable_list": split_list(job.undesirable),
        "import_message": import_message,
        "candidate_links": page_obj,
        "page_obj": page_obj,
        "candidate_filters": filters.values,
        "query_string": filters.query_string,
        "pipeline_status_choices": job.candidate_links.model.PipelineStatus.choices,
        "job_status_choices": Job.Status.choices,
        "import_status": cache.get(_import_status_key(job.id)),
        "search_status": cache.get(_search_status_key(job.id)),
        "pool_match_min_score": get_min_match_score(),
    }
    return render(request, "core/job_detail.html", context)


@login_required
@required_plan("BASIC")
def job_import_status(request, job_id: int):
    get_object_or_404(Job, id=job_id, user=request.user)
    payload = cache.get(_import_status_key(job_id)) or {"status": "idle"}
    return JsonResponse(payload)


@login_required
@required_plan("BASIC")
def job_search_status(request, job_id: int):
    """Endpoint AJAX para status da busca no banco."""
    get_object_or_404(Job, id=job_id, user=request.user)
    payload = cache.get(_search_status_key(job_id)) or {"status": "idle"}
    return JsonResponse(payload)


def _parse_min_score(request) -> int:
    """Lê o % mínimo de match informado pela recrutadora (fallback: padrão do sistema)."""
    raw = request.POST.get("min_score", "").strip()
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return get_min_match_score()


def _match_pool_candidates_for_job(job, user, min_score: int):
    """Aplica o pré-match da vaga aos candidatos do banco ainda não vinculados."""
    shared_pool = _uses_shared_pool(user)
    linked_candidate_ids = CandidateJob.objects.filter(job_id=job.id).values_list(
        "candidate_id", flat=True
    )
    candidates = Candidate.objects.exclude(id__in=linked_candidate_ids)
    if not shared_pool:
        candidates = candidates.filter(user=user)
    return match_candidates_for_job(job, candidates, min_score=min_score), shared_pool


@login_required
@required_plan("BASIC")
def preview_candidates_search(request, job_id: int):
    """Preview dos candidatos compatíveis com a vaga (pré-match, sem LLM)."""
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    job = get_object_or_404(Job, id=job_id, user=request.user)

    if not job_has_match_criteria(job):
        return JsonResponse(
            {
                "error": "A vaga não tem requisitos para o match. Preencha skills "
                "obrigatórias, stack, senioridade ou idioma na vaga."
            },
            status=400,
        )

    min_score = _parse_min_score(request)
    matches, _ = _match_pool_candidates_for_job(job, request.user, min_score)
    total = len(matches)

    # Paginação: 10 candidatos por página
    paginator = Paginator(matches, 10)
    page_number = request.POST.get("page", 1)
    try:
        page_obj = paginator.page(page_number)
    except Exception:
        page_obj = paginator.page(1)

    candidates_data = []
    for match in page_obj:
        candidate = match["candidate"]
        matched_terms = ", ".join(match["matched_terms"]) or "-"
        candidates_data.append(
            {
                "id": candidate.id,
                "name": candidate.name,
                "company": candidate.current_company or "-",
                "match_score": match["score"],
                "matched_terms": matched_terms[:120] + "..."
                if len(matched_terms) > 120
                else matched_terms,
                "has_resume": bool(candidate.resume_pdf),
                "ready_at": candidate.ready_at.strftime("%d/%m/%Y") if candidate.ready_at else "-",
            }
        )

    return JsonResponse(
        {
            "success": True,
            "total": total,
            "min_score": min_score,
            "page": page_obj.number,
            "num_pages": paginator.num_pages,
            "has_previous": page_obj.has_previous(),
            "has_next": page_obj.has_next(),
            "candidates": candidates_data,
        }
    )


@login_required
@required_plan("BASIC")
def search_candidates_in_pool(request, job_id: int):
    """Inicia a avaliação via LLM dos candidatos aprovados no pré-match da vaga."""
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    job = get_object_or_404(Job, id=job_id, user=request.user)

    if not job_has_match_criteria(job):
        return JsonResponse(
            {
                "error": "A vaga não tem requisitos para o match. Preencha skills "
                "obrigatórias, stack, senioridade ou idioma na vaga."
            },
            status=400,
        )

    min_score = _parse_min_score(request)
    matches, shared_pool = _match_pool_candidates_for_job(job, request.user, min_score)
    if not matches:
        return JsonResponse(
            {
                "error": f"Nenhum candidato do banco atingiu o match mínimo de "
                f"{min_score}% com esta vaga."
            },
            status=400,
        )

    candidate_ids = [match["candidate"].id for match in matches]
    job_description = _build_job_description(job)

    _set_search_status(job.id, {"status": "running", "processed": 0, "total": len(candidate_ids)})
    thread = threading.Thread(
        target=_run_search_in_pool,
        args=(
            job.id,
            job_description,
            job.title,
            candidate_ids,
            None if shared_pool else request.user.id,
            shared_pool,
        ),
        daemon=True,
    )
    thread.start()

    return JsonResponse(
        {
            "success": True,
            "message": f"Análise iniciada para {len(candidate_ids)} candidato(s) "
            "compatível(is). Acompanhe o progresso abaixo.",
        }
    )


@login_required
@required_plan("BASIC")
def generate_parecer_view(request, job_id: int, candidate_job_id: int):
    """Gera parecer ou retorna o existente se mesmo tipo."""
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    job = get_object_or_404(Job, id=job_id, user=request.user)
    candidate_job = get_object_or_404(CandidateJob, id=candidate_job_id, job=job)

    valid_statuses = (
        CandidateJob.PipelineStatus.SENT_MANAGER,
        CandidateJob.PipelineStatus.SENT_CLIENT,
    )
    if candidate_job.pipeline_status not in valid_statuses:
        return JsonResponse(
            {"error": "Parecer só pode ser gerado para candidatos enviados ao gestor ou cliente."},
            status=400,
        )

    parecer_type = request.POST.get("parecer_type", "").strip()
    valid_types = ["RESUMIDO", "COMPLETO", "ROBUSTO"]
    if parecer_type not in valid_types:
        return JsonResponse({"error": "Tipo de parecer inválido."}, status=400)

    # Se já existe parecer do mesmo tipo, retorna imediatamente
    if candidate_job.parecer_type == parecer_type and candidate_job.parecer:
        return JsonResponse(
            {
                "status": "completed",
                "parecer": candidate_job.parecer,
                "parecer_type": candidate_job.parecer_type,
            }
        )

    # Inicia geração em background
    _set_parecer_status(candidate_job_id, {"status": "running"})
    thread = threading.Thread(
        target=_run_parecer_generation,
        args=(candidate_job_id, parecer_type),
        daemon=True,
    )
    thread.start()

    return JsonResponse({"status": "running"})


@login_required
@required_plan("BASIC")
def parecer_status_view(request, job_id: int, candidate_job_id: int):
    """Retorna status da geração de parecer (para polling)."""
    job = get_object_or_404(Job, id=job_id, user=request.user)
    candidate_job = get_object_or_404(CandidateJob, id=candidate_job_id, job=job)

    payload = cache.get(_parecer_status_key(candidate_job_id))
    if payload:
        return JsonResponse(payload)

    # Se não há status em cache, retorna o que está no banco (já gerado antes)
    if candidate_job.parecer and candidate_job.parecer_type:
        return JsonResponse(
            {
                "status": "completed",
                "parecer": candidate_job.parecer,
                "parecer_type": candidate_job.parecer_type,
            }
        )

    return JsonResponse({"status": "idle"})


@login_required
@required_plan("BASIC")
def update_candidate_status(request, job_id: int, candidate_job_id: int):
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    try:
        job = get_object_or_404(Job, id=job_id, user=request.user)
        candidate_job = get_object_or_404(CandidateJob, id=candidate_job_id, job=job)

        new_status = request.POST.get("pipeline_status", "").strip()

        # Permite status vazio para limpar o status
        if new_status:
            valid_statuses = [choice[0] for choice in CandidateJob.PipelineStatus.choices]
            if new_status not in valid_statuses:
                return JsonResponse({"error": f"Status inválido: {new_status}"}, status=400)
            candidate_job.pipeline_status = new_status
        else:
            candidate_job.pipeline_status = ""

        candidate_job.save()

        return JsonResponse(
            {
                "success": True,
                "pipeline_status": candidate_job.pipeline_status or "",
                "pipeline_status_display": candidate_job.get_pipeline_status_display() or "-",
                "ready_at": candidate_job.ready_at.strftime("%d/%m/%Y")
                if candidate_job.ready_at
                else None,
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@required_plan("BASIC")
def update_job_status(request, job_id: int):
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    try:
        job = get_object_or_404(Job, id=job_id, user=request.user)

        new_status = request.POST.get("status", "").strip()

        if new_status:
            valid_statuses = [choice[0] for choice in Job.Status.choices]
            if new_status not in valid_statuses:
                return JsonResponse({"error": f"Status inválido: {new_status}"}, status=400)
            job.status = new_status
        else:
            job.status = Job.Status.OPEN

        job.save()

        return JsonResponse(
            {
                "success": True,
                "status": job.status,
                "status_display": job.get_status_display(),
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@required_plan("BASIC")
def generate_boolean_search(request, job_id: int):
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    try:
        job = get_object_or_404(Job, id=job_id, user=request.user)
        job.boolean_search = _build_boolean_search(job)
        job.save(update_fields=["boolean_search"])
        return JsonResponse(
            {
                "success": True,
                "boolean_search": job.boolean_search or "",
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@required_plan("BASIC")
def job_edit(request, job_id: int):
    job = get_object_or_404(Job, id=job_id, user=request.user)
    if request.method == "POST":
        form = JobForm(request.POST, instance=job)
        if form.is_valid():
            if request.POST.get("action") == "generate":
                job = form.save(commit=False)
                job.boolean_search = _build_boolean_search(job)
                job.save()
            else:
                form.save()
            return redirect("job_detail", job_id=job.id)
    else:
        form = JobForm(instance=job)
    return render(request, "core/job_edit.html", {"form": form, "job": job})

import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlencode

from django.contrib.auth import logout
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import F, Count, Q
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from .models import Job, Candidate, CandidateJob
from .forms import JobForm, CandidateForm, SignupForm
from .plans import required_plan
from .pdf_extractor import (
    import_candidates_from_folder,
    import_candidates_from_folder_no_ranking,
    search_and_rank_candidates_from_pool,
)


def home(request):
    return render(request, 'core/home.html')


def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = SignupForm()
    return render(request, 'registration/signup.html', {'form': form})


@login_required
def dashboard(request):
    return render(request, 'core/dashboard.html')


@login_required
@required_plan('BASIC')
def jobs(request):
    jobs_qs = Job.objects.filter(user=request.user)
    status = request.GET.get('status', '').strip()
    seniority = request.GET.get('seniority', '').strip()
    location = request.GET.get('location', '').strip()
    department = request.GET.get('department', '').strip()
    title = request.GET.get('title', '').strip()

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
        'jobs': jobs_qs,
        'filters': {
            'status': status,
            'seniority': seniority,
            'location': location,
            'department': department,
            'title': title,
        },
        'status_choices': Job.Status.choices,
    }
    return render(request, 'core/jobs.html', context)


@login_required
def search(request):
    return render(request, 'core/search.html')


@login_required
@required_plan('BASIC')
def talent_pool(request):
    message = ""
    import_message = ""
    form = CandidateForm()
    
    # Processa upload de ZIP/PDF
    if request.method == 'POST' and request.FILES.get('candidates_zip'):
        upload = request.FILES['candidates_zip']
        temp_dir = Path(tempfile.mkdtemp(prefix="talent_pool_import_"))
        uploaded_path = temp_dir / upload.name
        with uploaded_path.open('wb') as output:
            for chunk in upload.chunks():
                output.write(chunk)

        is_zip = zipfile.is_zipfile(uploaded_path)
        _set_talent_pool_import_status({"status": "running", "processed": 0, "total": 0})
        thread = threading.Thread(
            target=_run_talent_pool_import,
            args=(uploaded_path, is_zip, request.user.id),
            daemon=True,
        )
        thread.start()
        import_message = "Importação iniciada. Acompanhe o progresso abaixo."
    elif request.method == 'POST':
        # Processa formulário manual
        form = CandidateForm(request.POST)
        if form.is_valid():
            linkedin_url = form.cleaned_data['linkedin_url'].strip()
            candidate = Candidate.objects.filter(user=request.user, linkedin_url__iexact=linkedin_url).first()
            if candidate:
                changed = False
                for field, value in form.cleaned_data.items():
                    if value in (None, ''):
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

    # Filtros
    name_filter = request.GET.get('name', '').strip()
    location_filter = request.GET.get('location', '').strip()
    seniority_filter = request.GET.get('seniority', '').strip()
    company_filter = request.GET.get('company', '').strip()
    technologies_filter = request.GET.get('technologies', '').strip()

    candidates = Candidate.objects.filter(user=request.user)
    
    if name_filter:
        candidates = candidates.filter(name__icontains=name_filter)
    if location_filter:
        candidates = candidates.filter(location__icontains=location_filter)
    if seniority_filter:
        candidates = candidates.filter(seniority__icontains=seniority_filter)
    if company_filter:
        candidates = candidates.filter(current_company__icontains=company_filter)
    if technologies_filter:
        candidates = candidates.filter(technologies__icontains=technologies_filter)
    
    candidates = candidates.order_by('-updated_at', '-created_at')

    # Paginação: 10 candidatos por página
    paginator = Paginator(candidates, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Constrói query string para manter filtros na paginação
    query_params = {}
    if name_filter:
        query_params['name'] = name_filter
    if location_filter:
        query_params['location'] = location_filter
    if seniority_filter:
        query_params['seniority'] = seniority_filter
    if company_filter:
        query_params['company'] = company_filter
    if technologies_filter:
        query_params['technologies'] = technologies_filter
    query_string = urlencode(query_params)
    if query_string:
        query_string = '&' + query_string

    context = {
        'form': form,
        'candidates': page_obj,
        'page_obj': page_obj,
        'message': message,
        'import_message': import_message,
        'filters': {
            'name': name_filter,
            'location': location_filter,
            'seniority': seniority_filter,
            'company': company_filter,
            'technologies': technologies_filter,
        },
        'query_string': query_string,
        'import_status': cache.get(_talent_pool_import_status_key()),
    }
    return render(request, 'core/talent_pool.html', context)


def _run_talent_pool_import(uploaded_path: Path, is_zip: bool, user_id: int):
    """Executa importação de candidatos no banco de talentos do usuário em background."""
    temp_root = uploaded_path.parent
    try:
        def progress_callback(**kwargs):
            _set_talent_pool_import_status(kwargs)

        if is_zip:
            extract_dir = uploaded_path.parent
            with zipfile.ZipFile(uploaded_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            result = import_candidates_from_folder_no_ranking(
                str(extract_dir),
                user_id=user_id,
                progress_callback=progress_callback,
            )
        else:
            result = import_candidates_from_folder_no_ranking(
                str(uploaded_path),
                user_id=user_id,
                progress_callback=progress_callback,
            )
        _set_talent_pool_import_status({"status": "completed", "result": result})
    except Exception as exc:
        _set_talent_pool_import_status({"status": "error", "message": str(exc)})
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


@login_required
@required_plan('BASIC')
def talent_pool_import_status(request):
    """Endpoint AJAX para status da importação do banco de talentos."""
    payload = cache.get(_talent_pool_import_status_key()) or {"status": "idle"}
    return JsonResponse(payload)


@login_required
@required_plan('PREMIUM')
def reports(request):
    # Resumo geral (apenas dados do usuário)
    jobs_qs = Job.objects.filter(user=request.user)
    total_jobs = jobs_qs.count()
    jobs_by_status = dict(jobs_qs.values('status').annotate(cnt=Count('id')).values_list('status', 'cnt'))
    status_labels = dict(Job.Status.choices)
    jobs_by_status_display = [
        (status_labels.get(s, s), jobs_by_status.get(s, 0))
        for s in [Job.Status.OPEN, Job.Status.SEARCH_DONE, Job.Status.CANDIDATES_SENT, Job.Status.CLOSED]
    ]

    candidates_qs = Candidate.objects.filter(user=request.user)
    total_candidates = candidates_qs.count()
    candidates_ready = candidates_qs.filter(ready_at__isnull=False).count()
    total_links = CandidateJob.objects.filter(job__user=request.user).count()
    candidates_hired = CandidateJob.objects.filter(job__user=request.user, pipeline_status=CandidateJob.PipelineStatus.HIRED).count()

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
    for job in jobs_qs.order_by('-created_at')[:50]:
        links = job.candidate_links
        total_in_job = links.count()
        funnel = []
        for ps in pipeline_status_order:
            cnt = links.filter(pipeline_status=ps).count()
            funnel.append({'label': pipeline_labels.get(ps, ps), 'count': cnt})
        jobs_with_funnel.append({
            'job': job,
            'total_candidates': total_in_job,
            'funnel': funnel,
            'hired': links.filter(pipeline_status=CandidateJob.PipelineStatus.HIRED).count(),
        })

    funnel_headers = [pipeline_labels.get(ps, ps) for ps in pipeline_status_order]

    context = {
        'total_jobs': total_jobs,
        'jobs_by_status_display': jobs_by_status_display,
        'total_candidates': total_candidates,
        'candidates_ready': candidates_ready,
        'total_links': total_links,
        'candidates_hired': candidates_hired,
        'jobs_with_funnel': jobs_with_funnel,
        'funnel_headers': funnel_headers,
    }
    return render(request, 'core/reports.html', context)


@login_required
def logout_then_home(request):
    logout(request)
    return redirect('home')


@login_required
@required_plan('BASIC')
def job_create(request):
    if request.method == 'POST':
        form = JobForm(request.POST)
        if form.is_valid():
            job = form.save(commit=False)
            job.user = request.user
            job.save()
            return redirect('jobs')
    else:
        form = JobForm()
    return render(request, 'core/job_create.html', {'form': form})


def _build_boolean_search(job: Job) -> str:
    synonyms = {
        "js": ["javascript"],
        "javascript": ["js"],
        "node": ["node.js", "nodejs"],
        "nodejs": ["node.js", "node"],
        "node.js": ["node", "nodejs"],
        "react": ["reactjs"],
        "reactjs": ["react"],
        "k8s": ["kubernetes"],
        "kubernetes": ["k8s"],
        "aws": ["amazon web services"],
        "gcp": ["google cloud"],
        "ci/cd": ["cicd", "continuous integration", "continuous delivery"],
    }

    def normalize_list(value: str) -> list[str]:
        return [item.strip() for item in value.split(',') if item.strip()]

    def expand_term(term: str) -> list[str]:
        key = term.strip().lower()
        extra = synonyms.get(key, [])
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


def _import_status_key(job_id: int) -> str:
    return f"import_status_{job_id}"


def _search_status_key(job_id: int) -> str:
    return f"search_status_{job_id}"


def _talent_pool_import_status_key() -> str:
    return "talent_pool_import_status"


def _set_import_status(job_id: int, payload: dict) -> None:
    cache.set(_import_status_key(job_id), payload, timeout=60 * 60)


def _set_search_status(job_id: int, payload: dict) -> None:
    cache.set(_search_status_key(job_id), payload, timeout=60 * 60)


def _set_talent_pool_import_status(payload: dict) -> None:
    cache.set(_talent_pool_import_status_key(), payload, timeout=60 * 60)


def _run_import_job(job_id: int, uploaded_path: Path, is_zip: bool, job_description: str, role_title: str, user_id: int):
    temp_root = uploaded_path.parent
    try:
        def progress_callback(**kwargs):
            _set_import_status(job_id, kwargs)

        if is_zip:
            extract_dir = uploaded_path.parent
            with zipfile.ZipFile(uploaded_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            result = import_candidates_from_folder(
                str(extract_dir),
                job_description=job_description,
                weights={'skills': 40, 'technologies': 35, 'experience': 25},
                role_title=role_title,
                job_id=job_id,
                user_id=user_id,
                progress_callback=progress_callback,
            )
        else:
            result = import_candidates_from_folder(
                str(uploaded_path),
                job_description=job_description,
                weights={'skills': 40, 'technologies': 35, 'experience': 25},
                role_title=role_title,
                job_id=job_id,
                user_id=user_id,
                progress_callback=progress_callback,
            )
        _set_import_status(job_id, {"status": "completed", "result": result})
    except Exception as exc:
        _set_import_status(job_id, {"status": "error", "message": str(exc)})
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


@login_required
@required_plan('BASIC')
def job_detail(request, job_id: int):
    job = get_object_or_404(Job, id=job_id, user=request.user)
    def split_list(value: str):
        return [item.strip() for item in value.split(',') if item.strip()]

    filter_keys = {
        'pipeline_status',
        'candidate_seniority',
        'candidate_location',
        'candidate_name',
        'candidate_language',
        'candidate_must_have',
        'candidate_technologies',
        'min_adherence',
    }
    filters_storage_key = f"job_filters_{job.id}"
    if request.GET.get("clear_filters") == "1":
        request.session.pop(filters_storage_key, None)
    else:
        current_params = {k: request.GET.get(k, '').strip() for k in filter_keys}
        if any(v for v in current_params.values()):
            request.session[filters_storage_key] = current_params
        else:
            saved_filters = request.session.get(filters_storage_key, {})
            if saved_filters:
                return redirect(f"{request.path}?{urlencode(saved_filters)}")

    status_filter = request.GET.get('pipeline_status', '').strip()
    seniority_filter = request.GET.get('candidate_seniority', '').strip()
    location_filter = request.GET.get('candidate_location', '').strip()
    name_filter = request.GET.get('candidate_name', '').strip()
    language_filter = request.GET.get('candidate_language', '').strip()
    must_have_filter = request.GET.get('candidate_must_have', '').strip()
    technologies_filter = request.GET.get('candidate_technologies', '').strip()
    min_adherence_raw = request.GET.get('min_adherence', '').strip()

    import_message = ""
    if request.method == 'POST' and request.FILES.get('candidates_zip'):
        upload = request.FILES['candidates_zip']
        job_description = _build_job_description(job)
        role_title = job.title

        temp_dir = Path(tempfile.mkdtemp(prefix="talent_import_"))
        uploaded_path = temp_dir / upload.name
        with uploaded_path.open('wb') as output:
            for chunk in upload.chunks():
                output.write(chunk)

        is_zip = zipfile.is_zipfile(uploaded_path)
        _set_import_status(job.id, {"status": "running", "processed": 0, "total": 0})
        thread = threading.Thread(
            target=_run_import_job,
            args=(job.id, uploaded_path, is_zip, job_description, role_title, request.user.id),
            daemon=True,
        )
        thread.start()
        import_message = "Importação iniciada. Acompanhe o progresso abaixo."

    candidate_links = job.candidate_links.select_related('candidate')
    if status_filter:
        candidate_links = candidate_links.filter(pipeline_status=status_filter)
    if seniority_filter:
        candidate_links = candidate_links.filter(candidate__seniority__icontains=seniority_filter)
    if location_filter:
        candidate_links = candidate_links.filter(candidate__location__icontains=location_filter)
    if name_filter:
        candidate_links = candidate_links.filter(candidate__name__icontains=name_filter)
    if language_filter:
        candidate_links = candidate_links.filter(candidate__languages__icontains=language_filter)
    if must_have_filter:
        candidate_links = candidate_links.filter(candidate__skills__icontains=must_have_filter)
    if technologies_filter:
        candidate_links = candidate_links.filter(candidate__technologies__icontains=technologies_filter)
    if min_adherence_raw.isdigit():
        candidate_links = candidate_links.filter(adherence_score__gte=int(min_adherence_raw))
    candidate_links = candidate_links.order_by(F('adherence_score').desc(nulls_last=True))

    # Paginação: 10 candidatos por página
    paginator = Paginator(candidate_links, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Constrói query string para manter filtros na paginação
    query_params = {}
    if status_filter:
        query_params['pipeline_status'] = status_filter
    if seniority_filter:
        query_params['candidate_seniority'] = seniority_filter
    if location_filter:
        query_params['candidate_location'] = location_filter
    if name_filter:
        query_params['candidate_name'] = name_filter
    if language_filter:
        query_params['candidate_language'] = language_filter
    if must_have_filter:
        query_params['candidate_must_have'] = must_have_filter
    if technologies_filter:
        query_params['candidate_technologies'] = technologies_filter
    if min_adherence_raw and min_adherence_raw.strip():
        query_params['min_adherence'] = min_adherence_raw
    query_string = urlencode(query_params)
    if query_string:
        query_string = '&' + query_string

    context = {
        'job': job,
        'must_have_list': split_list(job.must_have),
        'nice_to_have_list': split_list(job.nice_to_have),
        'undesirable_list': split_list(job.undesirable),
        'import_message': import_message,
        'candidate_links': page_obj,
        'page_obj': page_obj,
        'candidate_filters': {
            'pipeline_status': status_filter,
            'candidate_seniority': seniority_filter,
            'candidate_location': location_filter,
            'candidate_name': name_filter,
            'candidate_language': language_filter,
            'candidate_must_have': must_have_filter,
            'candidate_technologies': technologies_filter,
            'min_adherence': min_adherence_raw,
        },
        'query_string': query_string,
        'pipeline_status_choices': job.candidate_links.model.PipelineStatus.choices,
        'job_status_choices': Job.Status.choices,
        'import_status': cache.get(_import_status_key(job.id)),
        'search_status': cache.get(_search_status_key(job.id)),
    }
    return render(request, 'core/job_detail.html', context)


@login_required
@required_plan('BASIC')
def job_import_status(request, job_id: int):
    get_object_or_404(Job, id=job_id, user=request.user)
    payload = cache.get(_import_status_key(job_id)) or {"status": "idle"}
    return JsonResponse(payload)


@login_required
@required_plan('BASIC')
def job_search_status(request, job_id: int):
    """Endpoint AJAX para status da busca no banco."""
    get_object_or_404(Job, id=job_id, user=request.user)
    payload = cache.get(_search_status_key(job_id)) or {"status": "idle"}
    return JsonResponse(payload)


def _run_search_in_pool(job_id: int, job_description: str, role_title: str, filters: dict | None = None, user_id: int | None = None):
    """Executa busca e rankeamento de candidatos do banco do usuário em background."""
    try:
        def progress_callback(**kwargs):
            _set_search_status(job_id, kwargs)
        
        weights = {'skills': 40, 'technologies': 35, 'experience': 25}
        result = search_and_rank_candidates_from_pool(
            job_id=job_id,
            job_description=job_description,
            weights=weights,
            role_title=role_title,
            progress_callback=progress_callback,
            filters=filters,
            user_id=user_id,
        )
        _set_search_status(job_id, {"status": "completed", "result": result})
    except Exception as exc:
        _set_search_status(job_id, {"status": "error", "message": str(exc)})


@login_required
@required_plan('BASIC')
def preview_candidates_search(request, job_id: int):
    """Preview de candidatos encontrados com filtros (sem rankeamento)."""
    if request.method != 'POST':
        return JsonResponse({"error": "Método não permitido"}, status=405)
    
    job = get_object_or_404(Job, id=job_id, user=request.user)
    
    # Extrai filtros do POST
    filters = {}
    name_filter = request.POST.get('name', '').strip()
    location_filter = request.POST.get('location', '').strip()
    seniority_filter = request.POST.get('seniority', '').strip()
    company_filter = request.POST.get('company', '').strip()
    technologies_filter = request.POST.get('technologies', '').strip()
    skills_filter = request.POST.get('skills', '').strip()
    languages_filter = request.POST.get('languages', '').strip()
    certifications_filter = request.POST.get('certifications', '').strip()
    ready_only = request.POST.get('ready_only') == 'on'
    
    if name_filter:
        filters['name'] = name_filter
    if location_filter:
        filters['location'] = location_filter
    if seniority_filter:
        filters['seniority'] = seniority_filter
    if company_filter:
        filters['company'] = company_filter
    if technologies_filter:
        filters['technologies'] = technologies_filter
    if skills_filter:
        filters['skills'] = skills_filter
    if languages_filter:
        filters['languages'] = languages_filter
    if certifications_filter:
        filters['certifications'] = certifications_filter
    if ready_only:
        filters['ready_only'] = True
    
    # Busca candidatos do usuário não vinculados à vaga
    linked_candidate_ids = CandidateJob.objects.filter(job_id=job_id).values_list('candidate_id', flat=True)
    candidates = Candidate.objects.filter(user=request.user).exclude(id__in=linked_candidate_ids)
    
    # Aplica filtros
    if name_filter:
        candidates = candidates.filter(name__icontains=name_filter)
    if location_filter:
        candidates = candidates.filter(location__icontains=location_filter)
    if seniority_filter:
        candidates = candidates.filter(seniority__icontains=seniority_filter)
    if company_filter:
        candidates = candidates.filter(current_company__icontains=company_filter)
    if technologies_filter:
        candidates = candidates.filter(technologies__icontains=technologies_filter)
    if skills_filter:
        candidates = candidates.filter(skills__icontains=skills_filter)
    if languages_filter:
        candidates = candidates.filter(languages__icontains=languages_filter)
    if certifications_filter:
        candidates = candidates.filter(certifications__icontains=certifications_filter)
    if ready_only:
        candidates = candidates.exclude(ready_at__isnull=True)
    
    total = candidates.count()
    
    # Paginação: 10 candidatos por página
    paginator = Paginator(candidates, 10)
    page_number = request.POST.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except:
        page_obj = paginator.page(1)
    
    # Prepara dados para JSON
    candidates_data = []
    for candidate in page_obj:
        candidates_data.append({
            'id': candidate.id,
            'name': candidate.name,
            'company': candidate.current_company or '-',
            'skills': candidate.skills[:100] + '...' if candidate.skills and len(candidate.skills) > 100 else (candidate.skills or '-'),
            'languages': candidate.languages[:100] + '...' if candidate.languages and len(candidate.languages) > 100 else (candidate.languages or '-'),
            'ready_at': candidate.ready_at.strftime('%d/%m/%Y') if candidate.ready_at else '-',
        })
    
    return JsonResponse({
        'success': True,
        'total': total,
        'page': page_obj.number,
        'num_pages': paginator.num_pages,
        'has_previous': page_obj.has_previous(),
        'has_next': page_obj.has_next(),
        'candidates': candidates_data,
        'filters': filters,
    })


@login_required
@required_plan('BASIC')
def search_candidates_in_pool(request, job_id: int):
    """Inicia busca e rankeamento de candidatos no banco de talentos do usuário para a vaga."""
    if request.method != 'POST':
        return JsonResponse({"error": "Método não permitido"}, status=405)
    
    job = get_object_or_404(Job, id=job_id, user=request.user)
    job_description = _build_job_description(job)
    role_title = job.title
    
    # Extrai filtros do POST (pode vir do preview)
    filters = {}
    name_filter = request.POST.get('name', '').strip()
    location_filter = request.POST.get('location', '').strip()
    seniority_filter = request.POST.get('seniority', '').strip()
    company_filter = request.POST.get('company', '').strip()
    technologies_filter = request.POST.get('technologies', '').strip()
    skills_filter = request.POST.get('skills', '').strip()
    languages_filter = request.POST.get('languages', '').strip()
    certifications_filter = request.POST.get('certifications', '').strip()
    ready_only = request.POST.get('ready_only') == 'on'
    
    if name_filter:
        filters['name'] = name_filter
    if location_filter:
        filters['location'] = location_filter
    if seniority_filter:
        filters['seniority'] = seniority_filter
    if company_filter:
        filters['company'] = company_filter
    if technologies_filter:
        filters['technologies'] = technologies_filter
    if skills_filter:
        filters['skills'] = skills_filter
    if languages_filter:
        filters['languages'] = languages_filter
    if certifications_filter:
        filters['certifications'] = certifications_filter
    if ready_only:
        filters['ready_only'] = True
    
    _set_search_status(job.id, {"status": "running", "processed": 0, "total": 0})
    thread = threading.Thread(
        target=_run_search_in_pool,
        args=(job.id, job_description, role_title, filters if filters else None, request.user.id),
        daemon=True,
    )
    thread.start()
    
    filter_msg = f" com {len(filters)} filtro(s) aplicado(s)" if filters else ""
    return JsonResponse({"success": True, "message": f"Análise iniciada{filter_msg}. Acompanhe o progresso abaixo."})


@login_required
@required_plan('BASIC')
def update_candidate_status(request, job_id: int, candidate_job_id: int):
    if request.method != 'POST':
        return JsonResponse({"error": "Método não permitido"}, status=405)
    
    try:
        job = get_object_or_404(Job, id=job_id, user=request.user)
        candidate_job = get_object_or_404(
            CandidateJob,
            id=candidate_job_id,
            job=job
        )
        
        new_status = request.POST.get('pipeline_status', '').strip()
        
        # Permite status vazio para limpar o status
        if new_status:
            valid_statuses = [choice[0] for choice in CandidateJob.PipelineStatus.choices]
            if new_status not in valid_statuses:
                return JsonResponse({"error": f"Status inválido: {new_status}"}, status=400)
            candidate_job.pipeline_status = new_status
        else:
            candidate_job.pipeline_status = ''
        
        candidate_job.save()
        
        return JsonResponse({
            "success": True,
            "pipeline_status": candidate_job.pipeline_status or "",
            "pipeline_status_display": candidate_job.get_pipeline_status_display() or "-",
            "ready_at": candidate_job.ready_at.strftime("%d/%m/%Y") if candidate_job.ready_at else None,
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@required_plan('BASIC')
def update_job_status(request, job_id: int):
    if request.method != 'POST':
        return JsonResponse({"error": "Método não permitido"}, status=405)
    
    try:
        job = get_object_or_404(Job, id=job_id, user=request.user)
        
        new_status = request.POST.get('status', '').strip()
        
        if new_status:
            valid_statuses = [choice[0] for choice in Job.Status.choices]
            if new_status not in valid_statuses:
                return JsonResponse({"error": f"Status inválido: {new_status}"}, status=400)
            job.status = new_status
        else:
            job.status = Job.Status.OPEN
        
        job.save()
        
        return JsonResponse({
            "success": True,
            "status": job.status,
            "status_display": job.get_status_display(),
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@required_plan('BASIC')
def generate_boolean_search(request, job_id: int):
    if request.method != 'POST':
        return JsonResponse({"error": "Método não permitido"}, status=405)

    try:
        job = get_object_or_404(Job, id=job_id, user=request.user)
        job.boolean_search = _build_boolean_search(job)
        job.save(update_fields=["boolean_search"])
        return JsonResponse({
            "success": True,
            "boolean_search": job.boolean_search or "",
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@required_plan('BASIC')
def job_edit(request, job_id: int):
    job = get_object_or_404(Job, id=job_id, user=request.user)
    if request.method == 'POST':
        form = JobForm(request.POST, instance=job)
        if form.is_valid():
            if request.POST.get('action') == 'generate':
                job = form.save(commit=False)
                job.boolean_search = _build_boolean_search(job)
                job.save()
            else:
                form.save()
            return redirect('job_detail', job_id=job.id)
    else:
        form = JobForm(instance=job)
    return render(request, 'core/job_edit.html', {'form': form, 'job': job})

# Talent Rank AI — Django Backend with LLM Integration (batch PDF/ZIP + scoring + async workers)

Python Django backend for screening, structured extraction, and ranking of candidates from PDFs exported from LinkedIn Recruiter, with LLM integration (Google GenAI).

[![CI](https://github.com/Cascapera/talent_rank_AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Cascapera/talent_rank_AI/actions/workflows/ci.yml)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/django-5.2-green.svg)](https://www.djangoproject.com/)

---

## Project Overview

Talent Rank AI is a backend system for technical recruiters who work with PDF exports from LinkedIn Recruiter. It extracts résumé data via LLM, normalizes it into a semantic structure, ranks candidates by job fit (0–100), and generates assessments ready to send to a hiring manager or client.

**Problem:** manual screening of dozens of CVs, repeated re-reading for every role, and low reuse of knowledge from previous searches.

**Main components:** web API (Django), asynchronous processing in threads, PostgreSQL database, LLM integration layer (Google GenAI).

---

## Repository Contents

- **REST API / Web:** endpoints for jobs, candidates, import, ranking, and assessments
- **Asynchronous processing:** background import via threads and status via cache
- **Batch ZIP/PDF pipeline:** ingestion of multiple PDFs or ZIPs in bulk
- **LLM integration layer:** structured extraction, ranking, and assessment generation
- **CI/CD + tests:** GitHub Actions, pytest, Ruff, pre-commit
- **Deploy:** AWS Lightsail, Gunicorn, Nginx

---

## Key Features

- PDF/ZIP ingestion via upload (API/forms)
- Résumé normalization and structured extraction via LLM
- Ranking (0–100) and technical justification per candidate
- Status pipeline (first contact → interview → sent to manager → hired)
- Asynchronous bulk import (talent pool and jobs)
- Optimized search and filters (PostgreSQL `unaccent`, filters by seniority, technologies, languages, minimum fit)
- Assessment generation (summary, full, or detailed) for manager/client
- AI-generated boolean search for LinkedIn Recruiter
- Single session per user

---

## System Architecture

```
Client/UI (browser)
       ↓
API Layer (Django views + forms)
       ↓
Application / Service Layer (views, pdf_extractor, llm_extractor)
       ↓
Domain (scoring rules, pipeline stages)
       ↓
Data Layer (PostgreSQL)
       ↓
Background threads (import jobs) ↔ Cache (FileBasedCache)
       ↓
LLM Provider (Google GenAI / Gemini)
```

The application follows a layered design: views orchestrate the flow, `pdf_extractor` coordinates text extraction and LLM calls, and `llm_extractor` holds all model integration logic. Asynchronous processing uses background threads (not Celery) with status stored in shared cache. The LLM layer is isolated in `llm_extractor`, so you can swap provider or model without changing the rest of the code.

---

## Observability

### Logging

Logs are emitted as structured JSON. Each run of the main vacancy processing flow carries a **correlation_id** so related log lines can be tied together. Events mark lifecycle steps: import, LLM extraction, ranking, and persistence. Together, this allows following a single vacancy import from start to finish in log aggregation tools.

### Metrics

Prometheus **counters** and **histograms** cover the same vacancy flow: candidate import, LLM extraction, ranking, and persistence. Histograms record duration in milliseconds. Counters record volume (e.g. starts) and failures. Label dimensions are intentionally narrow (**llm_provider**, **model_name**) to keep cardinality low.

### Endpoint

The app exposes **`GET /metrics`** in Prometheus text format for scraping. It is meant to be reached from an internal network or behind a reverse proxy; no authentication is implemented on this route.

### Scope

This is a first pass at observability, scoped to the core vacancy processing path. It does not include OpenTelemetry-style distributed tracing or bundled dashboards.

---

## Tech Stack

| Area | Technologies |
|------|----------------|
| **Backend** | Python 3.10 (prod), Django 5.2 |
| **Database** | PostgreSQL |
| **Async** | Threading (daemon threads) + FileBasedCache |
| **Infra** | Gunicorn, Nginx, Whitenoise, AWS Lightsail |
| **Quality** | Ruff, pytest, pytest-django, pre-commit, GitHub Actions |
| **AI** | Google GenAI (Gemini 2.5 Flash) via API |

---

## Domain Model

| Entity | Description |
|--------|-------------|
| **Profile** | User profile (plan, single session) |
| **Job** | Job posting (title, description, must-have, nice-to-have, status) |
| **Candidate** | Candidate (name, role, skills, technologies, languages, seniority, PDF résumé) |
| **CandidateJob** | Candidate–job link (fit score, justification, pipeline, assessment) |
| **Document / Resume** | Résumé PDF stored in `Candidate.resume_pdf` |

**Pipeline stages (CandidateJob):** First contact → Responded → Interview → Technical interview → Sent to manager → Candidate ready → Sent to client → Hired.

---

## Data Flow

1. **Upload (PDF/ZIP)** → API receives files via form
2. **Persistence and enqueue** → files saved to temp, import job started on a thread
3. **Worker processes** → sends the PDF to the LLM for structured extraction
4. **LLM layer call** → extraction, ranking, or assessment depending on the flow
5. **Save score + justification** → `CandidateJob.adherence_score`, `technical_justification`
6. **Update pipeline/status** → `CandidateJob.pipeline_status`, `ready_at`
7. **Expose via endpoints** → search, filters, and listings for the UI

---

## AI Integration Layer

### 8.1 Design (Isolation & Contracts)

AI integration lives in `core/llm_extractor.py`. Public functions expose clear contracts:

- **Extraction:** `extract_candidate_with_llm`, `extract_candidates_batch_with_llm`, `extract_candidate_no_ranking`, `extract_candidates_batch_no_ranking`
- **Ranking:** `calculate_adherence_for_candidate`, `calculate_adherence_batch_for_candidates`
- **Assessment:** `generate_parecer`

The rest of the system only calls these functions; the provider (Google GenAI) and prompt details stay encapsulated.

### 8.2 Providers

- **Google GenAI (Gemini 2.5 Flash):** primary use for extraction, ranking, and assessments
- **OpenAI:** not used at the moment; the architecture allows adding it as an alternate provider

### 8.3 Output Schema & Validation

- Structured JSON output (object or array depending on the flow)
- Validation and normalization of lists (skills, technologies, languages, certifications)
- Parsing fallback: JSON extraction even when the model returns markdown or extra text
- Failure handling: retries with backoff (3, 8, 15, 30s) for `RESOURCE_EXHAUSTED`, `429`, `503`, `UNAVAILABLE`

### 8.4 Cost & Performance Considerations

- **Batch processing:** multiple PDFs in a single LLM request when possible
- **Retries:** up to 4 attempts with exponential backoff
- **Cache:** no LLM result cache; job status uses FileBasedCache
- **Rate limiting:** depends on the Google API plan; retries mitigate temporary spikes

---

## API Reference

### Authentication

Django session (login/signup). No JWT/OAuth; the app targets web use with sessions.

### Main endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Home |
| GET | `/dashboard/` | Dashboard (authenticated) |
| GET/POST | `/vagas/` | List and create jobs |
| GET | `/vagas/<id>/` | Job detail and candidates |
| GET | `/vagas/<id>/import-status/` | Import status (JSON) |
| GET | `/vagas/<id>/search-status/` | Talent pool search status (JSON) |
| POST | `/vagas/<id>/candidatos/<cj_id>/status/` | Update candidate pipeline |
| POST | `/vagas/<id>/candidatos/<cj_id>/parecer/` | Generate assessment (async) |
| GET | `/vagas/<id>/candidatos/<cj_id>/parecer-status/` | Assessment status (JSON) |
| GET/POST | `/talentos/` | Talent pool |
| GET | `/talentos/import-status/` | Talent pool import status (JSON) |

### Sample response (import-status)

```json
{
  "status": "running",
  "processed": 5,
  "total": 10
}
```

There is no Swagger/OpenAPI; documentation lives in the views and this README.

---

## Background Processing

Asynchronous processing uses **threads** (not Celery):

- **Queues/tasks:** job import (`job_detail`), talent pool import (`talent_pool`), assessment generation
- **Retries:** implemented in the LLM layer (backoff for API errors)
- **Idempotency:** not guaranteed; re-import may create duplicates by `linkedin_url` (per-user constraint)
- **Running locally:** no separate worker; threads run inside the Django process (`python manage.py runserver` or Gunicorn)

---

## Security & Reliability

- **Authentication/authorization:** Django auth, `@login_required`, `@required_plan` (FREE/BASIC/PREMIUM)
- **Validation:** Django forms, file type and size checks
- **Single session:** `SingleSessionMiddleware` enforces one active login per user
- **Rate limiting:** not implemented at the moment
- **Access control:** candidates and jobs filtered by `user`
- **Error handling:** try/except in views, retries in the LLM layer, user-facing messages

---

## Testing & Code Quality

### Run tests

```bash
pytest core/tests/ -v --cov=core --cov-fail-under=50
make test   # via Makefile
```

### Coverage target

- Minimum 50% (`--cov-fail-under=50`)

### Lint

```bash
ruff check .
ruff format --check .
make lint
make format   # apply fixes
```

### CI/CD

- **Lint:** Ruff check + format on every push/PR
- **Tests:** pytest with coverage ≥ 50%
- **Deploy:** automatic CD via GitHub Actions after successful CI on `main` (SSH to Lightsail)

---

## Running Locally

### Requirements

- Python 3.10 — the version running in production. The CI also runs the suite
  on 3.12, but 3.10 is the gate: pin your local venv to it to avoid drift.
- PostgreSQL
- Google GenAI API key (`GEMINI_API_KEY`)

### .env.example

Create `.env` at the project root:

```
DJANGO_SECRET_KEY=your_secret_key
DJANGO_DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=talent_query
POSTGRES_USER=talent_query
POSTGRES_PASSWORD=talent_query
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

GEMINI_API_KEY=your_gemini_key
```

### Steps

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### Superuser (optional)

```bash
python manage.py createsuperuser
```

You do not need a separate worker; background processing runs in the Django process threads.

---

## Deployment

### AWS Lightsail

- Ubuntu instance + Lightsail PostgreSQL
- Gunicorn (systemd) + Nginx (reverse proxy)
- Environment variables in `.env` (do not commit)

### Environment variables (production)

```
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=False
ALLOWED_HOSTS=yourdomain.com,PUBLIC_IP
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
USE_X_FORWARDED_HOST=True
DJANGO_SECURE_PROXY_SSL=True

POSTGRES_DB=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_HOST=...
POSTGRES_PORT=5432

GEMINI_API_KEY=...
```

### Manual build / deploy

```bash
cd /var/www/talent_rank_ai
source .venv/bin/activate
git pull origin main
pip install -r requirements.txt --quiet
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart talent_rank_ai
```

### Automatic CI/CD deploy

The **CD - Deploy** workflow runs after successful CI on `main` and runs the steps above over SSH. See [docs/CD_SETUP.md](docs/CD_SETUP.md) for secrets and keys.

---

## Roadmap

- Observability (Sentry, metrics)
- LLM result caching (where applicable)
- Ranking optimization (configurable weights per job)
- Multi-tenant and RBAC
- Migration to Celery + Redis (more robust async processing)
- Horizontal scaling
- Docker / docker-compose for local environment and deploy

---

## Additional documentation

- [DEPLOY_LIGHTSAIL.md](DEPLOY_LIGHTSAIL.md) — Deploy on AWS Lightsail
- [DEPLOY_AWS.md](DEPLOY_AWS.md) — Deploy on AWS (general)
- [docs/CD_SETUP.md](docs/CD_SETUP.md) — Automatic deploy configuration
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contributing and standards

---

## Notes

- The system does not access or automate LinkedIn; it only works with files exported from LinkedIn Recruiter.
- Data and PDFs are processed according to your organization’s policy and the API in use (Google GenAI).

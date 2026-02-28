#Talent Rank AI — Django Backend com LLM Integration (batch PDF/ZIP + scoring + async workers)

Backend Django em Python para triagem, extração estruturada e ranking de candidatos a partir de PDFs exportados do LinkedIn Recruiter, com integração a LLMs (Google GenAI).

[![CI](https://github.com/Cascapera/talent_rank_AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Cascapera/talent_rank_AI/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/django-5.x-green.svg)](https://www.djangoproject.com/)

---

## Project Overview

O Talent Rank AI é um sistema backend para recrutadores técnicos que trabalham com exportações em PDF do LinkedIn Recruiter. Extrai dados dos currículos via LLM, normaliza em estrutura semântica, ranqueia candidatos por aderência à vaga (0–100) e gera pareceres prontos para envio ao gestor ou cliente.

**Problema:** triagem manual de dezenas de CVs, releitura massiva a cada vaga e baixo reaproveitamento do conhecimento gerado em buscas anteriores.

**Componentes principais:** API web (Django), processamento assíncrono em threads, banco PostgreSQL, camada de integração com LLM (Google GenAI).

---

## Repository Contents

- **API REST / Web:** endpoints para vagas, candidatos, importação, ranking e parecer
- **Processamento assíncrono:** importação em background via threads e status via cache
- **Pipeline batch ZIP/PDF:** ingestão de múltiplos PDFs ou ZIPs em lote
- **Camada de integração com LLM:** extração estruturada, ranking e geração de parecer
- **CI/CD + testes:** GitHub Actions, pytest, Ruff, pre-commit
- **Deploy:** AWS Lightsail, Gunicorn, Nginx

---

## Key Features

- Ingestão de PDFs/ZIPs via upload (API/forms)
- Normalização e extração estruturada de currículos via LLM
- Ranking (0–100) e justificativa técnica por candidato
- Pipeline de status (primeiro contato → entrevista → enviado ao gestor → contratado)
- Importação em lote assíncrona (banco de talentos e vagas)
- Busca e filtros otimizados (PostgreSQL `unaccent`, filtros por senioridade, tecnologias, idiomas, aderência mínima)
- Geração de parecer (resumido, completo ou robusto) para gestor/cliente
- Busca booleana gerada por IA para LinkedIn Recruiter
- Sessão única por usuário

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

A aplicação segue separação de camadas: views orquestram o fluxo, `pdf_extractor` coordena extração de texto e chamadas ao LLM, e `llm_extractor` concentra toda a lógica de integração com o modelo. O processamento assíncrono usa threads em background (não Celery) com status persistido em cache compartilhado. A camada de LLM fica isolada em `llm_extractor`, permitindo troca de provider ou modelo sem alterar o restante do código.

---

## Tech Stack

| Bloco | Tecnologias |
|-------|-------------|
| **Backend** | Python 3.12+, Django 5.x |
| **Database** | PostgreSQL |
| **Async** | Threading (daemon threads) + FileBasedCache |
| **Infra** | Gunicorn, Nginx, Whitenoise, AWS Lightsail |
| **Quality** | Ruff, pytest, pytest-django, pre-commit, GitHub Actions |
| **AI** | Google GenAI (Gemini 2.0 Flash) via API |

---

## Domain Model

| Entidade | Descrição |
|----------|-----------|
| **Profile** | Perfil do usuário (plano, sessão única) |
| **Job** | Vaga (título, descrição, must-have, nice-to-have, status) |
| **Candidate** | Candidato (nome, cargo, skills, tecnologias, idiomas, senioridade, currículo PDF) |
| **CandidateJob** | Vínculo candidato–vaga (aderência, justificativa, pipeline, parecer) |
| **Document / Resume** | PDF do currículo armazenado em `Candidate.resume_pdf` |

**Pipeline stages (CandidateJob):** Primeiro contato → Respondeu → Entrevista → Entrevista técnica → Enviado para gestor → Candidato pronto → Enviado para cliente → Contratado.

---

## Data Flow

1. **Upload (PDF/ZIP)** → API recebe arquivos via form
2. **Persistência e enfileiramento** → arquivos salvos em temp, job de importação iniciado em thread
3. **Worker processa** → extrai texto (pypdf) e/ou envia PDF ao LLM para extração estruturada
4. **Chamada à camada de LLM** → extração, ranking ou parecer conforme o fluxo
5. **Salva score + justificativa** → `CandidateJob.adherence_score`, `technical_justification`
6. **Atualiza pipeline/status** → `CandidateJob.pipeline_status`, `ready_at`
7. **Disponibiliza via endpoints** → busca, filtros e listagens para a UI

---

## AI Integration Layer

### 8.1 Design (Isolation & Contracts)

A integração com IA está isolada no módulo `core/llm_extractor.py`. Funções públicas expõem contratos claros:

- **Extração:** `extract_candidate_with_llm`, `extract_candidates_batch_with_llm`, `extract_candidate_no_ranking`, `extract_candidates_batch_no_ranking`
- **Ranking:** `calculate_adherence_for_candidate`, `calculate_adherence_batch_for_candidates`
- **Parecer:** `generate_parecer`

O restante do sistema consome apenas essas funções; o provider (Google GenAI) e os detalhes de prompt ficam encapsulados.

### 8.2 Providers

- **Google GenAI (Gemini 2.0 Flash):** uso principal para extração, rankeamento e parecer
- **OpenAI:** não utilizado no momento; a arquitetura permite adicionar como provider alternativo

### 8.3 Output Schema & Validation

- Saída estruturada em JSON (objeto ou array conforme o fluxo)
- Validação e normalização de listas (skills, technologies, languages, certifications)
- Fallback de parsing: extração de JSON mesmo quando o modelo retorna markdown ou texto extra
- Tratamento de falhas: retries com backoff (3, 8, 15, 30s) para `RESOURCE_EXHAUSTED`, `429`, `503`, `UNAVAILABLE`

### 8.4 Cost & Performance Considerations

- **Batch processing:** múltiplos PDFs em uma única requisição ao LLM quando possível
- **Retries:** até 4 tentativas com backoff exponencial
- **Cache:** não há cache de resultados de LLM; status de jobs usa FileBasedCache
- **Rate limiting:** dependente do plano da API Google; retries mitigam picos temporários

---

## API Reference

### Autenticação

Sessão Django (login/cadastro). Não há JWT/OAuth; a aplicação é voltada a uso web com sessões.

### Principais endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Home |
| GET | `/dashboard/` | Dashboard (autenticado) |
| GET/POST | `/vagas/` | Lista e cria vagas |
| GET | `/vagas/<id>/` | Detalhe da vaga e candidatos |
| GET | `/vagas/<id>/import-status/` | Status da importação (JSON) |
| GET | `/vagas/<id>/search-status/` | Status da busca no pool (JSON) |
| POST | `/vagas/<id>/candidatos/<cj_id>/status/` | Atualiza pipeline do candidato |
| POST | `/vagas/<id>/candidatos/<cj_id>/parecer/` | Gera parecer (assíncrono) |
| GET | `/vagas/<id>/candidatos/<cj_id>/parecer-status/` | Status do parecer (JSON) |
| GET/POST | `/talentos/` | Banco de talentos |
| GET | `/talentos/import-status/` | Status da importação do pool (JSON) |

### Exemplo de resposta (import-status)

```json
{
  "status": "running",
  "processed": 5,
  "total": 10
}
```

Não há Swagger/OpenAPI; a documentação está nas views e neste README.

---

## Background Processing

O processamento assíncrono usa **threads** (não Celery):

- **Filas/tarefas:** importação de vagas (`job_detail`), importação do banco de talentos (`talent_pool`), geração de parecer
- **Retries:** implementados na camada de LLM (backoff para erros de API)
- **Idempotência:** não garantida; reimportar pode criar duplicatas por `linkedin_url` (constraint por usuário)
- **Rodar localmente:** não há worker separado; as threads sobem com o processo Django (`python manage.py runserver` ou Gunicorn)

---

## Security & Reliability

- **Autenticação/autorização:** Django auth, `@login_required`, `@required_plan` (FREE/BASIC/PREMIUM)
- **Validações:** forms Django, validação de tipos e tamanhos de arquivo
- **Sessão única:** `SingleSessionMiddleware` garante um login ativo por usuário
- **Rate limiting:** não implementado no momento
- **Controle de acesso:** candidatos e vagas filtrados por `user`
- **Tratamento de erros:** try/except nas views, retries na camada de LLM, mensagens ao usuário

---

## Testing & Code Quality

### Rodar testes

```bash
pytest core/tests/ -v --cov=core --cov-fail-under=50
make test   # via Makefile
```

### Cobertura alvo

- Mínimo 50% (`--cov-fail-under=50`)

### Lint

```bash
ruff check .
ruff format --check .
make lint
make format   # aplica correções
```

### CI/CD

- **Lint:** Ruff check + format em todo push/PR
- **Testes:** pytest com coverage ≥ 50%
- **Deploy:** CD automático via GitHub Actions após CI bem-sucedido na `main` (SSH para Lightsail)

---

## Running Locally

### Requisitos

- Python 3.12+
- PostgreSQL
- Chave da API Google GenAI (`GEMINI_API_KEY`)

### .env.example

Crie `.env` na raiz:

```
DJANGO_SECRET_KEY=sua_chave_secreta
DJANGO_DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=talent_query
POSTGRES_USER=talent_query
POSTGRES_PASSWORD=talent_query
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

GEMINI_API_KEY=sua_chave_gemini
```

### Passos

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### Superuser (opcional)

```bash
python manage.py createsuperuser
```

Não é necessário subir worker separado; o processamento em background roda nas threads do processo Django.

---

## Deployment

### AWS Lightsail

- Instância Ubuntu + PostgreSQL Lightsail
- Gunicorn (systemd) + Nginx (reverse proxy)
- Variáveis de ambiente em `.env` (não commitar)

### Variáveis de ambiente (produção)

```
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=False
ALLOWED_HOSTS=seudominio.com.br,IP_PUBLICO
CSRF_TRUSTED_ORIGINS=https://seudominio.com.br
USE_X_FORWARDED_HOST=True
DJANGO_SECURE_PROXY_SSL=True

POSTGRES_DB=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_HOST=...
POSTGRES_PORT=5432

GEMINI_API_KEY=...
```

### Build / deploy manual

```bash
cd /var/www/talent_rank_ai
source .venv/bin/activate
git pull origin main
pip install -r requirements.txt --quiet
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart talent_rank_ai
```

### CI/CD deploy automático

O workflow **CD - Deploy** roda após o CI bem-sucedido na `main` e executa os passos acima via SSH. Ver [docs/CD_SETUP.md](docs/CD_SETUP.md) para configurar secrets e chaves.

---

## Roadmap

- Observabilidade (Sentry, métricas)
- Caching de resultados de LLM (quando aplicável)
- Otimização de ranking (pesos configuráveis por vaga)
- Multi-tenant e RBAC
- Migração para Celery + Redis (processamento assíncrono mais robusto)
- Escalabilidade horizontal
- Docker / docker-compose para ambiente local e deploy

---

## Documentação adicional

- [DEPLOY_LIGHTSAIL.md](DEPLOY_LIGHTSAIL.md) — Deploy no AWS Lightsail
- [DEPLOY_AWS.md](DEPLOY_AWS.md) — Deploy em AWS (geral)
- [docs/CD_SETUP.md](docs/CD_SETUP.md) — Configuração do deploy automático
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contribuição e padrões

---

## Observações

- O sistema não acessa nem automatiza o LinkedIn; trabalha apenas com arquivos exportados pelo LinkedIn Recruiter.
- Dados e PDFs são processados conforme a política de uso da organização e da API utilizada (Google GenAI).

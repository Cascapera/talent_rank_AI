# Talent Rank AI

Plataforma de recrutamento técnico com IA para triagem, ranking e parecer de candidatos a partir de exportações do LinkedIn Recruiter.

[![CI](https://github.com/Cascapera/talent_rank_AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Cascapera/talent_rank_AI/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/django-5.x-green.svg)](https://www.djangoproject.com/)

---

## Visão geral

Sistema para recrutadores técnicos que trabalham com exportações em PDF do LinkedIn Recruiter. Extrai dados dos currículos, ranqueia por aderência à vaga e gera pareceres prontos para envio ao gestor ou cliente.

**Problema:** triagem manual de dezenas de CVs, releitura massiva a cada vaga e baixo reaproveitamento do conhecimento gerado em buscas anteriores.

---

## Funcionalidades

| Recurso | Descrição |
|---------|-----------|
| Extração com IA | Dados normalizados dos PDFs: cargo, skills, idiomas, certificações, senioridade |
| Ranking por aderência | Nota 0–100% e justificativa técnica por candidato |
| Parecer para gestor | Geração de parecer (resumido, completo ou robusto) |
| Banco de talentos | Candidatos reutilizáveis, busca por skills/cargo/idiomas, vínculo a vagas |
| Busca booleana com IA | Geração automática da string de busca para LinkedIn Recruiter |
| Pipeline visual | Status: primeiro contato → entrevista → enviado ao gestor → contratado |
| Filtros avançados | Busca sem acento, filtros por senioridade, tecnologias, idiomas, aderência mínima |
| Sessão única | Um login ativo por usuário |

---

## Stack

| Camada | Tecnologia |
|--------|------------|
| Backend | Django 5.x, Python 3.12+ |
| Banco | PostgreSQL |
| IA | Google GenAI (Gemini) |
| Produção | Gunicorn, Nginx, AWS Lightsail |
| Qualidade | pytest, Ruff, pre-commit, CI/CD (GitHub Actions) |

---

## Desenvolvimento

**Requisitos:** Python 3.12+, PostgreSQL, chave da API Gemini.

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\Activate.ps1  # Windows

pip install -r requirements.txt
```

Crie `.env` na raiz com `DJANGO_SECRET_KEY`, `POSTGRES_*`, `GEMINI_API_KEY` e `ALLOWED_HOSTS`.

```bash
python manage.py migrate
python manage.py runserver
```

---

## Testes

```bash
pytest core/tests/ -v --cov=core --cov-fail-under=50
make test   # via Makefile
```

- pytest + pytest-django
- Cobertura mínima: 50%
- Ruff para lint e formatação
- pre-commit e CI no GitHub Actions

---

## Estrutura

```
core/           # App principal (vagas, candidatos, importação, ranking, parecer)
talent_query/   # Configuração Django
templates/      # Templates HTML
static/         # Arquivos estáticos
scripts/        # Backup do banco
```

---

## Documentação

- [DEPLOY_LIGHTSAIL.md](DEPLOY_LIGHTSAIL.md) — Deploy no AWS Lightsail
- [DEPLOY_AWS.md](DEPLOY_AWS.md) — Deploy em AWS (geral)
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contribuição e padrões

---

## Observações

- O sistema não acessa nem automatiza o LinkedIn; trabalha apenas com arquivos exportados pelo LinkedIn Recruiter.
- Dados e PDFs são processados conforme a política de uso da organização e da API utilizada (Google GenAI).

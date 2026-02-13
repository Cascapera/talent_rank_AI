# Talent Rank AI

**Rankeie candidatos por aderência à vaga em segundos — com IA.**

Plataforma para recrutadores que utilizam o LinkedIn Recruiter: transforme exportações em PDF em um banco de talentos pesquisável, ranqueado por aderência à vaga, com pipeline e filtros prontos para uso no dia a dia.

www.talentrankai.com

---

## Por que usar?

- **Menos tempo triando CVs** — A IA extrai dados dos PDFs e ranqueia os candidatos por fit com a vaga.
- **Banco de talentos reutilizável** — Candidatos ficam cadastrados; busque por skills, cargo, idiomas e use em novas vagas.
- **Pipeline visual** — Acompanhe status (primeiro contato, entrevista, enviado ao gestor etc.) direto na tela.
- **Controle por plano** — Plano Basic: banco próprio. Plano Premium: pool compartilhado entre recrutadores.

Ideal para equipes de recrutamento que exportam listas do LinkedIn Recruiter e querem centralizar, ranquear e filtrar candidatos sem planilhas.

---

## Como funciona

1. **Crie a vaga** — Preencha descrição, área, senioridade, stack, idiomas e requisitos.
2. **Importe os PDFs** — Envie um ZIP com os PDFs exportados do LinkedIn Recruiter (ou um PDF avulso).
3. **Deixe a IA trabalhar** — Extração de dados, normalização de skills e cálculo de aderência à vaga.
4. **Use filtros e ranking** — Veja os melhores fits, filtre por idioma, tecnologias, senioridade e acompanhe o pipeline.

---

## Principais recursos

| Recurso | Descrição |
|--------|------------|
| **Importação em lote** | ZIP com vários PDFs ou PDF único; processamento em background. |
| **Extração com IA** | Dados extraídos e normalizados (cargo, skills, idiomas, certificações, senioridade). |
| **Ranking por aderência** | Nota de 0–100% e justificativa técnica por candidato, com base na descrição da vaga. |
| **Banco de talentos** | Cadastro manual ou via importação; filtros por nome, cargo, empresa, skills, idiomas, certificações. |
| **Pipeline por vaga** | Status do candidato na vaga: primeiro contato, entrevista, enviado ao gestor, contratado etc. |
| **Busca e filtros** | Filtros com busca sem acento (ex.: "senior" ou "sênior") em todos os campos. |
| **Sessão única** | Um login ativo por usuário; novo login encerra o anterior. |

---

## Stack técnica

- **Backend:** Django 5.x, Python 3.12+
- **Banco:** PostgreSQL
- **IA:** Google GenAI (extração e ranking)
- **Produção:** Gunicorn, Nginx, AWS Lightsail

---

## Requisitos para rodar

- Python 3.12+
- PostgreSQL acessível
- Variáveis de ambiente (incluindo chave da API GenAI, se usar extração/ranking por IA)

---

## Configuração local

1. **Ambiente virtual e dependências**

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

2. **Arquivo `.env` na raiz do projeto**

```env
DJANGO_SECRET_KEY=sua_chave_secreta
DJANGO_DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=talent_rank_ai
POSTGRES_USER=usuario
POSTGRES_PASSWORD=senha
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Opcional: para extração e ranking com IA
GEMINI_API_KEY=sua_chave_gemini
```

3. **Migrações e servidor**

```bash
python manage.py migrate
python manage.py runserver
```

---

## Backup do banco (Linux)

O script `scripts/backup_postgres.sh` gera backups e mantém os dois últimos:

- Atual: `backups/db_backup.dump`
- Anterior: `backups/db_backup.prev.dump`

Exemplo de cron (domingo às 03:00):

```bash
0 3 * * 0 ENV_FILE=/var/www/talent_rank_ai/.env /var/www/talent_rank_ai/scripts/backup_postgres.sh >> /var/www/talent_rank_ai/backups/backup.log 2>&1
```

---

## Deploy

- **AWS Lightsail:** `DEPLOY_LIGHTSAIL.md`
- **AWS (geral):** `DEPLOY_AWS.md`

---

## Estrutura do projeto

```
core/              # App principal (vagas, candidatos, importação, ranking)
talent_query/      # Configuração Django
templates/         # Templates HTML
static/            # Arquivos estáticos
scripts/           # Scripts (backup, etc.)
```

---

## Observações

- O sistema **não** acessa nem automatiza o LinkedIn; trabalha apenas com arquivos exportados pelo próprio LinkedIn Recruiter.
- Dados e PDFs são processados conforme a política de uso da sua organização e da API utilizada (ex.: Google GenAI).

# Talent Rank AI

Plataforma interna para transformar PDFs exportados do LinkedIn Recruiter em um banco pesquisavel, ranquear candidatos por aderencia a uma vaga e gerar listas prontas para abordagem.

## Visao geral

O Talent Rank AI organiza dados de candidatos em um talent pool reutilizavel. O fluxo principal e:

1. Criar uma vaga e definir requisitos.
2. Importar ZIPs com PDFs exportados do LinkedIn Recruiter.
3. Extrair informacoes, normalizar dados e armazenar no banco.
4. Ranquear candidatos por aderencia.
5. Usar filtros e status para acompanhar o pipeline.

## Principais recursos

- Ingestao de ZIPs com PDFs exportados
- Extracao de dados e normalizacao de skills
- Busca interna por filtros e palavras-chave
- Ranking por aderencia a vaga
- Tabela web com prioridade e status
- Historico de vagas e candidatos

## Stack

- Django 5.x
- PostgreSQL
- python-dotenv
- pypdf
- Google GenAI (opcional)
- Gunicorn + Whitenoise (producao)

## Requisitos

- Python 3.12+
- PostgreSQL acessivel
- Pip e ambiente virtual

## Configuracao local

1. Crie o ambiente virtual:

```bash
python -m venv .venv
```

2. Ative o ambiente:

```bash
.venv\Scripts\Activate.ps1
```

3. Instale dependencias:

```bash
pip install -r requirements.txt
```

4. Configure o `.env` na raiz:

```
DJANGO_SECRET_KEY=gerar_uma_chave_segura
DJANGO_DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=talent_rank_ai
POSTGRES_USER=usuario
POSTGRES_PASSWORD=senha
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

5. Rode migracoes e servidor:

```bash
python manage.py migrate
python manage.py runserver
```

## Backup semanal do banco (Linux)

O script `scripts/backup_postgres.sh` cria backups semanais e mantem apenas os dois ultimos:

- Atual: `backups/db_backup.dump`
- Anterior: `backups/db_backup.prev.dump`

Exemplo de cron (domingo, 03:00):

```bash
0 3 * * 0 ENV_FILE=/var/www/talent_rank_ai/.env /var/www/talent_rank_ai/scripts/backup_postgres.sh >> /var/www/talent_rank_ai/backups/backup.log 2>&1
```

## Deploy

Consulte:

- `DEPLOY_LIGHTSAIL.md`
- `DEPLOY_AWS.md`

## Estrutura do projeto

```
core/                 # App principal
talent_query/         # Configuracao Django
templates/            # Templates HTML
static/               # Arquivos estaticos
scripts/              # Scripts utilitarios
```

## Observacoes

- O sistema nao automatiza a plataforma do LinkedIn.
- Trabalha apenas com arquivos exportados oficialmente.

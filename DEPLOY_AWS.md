# Deploy do Talent Rank AI na AWS e publicação do domínio

Este guia descreve como colocar o projeto no **AWS Elastic Beanstalk** e publicar um **domínio** com HTTPS usando **Route 53** e **AWS Certificate Manager (ACM)**.

---

## 1. Pré-requisitos

- Conta na **AWS**
- **PostgreSQL** disponível (RDS na AWS ou outro serviço)
- Domínio próprio (ex.: `talentrankai.com.br`) ou uso da URL gerada pelo Elastic Beanstalk
- **Git** (recomendado para deploy via EB CLI)
- **AWS CLI** instalado e configurado (`aws configure`) — opcional, mas útil

---

## 2. Banco de dados (RDS PostgreSQL)

### 2.1 Criar um banco na AWS RDS

1. No console AWS: **RDS** → **Create database**
2. Escolha **PostgreSQL** e a versão compatível (ex.: 15).
3. **Template:** Dev/Test ou Production, conforme necessidade.
4. Em **Settings**: DB name = `talent_rank_ai` (ou o que preferir).
5. **Master username** e **Master password**: anote para usar nas variáveis de ambiente.
6. **Connectivity**: VPC deve ser a **mesma** do Elastic Beanstalk (mesmo ambiente ou VPC vinculada).
7. **Security group**: permitir acesso na porta **5432** a partir do security group das instâncias do EB (ou do balanceador).

Crie o banco e anote: **endpoint**, **porta**, **nome**, **usuário**, **senha**.

### 2.2 (Opcional) Usar SQLite localmente

Se quiser testar o deploy sem RDS, dá para usar SQLite em produção só para teste — não recomendado para uso real. Para isso, seria preciso ajustar `settings.py` para usar SQLite quando `POSTGRES_HOST` estiver vazio (não descrito neste guia; em produção use PostgreSQL).

---

## 3. Variáveis de ambiente (produção)

No Elastic Beanstalk você deve configurar estas variáveis no ambiente:

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `DJANGO_SECRET_KEY` | Chave secreta do Django (gere uma nova para produção) | String longa e aleatória |
| `DJANGO_DEBUG` | Debug desligado em produção | `False` |
| `ALLOWED_HOSTS` | Domínios permitidos | `.seudominio.com.br,seu-ambiente.region.elasticbeanstalk.com` |
| `POSTGRES_DB` | Nome do banco | `talent_rank_ai` |
| `POSTGRES_USER` | Usuário do banco | usuário do RDS |
| `POSTGRES_PASSWORD` | Senha do banco | senha do RDS |
| `POSTGRES_HOST` | Endpoint do RDS | `seu-db.xxxxxxxx.region.rds.amazonaws.com` |
| `POSTGRES_PORT` | Porta do PostgreSQL | `5432` |

Para gerar uma nova `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**ALLOWED_HOSTS** deve incluir:
- O domínio que você vai usar (ex.: `talentrankai.com.br`, `.talentrankai.com.br` para subdomínios).
- A URL do Elastic Beanstalk (ex.: `nome-ambiente.us-east-1.elasticbeanstalk.com`).

Exemplo: `ALLOWED_HOSTS=.talentrankai.com.br,talentrankai.com.br,meuambiente.us-east-1.elasticbeanstalk.com`

---

## 4. Deploy no Elastic Beanstalk

### 4.1 Pelo Console AWS

1. Acesse **Elastic Beanstalk** → **Create Application**.
2. **Application name**: `talent-rank-ai` (ou outro).
3. **Platform**: **Python** e a versão usada no projeto (ex.: Python 3.12).
4. **Application code**: “Upload your code”.
5. Crie um **ZIP** da aplicação:
   - Inclua: pasta do projeto (com `manage.py`, `talent_query/`, `core/`, `templates/`, `static/`, `requirements.txt`, `Procfile`, `.ebextensions/`).
   - **Não** inclua: `__pycache__/`, `.venv/`, `venv/`, `*.pyc`, `.env`, `exemplos_pdf/`, `staticfiles/` (se existir).
6. Faça o upload do ZIP e crie o ambiente.
7. Depois que o ambiente existir:
   - **Configuration** → **Software** → **Edit** → **Environment properties** e preencha todas as variáveis da tabela acima.

### 4.2 Com EB CLI (recomendado)

```bash
# Instalar EB CLI (uma vez)
pip install awsebcli

# Na raiz do projeto (onde está manage.py)
cd C:\Users\Guillherme\Desktop\Alura\talent_rank_AI

# Inicializar aplicação EB
eb init

# Escolha a região (ex.: us-east-1), não crie SSH por enquanto
# Crie o ambiente e faça o primeiro deploy
eb create talent-rank-ai-prod
```

Para os próximos deploys:

```bash
eb deploy
```

Para definir variáveis de ambiente:

```bash
eb setenv DJANGO_SECRET_KEY="sua-chave" DJANGO_DEBUG=False ALLOWED_HOSTS=".seudominio.com.br,seu-ambiente.region.elasticbeanstalk.com" POSTGRES_DB=talent_rank_ai POSTGRES_USER=usuario POSTGRES_PASSWORD=senha POSTGRES_HOST=seu-db.xxxxx.region.rds.amazonaws.com POSTGRES_PORT=5432
```

(Substitua pelos valores reais do RDS e do domínio.)

---

## 5. Publicar o domínio (Route 53 + HTTPS)

### 5.1 Comprar/registrar o domínio (se ainda não tiver)

- No console AWS: **Route 53** → **Register domain**.
- Ou use um registrador externo e só gerencie o DNS no Route 53 (credenciais do registrador à parte).

### 5.2 Criar certificado SSL (ACM)

1. **AWS Certificate Manager** → **Request certificate**.
2. **Fully qualified domain name**: `seudominio.com.br` e, se quiser, `*.seudominio.com.br`.
3. **Validation**: DNS validation (recomendado).
4. **Route 53** → criar os registros de validação indicados pelo ACM (ou “Create records in Route 53” se o domínio estiver na mesma conta).
5. Aguarde o certificado ficar **Issued**.

### 5.3 Apontar o domínio para o Elastic Beanstalk

1. No **Elastic Beanstalk**, anote:
   - **Environment** → **Configuration** → **Load balancer**:
     - URL do ambiente (ex.: `talent-rank-ai-prod.us-east-1.elasticbeanstalk.com`).
2. No **Route 53**:
   - Crie uma **hosted zone** para o domínio (ex.: `seudominio.com.br`) se ainda não existir.
   - **Create record**:
     - **Record name**: em branco (para `seudominio.com.br`) ou um subdomínio (ex.: `app` para `app.seudominio.com.br`).
     - **Record type**: **A**.
     - **Alias**: **Yes**.
     - **Route traffic to**: “Alias to Elastic Beanstalk environment” e escolha a região e o ambiente do EB.

Assim o domínio passa a apontar para o ambiente do EB.

### 5.4 HTTPS no Load Balancer (Application Load Balancer)

1. **Elastic Beanstalk** → seu ambiente → **Configuration** → **Load balancer** → **Edit**.
2. Na **Listeners**:
   - Adicione um listener **HTTPS** na porta **443**.
   - **SSL certificate**: escolha o certificado que você criou no ACM.
   - (Opcional) Redirecione HTTP (80) → HTTPS (443) no mesmo load balancer.
3. Salve e aguarde a atualização do ambiente.

Depois disso, acesse `https://seudominio.com.br` (ou o subdomínio que configurou).

---

## 6. Backup semanal do banco (pg_dump)

1. Instale o cliente do PostgreSQL na instância (EC2/EB):

```bash
sudo apt install -y postgresql-client
```

2. Garanta o script no servidor:

```bash
chmod +x /var/app/current/scripts/backup_postgres.sh
```

3. Configure o cron para rodar semanalmente (domingo, 03:00):

```bash
crontab -e
```

Adicione:

```bash
0 3 * * 0 ENV_FILE=/var/app/current/.env /var/app/current/scripts/backup_postgres.sh >> /var/app/current/backups/backup.log 2>&1
```

Mantem apenas os 2 ultimos backups:
- Atual: `/var/app/current/backups/db_backup.dump`
- Anterior: `/var/app/current/backups/db_backup.prev.dump`
Se preferir, defina as variaveis diretamente no cron em vez de usar `.env`.

---

## 7. Checklist pós-deploy

- [ ] Ambiente do EB no ar (sem erro de health).
- [ ] Variáveis de ambiente corretas (principalmente `POSTGRES_*`, `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, `DJANGO_DEBUG=False`).
- [ ] Migrations aplicadas (já rodam pelo `.ebextensions` no deploy).
- [ ] Static files servidos (Whitenoise; `collectstatic` já é rodado no deploy).
- [ ] Domínio apontando no Route 53 para o ambiente do EB.
- [ ] Certificado ACM em **Issued** e associado ao listener 443 do load balancer.
- [ ] Teste de login, cadastro e fluxos principais em `https://seudominio.com.br`.

---

## 8. Arquivos do projeto usados no deploy

- **Procfile**: inicia o Gunicorn (útil para plataformas tipo Heroku; o EB usa o WSGIPath do `.ebextensions`).
- **.ebextensions/django.config**: define `WSGIPath`, `collectstatic` e `migrate` no deploy.
- **requirements.txt**: inclui `gunicorn` e `whitenoise` para produção.
- **settings.py**: usa `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `ALLOWED_HOSTS` e banco via variáveis de ambiente; Whitenoise para estáticos.

---

## 9. Dicas

- **Logs**: `eb logs` (com EB CLI) ou no console: Environment → **Logs** → **Request log**.
- **.env**: não envie `.env` no ZIP. Use apenas as variáveis de ambiente do EB (ou do RDS/Secrets Manager em cenários mais avançados).
- **Google GenAI**: se a app usar API da Google, adicione a chave como variável de ambiente no EB (ex.: `GOOGLE_API_KEY`) e leia em `settings.py` ou no código que consome a API.
- **Custos**: RDS, EB e Route 53 geram custo. Domínio registrado na AWS também. Monitore o **Billing** e use o **Free Tier** quando se aplicar.

Se quiser, na próxima etapa podemos detalhar apenas a parte do domínio (Route 53 + ACM) ou apenas o primeiro deploy no EB, passo a passo na sua conta.

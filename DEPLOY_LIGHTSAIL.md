# Deploy no AWS Lightsail (baixo custo) + PostgreSQL Lightsail

Este guia prepara o Talent Rank AI para rodar **em uma instância Lightsail** com **PostgreSQL no Lightsail** e domínio publicado.

> Objetivo: setup simples, custo baixo e fácil manutenção.

---

## 1. Criar instância Lightsail

1. **Lightsail → Create instance**
2. **Region/Zone**: escolha a região mais próxima.
3. **OS**: Linux (Ubuntu 22.04 LTS recomendado).
4. **Plano**: o menor inicialmente (ex.: 5–10 USD/mês).
5. Dê um nome (ex.: `talent_rank_AI_prod`).

### 1.1 Static IP (recomendado)

1. **Networking → Create static IP**
2. Atribua à instância.  
3. Use esse IP para DNS.

---

## 2. Criar PostgreSQL no Lightsail

1. **Lightsail → Databases → Create database**
2. Escolha **PostgreSQL**.
3. Plano inicial (menor disponível).
4. Nome ex.: `talent-rank-ai-db`
5. Aguarde estar **Running**.

### 2.1 Conectar instância ao banco

Na aba do banco, copie:

- **Endpoint**
- **Porta**
- **Usuário**
- **Senha**

No banco, habilite **public access** somente se necessário.  
O ideal é deixar acesso apenas da sua instância.

---

## 3. Abrir portas na instância

Em **Networking** da instância:

- **HTTP (80)**: aberto
- **HTTPS (443)**: aberto
- **SSH (22)**: aberto (apenas seu IP, se possível)

---

## 4. Acessar a instância via SSH

Pelo console Lightsail (botão **Connect**) ou via terminal:

```bash
ssh ubuntu@SEU_IP
```

---

## 5. Instalar dependências do sistema

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip nginx git
```

---

## 6. Baixar o projeto

Depois que você criar o repositório no Git:

```bash
cd /var/www
sudo mkdir -p talent_rank_ai
sudo chown -R $USER:$USER /var/www/talent_rank_ai

git clone https://github.com/SEU_USUARIO/SEU_REPO.git /var/www/talent_rank_ai
cd /var/www/talent_rank_ai
```

---

## 7. Criar ambiente virtual e instalar dependências

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 8. Variáveis de ambiente

Crie um arquivo `.env` no servidor **(somente no servidor, não commitar)**:

```bash
nano /var/www/talent_rank_ai/.env
```

Conteúdo sugerido:

```
# OBRIGATORIA desde o R-21: sem ela, com DJANGO_DEBUG=False, a aplicacao NAO SOBE.
DJANGO_SECRET_KEY=gerar_uma_chave_segura
DJANGO_DEBUG=False
ALLOWED_HOSTS=seudominio.com.br,SEU_IP_PUBLICO
CSRF_TRUSTED_ORIGINS=https://seudominio.com.br
USE_X_FORWARDED_HOST=True
DJANGO_SECURE_PROXY_SSL=True

POSTGRES_DB=talent_rank_ai
POSTGRES_USER=usuario_do_lightsail_db
POSTGRES_PASSWORD=senha_do_lightsail_db
POSTGRES_HOST=endpoint_do_lightsail_db
POSTGRES_PORT=5432

# Fecha o endpoint /metrics (ver secao 11.1). Vazio ou ausente = endpoint publico.
METRICS_TOKEN=gerar_um_token_longo
```

Gere o token do `/metrics`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Gere uma nova SECRET_KEY:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

### 8.1 Antes de subir o R-21 — conferir o `.env` do servidor

O R-21 faz a aplicacao **recusar subir** sem `DJANGO_SECRET_KEY` quando `DJANGO_DEBUG=False`,
e liga `SECURE_SSL_REDIRECT`. Duas conferencias antes do deploy que traz esse item:

```bash
grep -c DJANGO_SECRET_KEY /var/www/talent_rank_ai/.env    # tem que ser 1
curl -sI https://SEUDOMINIO/ | head -1                    # tem que ser 200, com HTTPS valido
```

**Se a primeira der 0, gere a chave antes de mergear:**

```bash
cd /var/www/talent_rank_ai && source .venv/bin/activate
python -c "from django.core.management.utils import get_random_secret_key as g; print('DJANGO_SECRET_KEY=' + g())" >> .env
```

Trocar a `SECRET_KEY` de um servidor que ja rodava **invalida as sessoes**: todo mundo cai
para a tela de login. Nao ha perda de dado.

O `SECURE_SSL_REDIRECT` depende do `SECURE_PROXY_SSL_HEADER`, que fora de `DEBUG` vem
ligado por default — o Nginx ja manda `X-Forwarded-Proto` (secao 11). Se algum dia esse
header sair da configuracao do Nginx, o site entra em **laco de redirect**.

---

## 9. Migrar banco e coletar estáticos

```bash
cd /var/www/talent_rank_ai
source .venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
```

---

## 10. Configurar Gunicorn (systemd)

Crie o service:

```bash
sudo nano /etc/systemd/system/talent_rank_ai.service
```

Conteúdo:

```
[Unit]
Description=Gunicorn for Talent Rank AI
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/talent_rank_ai
EnvironmentFile=/var/www/talent_rank_ai/.env
ExecStart=/var/www/talent_rank_ai/.venv/bin/gunicorn \
  --workers 3 \
  --bind 127.0.0.1:8000 \
  talent_query.wsgi:application

[Install]
WantedBy=multi-user.target
```

Ative o serviço:

```bash
sudo systemctl daemon-reload
sudo systemctl enable talent_rank_ai
sudo systemctl start talent_rank_ai
sudo systemctl status talent_rank_ai
```

---

## 11. Configurar Nginx (reverse proxy)

```bash
sudo nano /etc/nginx/sites-available/talent_rank_ai
```

Conteúdo:

```
server {
    listen 80;
    server_name seudominio.com.br SEU_IP_PUBLICO;

    location /static/ {
        alias /var/www/talent_rank_ai/staticfiles/;
    }

    location /media/ {
        alias /var/www/talent_rank_ai/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Ative o site:

```bash
sudo ln -s /etc/nginx/sites-available/talent_rank_ai /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

### 11.1 Fechar o endpoint `/metrics` (R-22)

O Nginx faz `proxy_pass` em `location /`, entao `GET /metrics` responde para qualquer um
na internet. Com `METRICS_TOKEN` preenchido no `.env`, o endpoint passa a exigir o token
em um dos dois headers:

```bash
curl -H "X-Metrics-Token: $TOKEN" https://seudominio.com.br/metrics      # 200
curl -H "Authorization: Bearer $TOKEN" https://seudominio.com.br/metrics # 200
curl https://seudominio.com.br/metrics                                   # 401
```

**A ordem importa (expand-contract).** O deploy do codigo sozinho nao fecha nada: sem a
variavel no `.env`, o endpoint continua aberto de proposito, para nao derrubar um scraper
que ja esteja consumindo. Feche assim:

1. deploy do codigo (endpoint continua aberto);
2. se houver Prometheus scrapeando, configure o token nele — `authorization: {credentials: <token>}`
   no `scrape_config` manda o header `Bearer`;
3. so entao ponha `METRICS_TOKEN` no `.env` do servidor e `sudo systemctl restart talent_rank_ai`.

Inverter 2 e 3 deixa o scraper cego ate ser reconfigurado.

---

### 11.2 Tirar os curriculos de `/media/` publico (R-23)

O `location /media/` entrega qualquer PDF de curriculo **sem autenticacao nenhuma** — o
Nginx serve direto do disco, o Django nem ve o pedido. Quem tiver a URL baixa, logado ou
nao, para sempre, inclusive depois de o candidato pedir exclusao. O nome do arquivo tem um
`uuid4`, entao ninguem enumera; o risco e a URL vazar em log, referrer, backup ou print.

A rota nova (`/curriculos/<id>/`) confere login e visibilidade no Django e delega a
entrega do arquivo ao Nginx por `X-Accel-Redirect`, apontando para um `location` marcado
`internal;` — inalcancavel de fora, so por redirecionamento interno. O PDF **nao**
atravessa o worker do gunicorn.

**Sao 3 etapas, e a ordem importa** (expand-contract). Pular para a 3 antes da 2 tira os
PDFs do ar.

**Etapa 1 — antes do deploy do codigo.** Adicione o location interno, **mantendo o
`/media/` publico**, no mesmo `server` do `listen 443`:

```
    location /protected-media/ {
        internal;
        alias /var/www/talent_rank_ai/media/;
    }
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Sozinha, esta etapa nao muda nada para quem usa: nenhuma URL responde diferente. Se ela
nao existir quando o codigo subir, o botao "Baixar PDF" da **404** — o Nginx nao conhece o
caminho interno e devolve o pedido ao Django.

**Etapa 2 — deploy do codigo, e conferir logado.** Entre no banco de talentos, clique em
**Baixar PDF** e confirme que o arquivo abre com o nome do candidato (`fulano-de-tal.pdf`,
nao o `uuid` do disco). Confira tambem que a URL antiga `/media/resumes/...` **ainda**
funciona — nesta etapa ela deve funcionar mesmo; e o que torna a volta atras barata.

> **O que aconteceu de verdade (2026-08-19):** neste servidor **nao existe** `location
> /media/` publico — a config tem so `/static/` e `/`. Confirmado com `nginx -T`, que
> imprime a config efetiva ja resolvida (o `grep -r` em `sites-enabled/` mente, porque la
> so ha symlink e ele nao segue). Entao a etapa 3 virou **verificacao, nao remocao**. Os
> comandos de conferencia estao no fim desta secao e devem ser rodados mesmo assim: e o
> `curl` que prova, nao a leitura do arquivo.

**Etapa 3 — so depois da 2 passar.** Remova o bloco publico, **se ele existir**:

```
    location /media/ {
        alias /var/www/talent_rank_ai/media/;
    }
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Verificacao final, de fora e deslogado:

```bash
curl -s -o /dev/null -w "%{http_code}
" https://talentrankai.com/media/resumes/<user>/<uuid>.pdf   # 404
```

E, logado, o botao **Baixar PDF** continua funcionando.

**O que a etapa 3 tambem derruba, de proposito:** o link de arquivo que o Django admin
mostra no candidato passa a dar 404, porque ele aponta para `MEDIA_URL`. O caminho para
baixar passa a ser um so, e ele confere permissao.

**Volta atras:** recolocar o `location /media/` e recarregar o Nginx. Os arquivos nunca
saem do lugar no disco — nenhuma das 3 etapas move, copia ou apaga arquivo.

**Armadilha que custou o botao quebrado por um dia:** `USE_X_ACCEL_REDIRECT` tem default
`str(not DEBUG)` no `settings.py` e o `.env` nao define a chave. Ou seja, **a flag se liga
sozinha em qualquer ambiente com `DEBUG=False`**, tenha o Nginx o `location` interno ou
nao — e quando nao tem, todo download da 404. Se for subir este codigo em servidor novo ou
em staging, ou a etapa 1 vem antes, ou `USE_X_ACCEL_REDIRECT=False` entra no `.env`
explicitamente ate ela vir.

**Como colar comando neste terminal:** ele quebra linha longa no meio e indenta bloco
multi-linha, o que arruina `sed`, `python3 -c` e principalmente heredoc (o delimitador
indentado nao fecha e o shell trava no `>`). Comandos curtos, um por vez. Para escrever
arquivo de config, `echo 'linha' >> arquivo` repetido — foi assim que o snippet
`/etc/nginx/snippets/protected_media.conf` entrou.

---

## 12. HTTPS no Lightsail

### Opção A (mais simples): Certificado via Lightsail

1. Lightsail → Networking → **Create certificate**
2. Siga o wizard e vincule o domínio.
3. Aplique o certificado ao serviço.

### Opção B (manual com Certbot)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d seudominio.com.br
```

---

## 13. Publicar domínio

1. Aponte o DNS do seu domínio para o **Static IP** da instância.
2. Registros típicos:
   - **A**: `@` → IP público
   - **A**: `www` → IP público (opcional)

Se usar Route 53:
1. Crie uma hosted zone
2. Crie os registros A para o IP público da instância

---

## 14. Backup semanal do banco (pg_dump)

1. Instale o cliente do PostgreSQL (uma vez):

```bash
sudo apt install -y postgresql-client
```

2. Garanta o script no servidor:

```bash
chmod +x /var/www/talent_rank_ai/scripts/backup_postgres.sh
```

3. Configure o cron para rodar semanalmente (domingo, 03:00):

```bash
crontab -e
```

Adicione:

```bash
0 3 * * 0 ENV_FILE=/var/www/talent_rank_ai/.env /var/www/talent_rank_ai/scripts/backup_postgres.sh >> /var/www/talent_rank_ai/backups/backup.log 2>&1
```

Mantem apenas os 2 ultimos backups:
- Atual: `/var/www/talent_rank_ai/backups/db_backup.dump`
- Anterior: `/var/www/talent_rank_ai/backups/db_backup.prev.dump`

---

## 15. CD (Deploy automático via GitHub Actions)

Após o merge na `main`, o deploy roda automaticamente se o CI passar.

### Secrets no GitHub

Em **Settings → Secrets and variables → Actions**, crie:

| Secret | Descrição |
|--------|-----------|
| `SSH_HOST` | IP público da instância Lightsail |
| `SSH_USER` | Usuário SSH (ex.: `ubuntu`) |
| `SSH_PRIVATE_KEY` | Chave privada SSH (conteúdo completo, incluindo `-----BEGIN...` e `-----END...`) |
| `SSH_PORT` | (opcional) Porta SSH, padrão 22 |

### Configurar a chave SSH

1. Gere um par de chaves (ou use uma existente):
   ```bash
   ssh-keygen -t ed25519 -C "github-cd" -f deploy_key -N ""
   ```

2. No servidor, adicione a **chave pública** ao `authorized_keys`:
   ```bash
   echo "conteúdo_de_deploy_key.pub" >> ~/.ssh/authorized_keys
   ```

3. No GitHub, use o conteúdo de `deploy_key` (chave privada) como secret `SSH_PRIVATE_KEY`.

4. O servidor precisa conseguir fazer `git pull` — se o repositório foi clonado via HTTPS, configure as credenciais ou use um Deploy Key no repositório.

---

## 16. Checklist rápido

- [ ] Instância Lightsail criada
- [ ] Banco PostgreSQL criado e acessível
- [ ] `.env` configurado com `POSTGRES_*` e `DJANGO_*`
- [ ] `METRICS_TOKEN` no `.env` e `curl` sem token devolvendo 401
- [ ] `DJANGO_SECRET_KEY` no `.env` (obrigatoria desde o R-21) e `manage.py check --deploy` limpo
- [ ] `migrate` e `collectstatic` executados
- [ ] Gunicorn ativo via systemd
- [ ] Nginx proxy ativo
- [ ] Domínio apontando para o IP
- [ ] HTTPS habilitado
- [ ] Backup semanal configurado
- [ ] Secrets do CD configurados no GitHub (se usar deploy automático)

---

## Observações finais

- Este setup é ideal para projetos pequenos e custo baixo.
- Quando crescer, você pode migrar para ECS, EC2 + RDS ou Elastic Beanstalk.
- Se preferir, posso montar a estrutura já com **Docker** para facilitar upgrades.

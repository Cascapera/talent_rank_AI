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
```

Gere uma nova SECRET_KEY:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

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

## 15. Checklist rápido

- [ ] Instância Lightsail criada
- [ ] Banco PostgreSQL criado e acessível
- [ ] `.env` configurado com `POSTGRES_*` e `DJANGO_*`
- [ ] `migrate` e `collectstatic` executados
- [ ] Gunicorn ativo via systemd
- [ ] Nginx proxy ativo
- [ ] Domínio apontando para o IP
- [ ] HTTPS habilitado
- [ ] Backup semanal configurado

---

## Observações finais

- Este setup é ideal para projetos pequenos e custo baixo.
- Quando crescer, você pode migrar para ECS, EC2 + RDS ou Elastic Beanstalk.
- Se preferir, posso montar a estrutura já com **Docker** para facilitar upgrades.

# UPGRADE — Python 3.10.12 → 3.13 (R-34)

> Plano escrito em **2026-08-21**. Alvo decidido por medição, não por palpite: o 3.13
> entrou na matriz do CI antes deste plano existir (PR #108) e passou.
> **Fonte de verdade do projeto continua sendo o `PROJETO_REFATORACAO.md`** — este
> arquivo é o detalhamento de um item dele, o R-34.

## 1. Resumo

| | |
|---|---|
| **O que sobe** | O interpretador Python do servidor de produção: **3.10.12 → 3.13** |
| **Por quê** | Fim do suporte do **3.10 em outubro/2026**. Manutenção com data marcada, não refatoração |
| **Custo** | ~30 min de preparação sem downtime + **~10 min de janela** com o serviço parado |
| **Risco geral** | **Baixo para o código, médio para a infra.** O código não usa nada removido; o que pode dar errado é do lado do servidor |
| **Ponto sem volta** | **Não existe.** Nenhuma migration de schema, nenhum dado tocado. O rollback é renomear uma pasta |

**Por que 3.13 e não 3.12:** o mesmo trabalho de servidor, e o prazo seguinte sai de
outubro/2028 (3.12) para **outubro/2029** (3.13). O plano original dizia 3.12 porque era
o que a matriz do CI provava; o PR #108 estendeu a matriz e o 3.13 passou igual.

## 2. Inventário (Fase 0)

### Versões reais, do lockfile

`requirements.txt` tem **36 pacotes fixados em `==`**, colhidos por `pip freeze` no
servidor. As sete diretas: `Django==5.2.10`, `psycopg[binary]==3.3.2`,
`python-dotenv==1.2.1`, `google-genai==1.60.0`, `gunicorn==24.1.1`,
`whitenoise==6.11.0`, `prometheus_client==0.24.1`.

### Distância até o alvo

Três minors (3.10 → 3.11 → 3.12 → 3.13). Em Python, minor é o que quebra: cada uma
remove APIs depreciadas.

### Quem depende do quê

Quatro pacotes têm extensão C e são os únicos que poderiam faltar wheel para 3.13:
`psycopg[binary]`, `pydantic-core`, `cryptography` e `cffi`. **Todos instalaram em 3.13
no CI** — e a prova é forte porque `requirements-dev.txt` começa com `-r
requirements.txt`, então o job de 3.13 instalou **os pins de produção inteiros**, não só
os de teste.

### Superfície de uso no repositório

**Zero.** `grep` por tudo que sai do ar no caminho 3.11→3.13 voltou vazio: `distutils`,
`pkg_resources`, `imp`, `datetime.utcnow`, `locale.getdefaultlocale`, os aliases legados
do `unittest` (`assertEquals`, `failUnless`, `assertRaisesRegexp`), `inspect.getargspec`,
`cgi`, `telnetlib`, `asynchat`, `smtpd`.

Isso é o esperado num projeto Django que usa a stdlib pelo básico — mas é o tipo de
verificação que se faz **antes**, não depois de o serviço não subir.

### Estado da rede de segurança

| Versão | Testes | Piso de cobertura | Resultado |
|---|---|---|---|
| 3.10 (produção) | 474 | 78% | ✅ |
| 3.12 | 474 | 78% | ✅ |
| **3.13** | 474 | 78% | ✅ **(PR #108, 2026-08-21)** |

⚠️ **O que essa evidência NÃO cobre:** o `pyproject.toml:47` tem
`filterwarnings = ["ignore::DeprecationWarning", "ignore::PendingDeprecationWarning"]`.
Os warnings exibidos nos três jobs são idênticos (só o `UserWarning` de `staticfiles`,
artefato do ambiente de teste) — **mas a suíte esconde as depreciações por configuração**,
então essa comparação não poderia mostrar diferença nenhuma. É o mesmo padrão que este
projeto já registrou quatro vezes: o instrumento passa nos dois mundos.

**Por isso o O-01 ganhou um passo:** rodar a suíte no servidor, no 3.13, com o filtro
desligado (`--override-ini`). A lista que sair dali é o mapa gratuito do próximo upgrade
— e, se vier vazia, aí sim a afirmação vale.

## 3. Mapa de impacto (Fase 1)

| Mudança de 3.10 → 3.13 | Tipo | Onde o projeto usa | Ação |
|---|---|---|---|
| `distutils` removido (3.12, PEP 632) | quebra | **não usado** — e nenhum pin depende dele | nenhuma |
| `imp` removido (3.12) | quebra | **não usado** | nenhuma |
| Aliases legados do `unittest` removidos (3.12) | quebra | **não usado** (a suíte é pytest) | nenhuma |
| `cgi`, `telnetlib`, `crypt`, `pipes` removidos (3.13) | quebra | **não usado** | nenhuma |
| `datetime.utcnow()` depreciado (3.12) | **silenciosa** | **não usado** — o código usa `django.utils.timezone` | nenhuma |
| `locale.getdefaultlocale()` depreciado (3.11) | **silenciosa** | **não usado** | nenhuma |
| Erros de sintaxe/f-string mais estritos (3.12) | quebra | suíte verde em 3.13 | nenhuma |
| `ruff target-version` desalinhado do runtime | **silenciosa e nossa** | `pyproject.toml:15` | **U-03**, e só **depois** de produção estar em 3.13 |

**A única armadilha silenciosa deste upgrade é de fabricação própria**, e já está
documentada no R-02: com `target-version` apontando para uma versão **acima** da de
produção, a regra `UP` do ruff reescreve o código em sintaxe nova, o CI aprova e o
servidor quebra. Hoje ela está apontada para baixo (`py310`), que é o lado seguro. Subir
o `target-version` **antes** do servidor inverte a armadilha e a arma. Por isso o U-03
vem depois da janela, não antes.

## 4. Estratégia

**Em paralelo, com troca por renomeação.** Não é upgrade in-place nem adaptador:

1. O 3.13 entra no servidor **ao lado** do 3.10, sem remover nada.
2. Um venv de teste (`.venv313`) prova a instalação e a suíte **no servidor**, com o
   serviço no ar o tempo todo.
3. A troca acontece numa janela curta, e o venv novo nasce **no caminho de sempre**
   (`.venv`), o que evita mexer no systemd e no `deploy.yml`.

**Por que não renomear o venv pronto:** venv não sobrevive a `mv`. Os executáveis
(`gunicorn`, `pip`, `python`) têm o caminho absoluto gravado no shebang, e o
`pyvenv.cfg` também. Construir `.venv313` e renomear para `.venv` produziria um venv com
shebangs apontando para uma pasta que não existe mais — o serviço não subiria, e o erro
não diria isso com clareza.

**O que salva o rollback é a mesma propriedade, ao contrário:** o `.venv` atual foi
construído *nesse* caminho. Renomeado para `.venv310` ele fica temporariamente inválido,
mas **renomeado de volta para `.venv` volta a funcionar**, porque os caminhos gravados
nele voltam a bater.

## 5. Sequência

### [U-01] Matriz do CI com 3.13 — ✅ FEITO (PR #108, 2026-08-21)

```
O que entra:     "3.13" na matriz de teste do ci.yml
Por que agora:   é a evidência que decide o alvo; sem ela, 3.12 ou 3.13 é palpite
Compatível com a versão atual? SIM — não toca em produção nem no pyproject
Risco:           nenhum
Como validar:    os 3 jobs verdes
Reversão:        remover a entrada da matriz
Esforço:         5 min
```

**Resultado:** 3.13 verde, 474 testes. Os warnings **exibidos** batem com os do 3.10 —
mas ver a seção acima: a suíte ignora depreciação por configuração, então isso não é
evidência de que não há nenhuma. Quem responde é o O-01.

### [O-01] Instalar 3.13 e provar no servidor — sem downtime

```
O que entra:     PPA deadsnakes, python3.13, venv de teste .venv313, suite rodada la
Por que agora:   prova a instalacao no servidor real, que o CI nao cobre
Compatível com a versão atual? SIM — nada em producao muda; o servico segue no ar
Risco:           baixo — instala pacote novo no sistema, nao substitui nenhum
Como validar:    474 testes verdes dentro do .venv313, no servidor
Reversão:        rm -rf .venv313 (e, se quiser, remover o PPA)
Esforço:         ~20 min
```

Comandos, um por vez:

```
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.13 python3.13-venv
python3.13 --version
cd /var/www/talent_rank_ai
python3.13 -m venv .venv313
.venv313/bin/pip install --upgrade pip
.venv313/bin/pip install -r requirements-dev.txt
```

E a suíte, **obrigatoriamente fora de `/var/www/talent_rank_ai`** (ver "O `.env` contamina
a suíte", abaixo — descoberto na execução):

```
cd /tmp
git clone -q /var/www/talent_rank_ai talent_test
cd /tmp/talent_test
/var/www/talent_rank_ai/.venv313/bin/python -m pytest -q
/var/www/talent_rank_ai/.venv313/bin/python -m pytest -q --override-ini=filterwarnings=default
```

A suíte instala do `requirements-dev.txt` porque é ele que traz o `pytest` — e ele começa
com `-r requirements.txt`, então instala junto tudo o que produção usa.

⚠️ **Não rodar `manage.py` com o `.venv313`** apontando para o banco de produção: a suíte
usa `settings_test`, com SQLite em memória, e não encosta no PostgreSQL.

### O `.env` contamina a suíte — achado em 2026-08-21

A primeira execução, feita de dentro de `/var/www/talent_rank_ai`, deu **85 falhas e 389
passes**. Não era o 3.13: `talent_query/settings.py:22` faz
`load_dotenv(BASE_DIR / ".env", override=True)`, e **`override=True` faz o arquivo vencer
as variáveis de ambiente**. O `.env` de produção entrou na suíte inteira — `DJANGO_DEBUG`
False, `ALLOWED_HOSTS` real, e o `USE_X_ACCEL_REDIRECT` ligando sozinho pelo default
`str(not DEBUG)`. As falhas se concentraram exatamente onde isso importa:
`test_resume_download`, `test_static_storage` e as views.

O `setdefault` do `settings_test` existe para evitar isso e **não tem chance** contra
`override=True`. E o CI nunca poderia mostrar o problema: lá não existe `.env`, então o
`load_dotenv` não acha arquivo nenhum.

**Como aplicar:** rodar a suíte de dentro do diretório de produção é medir o ambiente
errado. O clone descartável em `/tmp` custa 10 segundos e dá o resultado limpo. Nunca
renomear o `.env` para contornar — o systemd o lê como `EnvironmentFile` e o próximo
restart derrubaria a aplicação. Virou o achado **R-47**.

### [O-02] Trocar o venv — janela de ~10 min com o serviço parado

```
O que entra:     .venv passa a ser 3.13; o antigo vira .venv310, intacto
Por que agora:   e a troca de fato; so depois de O-01 verde
Compatível com a versão atual? NAO — e a janela
Risco:           medio — servico parado; erro aqui derruba a aplicacao
Como validar:    check --deploy, suite, telas, importacao real, /metrics/
Reversão:        rm -rf .venv && mv .venv310 .venv && systemctl start  (~30 s)
Esforço:         ~10 min de parada
```

```
sudo systemctl stop talent_rank_ai
cd /var/www/talent_rank_ai
mv .venv .venv310
python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py check --deploy
sudo systemctl start talent_rank_ai
systemctl is-active talent_rank_ai
```

O `check --deploy` tem que sair com **2 avisos**, os mesmos de sempre
(`SECURE_HSTS_INCLUDE_SUBDOMAINS` e `SECURE_HSTS_PRELOAD`, recusas conscientes do R-21).
Número diferente disso é sinal de que algo mudou de configuração, e aí é rollback antes
de investigar.

**Aproveitar a janela para o reboot pendente** (`*** System restart required ***`, visto
em 2026-08-21): `sudo reboot` depois da verificação, com o serviço já validado em 3.13.

### [U-03] Alinhar o repositório ao runtime novo — só depois de estável

```
O que entra:     pyproject (requires-python, ruff target-version), matriz do CI
Por que agora:   DEPOIS de producao estar em 3.13 — antes disso inverte a armadilha do R-02
Compatível com a versão atual? NAO — por isso vem depois
Risco:           baixo, mas so se a ordem for respeitada
Como validar:    CI verde; `ruff check` sem reescrever nada inesperado
Reversão:        reverter o PR
Esforço:         30 min
```

- `requires-python = ">=3.13"`, `target-version = "py313"`
- matriz do CI: **3.13 vira o portão**; manter 3.12 por um release como rede, depois
  simplificar para só 3.13
- rodar `make format` e revisar **cada** reescrita da regra `UP`: é aqui que o ruff vai
  querer modernizar sintaxe, e agora ele pode

### [U-04] Documentação

`README.md` (badge e duas menções), `DEPLOY_AWS.md:72`, cabeçalhos de `requirements.txt`
e `requirements-dev.txt`, e o R-34 no `PROJETO_REFATORACAO.md`.

### [O-03] Remover o venv antigo — **+1 semana**

```
rm -rf /var/www/talent_rank_ai/.venv310
```

Uma semana de aplicação em uso normal antes. Enquanto ele existir, o rollback custa 30
segundos.

## 6. Riscos e pontos cegos

| Risco | Por que preocupa | Mitigação |
|---|---|---|
| **PPA de terceiro** no servidor | deadsnakes é mantido pela comunidade, não pela Canonical | É o caminho padrão para 3.x no Ubuntu. Instala **ao lado**, sem substituir o Python do sistema — o `apt`, o `unattended-upgrades` e o resto continuam no 3.10 |
| **Deploy no meio da janela** | o CD reinicia o serviço a cada merge em `main` | Não mergear nada em `main` durante a janela |
| **Importação em andamento** | as threads são `daemon` e morrem no stop | A Bruna está fora até ~02/09. Conferir mesmo assim que não há job `RUNNING` |
| **`pip install` puxando algo diferente** | wheel de 3.13 é outro arquivo, não o mesmo binário testado no CI | Os pins são `==`; a versão é idêntica, só o wheel muda. A suíte no servidor (O-01) é o que confirma |
| **Ubuntu 22.04 vence em abril/2027** | o SO envelhece antes do próximo Python | Fora do escopo deste item; anotar como próximo projeto de infra |
| **`.env` lido pelo systemd** | `EnvironmentFile=` — o parser do systemd é mais rígido que o do dotenv | Não mexemos no `.env` aqui; só relevante se alguma chave for editada na mesma janela |

## 7. Plano de validação

Depois do O-02, na ordem:

1. `systemctl is-active talent_rank_ai` → `active`
2. `.venv/bin/python --version` → `Python 3.13.x`
3. Home e `/login/` → **200**
4. `/curriculos/1/` deslogado → **302**; `/media/resumes/...` → **404**
5. `/metrics/` → **401** sem token, **200** com
6. **Uma importação real, pela tela** — 1 PDF novo pelo fluxo de vaga, que é o que
   exercita o Gemini de ponta a ponta. *Esta é a caixa que conta.* O projeto já provou
   quatro vezes que suíte verde não cobre o lado que opera
7. Observar por **uma semana** antes do O-03

## 8. Rollback

```
sudo systemctl stop talent_rank_ai
cd /var/www/talent_rank_ai
rm -rf .venv
mv .venv310 .venv
sudo systemctl start talent_rank_ai
```

~30 segundos. Funciona porque o `.venv310` é o venv original **construído no caminho
`.venv`** — voltar o nome faz os caminhos gravados nele baterem de novo. Vale enquanto o
O-03 não tiver sido executado.

**Não há ponto sem volta:** nenhuma migration, nenhum dado alterado, nenhum arquivo de
mídia tocado.

## 9. Checklist

### U-01 — Matriz do CI com 3.13

- [x] **U-01** · 1 arquivo · compatível com a versão atual · risco: nenhum
  - [x] `3.13` na matriz
  - [x] Os 3 jobs verdes — 474 testes, cobertura acima do piso
  - [x] Warnings **exibidos** comparados com o 3.10 — idênticos, mas o filtro do
        `pyproject` esconde depreciação: a checagem de verdade é a do O-01
  - [x] Mergeado — PR #108, `ec359f8`
  - Status: **concluído em 2026-08-21**

### O-01 — 3.13 no servidor e suíte no venv de teste

- [x] **O-01** · servidor · sem downtime · risco: baixo
  - [x] PPA adicionado — **Python 3.13.15**, ao lado do 3.10.12, que segue sendo o
        `python3` do sistema. O `apt` só listou **NEW packages**, nada removido
  - [x] `.venv313` criado, `pip install -r requirements-dev.txt` **sem compilar nada**:
        `psycopg_binary`, `pydantic_core`, `cffi` e `coverage` vieram como wheel `cp313`, e
        o `cryptography` como `cp311-abi3` (ABI estável, roda no 3.13 por construção)
  - [x] **474 testes verdes no servidor**, em 3m02s — depois de descobrir que precisam
        rodar fora de `/var/www/talent_rank_ai` (ver o achado R-47 acima)
  - [x] Suíte rodada com o filtro desligado — **nenhum `DeprecationWarning` do Python**.
        Apareceram um `RemovedInDjango60Warning` (**R-48**) e um `ResourceWarning` de
        arquivo não fechado em `test_resume_download`, provável artefato de fixture
  - Status: **concluído em 2026-08-21** · Notas: o `needrestart` pediu confirmação de
    reinício de daemons durante o `apt` — a lista **não** incluía `talent_rank_ai`,
    `nginx` nem `postgresql`; só serviços de sistema. Reiniciar o `ssh.service` não
    derruba sessão aberta.

### O-02 — Troca do venv (janela)

- [ ] **O-02** · servidor · ~10 min parado · risco: médio
  - [ ] Nenhum job `RUNNING` e nenhum merge em `main` pendente
  - [ ] `.venv` → `.venv310`, `.venv` novo em 3.13
  - [ ] `pip install -r requirements.txt` sem erro
  - [ ] `check --deploy` com **2 avisos**, os conhecidos
  - [ ] Serviço `active` e `.venv/bin/python --version` em 3.13
  - [ ] Reboot pendente aproveitado
  - [ ] **Verificado em produção (comportamento observado)** — importação real pela tela
  - Status: não iniciado · Notas:

### U-03 — Repositório alinhado ao runtime

- [ ] **U-03** · `pyproject` + `ci.yml` · **só depois do O-02 estável** · risco: baixo
  - [ ] `requires-python = ">=3.13"` e `target-version = "py313"`
  - [ ] Matriz com 3.13 como portão
  - [ ] `make format` rodado e **cada** reescrita da regra `UP` revisada
  - [ ] Suíte verde
  - Status: não iniciado · Notas:

### U-04 — Documentação

- [ ] **U-04** · README, DEPLOY_AWS, cabeçalhos dos requirements, R-34 no plano
  - Status: não iniciado · Notas:

### O-03 — Remover o venv antigo

- [ ] **O-03** · **+1 semana depois do O-02** · o rollback morre aqui
  - Status: não iniciado · Notas:

## 10. Suposições e o que não foi verificado

- ✅ **Verificado em 2026-08-21:** o deadsnakes publica `python3.13` para `jammy` —
  instalou **3.13.15**.
- ✅ **Verificado em 2026-08-21:** nada foi compilado. Todos os pacotes com extensão C
  vieram como wheel pronta para `cp313`, então o binário é o mesmo tipo de artefato que o
  CI testou.
- ⚠️ **Descoberto na execução, e não previsto aqui:** a suíte não roda limpa de dentro do
  diretório de produção, por causa do `override=True` no `load_dotenv`. Custou uma
  execução de 3 minutos e 85 falhas que pareciam do 3.13. Ver R-47.
- **Suposição:** ninguém consome `/metrics/` externamente (confirmado na rotação das
  chaves em 2026-08-21), então o restart não quebra coletor nenhum.
- **Fora do escopo:** o fim do suporte do **Ubuntu 22.04 em abril/2027**. É o próximo
  projeto de infra depois deste, e nada aqui o antecipa nem o atrasa.

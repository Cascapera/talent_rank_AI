# Projeto de Refatoração — Talent Rank AI

> Documento **vivo**. Ao concluir qualquer item, atualize a seção 13 (checklist):
> marque as caixas, preencha o hash do commit, ajuste o contador de progresso e
> anote no registro de execução.

| | |
|---|---|
| **Repositório** | `talent_rank_AI` |
| **Branch** | `main` |
| **Último commit** | `0a8801d` — *feat: pre-match vaga x candidato na busca do banco de talentos* (2026-06-12) |
| **Data do plano** | 2026-08-15 |
| **Escopo** | Global |
| **Foco** | Global |
| **Itens no backlog** | 39 (29 originais + 10 achados na execução) |
| **Esforço total** | ~15–19 dias de trabalho focado |
| **Executado** | **Ondas 0 e 1 completas e em produção** · 15 itens · PRs #13 a #35 |

## ⛔ Impacto em produção — leia primeiro

**Nenhum item deste plano exige parada de produção.**

Todos os 29 itens são implantáveis com o sistema no ar. 18 são transparentes e 11 exigem
cuidado (ordem de deploy, migração concorrente, mudança de configuração do Nginx). O
detalhamento está na seção 9.

> ⚠️ **Condição pré-existente, não causada por este plano:** o deploy atual roda
> `sudo systemctl restart talent_rank_ai` (`.github/workflows/deploy.yml:28`), o que mata
> qualquer importação de candidatos em andamento — as threads são `daemon=True` e morrem
> sem aviso. **Isso já acontece hoje, em todo deploy.** Enquanto o item R-16 não estiver
> pronto, faça deploys em janela de baixo uso e confirme que não há importação rodando.

---

## 1. Resumo executivo

O Talent Rank AI é um app Django funcional, com boa higiene superficial: `ruff` limpo,
100 testes passando em 19s, migrations organizadas e uma camada de observabilidade
(métricas Prometheus + correlation_id) acima da média para um projeto deste porte.

O problema não é a superfície — é a densidade. Três arquivos concentram 3.700 das ~4.100
linhas de Python e praticamente todo o risco do sistema, e são justamente os que mais
mudam no histórico. Dentro deles há **872 linhas de código morto comprovado**, **quatro
cópias quase idênticas** do bloco que grava candidato no banco (uma delas já divergiu e
carrega um bug), **sete cópias** do bloco de cliente + retry do Gemini, e uma cobertura
de teste real de **25%** — mascarada como 88% por um `omit` no `pyproject.toml` que
exclui do cálculo exatamente os três arquivos onde tudo isso mora.

**Por que agora:** você quer implementar features novas. No estado atual, mudar um campo
do candidato significa editar quatro lugares sem rede de teste, e mudar o modelo de LLM
significa editar sete. O custo de cada feature nova é multiplicado por essa duplicação, e
o risco é invisível porque o CI mostra badge verde.

**Ganho esperado:** `pdf_extractor.py` sai de 1.888 para ~600 linhas; a regra de
persistência de candidato passa a existir em **um** lugar; a chamada ao Gemini passa a
existir em **um** lugar; a cobertura real sobe de 25% para ~55% concentrada no caminho
crítico. Depois disso, adicionar um campo ao candidato é uma edição, não quatro.

**Custo:** ~15–19 dias de trabalho focado, divididos em 29 PRs pequenos. As Ondas 0 e 1
(~8 dias, 13 PRs) entregam sozinhas a maior parte do ganho — se o projeto parar ali,
ainda terá valido a pena.

**Vale a pena?** Sim, mas com uma ressalva honesta: **as Ondas 0 e 1 são as que pagam.**
As Ondas 4 (segurança), 5 (performance) e 6 (frontend) são importantes por outros
motivos — LGPD, escala futura, manutenção do front — mas não são o que está travando a
evolução do código hoje. Se o tempo for curto, faça 0 e 1 completas e trate o resto como
backlog contínuo, não como projeto.

---

## 2. Escopo desta rodada

**Escopo:** global — todo o repositório `talent_rank_AI`.
**Foco:** global — priorizado por dor real (frequência de mudança × complexidade ×
risco), não por gosto estético.

### Dentro

- `core/` inteiro: `pdf_extractor.py`, `llm_extractor.py`, `views.py`, `models.py`,
  `matching.py`, `plans.py`, `middleware.py`, `signals.py`, `forms.py`
- `talent_query/settings.py` e configuração de deploy correlata
- `templates/` — apenas extração de JS/CSS inline e remoção de duplicata
- Configuração de qualidade: `pyproject.toml`, `Makefile`, `requirements*.txt`, CI/CD
- Testes: criação da rede de segurança

### Fora

- **Migração para Celery/Redis** — está no roadmap do README e é uma mudança de
  arquitetura, não refatoração. O item R-16 resolve o sintoma (job perdido no deploy) sem
  trocar a infraestrutura. Merece projeto próprio.
- **Redesenho visual / UX** — R-22 e R-23 movem JS e CSS de lugar sem alterar um pixel.
- **Multi-tenant e RBAC** — roadmap, mudança de produto.
- **Docker / docker-compose** — roadmap, não afeta a estrutura do código.
- **Conteúdo dos prompts do LLM** — mexer em prompt muda comportamento por definição;
  a refatoração só muda *onde* o prompt mora, nunca o que ele diz.

---

## 3. Linha de base

Tudo medido em 2026-08-15, não estimado. Comandos e saídas reproduzíveis.

| Métrica | Hoje |
|---|---|
| **Suíte de testes** | ✅ Verde — **100 testes, 18,94s** (`pytest`) |
| **Cobertura reportada** | 87,62% (sobre 421 statements) |
| **Cobertura real** | **25%** (sobre 2.241 statements) — o `omit` esconde 1.820 |
| **Lint (ruff check)** | **0 violações** — "All checks passed!" |
| **Format (ruff format)** | **0 pendências** — 35 arquivos já formatados |
| **Type check** | ❌ **Não existe** — sem mypy/pyright configurado |
| **`manage.py check --deploy`** | **6 avisos de segurança** |
| **Arquivos > 500 linhas** | **6** |
| **Funções > 50 linhas** | **25** |
| **Código morto** | **872 linhas / 23 funções** em `pdf_extractor.py` |
| **Commits no histórico** | 27 |

### Cobertura real por arquivo

Rodado com `--cov-config` sem o `omit` do `pyproject.toml`:

```
Name                    Stmts   Miss Branch BrPart  Cover
core\pdf_extractor.py     848    782    464      2     6%   ← 46% é código morto
core\views.py             604    475    212      0    17%
core\llm_extractor.py     358    280    158      6    20%
core\matching.py           93     12     32      6    84%
core\models.py            114      0      8      2    98%
core\forms.py              47      0      6      0   100%
core\plans.py              50      7     20      3    86%
core\signals.py            26      2      8      2    88%
core\middleware.py         13      0      6      1    95%
core\observability.py      34     18      8      0    38%
core\admin.py              28      0      0      0   100%
core\metrics.py            16      0      0      0   100%
-------------------------------------------------------
TOTAL                    2241   1576    922     22    25%
```

O `pyproject.toml:45-54` remove `views.py`, `llm_extractor.py`, `pdf_extractor.py` e
`urls.py` do cálculo, deixando 421 statements medidos de 2.241 reais — daí os 87,62%.

### Arquivos > 500 linhas

| Linhas | Arquivo |
|---:|---|
| 1.888 | `core/pdf_extractor.py` |
| 1.434 | `templates/core/job_detail.html` |
| 987 | `core/views.py` |
| 826 | `core/llm_extractor.py` |
| 774 | `landing.html` ← duplicata de `home.html` |
| 699 | `templates/core/home.html` |

### Funções > 50 linhas (25 no total — as 12 maiores)

| Linhas | Local | Função |
|---:|---|---|
| 435 | `pdf_extractor.py:977` | `import_candidates_from_folder` |
| 322 | `pdf_extractor.py:1414` | `import_candidates_from_folder_no_ranking` |
| 309 | `pdf_extractor.py:1738` | `search_and_rank_candidates_from_pool` |
| 211 | `pdf_extractor.py:332` | `_normalize_technologies` ☠️ morta |
| 209 | `pdf_extractor.py:545` | `_extract_technologies` ☠️ morta |
| 154 | `views.py:574` | `job_detail` |
| 141 | `views.py:153` | `talent_pool` |
| 139 | `llm_extractor.py:219` | `extract_candidates_batch_with_llm` |
| 121 | `llm_extractor.py:360` | `extract_candidate_with_llm` |
| 108 | `llm_extractor.py:649` | `calculate_adherence_batch_for_candidates` |
| 91 | `pdf_extractor.py:103` | `_find_name` ☠️ morta |
| 87 | `llm_extractor.py:821` | `generate_parecer` |

### Duplicação evidente

| O quê | Cópias | Onde |
|---|---:|---|
| Bloco de upsert de candidato (~85 linhas) | **4** | `pdf_extractor.py:1065`, `:1244`, `:1468`, `:1598` |
| Cliente Gemini + retry/backoff (~30 linhas) | **7** | `llm_extractor.py:229, 369, 487, 569, 656, 763, 832` |
| Loop de lotes + fallback individual (~50 linhas) | **3** | `pdf_extractor.py:1017`, `:1440`, `:1796` |
| Dicionário de sinônimos | **2** | `views.py:421` e `matching.py:27` |
| Normalização de acento | **2** | `views.py:77` (`_normalize_term`) e `matching.py:59` (`_normalize`) |
| Construção de payload do candidato p/ LLM (~14 linhas) | **4** | `views.py:926`, `pdf_extractor.py:1817, 1943, 1969` |
| Filtros + querystring de paginação (~55 linhas) | **2** | `views.py:208-270` e `views.py:602-700` |
| CSS de landing page (13 KB) | **2** | `landing.html` e `templates/core/home.html` |

### Módulos mais acoplados

- `core/views.py` importa 8 módulos internos e conhece `threading`, `zipfile`,
  `tempfile`, `shutil`, cache, ORM e a montagem do prompt do LLM. É o hub de tudo.
- `core/pdf_extractor.py` importa o ORM (`Candidate`, `CandidateJob`), o `llm_extractor`,
  as métricas e o `django.core.files`. O nome diz "extrator de PDF"; o conteúdo real é
  "orquestrador de importação com persistência". **Nome mente sobre a responsabilidade.**
- `core/matching.py` — o único módulo de domínio limpo: só depende de `settings` e
  `unicodedata`. É o modelo a seguir.

### Arquivos que mais mudam (`git log`, 27 commits)

| Mudanças | Arquivo | Linhas | Leitura |
|---:|---|---:|---|
| 11 | `core/views.py` | 987 | 🔴 **Muda muito + grande = refatorar** |
| 10 | `README.md` | — | documentação |
| 8 | `talent_query/settings.py` | 176 | configuração espalhada |
| 7 | `core/llm_extractor.py` | 826 | 🔴 **Muda muito + grande = refatorar** |
| 7 | `core/pdf_extractor.py` | 1.888 | 🔴 **Muda muito + grande = refatorar** |
| 5 | `core/models.py` | 162 | saudável |
| 5 | `core/urls.py` | 60 | saudável |
| 5 | `templates/core/job_detail.html` | 1.434 | 🟡 grande, muda com frequência |

**Os três arquivos com maior churn são exatamente os três maiores e os três com menor
cobertura.** Esse cruzamento é o mapa de onde refatorar — e ele aponta para um lugar só.

---

## 4. Diagnóstico

Ordenado por dor real.

### D-1 · 872 linhas de código morto em `pdf_extractor.py` (46% do arquivo)

**O que é:** todo o parser de currículo baseado em regex — 23 funções, de
`_fix_mojibake` (`:59`) até `parse_candidate_from_pdf` (`:904`) — está inalcançável.
Análise de alcançabilidade por AST a partir das três funções que `views.py:26` importa:

```
ALCANÇÁVEIS a partir do que views.py usa: 4 funções
NÃO ALCANÇÁVEIS (mortas): 23 funções / 872 linhas
```

`parse_candidate_from_pdf` não tem **nenhum** call site no repositório (`grep` em todo o
projeto: só a própria definição e o import em `test_pdf_extractor.py`). O caminho LLM
substituiu o parser e o parser nunca foi removido. Os 6% de cobertura do arquivo
confirmam: quase nada ali executa.

**Por que atrapalha:** metade do maior arquivo do projeto é ruído. Toda leitura, toda
busca, todo `Ctrl+F` e toda tentativa de entender o fluxo passa por 872 linhas que não
fazem nada. As duas maiores funções do projeto inteiro (`_normalize_technologies`, 211
linhas; `_extract_technologies`, 209 linhas) são mortas. É o que faz o arquivo parecer
intratável quando o código vivo tem ~1.000 linhas.

**Se nada for feito:** o arquivo continua sendo o mais assustador do projeto por um
motivo falso, e alguém eventualmente vai "consertar" ou "otimizar" código que não roda.

### D-2 · Cobertura de teste é 25%, mas o CI reporta 88%

**O que é:** `pyproject.toml:45-54` exclui do cálculo de cobertura `views.py`,
`llm_extractor.py`, `pdf_extractor.py` e `urls.py` — 1.820 dos 2.241 statements. O
`--cov-fail-under=50` do CI passa folgado medindo 421 statements de código simples
(models, forms, admin, matching), enquanto os 1.820 statements onde mora todo o risco
ficam invisíveis.

**Por que atrapalha:** não é só cosmético. É que **nenhuma refatoração pode começar aqui
com segurança**, e o badge verde diz o contrário. O comentário `# Views: integração HTTP,
testar via E2E` (`pyproject.toml:49`) promete um teste E2E que não existe no repositório.

**Se nada for feito:** qualquer mudança nos três arquivos críticos é feita no escuro, com
a suíte confirmando que os models continuam bem.

### D-3 · Quatro cópias do bloco de persistência de candidato — e uma já divergiu

**O que é:** o bloco "monta payload → busca por `linkedin_url` → atualiza ou cria →
salva PDF" aparece quatro vezes, ~85 linhas cada:

| Local | Contexto |
|---|---|
| `pdf_extractor.py:1065-1147` | `import_candidates_from_folder`, caminho batch |
| `pdf_extractor.py:1244-1329` | `import_candidates_from_folder`, fallback individual |
| `pdf_extractor.py:1468-1550` | `..._no_ranking`, caminho batch |
| `pdf_extractor.py:1598-1680` | `..._no_ranking`, fallback individual |

Cada cópia repete inline a mesma lista de 11 nomes de campo de texto, **duas vezes** (uma
no ramo "atualiza", outra no ramo "cria") — ou seja, a lista de campos do candidato está
escrita **8 vezes** no arquivo.

**A divergência já aconteceu:** três cópias começam com `if shared_pool:` para consultar o
pool global; a quarta (`:1614`) foi direto para o filtro por `user_id` e **ignora o
`shared_pool`**. Resultado: quando a importação em lote do banco de talentos falha e cai
no fallback individual, um usuário PREMIUM cria candidato duplicado em vez de atualizar o
existente do pool compartilhado. É um bug real, hoje, em produção.

**Por que atrapalha:** adicionar um campo ao `Candidate` são 8 edições. Esquecer uma
produz exatamente o tipo de bug acima — silencioso, dependente de caminho de erro, e
impossível de notar sem teste.

**Se nada for feito:** as quatro cópias continuam divergindo. A próxima divergência é
questão de tempo, e a de hoje já custou um bug.

### D-4 · Sete cópias do cliente Gemini + retry

**O que é:** o trio `os.getenv("GEMINI_API_KEY")` → `genai.Client(api_key=...)` → loop de
4 tentativas com `backoff_seconds = [3, 8, 15, 30]` está copiado em `llm_extractor.py`
nas linhas **229, 369, 487, 569, 656, 763 e 832**.

**Por que atrapalha:** trocar de modelo, adicionar timeout, mudar a política de backoff,
instrumentar custo de token ou trocar de provedor são 7 edições idênticas. O README
(linha 64) afirma que "a camada de LLM é isolada, então dá para trocar de provedor sem
mexer no resto" — verdade em relação ao resto do sistema, mentira dentro do próprio
módulo.

Agravante: nenhuma das 7 chamadas passa `timeout` ou usa `response_schema` do Gemini. O
parsing é heurístico (`_extract_json:198` procura o primeiro `{` e o último `}` no texto).
Uma chamada travada bloqueia a thread indefinidamente.

**Se nada for feito:** cada ajuste no LLM — e você vai fazer vários — custa 7× mais caro e
tem 7 chances de ficar inconsistente.

### D-5 · `views.py` acumula HTTP, regra de negócio, threading e prompt

**O que é:** 987 linhas, o arquivo que mais muda no histórico (11 de 27 commits). Dentro
dele:

- Montagem de prompt do LLM: `_build_job_description:482`
- Regra de negócio de busca booleana com dicionário de sinônimos próprio:
  `_build_boolean_search:420` — 60 linhas
- Gerenciamento de threads: 4 pontos (`:168`, `:625`, `:893`, `:1007`)
- Descompactação de ZIP e manipulação de arquivo temporário: `_prepare_uploaded_files:39`
- Normalização de acento e construção de filtro SQL: `_apply_unaccent_filter:82`
- Extração de dados do candidato para o LLM: `_run_parecer_generation:926`

`job_detail` (154 linhas) e `talent_pool` (141 linhas) fazem, cada uma, upload +
processamento + filtro + paginação + montagem de querystring numa função só.

**Por que atrapalha:** nada disso é testável sem subir uma request HTTP. É a causa direta
dos 17% de cobertura do arquivo, e a razão pela qual o `omit` do coverage foi criado — o
design tornou o teste difícil, e a resposta foi esconder a métrica em vez de corrigir o
design.

**Se nada for feito:** o arquivo que mais muda continua sendo o mais difícil de testar.

### D-6 · Jobs em background sem gestão de ciclo de vida

**O que é:** três problemas encadeados nas threads de `views.py`:

1. **Conexão de banco vazada.** Nenhum ponto chama `connection.close()` ou
   `close_old_connections()` (`grep` em todo o repositório: zero ocorrências). Cada thread
   abre sua conexão Postgres e não a devolve. O Django só fecha conexões no sinal
   `request_finished`, que thread manual não dispara.
2. **Job morre no deploy, silenciosamente.** `daemon=True` + `sudo systemctl restart` no
   `deploy.yml:28` = toda importação em andamento morre sem executar o `finally`. O status
   fica `"running"` no cache por 1h e a recrutadora olha uma barra de progresso parada.
3. **Chave de cache global.** `_talent_pool_import_status_key()` (`views.py:507`) retorna
   a string fixa `"talent_pool_import_status"`, **sem `user_id`**. Dois usuários importando
   ao mesmo tempo sobrescrevem o progresso um do outro. As chaves por vaga
   (`import_status_{job_id}`) estão corretas — essa passou despercebida.

**Por que atrapalha:** o fluxo mais demorado e mais visível do produto é o menos confiável,
e falha de um jeito que não gera erro em lugar nenhum.

**Se nada for feito:** conexões acumulam até o Postgres recusar novas; e todo deploy
durante um horário de uso corrompe uma importação.

### D-7 · Configuração de produção insegura

`manage.py check --deploy` retorna 6 avisos:

| Aviso | Onde |
|---|---|
| `SECRET_KEY` com fallback `django-insecure-...` hardcoded | `settings.py:31` |
| `DEBUG` com default `True` | `settings.py:36` |
| `SESSION_COOKIE_SECURE` não definido | `settings.py` |
| `CSRF_COOKIE_SECURE` não definido | `settings.py` |
| `SECURE_HSTS_SECONDS` não definido | `settings.py` |
| `SECURE_SSL_REDIRECT` não definido | `settings.py` |

Além disso: `/metrics` é público (`urls.py:7` sem decorator, e `DEPLOY_LIGHTSAIL.md:207`
tem `location / { proxy_pass }` — está exposto na internet), e currículos em PDF são
servidos pelo Nginx sem autenticação (`DEPLOY_LIGHTSAIL.md:203`: `location /media/`). Os
nomes são UUID, o que é segurança por obscuridade sobre **dado pessoal de candidato** —
URL vaza por log, referrer e compartilhamento. Para LGPD, é exposição.

O fallback do `SECRET_KEY` é o mais grave: se a variável de ambiente falhar em produção, a
aplicação **sobe normalmente** com uma chave que está publicada no Git.

### D-8 · Dependências sem versão travada

`requirements.txt` tem 8 pacotes, apenas um com restrição (`Django>=5.2`). O deploy roda
`pip install -r requirements.txt` a cada push em `main` (`deploy.yml:25`).

**A deriva já aconteceu:** o `.venv` local está com **Django 6.0.6 / Python 3.14.3**,
enquanto o CI testa em Python 3.12 e o README documenta Django 5.x. Você desenvolve numa
combinação, testa em outra e faz deploy numa terceira.

**Se nada for feito:** um release do Django com breaking change entra em produção sozinho,
num deploy que só mudava um texto.

> ✅ **Resolvido no R-02 (PR #23), e era pior que o diagnosticado.** O `pip freeze` do
> servidor (2026-08-17) mostrou produção em **Python 3.10.12 / Django 5.2.10** — nem a do
> venv local, nem a do CI. Eram **quatro** combinações, não três, e a suíte nunca tinha
> rodado na versão que atende as usuárias. Detalhe agravante: o Django 6.0.6 do venv local
> **nunca poderia** rodar em produção, porque Django 6.0 exige Python 3.12+. Ver a linha
> do R-02 no registro de execução para o que foi feito.

### D-9 · `reports` faz ~500 queries numa página

`views.py:368-382`: para cada vaga, um `links.count()`, oito `links.filter(...).count()` do
funil e mais um `.count()` de contratados = **10 queries por vaga**, sobre até 50 vagas.
Resolve com um `values('pipeline_status').annotate(Count('id'))` agrupado — 2 queries.

### D-10 · Pré-match carrega o banco de talentos inteiro em memória

`_match_pool_candidates_for_job` (`views.py:786`) traz todos os candidatos não vinculados
e roda `compute_match` em Python, um a um, **dentro do ciclo da request** — a cada clique
em "preview". Funciona hoje porque o volume é pequeno; é O(n) sobre a tabela inteira, com
normalização Unicode por candidato.

Some-se: `linkedin_url__iexact` é usado em todos os caminhos de upsert e **não tem índice
que o atenda** — a `UniqueConstraint(user, linkedin_url)` não serve para `iexact`. E
`CandidateJob.save()` (`models.py:174`) faz uma query de leitura extra em **todo** save,
inclusive quando `pipeline_status` não mudou.

### D-11 · 33 KB de JavaScript inline em um template

`templates/core/job_detail.html`: 1.434 linhas, das quais **33.101 caracteres são um único
bloco `<script>`**. Não existe **nenhum** arquivo `.js` ou `.css` em `static/` — só três
imagens. Os 12 templates têm, cada um, seu próprio `<style>`.

Sem cache de browser, sem lint, sem sintaxe destacada de verdade, sem reuso. É o motivo de
o arquivo aparecer no top de churn.

### D-12 · Código morto menor e configuração inconsistente

- `landing.html` (774 linhas, na raiz do projeto) é duplicata de
  `templates/core/home.html` (699 linhas), com 13 KB de CSS idêntico. Não é referenciado
  por nenhuma view.
- `core/tests.py` (vazio, do `startapp`) coexiste com o pacote `core/tests/`. O Python
  ignora o módulo, mas ele aparece no coverage como `core\tests.py 0 stmts 100%`.
- `--cov-fail-under` diverge: `Makefile:8` diz **20**, `pyproject.toml:58` diz **50**,
  `ci.yml:48` diz **50**.
- `settings.py:47` ativa `SECURE_PROXY_SSL_HEADER` por default `True`, inclusive em
  desenvolvimento local sem proxy.

---

## 5. Estado-alvo

### Antes

```
core/
├── views.py            987 l  ← HTTP + regra + threads + prompt + ZIP + filtros
├── pdf_extractor.py  1.888 l  ← 872 mortas + orquestração + persistência + métricas
├── llm_extractor.py    826 l  ← 7 cópias de client+retry, prompts, parsing
├── matching.py         167 l  ← 🟢 domínio limpo (o modelo a seguir)
├── models.py           162 l
├── plans.py            100 l
├── forms.py            166 l
├── metrics.py           90 l
├── observability.py     53 l
├── middleware.py        18 l
├── signals.py           35 l
└── tests.py              1 l  ← órfão

templates/core/job_detail.html  1.434 l  ← 33 KB de JS inline
landing.html                      774 l  ← duplicata de home.html
static/                                  ← só imagens
```

### Depois

```
core/
├── views.py           ~450 l  ← só HTTP: recebe, valida, delega, responde
├── forms.py, urls.py, admin.py, models.py, middleware.py, signals.py
│
├── services/                  ← orquestração: conhece ORM e casos de uso
│   ├── __init__.py
│   ├── import_service.py      ← loop de lotes, progresso, fallback, threads
│   ├── candidate_repository.py← _upsert_candidate: O ÚNICO lugar que grava candidato
│   └── ranking_service.py     ← busca no pool + persistência de aderência
│
├── domain/                    ← regra pura: NÃO importa Django nem ORM
│   ├── __init__.py
│   ├── matching.py            ← movido, sem mudança de lógica
│   ├── normalization.py       ← _normalize + SYNONYMS unificados (hoje duplicados)
│   ├── boolean_search.py      ← movido de views.py
│   └── job_description.py     ← movido de views.py
│
├── llm/                       ← integração com provedor
│   ├── __init__.py
│   ├── client.py              ← _generate(): O ÚNICO lugar que fala com o Gemini
│   ├── prompts.py             ← os prompts, isolados
│   └── extractor.py           ← as 7 funções públicas, agora finas
│
├── pdf.py             ~120 l  ← só PDF de verdade: ZIP, temp dir, salvar arquivo
├── metrics.py, observability.py, plans.py
└── tests/                     ← + characterization tests do caminho crítico

static/
├── js/job_detail.js           ← extraído do template
└── css/app.css                ← CSS compartilhado

templates/core/job_detail.html  ~500 l
(landing.html e core/tests.py removidos)
```

### Regra de dependência que passa a valer

```
views  →  services  →  domain
                   →  llm
                   →  models (ORM)

llm    →  domain          (nunca o contrário)
domain →  NADA do Django  (nem ORM, nem settings, nem forms)
```

**Setas só apontam para baixo.** `domain/` não importa Django — é o que o torna testável
sem banco, sem HTTP e sem chave de API. `matching.py` já é assim hoje, com 84% de
cobertura sem esforço: é a prova de que a forma funciona neste projeto.

**Por que camadas e não hexagonal/ports & adapters:** o sistema tem um provedor de LLM, um
banco e uma interface web. Ports & adapters resolveria um problema de múltiplos adaptadores
intercambiáveis que este app não tem, e cobraria indireção que não se paga. Camadas simples
resolvem a dor real — regra de negócio presa dentro de view e de função de I/O — sem
inventar abstração.

**Renomear `pdf_extractor.py`:** o nome mente. Depois de remover as 872 linhas mortas, o
que sobra é orquestração de importação com persistência — vai para `services/`. O que é
genuinamente PDF (ZIP, diretório temporário, salvar arquivo) fica em `pdf.py`.

---

## 6. Rede de segurança

**Passo zero, não opcional.** Os três arquivos que serão refatorados têm 6%, 17% e 20% de
cobertura. Antes de mover uma linha, é preciso fixar o comportamento atual — **inclusive o
esquisito**. Um characterization test não julga se o comportamento é certo; ele registra
o que o sistema faz hoje, para que a refatoração prove que nada mudou.

### Testes a escrever, por área

| # | Área | O que fixar | Esforço |
|---|---|---|---|
| **T-1** | Upsert de candidato (`pdf_extractor`) | Criar novo · atualizar existente · pular sem `name`/`linkedin_url` · campos `None` virando `""` · `user_id` aplicado · `shared_pool` ligado e desligado · PDF salvo nos dois ramos | 1d |
| **T-2** | Loop de lotes | Lote de 10 · lote parcial · falha do lote caindo no fallback individual · `progress_callback` recebendo os valores certos · contadores `created/updated/skipped/errors` · `error_details` truncado em 10 | 1d |
| **T-3** | `llm_extractor` — retry | Sucesso na 1ª · retry em `RESOURCE_EXHAUSTED` · retry em 503 · esgotar 4 tentativas e propagar · `_extract_json` com JSON puro, com markdown em volta, com lixo antes e depois, e array vs objeto | 0,5d |
| **T-4** | `llm_extractor` — contratos | Formato exato do dict devolvido por cada uma das 7 funções públicas, com o LLM mockado · normalização de listas · `_normalize_linkedin_url` | 0,5d |
| **T-5** | Views de import (`job_detail` POST, `talent_pool` POST) | ZIP com PDFs · PDFs soltos · arquivo sem PDF nenhum · thread disparada com os argumentos certos (mockar `threading.Thread`) · mensagens de retorno | 0,5d |
| **T-6** | Filtros e paginação | Cada filtro de `job_detail` e `talent_pool` isolado · combinação · querystring preservada entre páginas · filtros salvos em sessão e o redirect de `views.py:600` | 0,5d |
| **T-7** | `search_and_rank_candidates_from_pool` | Separação com-PDF / sem-PDF · `results_map` · `CandidateJob` criado com aderência · fallback individual | 0,5d |

**Total: ~4,5 dias.** É um terço do projeto e é o investimento que torna o resto possível.

### O que hoje é intestável, e a mudança mínima que resolve

| Intestável | Por quê | Mudança mínima |
|---|---|---|
| Threads de background | `threading.Thread` chamado direto dentro da view | Extrair `_start_background(fn, *args)`; o teste mocka **essa** função |
| Chamada ao Gemini | `genai.Client()` instanciado dentro de cada função | R-09 já resolve: um `_generate()` para mockar |
| `import_candidates_from_folder` | 435 linhas com I/O, ORM, métricas e LLM entrelaçados | Testar com LLM mockado e `tmp_path`; funciona **antes** de refatorar |
| Montagem de prompt | Concatenação dentro da função que chama a API | Extrair função pura `build_prompt(...) -> str` |

> **Nota:** T-1 a T-7 usam `pytest-mock`/`unittest.mock` sobre o `llm_extractor`. Nenhum
> teste chama a API do Gemini de verdade — nem em CI, nem localmente.

---

## 7. Backlog de refatorações

29 itens. Cada um cabe em um commit com a suíte verde e em um PR revisável em 15 minutos.

---

### Onda 0 — Verdade, limpeza e rede de segurança

```
[R-01] Expor a cobertura real: remover o `omit` do coverage
Motivação:   D-2 — o CI reporta 88% sobre 421 de 2.241 statements
Arquivos:    pyproject.toml, Makefile, .github/workflows/ci.yml
O que muda:  remove views.py, llm_extractor.py, pdf_extractor.py e urls.py do
             `[tool.coverage.run] omit`; ajusta `fail_under` para 24 (1 ponto abaixo
             do real, para não travar o CI hoje); unifica o valor nos três lugares,
             que hoje divergem (20 / 50 / 50)
Não muda:    nenhuma linha de código de aplicação; os 100 testes continuam iguais
Pré-requisito: nenhum
PR:          3 arquivos · ~20 linhas
Produção:    transparente (não toca em código que roda em produção)
Deploy:      deploy normal; o CD só dispara após CI verde, e o CI continua verde
Como validar: `pytest --cov=core` deve reportar ~25% e passar
Verificação pós-deploy: n/a
Risco:       baixo — se o fail_under ficar alto demais, o CI trava e ninguém faz deploy;
             por isso 24 e não 50
Reversão:    reverter o commit
Esforço:     30 min
Ganho:       o número passa a ser real; toda melhoria de cobertura vira visível

[R-02] Travar versões das dependências
Motivação:   D-8 — venv local com Django 6.0.6/Python 3.14, CI em 3.12, README em 5.x
Arquivos:    requirements.txt, requirements-dev.txt, .github/workflows/ci.yml
O que muda:  fixa todos os 8 pacotes em `==` na versão hoje validada; adiciona
             `python-requires`; alinha o CI e o venv local em 3.12
             ⚠️ CORRIGIDO NA EXECUÇÃO: produção roda **3.10.12**, não 3.12. O
             alinhamento foi para BAIXO (pyproject e ruff em py310) e o CI virou
             matriz 3.10 + 3.12. Ver R-34 para o upgrade de produção.
Não muda:    nenhuma linha de aplicação
Pré-requisito: nenhum
PR:          3 arquivos · ~20 linhas
Produção:    REQUER CUIDADO — ver seção 9, item P-1
Deploy:      o deploy roda `pip install -r requirements.txt`; se a versão fixada
             diferir da instalada no servidor, o pip vai baixar/downgradar. Confirme
             por SSH (`pip freeze`) qual versão está em produção HOJE e fixe NELA,
             não na do seu venv local. Depois, atualize por PR próprio.
Como validar: suíte verde em 3.12 no CI; `pip freeze` do servidor bate com o arquivo
Verificação pós-deploy: `systemctl status talent_rank_ai` + abrir a home e o dashboard
Risco:       médio se fixar na versão errada — daí o passo de confirmar no servidor
Reversão:    reverter o commit e redeployar
Esforço:     1h (inclui o SSH de conferência)
Ganho:       deploy deixa de poder trocar de major do Django sozinho

[R-03] Remover 872 linhas de código morto do pdf_extractor
Motivação:   D-1 — 46% do maior arquivo do projeto é inalcançável
Arquivos:    core/pdf_extractor.py, core/tests/test_pdf_extractor.py
O que muda:  apaga as 23 funções não alcançáveis (linhas 37-976: SECTION_TITLES,
             _fix_mojibake, _clean_lines, _find_linkedin_url, _find_name,
             _find_location, _extract_headline, _extract_skills, _filter_skills,
             _extract_languages, _extract_summary, _extract_certifications,
             _normalize_technologies, _extract_technologies, _extract_experience,
             _extract_experience_years, _duration_to_months, _normalize_text,
             _extract_experience_blocks, _extract_average_tenure,
             _extract_total_experience_years, _extract_role_experience_years,
             _infer_seniority_from_years, parse_candidate_from_pdf) e os imports
             que ficam órfãos (`re`, `unicodedata`, `Decimal`, `PdfReader`).
             Remove os 7 testes de test_pdf_extractor.py, que só cobrem 3 helpers
             mortos.
Não muda:    nada do comportamento — é código que não executa. Comprovado por
             análise AST de alcançabilidade e pelos 6% de cobertura.
Pré-requisito: nenhum — não precisa de teste antes, porque não há o que preservar
PR:          2 arquivos · −872 / −38 linhas (delete puro, zero linha adicionada)
Produção:    transparente
Deploy:      deploy normal
Como validar: `pytest` verde (93 testes, os 7 deletados a menos) · `ruff check .` sem
             import não usado · `grep -rn "parse_candidate_from_pdf" .` sem resultado
Verificação pós-deploy: rodar uma importação real de 1 PDF numa vaga de teste
Risco:       baixo — a única forma de errar é se houvesse import dinâmico; verificado
             por grep em todo o repositório, não há
Reversão:    reverter o commit (o código volta inteiro)
Esforço:     1h
Ganho:       pdf_extractor.py cai de 1.888 para ~1.016 linhas. O arquivo passa a ser
             legível, e o que sobra é exatamente o que precisa ser refatorado.

[R-04] Remover landing.html duplicado e core/tests.py órfão
Motivação:   D-12 — 774 linhas duplicadas de home.html e um módulo fantasma
Arquivos:    landing.html, core/tests.py
O que muda:  apaga os dois arquivos
Não muda:    nada — landing.html não é referenciado por nenhuma view nem template;
             core/tests.py é sombreado pelo pacote core/tests/
Pré-requisito: nenhum
PR:          2 arquivos · −775 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: `pytest` verde · `grep -rn "landing" --include=*.py --include=*.html`
             sem resultado · abrir a home
Verificação pós-deploy: abrir a página inicial
Risco:       baixo — confirme antes se o landing.html não está sendo servido
             direto pelo Nginx como página estática (não está na config atual)
Reversão:    reverter o commit
Esforço:     20 min
Ganho:       menos 775 linhas; deixa de existir a dúvida "qual é a landing de verdade"

[R-05] Characterization tests: upsert de candidato
Motivação:   D-2 + pré-requisito obrigatório de R-08
Arquivos:    core/tests/test_import_upsert.py (novo)
O que muda:  escreve os testes T-1 da seção 6, com o llm_extractor mockado e
             `tmp_path` para os PDFs
Não muda:    nenhuma linha de aplicação
Pré-requisito: R-03 (testar o arquivo já limpo)
PR:          1 arquivo · ~250 linhas de teste
Produção:    transparente
Deploy:      deploy normal
Como validar: os testes passam contra o código ATUAL, sem alterá-lo. Se um teste
             precisar de mudança no código para passar, ele está errado — o objetivo
             é fixar o comportamento de hoje, não o desejado.
Verificação pós-deploy: n/a
Risco:       baixo
Reversão:    reverter o commit
Esforço:     1d
Ganho:       destrava R-08, o item mais valioso do plano

[R-06] Characterization tests: loop de lotes e progresso
Motivação:   pré-requisito de R-10
Arquivos:    core/tests/test_import_batches.py (novo)
O que muda:  testes T-2 da seção 6
Não muda:    nenhuma linha de aplicação
Pré-requisito: R-05
PR:          1 arquivo · ~220 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: passam contra o código atual sem alterá-lo
Verificação pós-deploy: n/a
Risco:       baixo
Reversão:    reverter o commit
Esforço:     1d
Ganho:       destrava R-10

[R-07] Characterization tests: cliente LLM, retry e parsing
Motivação:   pré-requisito de R-11
Arquivos:    core/tests/test_llm_client.py (novo)
O que muda:  testes T-3 e T-4 da seção 6, sobre as 7 funções públicas
Não muda:    nenhuma linha de aplicação
Pré-requisito: nenhum (independente de R-05/R-06 — pode ir em paralelo)
PR:          1 arquivo · ~200 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: passam contra o código atual · nenhum teste chama a API de verdade
Verificação pós-deploy: n/a
Risco:       baixo
Reversão:    reverter o commit
Esforço:     1d
Ganho:       destrava R-11
```

---

### Onda 1 — Eliminar a duplicação estrutural

```
[R-08] Extrair _upsert_candidate() — unificar as 4 cópias
Motivação:   D-3 — o item central do plano
Arquivos:    core/pdf_extractor.py
O que muda:  técnica: EXTRAIR FUNÇÃO. Cria
             `_upsert_candidate(data, user_id, shared_pool, pdf_path) -> tuple[Candidate, str]`
             onde o segundo elemento é "created" | "updated" | "unchanged".
             As 4 cópias (linhas 1065, 1244, 1468, 1598) passam a chamá-la.
             A lista de 11 campos de texto, hoje escrita 8 vezes inline, vira uma
             constante única TEXT_FIELDS no topo do módulo.
Não muda:    o comportamento observável de cada uma das 4 chamadas, INCLUSIVE a
             divergência do shared_pool na cópia :1614. A função recebe `shared_pool`
             como parâmetro, e a chamada de :1614 continua passando o valor que
             produz o comportamento de hoje. O bug é corrigido em R-09, separado.
Pré-requisito: R-05 (sem os testes, isto é aposta)
PR:          1 arquivo · ~+90 / −340 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: os testes de R-05 passam SEM alteração. Se algum precisar mudar, a
             refatoração alterou comportamento e está errada.
Verificação pós-deploy: importar 2 PDFs numa vaga de teste — um novo e um já
             existente — e conferir created/updated no resultado
Risco:       médio — é o coração do fluxo de importação; mitigado inteiramente por R-05
Reversão:    reverter o commit
Esforço:     1d
Ganho:       adicionar campo ao candidato passa de 8 edições para 1. É o que torna
             qualquer feature nova sobre candidato barata.

[R-09] [BUGFIX — não é refatoração] shared_pool ignorado no fallback individual
Motivação:   D-3 — pdf_extractor.py:1614 não respeita o pool compartilhado
Arquivos:    core/pdf_extractor.py, core/tests/test_import_upsert.py
O que muda:  passa `shared_pool` na chamada de _upsert_candidate que hoje o omite
Não muda:    ⚠️ ESTE ITEM MUDA COMPORTAMENTO — é correção de bug, marcada como tal e
             em PR separado, exatamente para não se misturar com R-08.
             Efeito: usuário PREMIUM, quando o lote falha e cai no fallback individual,
             passa a ATUALIZAR o candidato do pool compartilhado em vez de criar
             duplicata.
Pré-requisito: R-08
PR:          2 arquivos · ~10 linhas + 1 teste de regressão
Produção:    REQUER CUIDADO — ver seção 9, item P-2
Deploy:      deploy normal, mas avise a usuária: importações PREMIUM que antes geravam
             duplicata passam a atualizar. Vale checar se existem duplicatas já criadas
             por este bug (query de linkedin_url repetido) antes de subir.
Como validar: novo teste de regressão falha antes e passa depois
Verificação pós-deploy: importar, como PREMIUM, um PDF de candidato que já está no pool
             de outro usuário; conferir que atualizou e não duplicou
Risco:       médio — muda comportamento observável em um caminho de erro
Reversão:    reverter o commit (volta a duplicar, comportamento de hoje)
Esforço:     2h
Ganho:       um bug real a menos, com teste que impede o retorno

[R-10] Extrair o loop de lotes com fallback individual
Motivação:   D-3 — 3 cópias do loop de lotes (linhas 1017, 1440, 1796)
Arquivos:    core/pdf_extractor.py
O que muda:  técnica: EXTRAIR FUNÇÃO + INJEÇÃO DE COMPORTAMENTO. Cria
             `_process_in_batches(items, batch_fn, single_fn, on_result, progress, size=10)`
             com o loop, a numeração de lote, o sleep entre lotes, o try/except que
             cai para o individual e a contabilidade de created/updated/skipped/errors.
             As 3 funções grandes passam a fornecer só as duas callbacks.
Não muda:    a sequência de chamadas ao LLM, os sleeps, o formato do progress_callback,
             os contadores e o truncamento de error_details em 10
Pré-requisito: R-06, R-08
PR:          1 arquivo · ~+120 / −400 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: testes de R-05 e R-06 passam sem alteração
Verificação pós-deploy: importar um ZIP com 12 PDFs (força 2 lotes) e acompanhar a
             barra de progresso do início ao fim
Risco:       médio — mitigado por R-06
Reversão:    reverter o commit
Esforço:     1d
Ganho:       import_candidates_from_folder cai de 435 para ~80 linhas;
             ..._no_ranking de 322 para ~50. pdf_extractor.py chega a ~600 linhas.

[R-11] Extrair _generate() — unificar as 7 cópias de client + retry
Motivação:   D-4 — 7 cópias idênticas em llm_extractor.py
Arquivos:    core/llm_extractor.py
O que muda:  técnica: EXTRAIR FUNÇÃO. Cria
             `_generate(payload, *, model=DEFAULT_GEMINI_MODEL) -> tuple[str, str]`
             (texto da resposta, modelo usado) com a validação da API key, o cliente e
             o loop de 4 tentativas com backoff [3, 8, 15, 30]. As 7 funções públicas
             passam a chamá-la.
Não muda:    número de tentativas, tempos de backoff, quais erros disparam retry,
             a exceção propagada, e o formato do dict devolvido por cada função
Pré-requisito: R-07
PR:          1 arquivo · ~+45 / −190 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: testes de R-07 passam sem alteração
Verificação pós-deploy: gerar um parecer e rodar uma importação de 1 PDF
Risco:       médio — todo o contato com o LLM passa por aqui; mitigado por R-07
Reversão:    reverter o commit
Esforço:     0,5d
Ganho:       trocar modelo, adicionar timeout, medir custo de token ou trocar de
             provedor passa a ser 1 edição em vez de 7

[R-12] Adicionar timeout à chamada do LLM
Motivação:   D-4 — nenhuma das 7 chamadas tem timeout; uma trava segura a thread
Arquivos:    core/llm_extractor.py, talent_query/settings.py
O que muda:  ⚠️ MUDANÇA DE COMPORTAMENTO em PR separado: `_generate()` passa a receber
             timeout de `settings.LLM_TIMEOUT_SECONDS` (default 120), via
             `types.HttpOptions(timeout=...)`
Não muda:    nada em caso de resposta normal — só o caso patológico deixa de ser infinito
Pré-requisito: R-11 (só é barato depois que existe um lugar só)
PR:          2 arquivos · ~15 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: teste que simula timeout e confirma que vira erro tratado
Verificação pós-deploy: importação normal funcionando; nenhum job preso
Risco:       baixo — o valor default (120s) é folgado para lote de 10 PDFs;
             se ficar curto, importações grandes passam a falhar. Comece em 180s
             se preferir margem.
Reversão:    reverter o commit
Esforço:     2h
Ganho:       thread travada deixa de ser possível

[R-13] Unificar normalização e sinônimos em domain/normalization.py
Motivação:   D-5 — SYNONYMS e a normalização de acento existem em 2 lugares
Arquivos:    core/domain/normalization.py (novo), core/matching.py, core/views.py
O que muda:  técnica: MOVER + REMOVER DUPLICATA. `matching.SYNONYMS` e
             `views._build_boolean_search.synonyms` viram um SYNONYMS único;
             `matching._normalize` e `views._normalize_term` viram um `normalize()`.
             Os dois chamadores passam a importar do novo módulo.
Não muda:    ⚠️ ATENÇÃO: os dois dicionários são idênticos hoje (conferido termo a
             termo) e as duas funções de normalização produzem a mesma saída. Confirme
             isso com um teste de equivalência ANTES de unificar. Se divergirem em
             algum caso, isto vira mudança de comportamento e precisa de decisão.
Pré-requisito: nenhum (independente da Onda 1 — pode ir em paralelo)
PR:          3 arquivos · ~+60 / −80 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: teste de equivalência + os 14 testes de matching passam sem alteração
Verificação pós-deploy: gerar uma busca booleana numa vaga e rodar um preview de match
Risco:       baixo
Reversão:    reverter o commit
Esforço:     3h
Ganho:       adicionar um sinônimo (ex.: "postgres" → "postgresql") passa a valer nos
             dois lugares automaticamente
```

---

### Onda 2 — Camada de serviço

```
[R-14] Criar core/services/ e mover a orquestração de importação
Motivação:   D-5 — views.py mistura HTTP com orquestração
Arquivos:    core/services/__init__.py, core/services/import_service.py (novos),
             core/views.py, core/pdf_extractor.py
O que muda:  técnica: MOVER MÓDULO (movimentação mecânica, PR separado de lógica).
             `_run_import_job`, `_run_talent_pool_import`, `_run_search_in_pool` e
             `_run_parecer_generation` saem de views.py para import_service.py.
             As chaves de cache e os setters de status vão junto.
Não muda:    uma linha sequer do corpo das funções — só o arquivo onde moram
Pré-requisito: R-10
PR:          4 arquivos · ~+230 / −230 linhas (movimentação pura)
Produção:    transparente
Deploy:      deploy normal
Como validar: suíte inteira verde · diff deve ser reconhecível como recorte e cola
Verificação pós-deploy: uma importação completa de ponta a ponta
Risco:       baixo — mecânico, e o revisor consegue conferir olhando
Reversão:    reverter o commit
Esforço:     0,5d
Ganho:       views.py cai para ~700 linhas; a orquestração ganha lugar próprio

[R-15] Extrair o helper de filtros + querystring das views
Motivação:   D-5 — job_detail (154 l) e talent_pool (141 l) duplicam ~55 linhas
Arquivos:    core/views.py, core/filters.py (novo)
O que muda:  técnica: EXTRAIR FUNÇÃO + PARÂMETRO-OBJETO. Cria
             `collect_filters(request, spec) -> Filters` com os valores lidos, o dict
             para o template e a querystring de paginação já montada. As duas views
             passam a declarar só a lista de campos.
Não muda:    quais filtros existem, como são aplicados, a ordem dos parâmetros na
             querystring e o comportamento de filtro salvo em sessão (views.py:590-600)
Pré-requisito: R-19 (testes de filtro)
PR:          2 arquivos · ~+90 / −120 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: testes de R-19 passam sem alteração
Verificação pós-deploy: aplicar 3 filtros em /vagas/<id>/, paginar e conferir que os
             filtros sobrevivem à troca de página
Risco:       baixo
Reversão:    reverter o commit
Esforço:     0,5d
Ganho:       job_detail cai para ~70 linhas; adicionar um filtro novo vira 1 linha

[R-16] Mover a construção de prompt e busca booleana para domain/
Motivação:   D-5 — regra de negócio dentro de handler HTTP
Arquivos:    core/domain/job_description.py, core/domain/boolean_search.py (novos),
             core/views.py, core/services/import_service.py
O que muda:  técnica: MOVER FUNÇÃO. `_build_job_description` (views.py:482) e
             `_build_boolean_search` (views.py:420) saem de views.py. Passam a ser
             funções puras, testáveis sem HTTP: recebem os campos da vaga, não o objeto
             Job, para não arrastar o ORM para dentro de domain/.
Não muda:    a string produzida — byte a byte. Esta é a garantia crítica: mudar o texto
             do prompt muda o resultado do LLM.
Pré-requisito: R-13, R-14
PR:          4 arquivos · ~+130 / −110 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: teste que compara a saída nova com a string exata produzida hoje,
             para uma vaga de exemplo com todos os campos e outra com campos vazios
Verificação pós-deploy: gerar busca booleana numa vaga; conferir que a string é a
             mesma de antes
Risco:       médio — se a string do prompt mudar, o ranking muda silenciosamente.
             Mitigado pelo teste de igualdade exata.
Reversão:    reverter o commit
Esforço:     0,5d
Ganho:       regra de negócio testável sem HTTP; matching e prompt no mesmo lugar

[R-17] Renomear pdf_extractor.py conforme a responsabilidade real
Motivação:   D-5 — o nome mente; depois de R-03 e R-10 sobrou orquestração
Arquivos:    core/pdf_extractor.py → core/services/candidate_import.py e core/pdf.py
O que muda:  técnica: MOVER MÓDULO. A orquestração vai para services/; o que é
             genuinamente PDF (`_save_resume_pdf`, e `_prepare_uploaded_files` vindo
             de views.py:39) vai para core/pdf.py. Ajusta os imports.
Não muda:    nenhuma linha de corpo de função
Pré-requisito: R-14
PR:          5 arquivos · ~+40 / −40 linhas + git mv
Produção:    transparente
Deploy:      deploy normal
Como validar: suíte verde · `ruff check .` sem import quebrado
Verificação pós-deploy: uma importação de ponta a ponta
Risco:       baixo — mecânico
Reversão:    reverter o commit
Esforço:     3h
Ganho:       o mapa do projeto passa a bater com o que o código faz
```

---

### Onda 3 — Confiabilidade dos jobs em background

```
[R-18] Fechar conexões de banco nas threads
Motivação:   D-6 — zero ocorrências de connection.close() no repositório
Arquivos:    core/services/import_service.py
O que muda:  ⚠️ CORREÇÃO em PR próprio: envolve o corpo de cada função de thread com
             `close_old_connections()` na entrada e no `finally`
Não muda:    o que os jobs fazem
Pré-requisito: R-14
PR:          1 arquivo · ~20 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: teste que roda a função de job e confirma a conexão devolvida
Verificação pós-deploy: `SELECT count(*) FROM pg_stat_activity WHERE datname='talent_query';`
             antes e ~5 min depois de uma importação — o número deve voltar ao patamar
Risco:       baixo
Reversão:    reverter o commit
Esforço:     3h
Ganho:       elimina o vazamento de conexão

[R-19] [BUGFIX] Chave de cache de importação do pool por usuário
Motivação:   D-6 — "talent_pool_import_status" é global (views.py:507)
Arquivos:    core/services/import_service.py, core/views.py, core/tests/
O que muda:  ⚠️ MUDA COMPORTAMENTO: a chave passa a ser
             `talent_pool_import_status_{user_id}` em todos os pontos (setter, getter,
             a view de status e o contexto do template)
Não muda:    o formato do payload de status
Pré-requisito: R-14
PR:          3 arquivos · ~30 linhas + teste de regressão com 2 usuários
Produção:    REQUER CUIDADO — ver seção 9, item P-3
Deploy:      no deploy, status em andamento sob a chave antiga ficam órfãos e a UI volta
             a "idle". Deploye quando não houver importação rodando.
Como validar: teste com dois usuários importando simultaneamente
Verificação pós-deploy: com duas contas, iniciar importações ao mesmo tempo e conferir
             que cada uma vê o próprio progresso
Risco:       baixo
Reversão:    reverter o commit
Esforço:     3h
Ganho:       corrige bug real de multiusuário

[R-20a] Estado do job no banco — modelo + escrita dupla
Motivação:   D-6 — todo deploy mata importação em andamento e deixa a UI travada
Arquivos:    core/models.py + migration, core/services/import_service.py
O que muda:  ⚠️ MUDANÇA DE COMPORTAMENTO (não é refatoração): novo modelo `ImportJob`
             (user, job, status, processed, total, started_at, heartbeat_at, error).
             O código passa a escrever no cache E no banco. A leitura continua no cache.
             É a etapa "expand" do expand-contract.
Não muda:    a forma como a importação processa os PDFs; nada do que a UI exibe hoje
Pré-requisito: R-18, R-19
PR:          3 arquivos · ~120 linhas
Produção:    REQUER CUIDADO — ver seção 9, item P-4
Deploy:      migration antes do código. Tabela nova e vazia, ninguém lê ainda: risco zero.
Como validar: migration aplica limpa; teste confirmando que o job grava nos dois lugares
Verificação pós-deploy: rodar uma importação real e conferir que a tabela é populada
Risco:       médio — é o item mais próximo de "feature nova" do plano
Reversão:    reverter o commit; a tabela pode ficar, inofensiva
Esforço:     0,75d
Ganho:       base para R-20b sem risco algum

[R-20b] Estado do job no banco — leitura do banco e remoção do cache
Motivação:   D-6 — status preso em "running" para sempre após restart
Arquivos:    core/services/import_service.py, core/views.py, templates
O que muda:  a leitura passa a vir do banco em vez do cache; a escrita no cache é
             removida. Um job com heartbeat parado há mais de N minutos é exibido como
             "interrompido — reinicie a importação", em vez de "running" para sempre.
             É a etapa "contract" do expand-contract.
Não muda:    a forma como a importação processa os PDFs
Pré-requisito: R-20a implantado E confirmado populando a tabela em produção
PR:          3 arquivos · ~80 linhas
Produção:    REQUER CUIDADO — ver seção 9, item P-4
Deploy:      só depois de (a) estar no ar e escrevendo corretamente
Como validar: teste que simula morte da thread e confirma que a UI mostra "interrompido"
Verificação pós-deploy: iniciar importação, reiniciar o serviço no meio, conferir que a
             tela informa a interrupção em vez de girar para sempre
Risco:       médio
Reversão:    reverter o commit (volta a ler do cache)
Esforço:     0,75d
Ganho:       o fluxo mais visível do produto para de falhar em silêncio
```

---

### Onda 4 — Segurança e configuração de produção

> Esta onda **não é refatoração** — é correção de risco. Está no plano porque envolve os
> mesmos arquivos e porque D-7 é o achado mais grave do diagnóstico. Se o tempo apertar,
> ela tem prioridade sobre as Ondas 5 e 6.

```
[R-21] Endurecer settings de produção
Motivação:   D-7 — manage.py check --deploy acusa 6 avisos
Arquivos:    talent_query/settings.py, README.md
O que muda:  SECRET_KEY passa a ser obrigatória quando DEBUG=False (levanta
             ImproperlyConfigured em vez de usar o fallback publicado no Git);
             DEBUG default vira False; SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE,
             SECURE_HSTS_SECONDS e SECURE_SSL_REDIRECT ligados quando DEBUG=False;
             SECURE_PROXY_SSL_HEADER deixa de vir ligado por default em dev
Não muda:    o comportamento em desenvolvimento (DEBUG=True no .env local)
Pré-requisito: nenhum
PR:          2 arquivos · ~40 linhas
Produção:    REQUER CUIDADO — ver seção 9, item P-5
Deploy:      ⚠️ CONFIRME POR SSH, ANTES DE SUBIR, que DJANGO_SECRET_KEY existe no .env
             do servidor. Se não existir, a aplicação NÃO SOBE depois deste deploy.
             Cookies Secure exigem HTTPS funcionando — confirme que o domínio está em
             TLS antes.
Como validar: `manage.py check --deploy` sai de 6 avisos para 0 ou 1
Verificação pós-deploy: login, navegação, e conferir no DevTools que os cookies têm
             a flag Secure
Risco:       ALTO SE O .env DO SERVIDOR ESTIVER INCOMPLETO — o app deixa de subir.
             Mitigação: conferir por SSH antes; é o passo obrigatório deste item.
Reversão:    reverter o commit e redeployar
Esforço:     3h (inclui a conferência no servidor)
Ganho:       fecha a exposição mais séria da configuração

[R-22] Proteger o endpoint /metrics
Motivação:   D-7 — /metrics é público (urls.py:7 + Nginx com proxy_pass em location /)
Arquivos:    core/views.py, DEPLOY_LIGHTSAIL.md
O que muda:  o endpoint passa a exigir token via header (comparado com
             `settings.METRICS_TOKEN`) ou restrição de IP no Nginx — escolha uma
Não muda:    o formato das métricas
Pré-requisito: nenhum
PR:          2 arquivos · ~30 linhas
Produção:    REQUER CUIDADO — se houver Prometheus scrapeando hoje, ele precisa do
             token antes de o endpoint fechar
Deploy:      adicionar o token e aceitar as duas formas → configurar o scraper →
             remover o acesso sem token (expand-contract)
Como validar: teste de 401 sem token e 200 com token
Verificação pós-deploy: `curl` sem token deve dar 401; com token, 200
Risco:       baixo
Reversão:    reverter o commit
Esforço:     2h
Ganho:       para de expor telemetria interna na internet

[R-23] Servir currículos em PDF por view autenticada
Motivação:   D-7 — /media/ é público no Nginx; dado pessoal de candidato (LGPD)
Arquivos:    core/views.py, core/urls.py, DEPLOY_LIGHTSAIL.md
O que muda:  nova view `resume_download(candidate_id)` com @login_required + checagem
             de dono, devolvendo X-Accel-Redirect para um `location /protected-media/`
             marcado `internal;` no Nginx
Não muda:    onde os arquivos ficam no disco
Pré-requisito: nenhum
PR:          3 arquivos · ~70 linhas
Produção:    REQUER CUIDADO — ver seção 9, item P-6
Deploy:      1) adicionar a view e o location interno, mantendo /media/ público;
             2) apontar os links da aplicação para a nova rota;
             3) só então remover o `location /media/` público do Nginx.
             Expand-contract clássico — se remover antes de migrar os links, os PDFs
             somem da interface.
Como validar: teste de 403 para PDF de outro usuário e 200 para o próprio
Verificação pós-deploy: baixar um currículo logado (deve funcionar); acessar a URL
             /media/ direta e deslogado (deve dar 404)
Risco:       médio — se a config do Nginx sair errada, os PDFs param de abrir
Reversão:    reverter o commit e restaurar o location /media/
Esforço:     0,5d
Ganho:       currículos deixam de ser acessíveis por quem tiver a URL
```

---

### Onda 5 — Performance

```
[R-24] reports: trocar ~500 queries por 2 agregações
Motivação:   D-9 — views.py:368-382, 10 queries por vaga sobre 50 vagas
Arquivos:    core/views.py (ou services/reports_service.py, se R-14 já entrou)
O que muda:  o laço aninhado vira um
             `.values('job_id', 'pipeline_status').annotate(Count('id'))` único,
             montado em dicionário em memória
Não muda:    os números exibidos, a ordem das colunas do funil e o limite de 50 vagas
Pré-requisito: teste que fixa a saída atual do contexto de reports
PR:          2 arquivos · ~+60 / −40 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: teste que compara o contexto novo com o atual para o mesmo dado;
             `assertNumQueries` provando a redução
Verificação pós-deploy: abrir /relatorios/ e conferir que os números batem com antes
Risco:       baixo
Reversão:    reverter o commit
Esforço:     0,5d
Ganho:       página de relatórios deixa de degradar com o crescimento

[R-25] Índice funcional para linkedin_url__iexact
Motivação:   D-10 — usado em todo upsert, sem índice que o atenda
Arquivos:    core/migrations/00XX_*.py (novo)
O que muda:  índice em `Lower(linkedin_url)` criado com AddIndexConcurrently
             (`django.contrib.postgres.operations`), com `atomic = False` na migration
Não muda:    nenhum resultado de query — só o plano de execução
Pré-requisito: nenhum
PR:          1 arquivo · ~25 linhas
Produção:    REQUER CUIDADO — ver seção 9, item P-7
Deploy:      CREATE INDEX CONCURRENTLY não trava a tabela, mas não roda dentro de
             transação: a migration precisa de `atomic = False`. Se falhar no meio,
             deixa índice INVALID que precisa ser removido à mão antes de tentar de novo.
Como validar: `EXPLAIN` da query de upsert usando Index Scan em vez de Seq Scan
Verificação pós-deploy: `SELECT indexname, indisvalid FROM pg_index ...` confirmando
             que o índice é válido; uma importação com tempo comparável ou melhor
Risco:       baixo — concorrente, sem lock de escrita
Reversão:    DROP INDEX CONCURRENTLY
Esforço:     2h
Ganho:       upsert deixa de fazer varredura completa conforme o pool cresce

[R-26] CandidateJob.save(): evitar a query extra
Motivação:   D-10 — models.py:174 lê o status anterior em todo save
Arquivos:    core/models.py, core/tests/test_models.py
O que muda:  guarda o status carregado em `from_db` e compara em memória, em vez de
             consultar o banco a cada save
Não muda:    quando ready_at é preenchido — os 13 testes de models cobrem isso e devem
             passar sem alteração
Pré-requisito: nenhum
PR:          2 arquivos · ~35 linhas
Produção:    transparente
Deploy:      deploy normal
Como validar: os 13 testes de test_models.py passam sem alteração;
             `assertNumQueries` provando 1 query a menos
Verificação pós-deploy: mudar o status de um candidato para "Candidato pronto" e
             conferir que a data de "pronto em" é preenchida
Risco:       baixo — atenção ao caso de objeto criado em memória (sem from_db)
Reversão:    reverter o commit
Esforço:     3h
Ganho:       menos uma query por atualização de pipeline
```

> **Nota sobre D-10 (pré-match carregando o pool inteiro):** não há item no backlog.
> É um problema real de escala, mas prematuro no volume atual, e a solução boa
> (pré-filtro por texto no banco antes do laço Python) muda quais candidatos entram no
> resultado — ou seja, é mudança de comportamento, não refatoração. Fica registrado na
> seção 12 para quando o volume justificar.

---

### Onda 6 — Frontend

```
[R-27] Extrair o JavaScript de job_detail.html
Motivação:   D-11 — 33 KB de JS inline em um template de 1.434 linhas
Arquivos:    templates/core/job_detail.html, static/js/job_detail.js (novo)
O que muda:  técnica: MOVER (mecânico). O bloco <script> vai para o arquivo estático,
             carregado com {% static %} e defer. Dados dinâmicos do template passam por
             atributos data-* num elemento raiz, em vez de interpolação no meio do JS.
Não muda:    nenhum comportamento da tela — mesma lógica, outro arquivo
Pré-requisito: nenhum
PR:          2 arquivos · ~+850 / −830 linhas (majoritariamente movimentação)
Produção:    REQUER CUIDADO — depende de collectstatic no deploy
Deploy:      o deploy já roda `collectstatic --noinput`; o Whitenoise faz hash no nome
             do arquivo, então não há problema de cache velho. Confirme mesmo assim
             que o /static/ do Nginx está servindo o arquivo novo.
Como validar: abrir /vagas/<id>/ e exercitar TUDO: importar, filtrar, paginar, mudar
             status, gerar parecer, gerar busca booleana, preview de match
Verificação pós-deploy: DevTools sem erro no console; job_detail.js retornando 200
Risco:       médio — não há teste de front; a validação é manual e precisa ser completa
Reversão:    reverter o commit
Esforço:     0,5d
Ganho:       JS ganha cache de browser, lint e sintaxe de verdade; o template cai
             para ~600 linhas

[R-28] Consolidar o CSS repetido em static/css/app.css
Motivação:   D-11 — 12 templates com <style> próprio
Arquivos:    static/css/app.css (novo), templates/core/base_logged.html + os 11 demais
O que muda:  o CSS comum (variáveis, botões, tabelas, cards, formulários) vai para o
             arquivo compartilhado, carregado no base. Cada template mantém só o que
             for genuinamente exclusivo dele.
Não muda:    nenhum pixel — se a aparência mudar, a extração errou
Pré-requisito: R-27
PR:          quebrar em 3 PRs por grupo de telas (autenticação; vagas; talentos e
             relatórios), para o diff visual continuar revisável.
             ~5 arquivos e ~250 linhas por PR
Produção:    REQUER CUIDADO — depende de collectstatic
Deploy:      igual a R-27
Como validar: comparar screenshots antes/depois de cada tela do grupo
Verificação pós-deploy: abrir cada tela do grupo em desktop e no celular
Risco:       médio — CSS quebra em silêncio e não há teste que pegue
Reversão:    reverter o commit do grupo afetado
Esforço:     1d no total
Ganho:       mudar a identidade visual passa a ser uma edição, não doze
```

---

---

### Onda 7 — achados da execução (adicionada em 2026-08-15)

> Estes 5 itens **não estavam no plano original**. Apareceram ao escrever os
> characterization tests de R-05 e R-06: o comportamento foi fixado como está, de
> propósito, para não misturar correção com refatoração. Agora viram trabalho próprio.

```
[R-29] 🐛 [BUGFIX] Reimportar candidato apaga o resumo escrito à mão
Motivação:   descoberto em R-05. `_candidate_payload` fixa `summary: ""` independente
             do que veio do LLM. Um candidato cujo resumo a recrutadora escreveu à mão
             PERDE o resumo ao ser reimportado. É perda de trabalho humano, silenciosa.
Arquivos:    core/pdf_extractor.py, core/tests/test_import_upsert.py
O que muda:  ⚠️ MUDA COMPORTAMENTO. Opções, a decidir com a usuária:
             (a) preservar o summary existente quando já houver um (mais conservador);
             (b) usar o summary do LLM quando o campo estiver vazio;
             (c) manter como está, se zerar for intencional.
             O teste `test_summary_is_always_wiped_on_update` inverte junto.
Não muda:    os demais campos do upsert
Pré-requisito: decisão de produto — não implemente sem perguntar
PR:          2 arquivos · ~20 linhas
Produção:    transparente
Como validar: o teste que hoje fixa o wipe passa a exigir a preservação
Verificação pós-deploy: escrever resumo à mão num candidato, reimportar, conferir
Risco:       baixo tecnicamente; a decisão é de produto
Reversão:    reverter o commit
Esforço:     2h
Ganho:       para de destruir trabalho manual da recrutadora
Prioridade:  ALTA — é o item de maior impacto direto no uso diário

[R-30] Unificar o payload final do callback de importação
⚠️ ESTE ITEM FOI DIAGNOSTICADO ERRADO. Título e motivação originais, mantidos para
   registro: "🐛 [BUGFIX] Barra de progresso mostra 100% mesmo quando tudo falhou —
   o callback final envia `processed=total_files` em vez do contador real".
   **Investigado em 2026-08-17, antes de escrever código, e a premissa não se sustenta
   por três motivos independentes:**
   1. NÃO EXISTE BARRA. `job_detail.html:711-723` renderiza o ramo `completed` a partir
      do `result` ("X criados, Y atualizados, N erro(s)"), sem usar `processed`/`total`.
      O `processed/total` só aparece como texto durante o `running`, e ali já é real.
   2. O CALLBACK FINAL É SEMPRE SOBRESCRITO. `views.py:557` (e :311 e :772) grava
      `{"status": "completed", "result": result}` microssegundos depois do retorno.
      O payload do `pdf_extractor` não sobrevive a um poll de 2s.
   3. O NÚMERO NUNCA ESTEVE ERRADO. `_process_in_batches` incrementa `processed` em
      TODOS os caminhos, inclusive nos de erro. Ao final, `processed == total` sempre —
      então `processed=total_files` e o contador real dão o mesmo valor. "Processado"
      significa tentado, não bem-sucedido; o teste do R-06 leu o nome, não a semântica.
Motivação:   o que sobrou de real: o fluxo de vaga não mandava `result` no callback
             final e o `..._no_ranking` mandava. Dois contratos para o mesmo consumidor,
             e uma janela de corrida em que um poll via `completed` sem `result` e a
             tela exibia "0 criados, 0 atualizados, 0 ignorados".
Arquivos:    core/pdf_extractor.py, core/tests/test_import_batches.py
O que muda:  o callback final do fluxo de vaga passa a mandar `total`, `processed` e
             `result`, idêntico ao `..._no_ranking`
Não muda:    o dicionário de resultado, nem o número de `processed` (ver ponto 3)
Pré-requisito: nenhum
PR:          2 arquivos · ~50 linhas (3 characterization tests invertidos)
Produção:    transparente
Como validar: os 3 testes de `final_call` falham antes (`KeyError: 'result'`) e passam
             depois
Verificação pós-deploy: nenhuma observável — o payload corrigido é sobrescrito de todo
             jeito. É higiene de contrato, não correção visível.
Risco:       baixo
Reversão:    reverter o commit
Esforço:     30 min (não 2h — a estimativa vinha do diagnóstico errado)
Ganho:       um contrato só, e a janela de corrida fechada. **Ganho pequeno e honesto:
             a recrutadora nunca viu 100% falso.** O item que de fato mexe no que ela
             lê é o R-32.

[R-31] PDFs órfãos acumulam no disco a cada reimportação
Motivação:   descoberto em R-05. `_upsert_candidate` sempre regrava o currículo, e o
             nome tem uuid — o arquivo anterior fica no disco para sempre. Reimportar
             o mesmo candidato 10 vezes deixa 10 PDFs, 9 inalcançáveis.
Arquivos:    core/pdf_extractor.py, core/tests/test_import_upsert.py
O que muda:  apagar o arquivo antigo ao substituir, ou pular a regravação quando o
             conteúdo não mudou
Não muda:    qual PDF fica associado ao candidato
Pré-requisito: nenhum
PR:          2 arquivos · ~30 linhas
Produção:    REQUER CUIDADO — apagar arquivo é irreversível; comece só evitando novos
             órfãos e trate os já existentes num comando separado, depois de conferir
Como validar: reimportar 3× e conferir que o diretório tem 1 arquivo
Verificação pós-deploy: `du -sh media/resumes/` estável entre importações
Risco:       médio — mexer em exclusão de arquivo de currículo pede cuidado
Reversão:    reverter o commit (não recupera arquivo apagado)
Esforço:     3h
Ganho:       o disco do Lightsail para de crescer sem limite

[R-32] Candidato sem alteração some da contabilidade
Motivação:   descoberto em R-05. O "unchanged" não entra em `created` nem em `updated`.
             O resumo da importação não fecha: 10 PDFs podem virar "3 criados, 2
             atualizados" sem explicar os outros 5.
Arquivos:    core/pdf_extractor.py, templates, core/tests/
O que muda:  ⚠️ MUDA COMPORTAMENTO: adiciona `unchanged` ao dicionário de resultado e
             exibe na tela
Não muda:    created, updated, skipped, errors
Pré-requisito: R-30 (mexem no mesmo contrato de resultado)
PR:          3 arquivos · ~40 linhas
Produção:    transparente
Como validar: teste que hoje fixa o sumiço passa a exigir `unchanged == 1`
Verificação pós-deploy: reimportar lote idêntico e conferir o resumo
Risco:       baixo
Reversão:    reverter o commit
Esforço:     3h
Ganho:       o resumo da importação passa a fechar a conta

[R-33] Characterization tests de search_and_rank_candidates_from_pool (T-7)
Motivação:   é a última função grande sem teste (309 linhas, o maior bloco do arquivo)
             e bloqueia a conversão do 3º laço, que ficou de fora do R-10
Arquivos:    core/tests/test_search_pool.py (novo)
O que muda:  testes T-7 da seção 6: separação com-PDF / sem-PDF, `results_map`,
             CandidateJob criado com aderência, fallback individual
Não muda:    nenhuma linha de aplicação
Pré-requisito: nenhum
PR:          1 arquivo · ~220 linhas
Produção:    transparente
Como validar: passam contra o código atual sem alterá-lo
Risco:       baixo
Reversão:    reverter o commit
Esforço:     1d
Ganho:       destrava converter o 3º laço para `_process_in_batches` e fecha a
             cobertura do `pdf_extractor`
```

---

## 8. Sequenciamento

```
Onda 0 ─ Verdade e rede de segurança ────────────────── ~4,5d · 7 PRs
  R-03 ─→ R-01            ← dependência descoberta na execução (ver nota abaixo)
  R-02 ─┐ independentes, podem ir em paralelo no mesmo dia
  R-04 ─┘
         └→ R-05 ─→ R-06        (T-1 e T-2, sequenciais)
         └→ R-07                (independente, pode ir em paralelo com R-05/R-06)
                    │
Onda 1 ─ Duplicação ┴──────────────────────────────────── ~3,5d · 6 PRs
  R-05 ─→ R-08 ─→ R-09
                └→ R-10  (também precisa de R-06)
  R-07 ─→ R-11 ─→ R-12
  R-13 ─ independente, encaixa em qualquer momento
                    │
Onda 2 ─ Serviços ──┴──────────────────────────────────── ~2d · 4 PRs
  R-10 ─→ R-14 ─→ R-17
              └─→ R-16  (também precisa de R-13)
  R-19(testes de filtro) ─→ R-15
                    │
Onda 3 ─ Jobs ──────┴──────────────────────────────────── ~2,5d · 4 PRs
  R-14 ─→ R-18
       └─→ R-19 ─→ R-20a ─→ R-20b   ← ponto de atenção: migration
                    │
Onda 4 ─ Segurança ─┴──────────────────────────────────── ~1,5d · 3 PRs
  R-21, R-22, R-23 ─ independentes entre si e de todo o resto
                    │
Onda 5 ─ Performance┴──────────────────────────────────── ~1,5d · 3 PRs
  R-24, R-25, R-26 ─ independentes entre si
                    │
Onda 6 ─ Frontend ──┴──────────────────────────────────── ~1,5d · 2 PRs (R-28 = 3 sub-PRs)
  R-27 ─→ R-28
```

> **Correção 1 do plano (2026-08-15, descoberta ao executar):** R-01 e R-03 estavam
> listados como independentes. Não são. Com o `fail_under` calibrado na cobertura real,
> R-01 sozinho na `main` reprova o CI, porque sem o delete de R-03 a cobertura é 25% e o
> piso é 27. R-01 passou a ser PR empilhado sobre R-03 e **só pode entrar depois dele**.
> A ordem correta da Onda 0 é: R-03 → R-01, com R-02 e R-04 livres.

> **Correção 2 do plano (2026-08-15, descoberta ao executar R-10):** o item dizia
> "3 cópias do loop de lotes". Apenas **2 foram convertidas**. A terceira, em
> `search_and_rank_candidates_from_pool` (309 linhas), tem forma diferente — separa
> candidatos com e sem PDF antes de chamar o LLM — e **não tem characterization test**.
> Converter sem rede seria exatamente o que este projeto existe para evitar. Virou o
> item **R-33** (escrever T-7) seguido da conversão. R-10 está fechado como parcial,
> de propósito.

> **Onda 7 acrescentada:** escrever os characterization tests de R-05 e R-06 revelou
> 6 comportamentos não intencionais. Todos foram **fixados como estão**, para não
> misturar correção com refatoração, e viraram os itens R-29 a R-33. Dois deles
> (R-29 e R-30) afetam o uso diário da recrutadora e merecem prioridade sobre boa
> parte do backlog original.

**Paralelizável:** R-07 corre junto com R-05/R-06. R-13 encaixa em qualquer ponto. A Onda
4 inteira é independente de todo o resto — se a segurança preocupar mais que a
manutenibilidade, pode vir logo depois da Onda 0.

**O que trava o quê:** R-05 é o gargalo do plano inteiro — sem ele, R-08 é aposta, e R-08
destrava R-10, que destrava a Onda 2, que destrava a Onda 3. É o item que não pode ser
pulado "para ganhar tempo".

**Ponto sem volta:** R-20a cria uma tabela nova. Depois de R-20b, o status deixa de ser
lido do cache; voltar atrás exige reverter os dois PRs. A tabela em si é inofensiva e
pode ficar.

**Se o tempo acabar:** pare depois da Onda 1. Ondas 0+1 são ~8 dias e 13 PRs, e entregam
o essencial: 872 linhas mortas fora, cobertura honesta, duplicação estrutural eliminada e
um bug real corrigido. As Ondas 2 a 6 são melhoria contínua e podem virar backlog normal.

---

## 9. Impacto em produção

### Contagem

| Nível | Itens |
|---|---:|
| **Transparente** | 18 |
| **Requer cuidado** | 11 |
| **REQUER PARADA** | **0** |

> ## ✅ Nenhum item exige parada de produção.

Todos os 29 itens são implantáveis com o sistema no ar e revertidos por rollback de
commit. Onde havia risco de indisponibilidade, o plano usa a alternativa incremental:

| Risco potencial | Alternativa adotada, em vez de parada |
|---|---|
| Criar índice em tabela grande (R-25) | `CREATE INDEX CONCURRENTLY` via `AddIndexConcurrently`, sem lock de escrita |
| Migrar status de cache para banco (R-20) | Expand-contract: escrita dupla → migrar leitura → remover o antigo |
| Fechar `/media/` público (R-23) | Expand-contract: nova rota → migrar links → remover a antiga |
| Fechar `/metrics` (R-22) | Aceitar token e sem-token → configurar scraper → exigir token |
| Mover 33 KB de JS (R-27) | Whitenoise já versiona por hash; sem invalidação manual de cache |

### Itens "requer cuidado" — procedimento

**P-1 · R-02 (travar dependências).** Antes de abrir o PR, entre por SSH no servidor,
rode `source .venv/bin/activate && pip freeze` e fixe as versões **que estão em produção
hoje**, não as do seu venv local (que está em Django 6.0.6). Fixar na versão local faria o
deploy instalar um major diferente do validado. Atualizar de versão vira PR próprio,
depois.

**P-2 · R-09 (bugfix do shared_pool).** Muda comportamento observável para usuários
PREMIUM. Antes de subir, rode uma query procurando candidatos com `linkedin_url` repetido
entre usuários — as duplicatas que já existem foram criadas por este bug e podem precisar
de limpeza manual. Avise a usuária de que a importação passa a atualizar em vez de
duplicar.

**P-3 · R-19 (chave de cache por usuário).** No momento do deploy, qualquer status sob a
chave antiga fica órfão e a tela volta a "idle" — sem perda de dado, mas com barra de
progresso sumindo. Deploye quando não houver importação rodando.

**P-4 · R-20 (estado do job no banco).** Dois PRs, nesta ordem, com o (a) já no ar antes
de abrir o (b):
1. **R-20a** — migration cria a tabela; o código passa a escrever no cache **e** no banco.
   A leitura continua no cache. Tabela nova e vazia: zero risco.
2. **R-20b** — a leitura passa para o banco; a escrita no cache é removida.
   Só depois de confirmar, em produção, que a tabela está sendo populada corretamente.

**P-5 · R-21 (settings de produção).** ⚠️ **O item de maior risco operacional do plano.**
`SECRET_KEY` passa a ser obrigatória: se `DJANGO_SECRET_KEY` não estiver no `.env` do
servidor, a aplicação **não sobe** depois do deploy. Passos obrigatórios, nesta ordem:
1. SSH no servidor, `grep DJANGO_SECRET_KEY /var/www/talent_rank_ai/.env` — tem que
   retornar uma chave real, não vazia.
2. Confirmar que o domínio está servindo HTTPS de verdade (os cookies `Secure` dependem
   disso; sem TLS, o login para de funcionar).
3. Só então fazer o merge.
4. Depois do deploy: `systemctl status talent_rank_ai` e um login completo.
Se algo falhar, o rollback é `git revert` + redeploy — mas o serviço fica fora até isso
acontecer. Prefira janela de baixo uso.

**P-6 · R-23 (currículos protegidos).** Três etapas, com intervalo entre elas. Remover o
`location /media/` do Nginx **antes** de migrar os links faz todos os PDFs sumirem da
interface. Mantenha o acesso antigo funcionando até confirmar que a nova rota entrega os
arquivos.

**P-7 · R-25 (índice concorrente).** A migration precisa de `atomic = False`. Se o
`CREATE INDEX CONCURRENTLY` falhar no meio, o Postgres deixa um índice `INVALID` que
precisa ser removido à mão (`DROP INDEX CONCURRENTLY`) antes de nova tentativa —
verifique com `SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE NOT indisvalid;`.

### Regra de execução

> Nenhum item classificado como **REQUER PARADA** existe neste plano. Se, durante a
> execução, você descobrir que um item classificado como transparente na verdade exige
> parada, **pare imediatamente, avise e reclassifique.** Não siga "porque já começou".

---

## 10. Métricas de sucesso

Atualizado em 2026-08-17, no fim das Ondas 0 e 1.

| Métrica | Linha de base | Meta | **Hoje** | |
|---|---:|---:|---:|:--:|
| Cobertura real (sem `omit`) | 25% | ≥ 55% | **72,08%** | ✅ |
| Cobertura de `pdf_extractor` | 6% | ≥ 70% | **88%** | ✅ |
| Cobertura de `llm_extractor` | 20% | ≥ 65% | **89%** | ✅ |
| Linhas em `pdf_extractor.py` | 1.888 | ≤ 600 | **590** | ✅ |
| Linhas em `views.py` | 987 | ≤ 450 | **692** | 🟡 |
| Arquivos > 500 linhas | 6 | ≤ 2 | **4** | 🟡 |
| Cópias do bloco de upsert | 4 | 1 | **1** | ✅ |
| Cópias do cliente Gemini | 7 | 1 | **1** | ✅ |
| Cópias do laço de lotes | 3 | 1 | **1** | ✅ |
| Código morto | 872 linhas | 0 | **0** | ✅ |
| Violações de ruff | 0 | 0 | **0** | ✅ |
| Tempo da suíte | 19s | ≤ 60s | **34s** | ✅ |
| Avisos do `check --deploy` | 6 | ≤ 1 | **6** | ⏳ Onda 4 |
| Queries em `/relatorios/` | ~500 | 2 | **~500** | ⏳ Onda 5 |
| Funções > 50 linhas | 25 | ≤ 10 | — | ⏳ |

**Leitura honesta:** as metas que dependiam das Ondas 0 e 1 estão batidas ou perto.
`views.py` **não encolheu** — e não era para encolher ainda: quem faz isso é a Onda 2
(R-14 a R-17), que move a orquestração para `services/`. `pdf_extractor` fica em 779
linhas até o R-17 tirar dele o que não é PDF. As duas últimas linhas dependem de ondas
que nem começaram.

### Ganho perceptível (o que não cabe em número)

- **Adicionar um campo ao candidato:** hoje 8 edições em 4 blocos duplicados, sem teste.
  Depois: 1 edição, com teste que prova que nada quebrou.
- **Trocar o modelo do Gemini:** hoje 7 edições. Depois: 1.
- **Abrir `pdf_extractor.py`:** hoje 1.888 linhas, metade sem função. Depois: ~600 linhas
  que todas fazem alguma coisa.
- **Confiar no CI:** hoje o badge verde mede 19% do código. Depois, mede o que importa.

---

## 11. Riscos do projeto

| Risco | Probabilidade | Mitigação |
|---|---|---|
| **Regressão silenciosa na importação** — o fluxo mais complexo, hoje com 6% de cobertura | Alta se pular a Onda 0 | R-05/R-06 são pré-requisito **obrigatório** de R-08/R-10. Não negocie isto para ganhar tempo — é exatamente o que o plano existe para evitar. |
| **Projeto parar no meio** — solo, tempo intermitente | Média | Ondas independentes, cada PR implantável sozinho. Parar depois da Onda 1 já entrega a maior parte do valor. Nenhum PR deixa o sistema pela metade. |
| **Refatoração vira reescrita** — "já que estou aqui, melhoro isto também" | Média | Seção 12 lista explicitamente o que não tocar. Se um PR passar de ~400 linhas, quebre. |
| **Mudar o prompt do LLM sem perceber** — R-16 mexe em quem monta a string | Média | R-16 exige teste de igualdade **exata** da string antes e depois. Prompt alterado muda ranking silenciosamente. |
| **Estimativa otimista** | Alta (sempre é) | Os ~15–19 dias são de trabalho focado. Em ritmo de projeto paralelo, considere 6 a 10 semanas de calendário. |
| **App em produção com usuária real durante o projeto** | Certa | Seção 9. Deploys em janela de baixo uso; nunca deployar com importação rodando (até R-20). |
| **Conhecimento concentrado em uma pessoa** | Certa | Este documento é parte da mitigação. Mantenha o registro de execução preenchido — as surpresas encontradas valem mais que o plano original. |
| **Front sem teste automatizado** (R-27/R-28) | Certa | Validação manual roteirizada, tela a tela, listada em cada item. É a razão de R-28 ser 3 PRs e não 1. |

---

## 12. O que NÃO refatorar

| O quê | Por quê |
|---|---|
| **`core/matching.py`** | 167 linhas, domínio puro, 84% de cobertura, 14 testes. É o melhor código do projeto. R-13 só extrai os sinônimos duplicados dele; a lógica de score não se toca. |
| **`core/models.py`** | 162 linhas, 98% de cobertura, modelo de domínio adequado. Só R-26 (query extra no save). Não mexa nos campos: migration em produção é risco sem ganho. |
| **`core/plans.py`** | 100 linhas, 86% de cobertura, contido. O `except Exception` largo em `get_user_plan:43` é feio mas **intencional** — falha de plano nunca deve derrubar a página. |
| **`core/forms.py`, `admin.py`, `signals.py`, `middleware.py`** | Pequenos, 88–100% de cobertura, estáveis, raramente mudam. Custo maior que o benefício. |
| **`core/metrics.py` e `observability.py`** | Recentes, coerentes, resolvem o que se propõem. Os 38% de `observability.py` são de funções triviais. |
| **As 20 migrations** | Nunca reescreva migration aplicada em produção. Squash não vale o risco neste volume. |
| **`SECTION_TITLES` e o parser regex** | Não refatorar — **deletar** (R-03). Não tente "consertar" ou "aproveitar": é código que não roda há tempo suficiente para ninguém sentir falta. |
| **Pré-match no banco (D-10)** | Real, mas prematuro. A solução muda quais candidatos aparecem no resultado — é mudança de produto, não refatoração. Revisite quando o pool passar de ~5.000 candidatos ou o preview passar de 2s. |
| **Threads → Celery** | Está no roadmap e é a solução "certa". Mas é troca de infraestrutura (Redis, worker, supervisor, deploy) para um app com uma usuária. R-18 e R-20 resolvem 90% da dor por 10% do custo. Reavalie quando houver mais usuários simultâneos. |

### Reescrever em vez de refatorar?

**Não.** Nenhuma parte deste sistema justifica reescrita. O código tem problemas
estruturais claros, mas são todos endereçáveis por movimentos mecânicos e reversíveis:
extrair função, mover módulo, deletar o que está morto. O sistema funciona, está em
produção e tem uma usuária dependendo dele. Uma reescrita trocaria problemas conhecidos
e mapeados por problemas desconhecidos — e é exatamente a armadilha que o volume de
código morto encontrado aqui (872 linhas de um parser abandonado por uma abordagem nova)
mostra que já aconteceu uma vez neste projeto, em escala menor.

---

## 13. Checklist de acompanhamento

```
Status: em andamento — **Ondas 0 e 1 EM PRODUÇÃO desde 2026-08-17**
Progresso: 9 itens implantados, aguardando só a verificação manual em produção
           (R-01, R-02, R-03, R-04, R-05, R-06, R-08, R-09, R-10) · 1 item fechado
           sem correção (R-29, decisão de produto) · 35 no backlog
           atualizado em 2026-08-17

           🚀 **Merge `develop` → `main` feito: PR #26, 26 commits, 13 PRs.**
           `main` saiu de `0a8801d` (12/06) para `b6f431c`. CI verde (lint, py3.10,
           py3.12); CD concluído em 46s. O deploy confirmou as duas previsões do
           pré-voo: `No migrations to apply` e `pip install` sem baixar, instalar ou
           desinstalar nada — os pins do R-02 bateram exatamente com o servidor.
           `0 static files copied, 130 unmodified`.

           ✅ As duas pendências que dependiam do dono do projeto foram resolvidas
           antes do merge: `pip freeze` do servidor (R-02) e levantamento das
           duplicatas (R-09).

           ✅ **Verificado em produção em 2026-08-17:** fluxo completo no front — criar
           vaga, importar candidatos e navegar — sem erro.

           ⚠️ **As ondas NÃO estão fechadas.** Foi para produção o que estava pronto:
           R-01 a R-06, R-08, R-09, R-10. Ainda faltam **R-07** (Onda 0) e **R-11, R-12,
           R-13** (Onda 1). O que já subiu é a maior parte do ganho — a duplicação
           estrutural do `pdf_extractor` acabou —, mas as 7 cópias do cliente Gemini
           (D-4) continuam de pé, e é R-07 que destrava elas.

           Duas verificações ficaram parciais, marcadas `[~]` e cobertas por teste
           automatizado: o caso de 2 lotes do R-10 (ZIP com 12+ PDFs) e o caso PREMIUM
           do R-09 (candidato que já existe no pool de outra conta). Nenhuma das duas
           justifica segurar o projeto; ficam como observação na próxima importação
           grande da usuária.
```

### Resultado até aqui

| Métrica | Linha de base | Hoje em `develop` |
|---|---:|---:|
| Testes | 100 | **145** |
| Cobertura real | 25% (reportada como 87,62%) | **41,84%** (real) |
| `pdf_extractor.py` | 2.046 linhas / 848 stmts | **779 linhas / 291 stmts** |
| Código morto | 872 linhas | **0** |
| Cópias do bloco de upsert | 4 (uma divergente) | **1** |
| Cópias do laço de lotes | 3 | **2** (a 3ª bloqueada em T-7) |
| Arquivos > 500 linhas | 6 | **4** |
| Bugs reais corrigidos | — | **1** (R-09) |

> **Fluxo de trabalho acordado:** todo item entra por **PR**, nunca push direto, e a base
> é sempre `develop`. `develop` foi criada a partir de `main` e não dispara deploy — o
> `deploy.yml` filtra `branches: [main]`. O merge `develop` → `main` acontece **só no
> final**, num único PR, porque é ele que aciona o CD em produção.

### ⛔ Itens que exigem parada de produção

**Nenhum.** Todos os 29 itens são implantáveis com o sistema no ar. Onze exigem cuidado
no deploy — o procedimento de cada um está na seção 9 (P-1 a P-7) e referenciado no item.

---

### Onda 0 — Verdade, limpeza e rede de segurança

- [ ] **R-01** · Expor a cobertura real: remover o `omit` do coverage
      risco: baixo · 30min · produção: transparente · PR: ~20 linhas / 3 arquivos
  - [x] Refatoração aplicada
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#14**, CI verde (lint 8s, test 49s), mergeado em `develop`
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [x] Verificado em produção — n/a em runtime (só configuração de cobertura); o CI da
        `main` rodou verde com o `fail_under` novo
  - [x] Commitado — `21eb996` · branch `refat/r-01-cobertura-real`
  - Status: **código pronto** · Notas: executado DEPOIS de R-03, então o `fail_under`
    ficou em **27** (não 24 como planejado) — o delete do código morto subiu a cobertura
    real de 25% para 28,46%. Valor unificado nos três lugares (pyproject, Makefile, ci.yml),
    que divergiam em 50/20/50.

- [ ] **R-02** · Travar versões das dependências
      risco: médio · 1h · produção: **requer cuidado (P-1)** · PR: ~140 linhas / 7 arquivos
  - [x] **`pip freeze` do servidor conferido por SSH — versões fixadas nas de produção**
  - [x] Refatoração aplicada
  - [x] Suíte verde em Python 3.10 **e** 3.12 no CI (matriz)
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#23**, CI verde (lint 8s, py3.10 1m1s, py3.12 1m2s),
        mergeado em `develop`
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [x] Verificado em produção — 2026-08-17, fluxo completo no front (criar vaga,
        importar, navegar) sem erro
  - [x] Commitado — `aa814d3` · branch `refat/r-02-travar-dependencias`
  - Status: **em `develop`** · Notas: o `pip freeze` mostrou produção em **Python 3.10.12
    / Django 5.2.10**, e não no 3.12 que o projeto inteiro declarava — a suíte nunca tinha
    rodado na versão que atende as usuárias. O alinhamento foi para **baixo**: `pyproject`
    e ruff em `py310`, CI vira matriz 3.10 (portão) + 3.12 (prova o upgrade futuro).
    Travadas as 7 diretas **e as 30 transitivas**, não só as diretas como o plano dizia —
    um `pydantic` novo derrubaria o `google-genai` do mesmo jeito. `requirements-dev.txt`
    saiu de `>=` para `==` e o CI passou a lê-lo (antes instalava pytest sem versão e sem
    ruff). `ruff` unificado em 0.15.17 nos três lugares que divergiam, incluindo o
    pre-commit em v0.8.0. Upgrade de produção para 3.12 virou **R-34**.

- [ ] **R-03** · Remover 872 linhas de código morto do pdf_extractor
      risco: baixo · 1h · produção: transparente · PR: −910 linhas / 2 arquivos
  - [x] `grep -rn "parse_candidate_from_pdf" .` confirmado sem call site
  - [x] Refatoração aplicada
  - [x] Suíte completa verde (94 testes)
  - [x] Lint e format verdes — sem import órfão
  - [x] PR aberto e revisado — **#13**, CI verde (lint 9s, test 55s), mergeado em `develop`
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [x] Verificado em produção — 2026-08-17, importação real numa vaga nova funcionou.
        É a prova mais forte do R-03: se alguma das 940 linhas deletadas fosse alcançável,
        a importação era o caminho que quebraria.
  - [x] Commitado — `4403ca8` · branch `refat/r-03-remover-codigo-morto`
  - Status: **código pronto** · Notas: removidas **940 linhas** (872 de corpo de função +
    a constante `SECTION_TITLES` + linhas em branco). `pdf_extractor.py`: 2.046 → 1.106
    linhas; 848 → 426 statements. Imports órfãos removidos: `re`, `unicodedata`,
    `Decimal`, `PdfReader`. **Escopo além do planejado:** o `pypdf` ficou sem nenhum uso
    no projeto (era só do parser deletado) — removido de `requirements.txt` e a menção
    corrigida no README. `test_pdf_extractor.py` foi reescrito em vez de deletado: os 7
    testes de helpers mortos saíram, e ficou 1 teste de fumaça garantindo que os 3
    entrypoints usados por `views.py` continuam existindo.

- [ ] **R-04** · Remover landing.html duplicado e core/tests.py órfão
      risco: baixo · 20min · produção: transparente · PR: −775 linhas / 2 arquivos
  - [x] Confirmado que o Nginx não serve landing.html diretamente
  - [x] Refatoração aplicada
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#15**, CI verde (lint 6s, test 56s)
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [x] Verificado em produção — 2026-08-17, front navegado sem erro
  - [x] Commitado — `958038b` · branch `refat/r-04-arquivos-orfaos`
  - Status: **código pronto** · Notas: `git grep` por "landing" não retornou nenhuma
    referência em `.py`, `.html`, `.conf` ou `.md`; o Nginx só declara `location /static/`
    e `location /media/`. Removidos com `git rm`.

- [ ] **R-05** · Characterization tests: upsert de candidato
      risco: baixo · 1d · produção: transparente · PR: ~250 linhas / 1 arquivo
      pré-requisito: R-03
  - [x] Testes escritos e passando **contra o código atual, sem alterá-lo**
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#17**, CI verde, mergeado em `develop`
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [x] Commitado — `653de97`
  - Status: **em `develop`** · Notas: 24 testes. Cobertura 28,46% → 34,83%,
    `pdf_extractor` 2% → 24%. Fixou 3 quirks que viraram itens novos do backlog:
    R-29 (summary zerado), R-31 (PDF órfão a cada import), R-32 (unchanged some
    da contabilidade).

- [ ] **R-06** · Characterization tests: loop de lotes e progresso
      risco: baixo · 1d · produção: transparente · PR: ~220 linhas / 1 arquivo
      pré-requisito: R-05
  - [x] Testes escritos e passando contra o código atual
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#18**, CI verde, mergeado em `develop`
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [x] Commitado — `1edfc17`
  - Status: **em `develop`** · Notas: 21 testes. Cobertura 34,83% → 37,47%,
    `pdf_extractor` 24% → 34%. Fixou mais 3 quirks: fallback é por lote (aceitável,
    só não era óbvio), callback final mente sobre o progresso (virou R-30) e os dois
    importadores têm contrato final diferente.

- [ ] **R-07** · Characterization tests: cliente LLM, retry e parsing
      risco: baixo · 1d · produção: transparente · PR: ~200 linhas / 1 arquivo
  - [x] Testes escritos e passando contra o código atual, **sem alterá-lo**
  - [x] Confirmado que nenhum teste chama a API do Gemini de verdade — `genai.Client`
        substituído por duplo e `time.sleep` capturado numa lista
  - [x] Suíte completa verde — **195 testes**, cobertura **53,58%**
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#31**, CI verde nos 3 jobs
  - [x] Implantado — **2026-08-17**, PR #35, deploy `8c2130a`
  - [x] Commitado — `e8649dd`
  - Status: **em produção** · Notas: 50 testes em `test_llm_client.py`, divididos em
    `_extract_json` · `_normalize_list` · `_normalize_linkedin_url` · guarda da API key
    (parametrizada nas 7 funções) · retry · contratos · validação de tamanho do lote.
    **Cobertura do `llm_extractor` foi de 20% para 71%**, e a total de 41,83% para
    53,58% — o maior salto de uma tacada só no projeto. Piso do CI subiu 41 → 53 nos
    três lugares. A meta de 55% da seção 10 está a um item de distância.

    Três comportamentos fixados que ninguém tinha visto:
    1. **`_extract_json` procura array ANTES de objeto** — virou **R-35**, é o mais sério.
    2. O laço **dorme depois da 4ª tentativa** também, antes de propagar: com rate
       limit são 30s parados sem nenhuma tentativa pela frente.
    3. Erro que não é rate limit nem 503 **não usa o backoff** — dorme 3s fixos, mas
       ainda assim tenta as 4 vezes.

- [x] **Onda 0 concluída** — 2026-08-17. Suíte verde, cobertura real exposta e subindo
      (25% → 53,58%), código morto eliminado, rede de segurança de 145 testes no lugar.
      R-01 a R-06 já em produção; R-07 em `develop`.

---

### Onda 1 — Eliminar a duplicação estrutural

- [ ] **R-08** · Extrair `_upsert_candidate()` — unificar as 4 cópias
      risco: médio · 1d · produção: transparente · PR: ~430 linhas / 1 arquivo
      pré-requisito: R-05
  - [x] Refatoração aplicada
  - [x] **Testes de R-05 passam SEM nenhuma alteração** — 45/45, incluindo os quirks
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#19**, CI verde, mergeado em `develop`
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [x] Verificado em produção — 2026-08-17, importação real gravou candidato pela
        `_upsert_candidate` nova, sem erro. O par novo/existente não foi isolado, mas os
        24 testes do R-05 cobrem os dois ramos.
  - [x] Commitado — `802929a`
  - Status: **em `develop`** · Notas: o item central do plano, entregue como previsto.
    4 cópias → 1 (`_upsert_candidate`, apoiado por `_candidate_payload` e
    `_find_candidate`). A lista de 11 campos saiu de 8 ocorrências para 1
    (`_TEXT_FIELDS`). `pdf_extractor` 1.102 → 893 linhas; diff +121/−330.
    A divergência do `shared_pool` foi preservada com `shared_pool=False` explícito
    e comentário apontando R-09 — corrigida no PR seguinte.

- [ ] **R-09** · 🐛 [BUGFIX] shared_pool ignorado no fallback individual
      risco: médio · 2h · produção: **requer cuidado (P-2)** · PR: ~10 linhas / 2 arquivos
      pré-requisito: R-08
  - [x] ⚠️ **Duplicatas já existentes levantadas por query antes do deploy** — feito em
        2026-08-17, direto no banco de produção via `manage.py dbshell`. **Resultado: 1
        grupo duplicado, 2 linhas.** Decisão: **não mexer no banco** (justificativa abaixo).
  - [x] Teste de regressão escrito — **falha antes** (`assert 1 == 0`), **passa depois**
  - [x] Correção aplicada
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#20**, CI verde, mergeado em `develop`
  - [ ] Usuária avisada da mudança de comportamento — **stakes baixas depois do
        levantamento**: a única duplicata existente é da conta do dono do projeto, não da
        dela. O aviso vira cortesia ("importar deixa de duplicar"), não contenção de dano.
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [~] Verificado em produção **parcialmente** — 2026-08-17, importação real como PREMIUM
        funcionou, mas **o caso específico (candidato que já existe no pool de outra conta)
        não foi isolado**. Coberto pelo teste de regressão de `test_import_no_ranking.py`,
        que falha antes da correção e passa depois. Sinal prático de que está certo: parar
        de aparecer duplicata nova. A query de `duplicatas-r09.sql` reconfirma quando você
        quiser — hoje o número de referência é **1 grupo**.
  - [x] Commitado — `0b9b94b`
  - Status: **em `develop`, sem pendência de dado** · Notas: correção de 1 linha,
    exatamente como previsto — R-08 preparou o terreno. Novo arquivo
    `test_import_no_ranking.py` (6 testes) cobre a função que não tinha teste nenhum,
    incluindo um teste de equivalência provando que lote e fallback dão o mesmo
    resultado para a mesma entrada.

    **Levantamento das duplicatas (2026-08-17).** O banco de produção tem **1 grupo
    duplicado, 2 linhas** — o mesmo candidato sob duas contas, ambas PREMIUM: a linha
    original (29/01, conta da usuária, sem PDF, 1 vínculo com vaga) e a cópia (27/02,
    conta do dono do projeto, com PDF, 1 vínculo). Bate com a assinatura do R-09: com
    `shared_pool` ligado nos dois lados, a importação de 27/02 deveria ter atualizado a
    linha existente e criou outra. Descartada a hipótese alternativa de sujeira no dado —
    `md5(lower(linkedin_url))` idêntico e `length = length(trim)` nas duas linhas, então
    o `linkedin_url__iexact` teria encontrado. Não dá para provar que a conta era PREMIUM
    *naquela data* (o plano é editado à mão no admin, sem histórico), mas o resto bate.

    **Decisão: não mexer no banco.** Uma duplicata, na conta do dono do projeto e não na
    da usuária, sem resumo escrito à mão em risco (`summary` vazio nas duas). Apagar
    qualquer uma perde dado: a original tem o vínculo com vaga, a cópia tem o PDF, e
    `on_delete=CASCADE` levaria aderência e parecer junto. Script de mesclagem para uma
    linha é mais risco que benefício.

    **Efeito residual conhecido:** `_find_candidate` (`pdf_extractor.py:71-82`) devolve
    `qs.first()` e o `Meta.ordering` do `Candidate` é `["-updated_at", "-created_at"]`.
    Numa reimportação futura desse candidato, a atualização cai na cópia mais recente e a
    outra fica parada. Como PREMIUM enxerga o banco inteiro (`views.py:219`), as duas
    aparecem na listagem. Um candidato entre centenas — aceito conscientemente.

    O `.sql` completo do diagnóstico, com os falsos positivos documentados, está fora do
    git em `Desktop\apps\Talent_Rank\duplicatas-r09.sql`.

- [ ] **R-10** · Extrair o loop de lotes com fallback individual
      risco: médio · 1d · produção: transparente · PR: ~520 linhas / 1 arquivo
      pré-requisito: R-06, R-08
  - [x] Refatoração aplicada
  - [x] Testes de R-05 e R-06 passam sem alteração — 51/51
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#21**, CI verde, mergeado em `develop`
  - [x] Implantado — **2026-08-17**, PR #26, deploy `b6f431c` em 46s
  - [~] Verificado em produção **parcialmente** — 2026-08-17, importação real passou pelo
        `_process_in_batches`. **O caso de 2 lotes (ZIP com 12+ PDFs) não foi exercitado
        em produção**; está coberto pelos 21 testes do R-06. Fica como observação na
        próxima importação grande da usuária.
  - [x] Commitado — `a604872`
  - Status: **em `develop`, parcial** · Notas: `_process_in_batches` com 3 callbacks
    obrigatórios + 3 hooks opcionais de instrumentação; o fluxo de vaga mantém todas as
    métricas, o banco de talentos passa sem elas. Devolve `(resultado, processados)`
    porque os dois fluxos divergem no callback final. `import_candidates_from_folder`
    280 → 134 linhas; `..._no_ranking` 173 → 33.
    **Só 2 dos 3 laços foram convertidos** — ver a correção do plano abaixo.
    Piso de cobertura desceu 42 → 41: não é regressão, o código duplicado removido
    estava coberto e numerador e denominador caíram juntos (1.755 → 1.684 stmts).

- [ ] **R-11** · Extrair `_generate()` — unificar as 7 cópias de client + retry
      risco: médio · 0,5d · produção: transparente · PR: ~235 linhas / 1 arquivo
      pré-requisito: R-07
  - [x] Refatoração aplicada
  - [x] **Testes de R-07 passam SEM nenhuma alteração** — 195/195, incluindo os 3 quirks
  - [x] `grep -c "genai.Client"` retorna **1** (era 7) · `os.getenv("GEMINI_API_KEY")`
        também caiu de 7 para 1
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#32**, CI verde nos 3 jobs
  - [x] Implantado — **2026-08-17**, PR #35, deploy `8c2130a`
  - [ ] Verificado em produção — gerar 1 parecer e importar 1 PDF
  - [x] Commitado — `30193a2`
  - Status: **em produção** · Notas: `llm_extractor.py` 940 → 661 linhas, 358 → 207
    statements, cobertura 71% → **89%**. Diff +74/−241. Os 50 characterization tests do
    R-07 passaram sem tocar em uma linha, que era o critério de sucesso.

    ⚠️ **Uma mudança de comportamento, pequena e proposital:** a guarda da
    `GEMINI_API_KEY` saiu do topo de cada função pública e foi para dentro do
    `_generate()`. Nas duas funções instrumentadas (`extract_candidates_batch_with_llm`
    e `extract_candidate_with_llm`), a `RuntimeError` de chave ausente agora nasce
    **dentro** do `try`, então dispara a métrica de falha e o `log_event` de erro — antes
    escapava antes do bloco e não registrava nada. Só acontece com a chave desconfigurada,
    e registrar essa falha é mais correto que silenciá-la. Fica anotado por honestidade,
    não porque preocupe.

- [ ] **R-12** · Adicionar timeout à chamada do LLM
      risco: baixo · 2h · produção: transparente · PR: ~15 linhas / 2 arquivos
      pré-requisito: R-11
  - [x] Valor de timeout decidido — **180s**, a margem que o próprio item sugeria.
        Timeout curto demais troca um problema raro (thread travada) por um comum
        (importação lenta que falha). Configurável por `LLM_TIMEOUT_SECONDS`.
  - [x] Mudança aplicada + 3 testes de timeout
  - [x] Suíte completa verde — 198 testes, cobertura 53,94%
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#33**, CI verde nos 3 jobs
  - [x] Implantado — **2026-08-17**, PR #35, deploy `8c2130a`
  - [ ] Verificado em produção — importação de lote grande conclui sem estourar
  - [x] Commitado — `7f8e798`
  - Status: **em produção** · Notas: uma edição em vez de sete, exatamente como o R-11
    prometia.

    ⚠️ **Armadilha de unidade, verificada antes de escrever:** `types.HttpOptions.timeout`
    é documentado no SDK como *"Timeout for the request in milliseconds"*. Passar o valor
    em segundos daria **180ms** e derrubaria toda chamada ao LLM em produção. O setting
    fica em segundos (é o que faz sentido para quem configura) e a conversão mora só
    dentro do `_generate()`, travada por
    `test_timeout_is_converted_from_seconds_to_milliseconds`.

    **Ganho honesto:** o pior caso passa de *infinito* para *limitado*, não para *curto*.
    O erro de timeout não casa com RESOURCE_EXHAUSTED nem com 503, então cai no ramo
    genérico e consome as 4 tentativas — ~12min (4 × 180s + sleeps) até desistir. Melhor
    que "para sempre", e o número está em setting para poder ser reduzido. Fazer o timeout
    pular o retry seria mudança de política de retry, ou seja, outro item.

- [ ] **R-13** · Unificar normalização e sinônimos em `domain/normalization.py`
      risco: baixo · 3h · produção: transparente · PR: ~140 linhas / 3 arquivos
  - [x] **Teste de equivalência feito — e as versões DIVERGEM.** `test_normalization.py`
        prova, caso a caso. O dicionário era idêntico (unificado); as normalizações não.
  - [x] Refatoração aplicada — **só a parte segura**
  - [x] Os 14 testes de matching passam sem alteração
  - [x] Suíte completa verde — 213 testes, cobertura 54,11%
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#34**, CI verde nos 3 jobs
  - [x] Implantado — **2026-08-17**, PR #35, deploy `8c2130a`
  - [ ] Verificado em produção — busca booleana + preview de match
  - [x] Commitado — `967c4af`
  - Status: **em produção, escopo reduzido de propósito** · Notas: o item mandava
    confirmar a equivalência antes de unificar e avisava que divergência viraria decisão.
    Divergiram — e são **três** variantes, não duas:

    | Onde | O que faz |
    |---|---|
    | `matching._normalize` | NFKD + lower + **strip**, tolera `None` |
    | `views._normalize_term` | NFKD + lower, **sem strip**, estoura com `None` |
    | `views._build_boolean_search.expand_term` | strip + lower, **sem remover acento** |

    Então o R-13 entregou só a parte de risco zero: `core/domain/` criado (primeiro
    módulo da camada de domínio, sem nenhum import de Django) com o `SYNONYMS` único e o
    `normalize()`, que é o do `matching` movido sem alterar uma linha. As duas pontas
    passam a apontar para **o mesmo objeto** — adicionar um sinônimo vale nos dois lugares
    automaticamente, que era o ganho prometido.

    Unificar as três normalizações é mudança de comportamento (o `strip` muda o resultado
    de filtro com espaço sobrando) e virou **R-36**.

    Achado de brinde, fixado por teste: enquanto todas as chaves de `SYNONYMS` forem
    ASCII, os dois caminhos de lookup chegam ao mesmo lugar. **Uma chave acentuada faria
    os dois consumidores discordarem em silêncio** — mesma classe do bug do R-09.

- [x] **Onda 1 concluída** — 2026-08-17. Duplicação estrutural eliminada: o upsert de
      candidato existe em 1 lugar (era 4), o cliente Gemini em 1 (era 7), o laço de lotes
      em 1 (era 3, com o 3º bloqueado no R-33), o dicionário de sinônimos em 1 (era 2).
      213 testes, cobertura 54,11%. R-08 a R-10 já em produção; R-11, R-12 e R-13 em
      `develop`.

---

### Onda 2 — Camada de serviço

- [ ] **R-14** · Criar `core/services/` e mover a orquestração de importação
      risco: baixo · 0,5d · produção: transparente · PR: ~460 linhas / 4 arquivos
      pré-requisito: R-10
  - [x] Movimentação aplicada — **diff reconhecível como recorte e cola**: −187/+15 em
        `views.py`, e o `import_service.py` é o recorte literal, feito por script
  - [x] Suíte completa verde — 235 testes, sem alteração em nenhum
  - [x] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — importação de ponta a ponta
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: `core/services/` criado com os **12 blocos** de
    orquestração — as 4 funções `_run_*` mais as 4 chaves de cache e os 4 setters de
    status. `views.py` **975 → 837 linhas**.

    A movimentação foi feita por script (recorte de bloco por AST-ish, não transcrição)
    exatamente para o diff ser revisável como recorte e cola. Nenhum corpo de função foi
    reescrito.

    **Uma exceção, documentada:** `_run_parecer_generation` chama
    `_build_job_description`, que ainda mora em `views.py` — import de módulo criaria
    ciclo. Ficou como **import adiado dentro da função**, com comentário apontando o
    R-16, que move essa função para `domain/` e transforma isto em import normal.

    Os testes de `test_views_parecer.py` continuam mockando `core.views._run_parecer_generation`
    e seguem válidos: o nome continua existindo em `views` (agora importado), e a view o
    referencia pelo global do módulo.

- [x] **R-38** · Characterization tests de filtros e paginação (T-6)
      risco: baixo · 0,5d · produção: transparente · PR: ~230 linhas / 1 arquivo
      **Pré-requisito real do R-15**, que faltava. O R-15 declarava depender de
      "R-19 (testes de filtro)", mas o R-19 é o bugfix de chave de cache por usuário —
      **referência quebrada no plano**. O T-6 da seção 6 nunca virou item, e não havia
      teste nenhum tocando em filtro ou querystring.
  - [x] 25 testes escritos e passando contra o código atual, sem alterá-lo
  - [x] Suíte completa verde — 260 testes, cobertura **72,08%**
  - [x] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: cobrem os 9 filtros do banco de talentos (cada um
    parametrizado), combinação, valor em branco, o dict `filters` do template, paginação
    de 10, ordenação, e os filtros da tela da vaga com o comportamento de sessão.

    **`views.py` saiu de 22% para 47%** de cobertura e a total de 62,18% para **72,08%**.
    Piso do CI subiu 62 → 72.

    Dois comportamentos fixados que o R-15 não pode quebrar:
    1. A querystring de paginação **já vem com `&` na frente**, para ser colada depois de
       `?page=N`. Perder isso gera link `?page=2name=Ana`.
    2. Entrar na vaga **sem nenhum parâmetro redireciona** (302) para a última busca
       salva na sessão. É conveniente para a usuária e surpreendente para quem espera
       um GET simples.

    Um teste meu saiu flaky na primeira rodada: `auto_now` empata na resolução do SQLite
    quando as escritas caem no mesmo instante, e o desempate vira `-created_at`. Passava
    sozinho e falhava na suíte cheia. Reescrito com `.update()` e timestamps explícitos;
    confirmado com duas rodadas completas.

- [ ] **R-15** · Extrair o helper de filtros + querystring das views
      risco: baixo · 0,5d · produção: transparente · PR: ~210 linhas / 2 arquivos
      pré-requisito: ~~R-19~~ **R-38** (referência corrigida)
  - [x] Refatoração aplicada
  - [x] **Os 25 testes de filtro do R-38 passam sem alteração** — 260/260
  - [x] Suíte completa verde
  - [x] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — 3 filtros + paginação preservando os filtros
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: `core/filters.py` com `collect_filters(request,
    params) -> Filters`. As duas views passam a **declarar só os campos**; a mecânica de
    ler, aparar, montar o dict do template e remontar a querystring mora num lugar só.

    `views.py` **837 → 746 linhas** (−144/+54). Os 9 `if` do banco de talentos e os 6 da
    tela da vaga viraram laços sobre dicionários de especificação, onde a **ordem da
    declaração é a ordem na URL** — está comentado no código, porque reordenar muda o
    link que a usuária compartilha.

    **Achado no caminho:** o `filter_keys` da tela da vaga era um `set` literal, então a
    ordem dos parâmetros na URL do *redirect* de filtro salvo variava entre reinícios do
    servidor (hash randomization do Python). Virou tupla ordenada — a URL passa a ser
    estável. Cosmético, mas era não-determinismo de verdade.

    Piso do CI **72 → 71**: a cobertura caiu de 72,08% para 71,41% porque removi 90
    linhas de `views.py` que estavam cobertas. Mesmo efeito do R-10 e do R-37; nenhum
    teste foi perdido.

- [ ] **R-16** · Mover construção de prompt e busca booleana para `domain/`
      risco: médio · 0,5d · produção: transparente · PR: ~240 linhas / 4 arquivos
      pré-requisito: R-13, R-14
  - [x] **Teste de igualdade EXATA da string do prompt (antes vs depois)** — as strings
        foram capturadas rodando a implementação antiga e coladas literalmente em
        `test_job_prompts.py`. 12 testes golden.
  - [x] Movimentação aplicada
  - [x] Suíte completa verde — 272 testes, cobertura 72,58%
  - [x] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — busca booleana gera a mesma string de antes
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: `domain/job_description.py` e
    `domain/boolean_search.py` criados. `views.py` **746 → 692 linhas**.

    As funções puras recebem **campos**, não o objeto `Job` — é o que mantém o `domain/`
    sem Django. Cada uma ganhou um atalho `*_from(job)` que só **lê atributos**: não
    importa o ORM, funciona com um `SimpleNamespace`, e evita repetir a lista de campos
    em cada chamador. Os 12 testes golden rodam **sem banco e sem HTTP, em 0,06s** —
    antes, testar isso exigia subir uma request.

    **O remendo do R-14 foi desfeito:** `import_service` importava
    `views._build_job_description` de forma adiada para não criar ciclo. Agora importa
    `domain.job_description` normalmente.

    Um teste do R-13 precisou mudar de alvo: ele afirmava que `views.SYNONYMS` e o
    domínio eram o mesmo objeto, mas o `views.py` não consome mais o dicionário — quem
    consome é `domain.boolean_search`. A afirmação (`is`, não `==`) continua idêntica;
    só o consumidor mudou de lugar. Piso do CI 71 → 72.

- [ ] **R-17** · Renomear `pdf_extractor.py` conforme a responsabilidade real
      risco: baixo · 3h · produção: transparente · PR: ~80 linhas + git mv / 5 arquivos
      pré-requisito: R-14
  - [ ] Movimentação aplicada
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes — nenhum import quebrado
  - [ ] README atualizado (cita `pdf_extractor` nas linhas 53 e 64)
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — importação de ponta a ponta
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **Onda 2 concluída** — views.py ≤ 450 linhas, camadas separadas, suíte verde

---

### Onda 3 — Confiabilidade dos jobs em background

- [ ] **R-18** · Fechar conexões de banco nas threads
      risco: baixo · 3h · produção: transparente · PR: ~20 linhas / 1 arquivo
      pré-requisito: R-14
  - [ ] Correção aplicada + teste
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — `pg_stat_activity` volta ao patamar após importação
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-19** · 🐛 [BUGFIX] Chave de cache de importação do pool por usuário
      risco: baixo · 3h · produção: **requer cuidado (P-3)** · PR: ~30 linhas / 3 arquivos
      pré-requisito: R-14
  - [ ] Confirmado que não há importação rodando no momento do deploy
  - [ ] Teste de regressão com 2 usuários — falha antes, passa depois
  - [ ] Correção aplicada
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — 2 contas importando, cada uma vê seu progresso
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-20a** · Estado do job no banco — modelo + escrita dupla
      risco: médio · 0,75d · produção: **requer cuidado (P-4)** · PR: ~120 linhas / 3 arquivos
      pré-requisito: R-18, R-19
  - [ ] Migration criada (tabela nova, vazia — ninguém lê ainda)
  - [ ] Escrita dupla (cache + banco) aplicada
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado — migration antes do código
  - [ ] Verificado em produção — tabela sendo populada em uma importação real
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-20b** · Estado do job no banco — leitura do banco e remoção do cache
      risco: médio · 0,75d · produção: **requer cuidado (P-4)** · PR: ~80 linhas / 3 arquivos
      pré-requisito: **R-20a implantado e confirmado populando em produção**
  - [ ] R-20a confirmado no ar e escrevendo corretamente
  - [ ] Leitura migrada para o banco; escrita no cache removida
  - [ ] Teste que simula morte da thread → UI mostra "interrompido"
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — restart no meio da importação mostra "interrompido"
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **Onda 3 concluída** — jobs não vazam conexão nem falham em silêncio

---

### Onda 4 — Segurança e configuração de produção

- [ ] **R-21** · Endurecer settings de produção
      risco: **alto se o `.env` do servidor estiver incompleto** · 3h
      produção: **requer cuidado (P-5)** · PR: ~40 linhas / 2 arquivos
  - [ ] **`grep DJANGO_SECRET_KEY` no `.env` do servidor retorna chave real**
  - [ ] **HTTPS confirmado funcionando no domínio** (cookies Secure dependem disso)
  - [ ] Janela de baixo uso escolhida
  - [ ] Mudança aplicada
  - [ ] `manage.py check --deploy` sai de 6 avisos para ≤1
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — `systemctl status` OK + login completo + cookies Secure
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-22** · Proteger o endpoint `/metrics`
      risco: baixo · 2h · produção: requer cuidado · PR: ~30 linhas / 2 arquivos
  - [ ] Verificado se existe algum scraper consumindo /metrics hoje
  - [ ] Mudança aplicada (aceita com e sem token)
  - [ ] Scraper reconfigurado, se houver
  - [ ] Acesso sem token removido
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — `curl` sem token = 401, com token = 200
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-23** · Servir currículos em PDF por view autenticada
      risco: médio · 0,5d · produção: **requer cuidado (P-6)** · PR: ~70 linhas / 3 arquivos
  - [ ] Etapa 1: view + `location` interno no Nginx, `/media/` ainda público
  - [ ] Etapa 2: links da aplicação apontando para a nova rota
  - [ ] Etapa 2 confirmada funcionando em produção
  - [ ] Etapa 3: `location /media/` público removido do Nginx
  - [ ] Suíte completa verde (403 para PDF de outro usuário, 200 para o próprio)
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — download logado OK; URL `/media/` direta = 404
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **Onda 4 concluída** — `check --deploy` limpo, currículos e métricas protegidos

---

### Onda 5 — Performance

- [ ] **R-24** · `reports`: trocar ~500 queries por 2 agregações
      risco: baixo · 0,5d · produção: transparente · PR: ~100 linhas / 2 arquivos
  - [ ] Teste que fixa a saída atual do contexto escrito primeiro
  - [ ] Refatoração aplicada
  - [ ] `assertNumQueries` provando a redução
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — `/relatorios/` com os mesmos números de antes
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-25** · Índice funcional para `linkedin_url__iexact`
      risco: baixo · 2h · produção: **requer cuidado (P-7)** · PR: ~25 linhas / 1 arquivo
  - [ ] Migration com `atomic = False` e `AddIndexConcurrently`
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — `SELECT ... FROM pg_index WHERE NOT indisvalid;` vazio
  - [ ] Verificado em produção — `EXPLAIN` da query de upsert usando Index Scan
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-26** · `CandidateJob.save()`: evitar a query extra
      risco: baixo · 3h · produção: transparente · PR: ~35 linhas / 2 arquivos
  - [ ] Refatoração aplicada
  - [ ] Os 13 testes de `test_models.py` passam sem alteração
  - [ ] `assertNumQueries` provando 1 query a menos
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — status "Candidato pronto" preenche a data
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **Onda 5 concluída** — relatórios em 2 queries, upsert indexado

---

### Onda 6 — Frontend

- [ ] **R-27** · Extrair o JavaScript de `job_detail.html`
      risco: médio · 0,5d · produção: requer cuidado · PR: ~1.680 linhas / 2 arquivos
  - [ ] Movimentação aplicada; dados dinâmicos via `data-*`
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] **Validação manual completa:** importar · filtrar · paginar · mudar status ·
        gerar parecer · gerar busca booleana · preview de match
  - [ ] PR aberto e revisado
  - [ ] Implantado (com `collectstatic`)
  - [ ] Verificado em produção — console sem erro, `job_detail.js` retornando 200
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-28** · Consolidar o CSS repetido em `static/css/app.css` (3 sub-PRs)
      risco: médio · 1d · produção: requer cuidado · PR: ~250 linhas cada
      pré-requisito: R-27
  - [ ] Sub-PR a — telas de autenticação (login, cadastro) · screenshots comparados
  - [ ] Sub-PR b — telas de vagas (jobs, job_create, job_edit, job_detail) · screenshots
  - [ ] Sub-PR c — talentos, relatórios, dashboard, base · screenshots
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PRs abertos e revisados
  - [ ] Implantado
  - [ ] Verificado em produção — cada tela do grupo em desktop e celular
  - [ ] Commitado — `<hash>` `<hash>` `<hash>`
  - Status: não iniciado · Notas:

- [ ] **Onda 6 concluída** — JS e CSS fora dos templates, sem mudança visual

---

### Onda 7 — achados da execução

- [x] ⚪ **R-29** · Reimportar candidato apaga o resumo escrito à mão — **FECHADO SEM
      CORREÇÃO, por decisão de produto (2026-08-17)**
      risco: baixo · 2h se for reaberto · produção: transparente
  - [x] **Decisão de produto tomada** — escolhido **manter o comportamento atual**:
        reimportar continua sobrescrevendo o resumo escrito à mão.
        ⚠️ Decidido pelo **dono do projeto**, não pela usuária que opera o sistema.
  - Status: **fechado (won't fix)** · Notas: não é bug de código, é escolha de produto —
    o comportamento passa a ser intencional e documentado, em vez de acidental e
    desconhecido. Os characterization tests do R-05 já fixam esse comportamento, então
    ele não muda sozinho numa refatoração futura.

    **Gatilho para reabrir:** se a usuária relatar ter perdido um resumo escrito à mão.
    Aí volta como os mesmos ~2h de trabalho, e a opção mais provável é "preencher só se
    vazio" — preserva o texto manual sem impedir que a importação enriqueça candidato
    novo. No levantamento de duplicatas de 2026-08-17 o campo `summary` estava vazio nas
    duas linhas verificadas, o que sugere que o recurso ainda é pouco usado — parte de
    por que o custo de manter como está é baixo hoje.

- [ ] **R-30** · Unificar o payload final do callback de importação
      risco: baixo · 30min · produção: transparente · PR: ~50 linhas / 2 arquivos
      ⚠️ **diagnóstico original refutado** — ver a entrada na seção 7
  - [x] Correção aplicada + 3 characterization tests invertidos
  - [x] Vermelho antes / verde depois provado — os 3 testes de `final_call` falham
        com `KeyError: 'result'` no código anterior
  - [x] Suíte completa verde — 145 testes, cobertura 41,84% (inalterada)
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#29**, CI verde nos 3 jobs
  - [x] Implantado — **2026-08-17**, PR #35, deploy `8c2130a`
  - [x] Verificado em produção — **n/a**: o payload é sobrescrito por `views.py:557`
        de qualquer forma. Não há efeito observável, e isso é o próprio achado.
  - [x] Commitado — `de94f08`
  - Status: **CONCLUÍDO** · Notas: investigado antes de escrever código e a premissa
    caiu — não existe barra de progresso, o callback final é sempre sobrescrito, e
    `processed` já era o número certo (conta tentativa, não sucesso). Sobrou unificar o
    contrato: o fluxo de vaga passa a mandar `result` como o `..._no_ranking` já fazia,
    fechando uma janela de corrida em que um poll via `completed` sem `result` e a tela
    mostrava tudo zerado. Estimativa corrigida de 2h para 30min.

- [ ] **R-31** · PDFs órfãos acumulam no disco a cada reimportação
      risco: médio · 3h · produção: requer cuidado · PR: ~30 linhas / 2 arquivos
  - [ ] Confirmado o tamanho atual de `media/resumes/` no servidor
  - [ ] Etapa 1: parar de gerar novos órfãos
  - [ ] Etapa 2 (separada): limpar os já existentes, após conferência manual
  - [ ] Suíte completa verde
  - [ ] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — `du -sh media/resumes/` estável entre importações
  - [ ] Commitado — `<hash>`
  - Status: não iniciado · Notas:

- [ ] **R-32** · Candidato sem alteração some da contabilidade
      risco: baixo · 3h · produção: transparente · PR: ~40 linhas / 3 arquivos
      pré-requisito: R-30
  - [x] Correção aplicada + teste invertido
  - [x] Template atualizado para exibir `unchanged` — **4 pontos**, não 1:
        `job_detail.html` e `talent_pool.html`, cada um no bloco Django e no JS do poll
  - [x] Vermelho antes / verde depois provado
  - [x] Suíte completa verde — 145 testes, cobertura 41,83%
  - [x] Lint e format verdes
  - [x] PR aberto e revisado — **#30**, CI verde nos 3 jobs
  - [x] Implantado — **2026-08-17**, PR #35, deploy `8c2130a`
  - [ ] Verificado em produção — reimportar lote idêntico e conferir o resumo
  - [x] Commitado — `547970b`
  - Status: **em produção** · Notas: `unchanged` entra no `result` e a conta passa a
    fechar — o teste afirma `created + updated + unchanged + skipped + errors == total`,
    que é a garantia de verdade, mais forte que conferir cada contador. Como os dois
    importadores usam o `_process_in_batches`, os dois ganharam de uma vez. Nos templates
    usei `|default:0` e `|| 0` porque o cache de status tem TTL de 1h: um payload gravado
    antes do deploy não tem a chave, e sem o default a tela renderizaria vazio na primeira
    hora. Esforço real bem abaixo das 3h estimadas.

- [ ] **R-33** · Characterization tests de `search_and_rank_candidates_from_pool` (T-7)
      risco: baixo · 1d · produção: transparente · PR: ~220 linhas / 1 arquivo
      **destrava a conversão do 3º laço, que ficou fora do R-10**
  - [x] Testes escritos e passando contra o código atual, **sem alterá-lo**
  - [x] Suíte completa verde — **235 testes**, cobertura **62,30%**
  - [x] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: 19 testes em `test_search_pool.py`, cobrindo
    seleção (vinculado é pulado, `user_id` vs `shared_pool`, `candidate_ids`), caso
    vazio, separação com-PDF / sem-PDF, persistência do `CandidateJob`, fallback
    individual e progresso.

    **`pdf_extractor.py` saiu de 57% para 88%** de cobertura e a total de 55,94% para
    **62,30%**. Piso do CI subiu 55 → 62.

    Comportamento fixado que vale conhecer: **o registro do PDF no banco não basta, o
    arquivo tem que existir em disco.** Um `media/` limpo sem limpar o banco não quebra
    a busca — o candidato só passa a ser avaliado pelos dados estruturados, em silêncio.

    **Destrava a conversão do 3º laço** para `_process_in_batches`, que ficou de fora do
    R-10 exatamente por não ter rede.

- [ ] **R-37** · Converter o 3º laço de lotes para `_process_in_batches`
      risco: médio · 0,5d · produção: transparente · PR: ~300 linhas / 1 arquivo
      pré-requisito: **R-33** (era ele que faltava desde o R-10)
      Fecha a pendência aberta no R-10, que converteu 2 dos 3 laços.
  - [x] `_process_in_batches` generalizado — `is_incomplete` e `persist_error_label`
        viraram parâmetros, com o default preservando o comportamento da importação
  - [x] `search_and_rank_candidates_from_pool` convertida
  - [x] **Os 19 testes do R-33 passam SEM nenhuma alteração** — 235/235
  - [x] Suíte completa verde · Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — buscar candidatos do banco numa vaga, com e sem PDF
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: `for batch_start in range` cai de **3 para 1** —
    D-3 do diagnóstico fechado por completo. `pdf_extractor.py` 779 → **590 linhas**
    (295 → 254 statements), cobertura do arquivo 88% → **91%**.

    O `_process_in_batches` precisou de **2 parâmetros novos, não 3**: o `is_incomplete`
    era fixo em `name`/`linkedin_url` e dicionário de aderência não tem nenhum dos dois
    (tudo viraria "pulado"), e o prefixo da mensagem de erro difere entre os fluxos
    ("Erro ao salvar" vs "Erro ao vincular"). O terceiro delta — o sufixo `(erro)` na
    mensagem de progresso — foi **eliminado em vez de parametrizado**: agora os dois
    fluxos marcam a falha ao vivo, o que o fluxo de vaga não fazia.

    Extraído `_resume_path()`, que concentra a regra "o registro no banco não basta, o
    arquivo tem que existir" — antes escrita 3 vezes com try/except ligeiramente
    diferentes.

    A cobertura total caiu 62,30% → 62,18%: mesmo efeito do R-10, o código duplicado
    removido estava coberto. Em absoluto há menos código sem teste.

- [ ] **R-36** · Unificar as três normalizações de termo
      risco: **médio — muda resultado de busca** · 3h · produção: transparente
      **Achado no R-13**, que só unificou o dicionário. O plano supunha que as
      normalizações eram equivalentes; `test_normalization.py` prova que não:

      | Onde | O que faz |
      |---|---|
      | `domain.normalization.normalize` | NFKD + lower + **strip**, tolera `None` |
      | `views._normalize_term` | NFKD + lower, **sem strip**, estoura com `None` |
      | `views._build_boolean_search.expand_term` | strip + lower, **sem acento** |

      **A decisão de produto:** hoje, filtrar por `" python "` com espaço sobrando
      procura literalmente `" python "` no campo. Unificar em `normalize()` faz o
      espaço ser aparado — quase certamente o que a usuária espera, mas é mudança de
      resultado de busca, então merece PR próprio e marcado.
  - [x] Decidido: **o `strip` passa a valer no filtro**. Espaço sobrando numa caixa de
        busca é digitação, não intenção — hoje `" python "` não achava nada.
  - [x] `views._normalize_term` **deletada**; `expand_term` passa a usar `normalize()`
  - [x] Testes de divergência de `test_normalization.py` invertidos — a classe
        `TestTheThreeNormalizersDiverge` virou `TestTheThreeNormalizersAreNowOne`
  - [x] Suíte completa verde — 216 testes, cobertura **55,94%**
  - [x] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Verificado em produção — filtrar com espaço sobrando encontra o candidato
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: três normalizações viram uma. `unicodedata` sai do
    `views.py` (ficou órfão). Um dos testes garante que `views._normalize_term` **não
    existe mais**, para ninguém reintroduzir por hábito.

    ⚠️ **Muda comportamento em dois pontos, ambos para melhor:** o filtro das listagens
    passa a aparar as pontas do termo, e a busca booleana passa a expandir sinônimo de
    termo acentuado. Bugfix em PR separado, como manda a regra do projeto.

    **Com este item, a meta de cobertura de 55% da seção 10 foi batida: 55,94%.**
    Piso do CI subiu 53 → 55 nos três lugares.

- [ ] 🐛 **R-35** · `_extract_json` devolve o array interno em vez do objeto
      risco: baixo · 2h · produção: transparente · PR: ~15 linhas / 2 arquivos
      **Achado no R-07.** `llm_extractor.py:198-216`: quando o `json.loads` do texto
      inteiro falha, a função procura **array antes de objeto**. Se a resposta vier
      embrulhada em ``` e o objeto tiver um array interno — e todo candidato tem
      `skills` —, o slice do array vence e o candidato inteiro vira a lista de skills.
      Hoje não dispara porque o prompt pede "apenas JSON válido (sem markdown)" e o
      `json.loads` resolve na primeira tentativa. É uma bomba armada, não um incêndio:
      basta o modelo embrulhar a resposta uma vez. Fixado por
      `test_array_is_tried_before_object`.
      Correção provável: procurar objeto e array e escolher o que começa antes no
      texto, em vez de fixar a ordem.
  - [x] Correção aplicada + teste invertido
  - [x] Conferido que o caso do array puro (lote) continua funcionando — a resposta em
        lote é um array de objetos, então o `[` vem antes do primeiro `{` e o array
        continua ganhando. Coberto por `test_whichever_structure_starts_first_wins`.
  - [x] Vermelho antes / verde depois provado
  - [x] Suíte completa verde — 215 testes, cobertura 54,28%
  - [x] Lint e format verdes
  - [ ] PR aberto e revisado
  - [ ] Implantado
  - [ ] Commitado — `<hash>`
  - Status: **em andamento** · Notas: a ordem fixa (array sempre antes de objeto) virou
    **"vence quem começa antes no texto"**, com fallback para a outra estrutura se o
    primeiro recorte não for JSON válido. O `raise` continua propagando o erro original
    do texto inteiro quando não há nada recortável, como antes.

    ⚠️ **Muda comportamento** — é bugfix, em PR separado, exatamente como R-09 e R-30.
    O caso que mudou: `{"skills": [...]}` embrulhado em markdown devolvia `[...]` e
    agora devolve o objeto.

- [ ] ⏳ **R-34** · Subir produção de Python 3.10 para 3.12 — **prazo: outubro/2026**
      risco: **alto (mexe no servidor)** · 0,5d + janela · produção: requer parada curta
      pré-requisito: R-02 (a matriz do CI já prova que a suíte passa em 3.12)
      **Achado na execução do R-02.** O suporte do Python 3.10 acaba em outubro/2026;
      o Ubuntu do Lightsail não traz 3.12 no apt padrão. Não é refatoração — é
      manutenção de infra com data marcada. Vale projeto próprio, não item de PR.
  - [ ] Confirmado como instalar 3.12 no servidor (deadsnakes PPA ou upgrade do Ubuntu)
  - [ ] Venv novo criado em paralelo, sem tocar no que está no ar
  - [ ] `pip install -r requirements.txt` no venv novo, sem erro
  - [ ] Suíte rodada **no servidor**, no venv novo
  - [ ] Janela de baixo uso combinada com a usuária
  - [ ] `ExecStart` do systemd apontado para o venv novo + restart
  - [ ] Verificado em produção — home, dashboard, login e uma importação real
  - [ ] Venv antigo removido só depois de 1 semana estável
  - [ ] `pyproject`, ruff e CI subidos de volta para 3.12; matriz simplificada
  - Status: não iniciado · Notas:

- [ ] **Onda 7 concluída** — quirks resolvidos, `pdf_extractor` coberto de ponta a ponta

---

### Registro de execução

| Data | Item | O que mudou de fato | Surpresas encontradas |
|---|---|---|---|
| 2026-08-15 | **R-03** | 940 linhas removidas de `pdf_extractor.py` (2.046 → 1.106). Imports `re`, `unicodedata`, `Decimal`, `PdfReader` removidos. `test_pdf_extractor.py` reescrito (7 testes de helpers mortos → 1 teste de fumaça da API pública). | O `pypdf` virou dependência morta — era usado só pelo parser deletado. Removido de `requirements.txt` e a menção corrigida no README (escopo além do planejado, mas consequência direta do delete). |
| 2026-08-15 | **R-01** | `omit` de `views.py`/`urls.py`/`llm_extractor.py`/`pdf_extractor.py` removido do `pyproject.toml`. `fail_under` unificado em **27** nos três lugares (pyproject 50, Makefile 20, ci.yml 50 → todos 27). | Duas. (1) Rodado depois de R-03, a cobertura real já era 28,46% e não 25% — o delete tirou 415 statements não cobertos do denominador; `fail_under` ficou em 27, não nos 24 planejados. (2) **R-01 não é independente de R-03**, ao contrário do que a seção 8 dizia: sozinho na `main` ele reprova o CI. Virou PR empilhado; sequenciamento corrigido. |
| 2026-08-15 | **R-04** | `landing.html` (828 l) e `core/tests.py` removidos com `git rm`. PR #15. | Nenhuma. `git grep` confirmou zero referências. |
| 2026-08-15 | **R-05** | 24 characterization tests do upsert (`test_import_upsert.py`). Piso 27 → 34. Cobertura 28,46% → 34,83%. PR #17, `653de97`. | O teste do caminho sem `user_id` precisou de `django_db(transaction=True)`: o `IntegrityError` envenena o bloco atomic que o pytest abre em volta do teste, o que não acontece em produção (thread própria, autocommit). Fixou 3 quirks → R-29, R-31, R-32. |
| 2026-08-15 | **R-06** | 21 tests do laço de lotes e fallback (`test_import_batches.py`). Piso 34 → 37. Cobertura 34,83% → 37,47%. PR #18, `1edfc17`. | Fixou mais 3 quirks. O do callback final virou R-30. |
| 2026-08-15 | **R-08** | `_upsert_candidate` + `_candidate_payload` + `_find_candidate`. 4 cópias → 1; lista de campos de 8 ocorrências → 1. `pdf_extractor` 1.102 → 893 linhas. PR #19, `802929a`. | Nenhuma surpresa: **os 45 testes passaram sem uma única alteração**, que era exatamente o critério de sucesso. A separação R-08/R-09 se pagou. |
| 2026-08-15 | **R-09** | `shared_pool` repassado no fallback (1 linha). Novo `test_import_no_ranking.py` (6 testes). Cobertura 38,92% → 42,12%. PR #20, `0b9b94b`. | O teste falhou antes (`assert 1 == 0`) e passou depois, como planejado. **Pendências abertas:** levantar duplicatas já criadas pelo bug e avisar a usuária. |
| 2026-08-15 | **R-10** | `_process_in_batches` com 3 callbacks + 3 hooks opcionais. `import_candidates_from_folder` 280 → 134 linhas; `..._no_ranking` 173 → 33. PR #21, `a604872`. | Duas. (1) **Só 2 dos 3 laços convertidos** — o de `search_and_rank` não tem teste; virou R-33. (2) A cobertura **caiu** 42,12% → 41,84% e o piso desceu para 41: o código duplicado removido estava coberto, então numerador e denominador caíram juntos. Não é regressão, mas engana quem olhar só o número. |
| 2026-08-17 | **R-02** | 7 diretas + 30 transitivas fixadas em `==` nas versões do servidor. `requirements-dev.txt` de `>=` para `==`; o CI passou a instalar dele. `pyproject` `requires-python` e ruff `target-version` de 3.12 para **3.10**. `ci.yml` virou matriz 3.10 + 3.12. `ruff` unificado em 0.15.17 (CI, dev e pre-commit, que estava em v0.8.0). README e DEPLOY_AWS corrigidos. PR #23, `aa814d3`. | Três. (1) **Produção roda Python 3.10.12, não 3.12** — o projeto inteiro (pyproject, ruff, CI, README) declarava 3.12+ e a suíte nunca tinha rodado na versão que atende as usuárias. O alinhamento teve que ser para baixo, e o plano dizia o contrário. (2) **Armadilha ativa:** ruff com `target-version = py312`, regra `UP` ligada e `make format` rodando `ruff check --fix .` podiam reescrever o código em sintaxe 3.12, passar no CI em 3.12 e quebrar em produção no 3.10. (3) Travar só as diretas, como o plano pedia, deixaria ~30 transitivas flutuando — um `pydantic` novo derruba o `google-genai` igual. Fixei tudo. Bônus: o Django 6.0.6 do venv local nunca poderia rodar em produção (Django 6.0 exige 3.12+). Fim do suporte do 3.10 em outubro/2026 virou **R-34**. |
| 2026-08-17 | **R-09** (pendência) / **R-29** | Levantamento das duplicatas rodado no banco de produção via `manage.py dbshell`: **1 grupo, 2 linhas**. Confirmada a assinatura do R-09 e descartada a hipótese de sujeira no dado. Decisão: não mexer no banco. R-29 fechado sem correção — mantém o comportamento atual de sobrescrever o resumo. | Três. (1) O query que estava na descrição do PR #20 **superestimava o problema**: agrupava por `linkedin_url` entre todos os usuários, e duas recrutadoras terem o mesmo perfil é normal. Reescrito para a assinatura real (linha PREMIUM criada depois de outra). (2) A duplicata é da conta do dono do projeto, não da usuária — provável resíduo de teste, não trabalho perdido dela. (3) Achado no caminho: `_find_candidate` devolve `qs.first()` sobre `ordering = ["-updated_at", ...]`, então com duplicata pré-existente a reimportação atualiza a cópia mais recente e deixa a outra parada. O R-09 impede duplicata nova, não resolve as velhas. |
| 2026-08-17 | **R-01 a R-10 → produção** | Merge `develop` → `main` (PR #26): 26 commits, 13 PRs, `0a8801d` → `b6f431c`. CI verde nas duas versões da matriz; CD concluído em 46s. Superfície real: **1 arquivo de aplicação alterado** (`pdf_extractor.py`), `views.py` intocado, **zero migrations**, nenhum template alterado. | Duas confirmações e nenhuma surpresa. (1) `pip install` no deploy **não baixou, instalou nem desinstalou nada** — os pins do R-02, colhidos do próprio servidor horas antes, bateram exatamente. O item se validou no primeiro deploy. (2) `No migrations to apply` e `0 static files copied, 130 unmodified`, como o pré-voo previa. O `pypdf` segue instalado no servidor (o `pip install` não desinstala) e sem uso — inofensivo, não deve voltar ao `requirements.txt`. |
| 2026-08-17 | **Verificação em produção** | Fluxo completo exercitado no front pelo dono do projeto: criar vaga, importar candidatos, navegar. Sem erro. 9 itens fechados de ponta a ponta (R-01 a R-06, R-08, R-09, R-10). | Duas verificações ficaram parciais e foram marcadas `[~]` em vez de `[x]`: o caso de 2 lotes do R-10 (exige ZIP com 12+ PDFs) e o caso PREMIUM do R-09 (exige candidato que já exista no pool de outra conta). Ambas cobertas por teste automatizado — 21 testes do R-06 e o teste de regressão do R-09 —, mas registrar como "verificado" seria falsear o registro. Ficam como observação na próxima importação grande da usuária. |
| 2026-08-17 | **R-30** | Callback final do fluxo de vaga passa a mandar `total`, `processed` e `result`, igual ao `..._no_ranking`. 3 characterization tests do R-06 invertidos. PR #29. | **O diagnóstico do item estava errado e foi refutado antes de escrever código.** Três motivos independentes: (1) não existe barra de progresso — `job_detail.html:711-723` renderiza o ramo `completed` a partir do `result`, sem usar `processed`/`total`; (2) o callback final é sempre sobrescrito por `views.py:557` microssegundos depois, então não sobrevive a um poll de 2s; (3) `processed` nunca esteve errado — `_process_in_batches` incrementa em todos os caminhos, inclusive nos de erro, então `processed == total` sempre. "Processado" significa tentado, não bem-sucedido; o teste do R-06 leu o nome da variável, não a semântica. Sobrou unificar o contrato e fechar uma janela de corrida em que um poll via `completed` sem `result` e a tela mostrava tudo zerado. Estimativa corrigida de 2h para 30min. |
| 2026-08-17 | **R-32** | `unchanged` entra no `result` do `_process_in_batches` e passa a ser exibido. Teste do R-05 invertido, agora exigindo que a soma feche com o total. | Duas. (1) O plano dizia "3 arquivos" e eram **5**: a exibição vive em **4 lugares**, não 1 — `job_detail.html` e `talent_pool.html`, cada um com um bloco Django e um bloco JS de poll que renderizam a mesma frase de formas diferentes. É a duplicação do D-11 cobrando o preço na prática. (2) O cache de status tem TTL de 1h, então na primeira hora após o deploy existem payloads sem a chave nova — resolvido com `\|default:0` no template e `\|\| 0` no JS. |
| 2026-08-17 | **R-07** | 50 characterization tests do cliente LLM em `test_llm_client.py`: `_extract_json`, `_normalize_list`, `_normalize_linkedin_url`, guarda da API key parametrizada nas 7 funções, retry, contratos das 7 públicas e validação de tamanho do lote. Nenhuma linha de aplicação alterada. Piso do CI 41 → 53. | **Maior salto de cobertura do projeto: 41,83% → 53,58%**, com o `llm_extractor` indo de 20% para 71%. A meta de 55% da seção 10 ficou a um item de distância. Três comportamentos fixados que ninguém tinha visto: (1) **`_extract_json` procura array antes de objeto** — resposta embrulhada em ``` com array interno faz o candidato virar a lista de skills dele; virou **R-35** e é o mais sério; (2) o laço **dorme depois da 4ª tentativa** antes de propagar — com rate limit são 30s parados à toa; (3) erro que não é rate limit nem 503 não usa backoff, dorme 3s fixos, mas ainda tenta 4 vezes. |
| 2026-08-17 | **R-11** | `_generate()` criado: as 7 cópias de `api_key` + `genai.Client` + laço de retry viram 1. `llm_extractor.py` 940 → 661 linhas, 358 → 207 stmts, cobertura 71% → 89%. Diff +74/−241. PR #32. | **Os 50 characterization tests do R-07 passaram sem tocar em uma linha** — era o critério de sucesso, e é a prova de que a extração não mudou comportamento. Uma diferença registrada por honestidade: a guarda da `GEMINI_API_KEY` foi para dentro do `_generate()`, então nas duas funções instrumentadas a `RuntimeError` de chave ausente passa a nascer dentro do `try` e a disparar a métrica de falha. Só ocorre com a chave desconfigurada, e registrar é mais correto que silenciar. |
| 2026-08-17 | **R-12** | Timeout de 180s em toda chamada ao LLM, via `settings.LLM_TIMEOUT_SECONDS` e `types.HttpOptions`. 3 testes novos. PR #33. | Duas. (1) **Armadilha de unidade:** `HttpOptions.timeout` é em MILISSEGUNDOS — conferido no pacote instalado antes de escrever a linha. Passar segundos daria 180ms e derrubaria toda chamada ao LLM em produção. O setting fica em segundos e a conversão mora só no `_generate()`, travada por teste. (2) **O ganho é "de infinito para limitado", não "para curto":** o erro de timeout cai no ramo genérico do retry e consome as 4 tentativas, ~12min até desistir. Fixado por teste em vez de escondido; encurtar seria mudar a política de retry, ou seja, outro item. |
| 2026-08-17 | **R-13** | `core/domain/` criado — primeiro módulo da camada de domínio, sem nenhum import de Django. `SYNONYMS` unificado (era 2 cópias) e `normalize()` movido do matching sem alterar uma linha. PR #34. | **O teste de equivalência que o item exigia reprovou a premissa.** O dicionário era idêntico, mas as normalizações não — e são **três** variantes, não duas: `normalize` apara as pontas e tolera `None`; `views._normalize_term` não apara e estoura com `None`; a chave de `expand_term` nem remove acento. Entreguei só a parte de risco zero e a unificação das funções virou **R-36**, porque o `strip` muda resultado de busca. Achado de brinde, fixado por teste: os dois caminhos de lookup só concordam porque **todas as chaves de `SYNONYMS` são ASCII** — uma chave acentuada faria as duas pontas discordarem em silêncio, mesma classe do bug do R-09. |
| 2026-08-17 | **Ondas 0 e 1 → produção** | Segundo release (PR #35): 16 commits, 6 PRs, `b6f431c` → `8c2130a`. CI verde nas duas versões da matriz; CD em 1m21s. `No migrations to apply`, `pip install` no-op de novo, `0 static files copied`. **Ondas 0 e 1 completas em produção.** | Nenhuma surpresa no deploy. Diferente do primeiro release, este mexeu em `views.py` e em 2 templates — o R-32 muda o que a usuária lê na tela. Resultado acumulado do dia: testes 100 → **213**, cobertura real 25% → **54,11%**, `pdf_extractor` 2.046 → 779 linhas, `llm_extractor` 940 → 661, cliente Gemini de 7 cópias para 1, upsert de 4 para 1, laço de lotes de 3 para 1, dicionário de sinônimos de 2 para 1, e 1 bug real corrigido (R-09). Falta a verificação manual dos 4 itens marcados. |
| 2026-08-17 | **R-35** | 🐛 `_extract_json`: a ordem fixa (array antes de objeto) virou "vence quem começa antes no texto", com fallback. PR #37. | O caso corrigido: `{"skills": [...]}` embrulhado em markdown devolvia `[...]` — o candidato virava a lista de skills dele. O caminho de lote segue intacto porque a resposta em lote é um array de objetos, então o `[` vem antes do primeiro `{`. Achado pelos testes do R-07, corrigido no dia seguinte à descoberta. |
| 2026-08-17 | **R-36** | As três normalizações de termo viram uma. `views._normalize_term` deletada, `expand_term` passa a usar `normalize()`, `unicodedata` sai do `views.py`. Piso do CI 53 → 55. PR #38. | **Meta de cobertura de 55% da seção 10 batida: 55,94%.** Muda comportamento em dois pontos, ambos para melhor: o filtro das listagens passa a aparar as pontas (antes, `" python "` com espaço sobrando não achava nada) e a busca booleana passa a expandir sinônimo de termo acentuado. Um teste garante que `views._normalize_term` não existe mais, para ninguém reintroduzir por hábito. |
| 2026-08-17 | **R-33** | 19 characterization tests de `search_and_rank_candidates_from_pool` em `test_search_pool.py` — a última função grande sem teste (309 linhas). Nenhuma linha de aplicação alterada. Piso do CI 55 → 62. | **`pdf_extractor.py` foi de 57% para 88%** e a cobertura total de 55,94% para **62,30%**, ultrapassando a meta da seção 10 com folga. Comportamento fixado que vale conhecer: **o registro do PDF no banco não basta, o arquivo tem que existir em disco** — um `media/` limpo sem limpar o banco não quebra a busca, o candidato só passa a ser avaliado pelos dados estruturados, em silêncio. Destrava a conversão do 3º laço para `_process_in_batches`, que ficou de fora do R-10 por não ter rede. |
| 2026-08-17 | **R-37** | 3º laço convertido para `_process_in_batches`. `for batch_start in range` cai de **3 para 1** — D-3 fechado por completo. `pdf_extractor.py` 779 → **590 linhas**, cobertura do arquivo 88% → **91%**. Extraído `_resume_path()`. | **Os 19 testes do R-33 passaram sem tocar em uma linha** — o item foi escrito ontem justamente para isto. O `_process_in_batches` precisou de **2 parâmetros novos, não 3**: `is_incomplete` (era fixo em `name`/`linkedin_url`, e dicionário de aderência não tem nenhum dos dois — tudo viraria "pulado") e `persist_error_label` ("Erro ao salvar" vs "Erro ao vincular"). O terceiro delta, o sufixo `(erro)` na mensagem de progresso, foi **eliminado em vez de parametrizado**: os dois fluxos passam a marcar a falha ao vivo, o que o fluxo de vaga não fazia. Cobertura total 62,30% → 62,18%, mesmo efeito do R-10 — o duplicado removido estava coberto. |
| 2026-08-17 | **R-14** | `core/services/` criado. Os **12 blocos** de orquestração saem do `views.py`: as 4 funções `_run_*`, as 4 chaves de cache e os 4 setters de status. `views.py` **975 → 837 linhas** (−187/+15). | Movimentação feita por **script**, recortando blocos inteiros em vez de transcrever — é o que garante o diff revisável como recorte e cola, que era o critério do item. Nenhum corpo de função reescrito; 235 testes passando sem alteração. **Uma exceção documentada:** `_run_parecer_generation` chama `_build_job_description`, que ainda mora no `views.py`; import de módulo criaria ciclo, então ficou como **import adiado dentro da função**, com comentário apontando o R-16 — que move essa função para `domain/` e desfaz o remendo. |

---

> **Para as próximas sessões:** ao concluir qualquer item deste plano, atualize este
> arquivo — marque as caixas, preencha o hash do commit, ajuste o contador de progresso
> no topo da seção 13 e anote no registro de execução acima. Se a realidade divergir do
> plano, **corrija o plano** — não o abandone. Uma surpresa registrada vale mais que um
> plano que parecia certo.

---

## 14. Fora do escopo / fora do foco

Escopo e foco são globais nesta rodada, então não há corte por delimitação. O que ficou
de fora ficou por decisão de prioridade, e está justificado na seção 12 (O que NÃO
refatorar) e na seção 2 (Fora).

---

## 15. Limitações

Onde a confiança é menor e o que precisa de decisão sua:

1. ~~**Não tenho acesso ao servidor de produção.** As versões reais de Django, Python e
   pacotes em `/var/www/talent_rank_ai` são desconhecidas~~ — **resolvido em 2026-08-17**:
   o `pip freeze` conferido por SSH mostrou **Python 3.10.12 / Django 5.2.10**, e o R-02
   travou tudo nessas versões. **Continua valendo para o R-21:** ainda não sei se
   `DJANGO_SECRET_KEY` existe no `.env` do servidor, e o R-21 derruba a aplicação se não
   existir. Confira antes (`grep DJANGO_SECRET_KEY /var/www/talent_rank_ai/.env`).

2. **Não sei o volume real de dados.** Quantidade de candidatos, vagas e importações por
   dia muda a prioridade de toda a Onda 5. Classifiquei R-25 como baixo risco assumindo
   uma tabela de porte moderado; em uma tabela muito grande, o `CREATE INDEX CONCURRENTLY`
   demora mais e merece janela.

3. **Decisão de produto pendente:** o plano PREMIUM ativa `Candidate.objects.all()`
   (`views.py:219`), fazendo o usuário ver candidatos de **todos** os outros. Tratei como
   intencional (pool comunitário) e R-09 corrige o bug **preservando** essa intenção. **Se
   não for intencional, é vazamento entre clientes e vira o item mais urgente do plano,
   acima de tudo.** Só você pode responder.

4. **Nunca vi a aplicação rodando.** A validação manual de R-27 e R-28 foi montada lendo o
   template; pode haver interação que não identifiquei. Trate a lista como mínimo, não
   como completa.

5. **Não avaliei acessibilidade, responsividade nem compatibilidade de browser** — fora do
   foco desta rodada, mas relevante se a usuária trabalhar do celular.

6. **A equivalência dos dois dicionários de sinônimos (R-13) foi conferida por leitura**,
   termo a termo, não por execução. O item exige um teste de equivalência antes de
   unificar — não pule esse passo.

7. **As estimativas assumem trabalho focado** e conhecimento prévio do código (é seu
   projeto, então isso vale). Em ritmo de projeto paralelo, multiplique o calendário por
   3 ou 4.

8. **Não há histórico de bugs para cruzar.** Com 27 commits e sem issue tracker, usei
   frequência de mudança como proxy de "onde dói". É um bom proxy, mas commits marcados
   como correção seriam um sinal melhor — se você lembrar de onde os bugs apareceram na
   prática, isso reordena o backlog melhor do que qualquer métrica que eu consiga extrair.

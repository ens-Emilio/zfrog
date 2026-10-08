# Zfrog - Design Reference Engine

<img src="docs/mascot.png" alt="Mascote do zfrog: um sapinho com uma lupa e uma folha em branco" width="140" align="right">

Ferramenta de coleta, organização e adaptação de referências de design da web. Capture
qualquer página, guarde o visual como referência offline e consulte o que foi capturado
depois.

## Funcionalidades

- **4 motores com papéis distintos**: Playwright (captura visual, o padrão), Scrapy
  (descoberta), StaticFile (páginas leves), wget (assets)
- **Auto-detecção**: escolhe o motor conforme a página precisa ou não de JavaScript
- **Captura visual**: screenshot full page de cada página capturada
- **Pipeline completo**: reescrita de links, limpeza de trackers, empacotamento ZIP
- **API REST**: endpoints para jobs, probe, download, health check, metrics
- **Dashboard UI**: interface web para gerenciar jobs
- **Produção**: rate limiting, retry com circuit breaker, cleanup automático, webhooks

## Instalação

```bash
# Clonar repositório
git clone <repo-url>
cd zfrog

# Criar ambiente virtual e instalar dependências
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Instalar navegador do Playwright
.venv/bin/playwright install chromium
```

O repositório traz um launcher `./zfrog` na raiz que usa o virtualenv do projeto, então
**não é preciso ativar o venv** para rodar os comandos:

```bash
./zfrog dev
```

Para usar como `zfrog` (sem o `./`), adicione a raiz do projeto ao `PATH` ou crie um alias:

```bash
# Opção 1: alias no shell (~/.bashrc, ~/.zshrc)
alias zfrog="$PWD/zfrog"

# Opção 2: link simbólico em um diretório que já está no PATH
ln -s "$PWD/zfrog" ~/.local/bin/zfrog
```

Alternativamente, ative o venv e use o comando instalado:

```bash
source .venv/bin/activate
zfrog dev
```

## Uso Rápido

### Tudo junto (API + Dashboard)

```bash
./zfrog dev
```

Sobe a API (`http://127.0.0.1:8000`) e o dashboard (`http://localhost:3000`) com um único
comando. O output de cada serviço vem prefixado (`api` / `web` / `worker`). Ctrl+C para todos;
se um cair, os outros são encerrados automaticamente.

Com o Redis respondendo, um worker Celery sobe junto. Ele não é opcional: a API despacha
para a fila e devolve `pending` na hora, então sem alguém consumindo a fila toda extração
começada no painel fica "na fila" para sempre, sem nada dizendo por quê. Sem Redis, os jobs
rodam no processo da API e não há worker.

```bash
./zfrog dev --api-port 9000 --web-port 4000   # portas customizadas
./zfrog dev --no-reload                       # sem auto-reload da API
./zfrog dev --no-install                      # não roda npm install
```

### CLI

```bash
# Captura automática (padrão): o probe escolhe o motor
zfrog clone https://example.com

# Capturar uma referência de design: screenshot + tokens + card no catálogo
zfrog jump https://stripe.com
zfrog jump https://stripe.com --breakpoint mobile --tag fintech

# Extrair um componente: o HTML e o CSS que o navegador aplicou nele
zfrog tongue https://stripe.com ".hero"

# A coleção: listar, filtrar e buscar por descrição visual
zfrog pond                                   # todas as referências
zfrog pond --tag fintech                     # por etiqueta
zfrog pond --color "#635BFF"                 # por cor
zfrog pond --search "layouts escuros com cards arredondados"
zfrog show 9cc7eb98                          # detalhes de uma referência
zfrog export 9cc7eb98 --format html          # mini style guide

# Clonar site estático
zfrog clone https://example.com --mode singlepage

# Espelhar site recursivamente
zfrog clone https://example.com --mode mirror --depth 2

# Clonar SPA (React/Vue/Next.js)
zfrog clone https://nextjs.org --mode scrape

# Extrair dados estruturados
zfrog clone https://products.com --mode extract --depth 1

# Gerar PDF da página
zfrog clone https://example.com --mode pdf

# Gerar PDF com nome escolhido
zfrog clone https://example.com --mode pdf --pdf-filename relatorio

# Resumir a página com IA
zfrog clone https://example.com --mode summarize

# Analisar URL
zfrog probe https://example.com

# Guardar uma versão do site (histórico com rollback)
zfrog clone https://example.com --mode mirror --versioned
zfrog versions https://example.com
zfrog rollback https://example.com HEAD --dest ./restaurado

# Baixar só o que mudou desde a última cópia
zfrog clone https://example.com --mode delta

# Agendar cópias recorrentes
zfrog schedule add https://example.com --cron "0 2 * * *"
zfrog scheduler                      # daemon que executa os agendamentos

# Procurar dentro do que já foi baixado
zfrog search "política de privacidade" --dir output
zfrog search "preço do produto" --semantic

# Perguntar a vários sites ao mesmo tempo (com citações)
zfrog chat "quanto custa?" --site lojaA=output/lojaA --site lojaB=output/lojaB

# Entrar em um site e guardar a sessão (sites com login)
zfrog login https://site-com-login.com
zfrog sessions

# Sequências de passos salvas
zfrog workflow list
zfrog workflow run <id>

# Listar jobs
zfrog jobs

# Qualidade e conformidade
zfrog safety output/meusite            # sinais de página perigosa
zfrog analytics                        # qual motor funciona melhor
zfrog audit --limit 20                 # quem fez o quê
zfrog ipfs output/meusite              # publicar no IPFS
zfrog tos https://exemplo.com.br       # robots.txt e termos
zfrog watermark output/meusite         # marcar procedência
zfrog cost                             # custo estimado
zfrog key create painel -r operator    # chave de API
zfrog market list                      # itens compartilhados

# Cancelar job
zfrog cancel <job-id>

# Ver configuração
zfrog config
```

### API

```bash
# Iniciar servidor
zfrog serve

# Criar job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","mode":"mirror","max_depth":2}'

# Verificar status
curl http://localhost:8000/jobs/<job-id>

# Download
curl -O http://localhost:8000/jobs/<job-id>/download

# Probe
curl http://localhost:8000/probe/https://example.com

# Health check
curl http://localhost:8000/health

# Metrics
curl http://localhost:8000/metrics
```

### Dashboard

Forma recomendada — sobe API e dashboard juntos:

```bash
zfrog dev
# API:       http://127.0.0.1:8000
# Dashboard: http://localhost:3000
```

Manualmente (dois terminais):

```bash
# Terminal 1
zfrog serve

# Terminal 2
cd dashboard
npm install
npm run dev
```

 **Páginas do dashboard (27 rotas):** `execuções` (`/`), `coleção` (`/colecao`), `extrair` (`/probe`), `captura` (`/captura`), `busca` (`/busca`), `fluxos` (`/fluxos`), `chat` (`/chat`), `comparar` (`/comparar`), `grafo` (`/grafo`), `precos` (`/precos`), `datasets` (`/datasets`), `graphql` (`/graphql`), `qualidade` (`/qualidade`), `analytics` (`/analytics`), `stats` (`/stats`), `timeline` (`/timeline`), `snapshots` (`/snapshots`), `workers` (`/workers`), `revisao` (`/revisao`), `roi` (`/roi`), `equipe` (`/equipe`), `config` (`/config`), `ajuda` (`/ajuda`), `webhooks` (`/webhooks`), `marketplace` (`/marketplace`), `design` (`/design`). Toda operação da CLI tem equivalente no dashboard; rotas restantes ficam na paleta `ctrl+k`.
 
 **Design system (TUI):** tokens nativos de terminal em `dashboard/src/styles/tui.css` (papel `#f4f2ec`, acento `#4f6b3a` / `#93b27b`, Iosevka 400/500, hairline 1px, radius 0) conectados via `dashboard/src/routes/__root.tsx` + `globals.css`. Primitivos em `dashboard/src/components/ui/tui.tsx` (`Gut`, `Sym`, `Spinner`, `Swatch`, `DetailLine`, `CodeBlock`, `Prompt`, `TuiModal`) e cliente tipado em `dashboard/src/lib/api.ts`. A página `/design` documenta tokens, tipografia e componentes.

> O dashboard precisa do CORS habilitado na API (já configurado via `CORSMiddleware`).

### Docker

```bash
# Subir tudo (Redis + Worker + API)
docker compose up -d

# Ver logs
docker compose logs -f

# Parar
docker compose down
```

## Motores

Cada motor tem um papel distinto e não concorre com os outros.

| Motor | Papel | Quando usar | Modo |
|-------|-------|-------------|------|
| **jump** | Referência: renderiza a página, tira screenshot full page e extrai os tokens de design | Quando o alvo é uma referência visual | `jump` |
| **tongue** | Componente: devolve o HTML e o CSS computado de um seletor | Para estudar um card, navbar ou botão específico | `tongue` |
| **Playwright** | Captura visual: renderiza e guarda o HTML renderizado + CSS/JS/imagens que o navegador carregou | Sempre. É o motor padrão. | `scrape` |
| **Scrapy** | Descoberta: mapeia quais páginas existem no site | Site inteiro ou lote de URLs | `extract` |
| **StaticFile** | Captura leve: página única, com os assets embutidos | Quando a página não depende de JavaScript | `singlepage` |
| **wget** | Assets: baixa imagens, CSS, fontes e ícones | Complemento para consulta offline | `mirror` |

O modo `auto` (padrão) não escolhe motor por conta própria: ele roda o probe e deixa a
decisão acima acontecer. Sem modo informado, `zfrog clone <url>` captura visualmente.

Fluxo de captura:

```
Usuário informa URL
       │
       ├─ Modo auto (padrão) ──► probe ──► Playwright (JS) ou StaticFile (página pronta)
       │
       └─ Site inteiro ──► Scrapy mapeia ──► Playwright captura cada página
                                                   │
                                              wget baixa os assets
```

Além dos quatro motores de captura, o Zfrog traz motores de análise e exportação:

| Motor | Modo | O que faz |
|-------|------|-----------|
| **Analyze** | `analyze` | Auditoria técnica (SEO, acessibilidade, performance) |
| **Compare** | `compare` | Fidelity Score entre clone e original |
| **Ask** | `ask` | Pergunta em linguagem natural sobre a página |
| **PDF** | `pdf` | Renderização em PDF (A4) |
| **Summarize** | `summarize` | Resumo IA da página |
| **Delta** | `delta` | Baixar só as páginas que mudaram |
| **Entities** | `entities` | Nomes de pessoas, empresas, lugares, datas, produtos |
| **Enrich** | `enrich`, `sentiment`, `tags` | Tom do texto e assuntos principais |
| **Translate** | `translate` | Traduzir o conteúdo |
| **Video** | `video` | HLS/DASH: detectar e baixar vídeo |
| **API Discovery** | `api_discovery` | Descobrir endpoints REST/GraphQL |

`zfrog engines` lista os motores disponíveis com a origem de cada um (built-in, entry point
ou plugin local).

### Plugins de Engines

Qualquer pacote pode publicar um motor: basta declarar o entry point
`[project.entry-points."zfrog.engines"]` apontando para uma subclasse de `EngineAdapter`
(`name`, `execute`, `can_handle`) — o Zfrog descobre e registra no import. Para plugins
locais, coloque arquivos `.py` em `plugins/` (ou aponte `ZFROG_PLUGINS_DIR` para outro
diretório); toda subclasse de `EngineAdapter` do arquivo é registrada. Plugin quebrado ou
nome já existente é ignorado com warning — nunca derruba o Zfrog.

### Auto-Detecção

O probe analisa a página e sugere o motor de captura:

- Presença de frameworks JS (React, Vue, Next, Nuxt, Angular)
- Tamanho do HTML vs scripts carregados
- Corpo com pouco texto e vários scripts (SPA que só renderiza no cliente)
- Tipo de conteúdo retornado

A decisão é simples: **JavaScript detectado → Playwright**; **página simples → StaticFile**.
Uma página que o probe não conseguiu ler também vai para o Playwright — perder a renderização
perde o design, perder o atalho só custa tempo. O Scrapy entra quando o alvo é o site inteiro
(`--mode extract`), e o wget quando o alvo são os assets (`--mode mirror`).

O probe também registra se o `robots.txt` restringe a URL (`robots_restricted`). O motor wget
respeita `respect_robots` (padrão `true`; desligue com `--no-robots`).

## Referências de design

O fluxo que dá nome ao projeto: capturar uma página como referência visual,
guardá-la num catálogo e encontrá-la depois.

```bash
zfrog jump https://stripe.com --tag fintech --breakpoint desktop
zfrog jump https://stripe.com --viewport-only --format webp   # mais leve
```

Isso renderiza a página, tira um screenshot de página inteira e extrai os tokens
de design dela — paleta (com a cor dominante e o papel de cada uma), tipografia
(família, tamanhos, pesos), escala (padding, margin, raios, sombras) e os assets
principais. O resultado vira um **card** no catálogo, com o screenshot, a URL de
origem, a data e as etiquetas que você definiu.

Um componente específico, em vez da página toda:

```bash
zfrog tongue https://stripe.com ".hero"
```

Devolve o HTML do elemento e o **CSS que o navegador resolveu para ele**,
agrupado em layout, cor e tipografia — mais a caixa e os filhos diretos. O HTML
sai sanitizado (scripts, `onclick` e `javascript:` removidos).

O catálogo:

```bash
zfrog pond --tag fintech               # por etiqueta
zfrog pond --color "#635BFF"           # por cor dominante
zfrog pond --site stripe.com           # por site
zfrog pond --search "escuro com cards arredondados"
zfrog show <id>                        # detalhe, com a paleta
zfrog export <id> --format html        # mini style guide autocontido
```

A captura padrão também produz design: `zfrog clone <url>` roda a extração de
tokens junto do screenshot, na mesma visita ao navegador, e registra um card — nos
modos que capturam página (`auto`, `mirror`, `scrape`, `singlepage`, `delta`). Os
motores de análise de texto não entram nessa, porque uma paleta vinda deles seria
ruído.

No painel, a tela **Nova extração** oferece o modo *Referência de design* (com
resolução, formato, página inteira ou viewport, e etiquetas) e *Extrair componente*
(com o campo do seletor CSS).

**Como a busca por descrição funciona, e o que ela não faz.** Cada card é
descrito em palavras a partir dos tokens medidos — luminosidade e matiz das
cores, arredondamento dos cantos, vocabulário de sombras, serifa ou não. Essa
descrição é embedada e o ranking é por similaridade de cosseno. Isso responde
"layouts escuros com cards arredondados" porque a extração mediu exatamente
esses atributos. **Não** embeda os pixels: não acha "a que tem foto de cachorro".
Para isso, `visual_search.describe()` é o único ponto que muda.

Sem um modelo de embeddings configurado, a busca cai para comparação de palavras
— degrada para algo útil, não para nada. Configure `ZFROG_AI_EMBEDDING` (e rode
`zfrog pond --reindex`) para usar os vetores. Pela API, `POST /catalog/reindex` faz
o mesmo e informa quantos vetores escreveu; sem modelo, responde `indexed: 0` com o
motivo, em vez de falhar.

No painel, a rota **Coleção** é o moodboard: os screenshots em grade, filtros por
etiqueta, cor e site, a busca por descrição e um painel de detalhe com paleta,
tipografia, etiquetas e nota.

## Change Detection

Jobs `mirror` e `scrape` gravam um snapshot versionado em
`output/snapshots/<url_slug>/<timestamp>.json` (URL, data, engine e, por página, hash
SHA-256, tamanho, título e texto extraído). O diretório `snapshots/` fica fora dos
diretórios de job, então sobrevive à limpeza automática de 24h.

```bash
zfrog snapshots                          # listar todos os snapshots
zfrog snapshots https://example.com      # só os de uma URL
zfrog diff <snap-a.json> <snap-b.json>   # comparar (markdown)
zfrog diff <snap-a.json> <snap-b.json> --json   # relatório em JSON
```

O diff mostra páginas adicionadas, removidas, alteradas (com a quantidade de linhas que
mudaram) e inalteradas, além da proporção de mudança. Mudança não é erro: o comando sai com
código 0.

Quando a proporção de páginas alteradas atinge `ZFROG_CHANGE_ALERT_THRESHOLD`
(default `0.1`, ou seja 10%), o job dispara o webhook `site.changed` com `url`,
`change_ratio`, `added`, `removed`, `changed` e o caminho do snapshot. Registre o webhook
com `POST /webhooks` incluindo `site.changed` em `events`.

## Versionamento

`zfrog clone --versioned` guarda cada cópia como uma versão no histórico (blobs com dedup
por SHA-256 em `versions/`, metadados por versão). Ramo padrão: `main`.

```bash
zfrog versions https://example.com              # lista (mais nova primeiro, marca HEAD)
zfrog branches https://example.com              # ramos
zfrog branch https://example.com experimental   # novo ramo a partir do HEAD
zfrog rollback https://example.com HEAD --dest ./saida
zfrog rollback https://example.com bfa11d2d9bc2
```

O `ref` aceita `HEAD`, nome de ramo, id completo ou prefixo do id (≥ 4 caracteres).

## Delta Crawling

`--mode delta` revalida as páginas conhecidas com requisições condicionais (`If-None-Match` /
`If-Modified-Since`) e baixa apenas o que mudou. A primeira execução baixa tudo; as seguintes
reaproveitam os validadores guardados no snapshot anterior.

O resultado fica em `delta_report.json` (`added`, `changed`, `unchanged`, `removed`,
`bytes_saved`, `pages_written`). Páginas revalidadas com HTTP 304 não geram arquivo, mas
continuam no snapshot — sem isso a execução seguinte não teria como revalidá-las.

## Agendamento

```bash
zfrog schedule add https://example.com --cron "0 2 * * *" --mode mirror --depth 1
zfrog schedule list
zfrog schedule run <id>      # roda agora
zfrog schedule remove <id>
zfrog scheduler --interval 30
```

Cron de 5 campos, com `*`, `*/n`, `a`, `a-b`, `a-b/n` e listas. Quando dia-do-mês e
dia-da-semana estão ambos restritos, vale o clássico "ou" (basta um casar). Agendamentos
ficam em `ZFROG_SCHEDULES_FILE` (default `schedules.json`).

## Busca

Índice SQLite (FTS5) com busca por texto e por significado:

```bash
zfrog search "frete grátis" --dir output --reindex
zfrog search "prazo de entrega" --semantic
```

`fulltext` usa FTS5 com ranking BM25; `semantic` usa embeddings quando há modelo de IA
configurado e devolve lista vazia quando não há. A extração de texto é sem perdas — listas e
tabelas entram no índice (a extração "de artigo" do trafilatura descartava `<ul>` inteiras).

## Multi-Site RAG

```bash
zfrog chat "qual o prazo de devolução?" --site lojaA=output/lojaA --site lojaB=output/lojaB
```

Uma pergunta, vários sites, resposta com citações (`site`, `url`, `path`, trecho). As citações
vêm dos trechos recuperados, não do texto gerado — então aparecem mesmo sem modelo de IA.

## Sessões (sites com login)

```bash
zfrog login https://site-com-login.com   # abre o navegador; entre e aperte Enter
zfrog sessions
zfrog logout site-com-login.com
```

Os engines Playwright/PDF reutilizam a sessão salva do domínio automaticamente. Os arquivos
ficam em `ZFROG_SESSIONS_DIR` com permissão `0600` — são protegidos só por permissão de
arquivo (não são criptografados) e **nunca** devem ir para o controle de versão.

## Fluxos (pipelines)

```bash
zfrog workflow list
zfrog workflow show <id>
zfrog workflow run <id>
```

Passos disponíveis: `probe`, `clone`, `summarize`, `analyze`, `extract`, `compare`, `pdf`,
`search`, `commit`. O `clone` define o diretório de saída que os passos seguintes usam. Um
passo que falha interrompe o fluxo e os restantes ficam marcados como pulados. No dashboard,
a página **Fluxos** monta e executa sequências; **Captura** monta o seletor clicando na página.

## Kubernetes Operator

`deploy/k8s/` traz o CRD `ZfrogJob` (grupo `zfrog.io`, versão `v1alpha1`), RBAC, o Deployment
do operador e um exemplo. O operador cria um Job do Kubernetes por `ZfrogJob` e espelha o
estado (`Pending`/`Running`/`Succeeded`/`Failed`) no `status` do recurso.

```bash
kubectl apply -f deploy/k8s/crd.yaml -f deploy/k8s/rbac.yaml -f deploy/k8s/operator.yaml
kubectl apply -f deploy/k8s/example-job.yaml
zfrog operator          # fora do cluster (usa ZFROG_K8S_API_SERVER)
```

## Qualidade e conformidade

**Segurança**: procura mineradores, iframes escondidos, código ofuscado, formulários que enviam senha
para outro site, `javascript:`/`data:text/html` e downloads executáveis.

```bash
zfrog safety output/meusite
```

Jobs rodam essa varredura automaticamente (`ZFROG_SAFETY_ENABLED`); um achado vira aviso no log, nunca
falha o job.

## Desempenho por motor

```bash
zfrog analytics
```

Guarda, por execução, o motor, o resultado, a duração e o tamanho — o suficiente para responder qual
motor funciona melhor em qual tipo de site. A coleta é automática a cada job.

## Auditoria

Ações que mudam estado (criar/cancelar job, rollback, ramo, agendamento, fluxo) ficam registradas em
JSONL, com origem derivada de `X-Forwarded-For` → `X-Real-IP` → `User-Agent`.

```bash
zfrog audit --limit 20
zfrog audit --action version.rollback
```

## IPFS

```bash
zfrog ipfs output/meusite
```

Publica pelo HTTP API de um nó Kubo (`ZFROG_IPFS_API_URL`) e devolve o CID. Requer
`ZFROG_IPFS_ENABLED=true`; o store endereçável por conteúdo já deduplica os arquivos antes do envio.

## Criptografia das sessões

Com o pacote `cryptography` instalado, os arquivos de sessão são cifrados em repouso com AES-GCM (chave
em `ZFROG_SESSIONS_KEY_FILE`, modo `0600`). Sem ele, o Zfrog avisa **uma vez por processo** que a sessão
está em texto claro e segue funcionando — degradação visível, não silenciosa. Adulteração do arquivo é
detectada e tratada como sessão inexistente.

## Fluxos com dependências

Passos podem declarar de que precisam:

```json
[{"id": "step-0", "type": "probe", "params": {"url": "https://x.com"}, "needs": []},
 {"id": "step-1", "type": "clone", "params": {"mode": "mirror"}, "needs": ["step-0"]}]
```

`needs` ausente mantém o comportamento linear de sempre (espera o passo anterior) — por isso fluxos
salvos antes desta mudança continuam funcionando. `needs: []` diz "não espero ninguém" e permite
execução em paralelo, limitada por `ZFROG_MAX_PARALLEL_STEPS`. Um passo que falha marca os dependentes
como pulados e não impede ramos independentes.

## Conversar com o que foi clonado

```bash
zfrog chat ask "qual o prazo de entrega?" --site loja=output/loja --site blog=output/blog
zfrog chat ask "e a garantia?" --conversation <id> --history   # continua a conversa
zfrog chat list
```

A conversa guarda o histórico: perguntas de acompanhamento ("e o segundo?") funcionam porque os turnos
anteriores vão no contexto. As citações vêm dos trechos recuperados, não do texto gerado — aparecem mesmo
sem modelo de IA. O histórico fica em `output/chats/<id>.json` (modo 0600).

## Grafo de relacionamentos

```bash
zfrog graph output/loja              # resumo + graph.json
zfrog graph output/loja --dot        # saída Graphviz
```

Extrai entidades das páginas e liga o que aparece junto: `co_occurrence` (mesma página) e `located_in`
(local citado na mesma frase que uma organização).

## Qualidade e conformidade (continuação)

```bash
zfrog tos https://exemplo.com.br                 # robots.txt + Termos de Uso
```

O `tos` lê o robots.txt e a página de termos e devolve `clear` / `caution` / `restricted` com o
trecho exato como evidência. **É leitura automática, não parecer jurídico.**

## Procedência (watermark)

```bash
zfrog watermark output/loja --source https://exemplo.com.br
zfrog watermark output/loja --verify
```

Insere metadados invisíveis (meta tag, atributo, comentário e marcador de largura zero no texto) para
rastrear a origem de uma cópia. **O texto visível não muda.** É metadado de procedência — não é DRM e não
é prova de propriedade: quem quiser remove.

## Custos

```bash
zfrog cost
```

Combina as tarifas configuradas com o que já foi medido por execução: transferência (GB), computação
(horas de CPU) e armazenamento (GB-mês). Sem tarifas configuradas os valores ficam em zero — o Zfrog não
inventa dinheiro.

## Marketplace

```bash
zfrog market list
zfrog market install workflow-backup-diario
```

Fluxos, plugins de engine e templates publicados em `ZFROG_MARKETPLACE_DIR`. Instalar um plugin grava o
arquivo em `plugins/`, e o registro de engines o carrega na próxima vez — verificado. A validação acontece
na publicação **e** na instalação, então um arquivo editado à mão não instala conteúdo quebrado.

## Regiões (edge)

```bash
zfrog regions https://loja.example.com.br/carrinho
```

Escolhe onde processar com base em latência, workers disponíveis e residência de dados pelo domínio, e
explica a decisão. Configuração: `ZFROG_WORKER_REGIONS=sa-east:20:4,us-east:180:2`.

## Autenticação e papéis

```bash
zfrog key create painel -r operator
zfrog key list
zfrog key revoke <id>
```

Três papéis: `viewer` (só leitura), `operator` (+ criar/cancelar jobs), `admin` (tudo, inclui chaves e
agendamentos). O segredo é mostrado **uma vez** — só o hash fica no arquivo (modo 0600). Com
`ZFROG_AUTH_ENABLED=true`, tanto leitura quanto escrita exigem chave (`Authorization: Bearer` ou
`X-API-Key`); sem chave a resposta é 401, com papel insuficiente é 403. `/health` continua aberto para
sondas. O padrão é desligado, então nada muda para quem já usa.

O que cada ação exige além de `read:jobs` (o papel `viewer` basta para ler):

| Rota | Ação | Por quê |
|---|---|---|
| `POST /jobs`, `POST /jobs/{id}/cancel`, `DELETE /jobs` | `job:create` / `job:cancel` | consome banda e disco do servidor |
| `POST /watermark` | `version:manage` | reescreve os arquivos guardados |
| `POST /ipfs/publish` | `admin:all` | manda a cópia para terceiros |
| `POST /webhooks`, `DELETE /webhooks/{id}` | `admin:all` | o registro é global e o servidor passa a fazer POST para a URL escolhida |
| `DELETE /sessions/{domain}` | `admin:all` | o arquivo guarda cookies válidos de um site |
| `POST /config/rate-limit` | `admin:all` | o limite é do processo inteiro |
| `POST /extract/preview` | `read:jobs` | busca server-side de URL escolhida, mas não guarda nada |

`tests/test_route_auth.py` percorre a tabela de rotas do FastAPI e falha se alguma rota que muda estado
ficar sem credencial — inclusive um WebSocket novo. A allowlist de rotas públicas (`/`, `/health`,
`/auth/*`, docs) é verificada para não conseguir esconder uma rota mutante.

**No painel:** com a autenticação ligada, o dashboard usa **sessão em cookie assinado** — sem chave de
API no navegador.

1. O gate chama `GET /auth/config` para saber se a instalação exige login.
2. Com SSO configurado, o botão vai para `/auth/login`; o provedor devolve o navegador para
   `/auth/callback`, que valida o ID token e **grava o cookie** `zfrog_session`
   (`HttpOnly`, `SameSite=Lax`, `Secure` quando o login veio por https) e redireciona para
   `ZFROG_POST_LOGIN_REDIRECT`.
3. Sem SSO, o gate aceita uma chave de API colada à mão, guardada em `localStorage` — é o caminho de
   quem não tem provedor de identidade.
4. Nos dois casos o gate confirma pedindo `GET /config`, que exige `read:jobs`: um 200 é a prova de
   que a credencial vale, em vez de uma suposição.

O cookie é **assinado, não criptografado** — não há segredo dentro dele, só o id do usuário e a
validade. Papel e organização **não** ficam no cookie: são lidos do arquivo de usuários a cada
requisição, então desativar alguém ou mudar um papel vale imediatamente, sem esperar o cookie expirar.
A chave de assinatura fica em `ZFROG_WEBSESSION_KEY_FILE` (modo `0600`, criada no primeiro login).

Sessões em cookie exigem `ZFROG_CORS_ORIGINS` com origens explícitas — o navegador só envia o cookie
quando a resposta nomeia a origem exata, e a especificação proíbe casar credenciais com `*`. Com o
padrão `*`, a API continua funcionando, mas só por chave de API.

**WebSocket:** o navegador envia o cookie no handshake, então o painel não põe credencial nenhuma na
URL. Além disso o servidor confere o `Origin` (sem isso, qualquer site que a pessoa visitasse poderia
abrir um socket como ela — *Cross-Site WebSocket Hijacking*). Clientes de script, que não têm cookie,
mandam a chave como subprotocolo: `Sec-WebSocket-Protocol: zfrog.v1, zfrog.key.<segredo>`. É um
header, não query string — por isso não vai parar no log de acesso de um proxy reverso.

## Integrações de saída

```bash
zfrog integrations list
zfrog integrations push planilha dados.json
```

Envia registros para Google Sheets, Airtable ou Notion pelas APIs HTTP de cada um. Falha em um lote não
derruba os outros: os erros voltam no resultado. Tokens ficam em arquivo 0600 e aparecem redigidos na
listagem.

## GraphQL

```bash
curl -X POST localhost:8000/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ jobs(limit: 5) { id url status } engines { name } }"}'
curl localhost:8000/graphql/schema      # SDL
```

API **somente leitura** sobre os mesmos dados do REST: `jobs`, `job`, `snapshots`, `versions`, `schedules`,
`engines`, `analytics`, `search`, `sites`, `conversations`. Respeita a seleção pedida (não devolve campos
que você não pediu) e devolve `errors` por campo, como a especificação manda. Mutations são recusadas.

## SDKs

```bash
cd sdk/js && bun test     # 21 testes
cd sdk/go && go test ./... # 37 subtestes
```

Clientes para JavaScript/TypeScript (`sdk/js`, sem dependências) e Go (`sdk/go`, só stdlib). Cobrem os
mesmos endpoints do REST, com erro tipado (`ZfrogError` / `*APIError`) carregando status e `detail`.

## Equipes: usuários, organizações e SSO

```bash
zfrog user create ana@empresa.com -r operator -p senha-inicial
zfrog org create "Acme Corp" --owner <user-id>
zfrog org add-member acme-corp <user-id> --role operator
zfrog user list
```

Senhas usam PBKDF2-HMAC-SHA256 (200 mil iterações, salt por usuário) e o arquivo é `0600`. A senha é
mostrada **uma vez**; só o hash fica guardado.

**SSO (OpenID Connect)** — configure `ZFROG_OIDC_ISSUER` e `ZFROG_OIDC_CLIENT_ID` e o login passa a
existir em `GET /auth/login`. A verificação da assinatura do ID token é feita de verdade (RS256/ES256 com
`cryptography`, chave escolhida pelo `kid` do JWKS): issuer, audience, expiração e `nonce` são conferidos.
O `state` é de uso único e o `nonce` precisa ser o mesmo que foi enviado no início — sem isso um token
emitido para outro fluxo seria aceito.

**Como o SSO vira credencial:** o callback autentica no provedor, cria/atualiza o usuário local e
**grava o cookie de sessão** descrito em *Autenticação e papéis*. O SSO não precisa de chave de API
para o painel; a chave continua existindo para scripts e para quem não tem provedor de identidade.

## Isolamento por organização

Cada organização tem seus próprios dados: clones, versões, agendamentos, busca, métricas, auditoria e
sessões ficam sob `output/orgs/<slug>/`. A organização vem da **chave de API do chamador**, nunca do corpo
da requisição — um cliente não consegue escrever no espaço de outro. Sem organização, tudo continua no
diretório compartilhado, como antes.

```bash
zfrog clone https://example.com --mode mirror --org acme-corp
```

## Revisão: comentários nas cópias

```bash
zfrog annotate <job-id> index.html "o preço mudou aqui" --selector ".preco" --tag preco
zfrog annotations <job-id> --open
```

Comentários aceitam seletor CSS (validado), etiquetas e respostas, e podem ser resolvidos. A exportação
gera um Markdown para revisão em equipe. No dashboard, a página **Revisão** faz o mesmo pela interface.

## Perfis de domínio

```bash
zfrog domain list
zfrog domain suggest https://tribunal.jus.br/processo
```

Três perfis embutidos — jurídico, e-commerce e notícias — com vocabulário, exemplos e tipos de entidade.
Isso especializa **as instruções dadas ao modelo** (terminologia e exemplos), não os pesos: é prompt
engineering por domínio, não um modelo treinado. Seja claro sobre essa diferença antes de prometer precisão.

## Backends de busca

`ZFROG_SEARCH_BACKEND` escolhe entre `sqlite` (padrão, FTS5 embutido), `meilisearch` e `elasticsearch`.
Os backends HTTP falam as APIs reais; uma falha de rede degrada para resultado vazio com aviso, nunca
derruba a requisição.

## Workers e regiões

```bash
zfrog worker run --region sa-east --capacity 4
zfrog worker list
zfrog worker assign https://loja.com.br
```

Um worker registra-se, manda batidas de coração e informa quantos jobs está processando. A atribuição usa
a decisão de região (`zfrog regions`) e escolhe quem tem mais capacidade livre; sem worker vivo na região
escolhida, cai para outra e explica o motivo.

## Marketplace remoto

```bash
zfrog market-index build -o index.json --source "time interno"
zfrog market-index sync https://exemplo.com/index.json
```

O índice leva um checksum por item, então dá para saber se o que está instalado é o que o índice anuncia.
A sincronização valida cada payload antes de gravar: item inválido é contado como ignorado, com o motivo,
e **não** é escrito.

## Máquina do tempo

```bash
zfrog timeline https://exemplo.com.br                       # lista as versões
zfrog timeline https://exemplo.com.br --when 2026-09-01     # a versão daquela data
zfrog timeline https://exemplo.com.br --ref 8cdd77f3 --page index.html
zfrog timeline https://exemplo.com.br --restore ./saida
```

`--when` aceita `2026-09-01`, `2026-09-01T12:00` ou `2026-09-01 12:00`. Sem hora, vale o dia inteiro (a
última versão até o fim daquele dia). O `--page` devolve o **HTML original** guardado — não o texto
extraído — e o dashboard abre a página num visualizador, deixando claro que é uma cópia arquivada e não o
site ao vivo.

## Monitoramento de preços

```bash
zfrog price watch https://loja.com.br/produto
zfrog price changes https://loja.com.br/produto
```

Reconhece `R$ 1.234,56`, `$1,234.56`, `€ 89,90` e `1234 reais`. A convenção do separador vem do **último**
separador do número, então `1.234,56` é mil duzentos e trinta e quatro vírgula cinquenta e seis — e um
número sem sinal de moeda (`2026`) não é preço. O alerta dispara quando a variação passa de
`ZFROG_PRICE_ALERT_DROP_PCT` / `ZFROG_PRICE_ALERT_RISE_PCT`.

## Análise competitiva e tendências

```bash
zfrog compare-sites -s lojaA=output/lojaA -s lojaB=output/lojaB --markdown
zfrog trends https://exemplo.com.br -t preco -t frete
```

A comparação põe os clones lado a lado: páginas, palavras, preços por item (com o mais barato), entidades
em comum, o que cada um tem de próprio e as lacunas reais. As tendências contam um termo ao longo do
histórico e dizem a direção — com "sem histórico suficiente" quando é o caso, em vez de um palpite.

## Dois fatores (TOTP)

```bash
zfrog totp add email SEGREDO_BASE32
zfrog totp code email
```

Gera os códigos de 6 dígitos (RFC 6238) para entrar na **sua própria conta**. O arquivo de segredos é
`0600`, o segredo nunca aparece na listagem nem em log, e o `repr` o mascara. Isto **não** resolve CAPTCHA
nem burla qualquer controle anti-automação — está fora do escopo de propósito.

## Dataset para fine-tuning

```bash
zfrog dataset output/meusite --kind extraction --format chat
```

Gera pares instrução/resposta em JSONL (`chat` ou `alpaca`) a partir dos clones. Os exemplos são
**derivados da própria página** (extração, resumo extrativo, perguntas por cabeçalho), nunca inventados.
O treinamento em si roda fora daqui — precisa de GPU e de um treinador que não vem neste projeto. O
`ai/domains.py` especializa o **prompt** na hora de usar; isto prepara dados para especializar os **pesos**.

## Retorno (ROI)

```bash
zfrog roi
```

    valor = páginas × minutos-por-página ÷ 60 × valor-hora
    custo = computação + transferência + armazenamento
    saldo = valor − custo

As duas primeiras são **premissas suas** (`ZFROG_ROI_HOURLY_RATE`, `ZFROG_ROI_MANUAL_MINUTES_PER_PAGE`), não
medições — e o relatório devolve isso junto com o número. Sem custo, a razão é `—`, não "infinito". A
contagem de páginas é estimada pelos arquivos gerados, e o relatório diz isso.

## Marketplace servido

```bash
zfrog market-serve --port 8200 --token s3cret
```

Serve o índice por HTTP: `GET /index.json`, `GET /assets`, `GET /verify/{id}` e `POST /assets`. Com
`--token`, publicar exige `Authorization: Bearer`; a leitura continua aberta (um índice é para ser
consultado). O `verify` compara o checksum anunciado com o arquivo local — é o que denuncia um item alterado.

## Despacho entre workers

```bash
zfrog dispatch --url https://exemplo.com --dry-run
zfrog dispatch --url https://exemplo.com --region sa-east
```

O `--dry-run` mostra para qual worker e região cada job iria, sem enviar nada. Sem `--dry-run`, o job é
enviado ao `/jobs` do worker escolhido e o slot é marcado como ocupado — uma resposta sem `job_id` conta
como falha, não como sucesso.

## Arquivamento permanente (Arweave)

```bash
zfrog arweave output/meusite
```

Empacota o clone em tar.gz e publica numa transação Arweave (formato ANS-104, assinatura RSA-PSS). Requer
`ZFROG_ARWEAVE_ENABLED=true` e uma carteira em `ZFROG_ARWEAVE_WALLET_FILE`. **O protocolo foi implementado e
testado contra um gateway simulado — nunca contra a rede real**, que exige AR pago.

## Rodando em produção

O Zfrog foi feito para rodar local. Subir para produção funciona, mas exige quatro
ajustes — sem eles o sistema perde dados ou fica aberto.

**1. Um volume, um `ZFROG_DATA_DIR`.** Tudo que o Zfrog guarda (chaves de API,
usuários, sessões, histórico de versões, índices) vive sob esse diretório. Sem ele
cada store escreve dentro da camada gravável do container e **um restart apaga
tudo**: você fica trancado fora e precisa re-logar em cada site.

```bash
# docker-compose.prod.yml já faz isso
volumes:
  - zfrog-data:/app/data
environment:
  - ZFROG_DATA_DIR=/app/data
```

**2. Autenticação ligada.** `ZFROG_AUTH_ENABLED=true` (o default é `false`, para
uso local). Com ela desligada e a API exposta, qualquer um que alcance a porta
cria jobs, publica no Arweave e lê todos os clones. Com ela ligada, o dashboard
pede a chave uma vez e a guarda no navegador.

**3. CORS restrito.** `ZFROG_CORS_ORIGINS=https://app.seudominio.com` em vez de `*`.

**4. Sem acesso à rede interna.** `ZFROG_ALLOW_PRIVATE_HOSTS=false`. Localmente é
`true` (você clona `localhost` e a LAN), mas exposto isso transforma o servidor num
proxy para a rede interna: `POST /jobs {"url":"http://169.254.169.254/..."}` faz o
servidor ler o metadata da sua cloud.

```bash
docker compose -f docker-compose.prod.yml up -d
```

O `api` roda com `--workers 2`: o estado que não pode ser por processo (jobs,
webhooks, login SSO) vai para o Redis/valkey, então os workers se enxergam. Sem
Redis, use `--workers 1`.

### Limites conhecidos

- **SQLite com um só arquivo por store, agora com espera.** `busy_timeout` (5s) e WAL
  estão ligados em `storage/sqlite.py`, então dois workers concorrentes esperam a vez
  em vez de receber `database is locked`. Ainda é SQLite: para muitas réplicas o
  caminho é Postgres — os stores têm interface própria e o `search_backends.py` já
  aceita Meilisearch ou Elasticsearch.
- **Schema com versão.** `PRAGMA user_version` mais uma lista ordenada de migrações
  por store. A primeira entrada é o schema original escrito com `IF NOT EXISTS`, então
  um banco criado antes disso migra sem quebrar. Ao mudar o formato, **acrescente** uma
  entrada; nunca edite uma que já rodou.
- **`/health` diz "degraded" quando é verdade.** Ele confere o broker e a escrita no
  volume, e responde 503 se qualquer um falhar — antes respondia `healthy` sempre, o
  que mantinha uma instância quebrada no balanceador. `/metrics` lê o `analytics.py`
  (uma linha por execução de motor); antes lia um contador em memória que nada
  incrementava e devolvia `{}` para sempre.
- **Backup**: o volume inteiro. Guarde `sessions/.key` com cuidado — sem ele os
  cookies criptografados ficam ilegíveis mesmo com backup. O mesmo vale para
  `websession.key`: perdê-lo invalida as sessões do painel (todo mundo loga de novo),
  o que é recuperável — mas não o apague esperando manter as sessões.
- **Sem TLS embutido.** Coloque nginx/Caddy na frente; o compose já escuta em
  `127.0.0.1`.
- **O guard de URL não é um sandbox.** Ele resolve o nome antes de conectar, então
  um DNS que responda diferente na segunda consulta (rebinding) ainda pode passar.

## Arquitetura

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   CLI/API   │────▶│ Orchestrator │────▶│   Engines   │
└─────────────┘     └──────────────┘     └─────────────┘
                           │                     │
                           ▼                     ▼
                    ┌──────────────┐     ┌─────────────┐
                    │    Probe     │     │  Pipeline   │
                    └──────────────┘     └─────────────┘
                           │                     │
                           ▼                     ▼
                    ┌──────────────┐     ┌─────────────┐
                    │  Storage     │     │  Webhooks   │
                    └──────────────┘     └─────────────┘
```

### Fluxo de Execução

1. **Probe**: Analisa a URL e detecta tipo de site
2. **Route**: Seleciona motor baseado no modo ou detecção
3. **Execute**: Baixa/processa conteúdo
4. **Pipeline**: Reescreve links, remove trackers
5. **Package**: Gera ZIP para download

## Configuração

### Variáveis de Ambiente

| Variável | Default | Descrição |
|----------|---------|-----------|
| `ZFROG_REDIS_URL` | `redis://localhost:6379/0` | URL do Redis |
| `ZFROG_OUTPUT_DIR` | `output` | Diretório de saída |
| `ZFROG_MAX_CONCURRENT_JOBS` | `5` | Jobs simultâneos |
| `ZFROG_WORKER_CONCURRENCY` | `2` | Workers Celery |
| `ZFROG_PROXY_URL` | `None` | Proxy HTTP |
| `ZFROG_HTTP_TIMEOUT_CONNECT` | `30` | Timeout conexão (s) |
| `ZFROG_HTTP_TIMEOUT_READ` | `60` | Timeout leitura (s) |
| `ZFROG_PLUGINS_DIR` | `plugins` | Diretório de plugins de engines |
| `ZFROG_CHANGE_ALERT_THRESHOLD` | `0.1` | Proporção de páginas alteradas que dispara `site.changed` |
| `ZFROG_VERSIONS_DIR` | `versions` | Histórico de versões |
| `ZFROG_DELTA_MAX_PAGES` | `200` | Máx. de páginas revalidadas por execução delta |
| `ZFROG_SCHEDULES_FILE` | `schedules.json` | Agendamentos salvos |
| `ZFROG_SCHEDULER_INTERVAL_S` | `30` | Intervalo de verificação do agendador |
| `ZFROG_SEARCH_DB` | `search.db` | Índice de busca |
| `ZFROG_SESSIONS_DIR` | `sessions` | Sessões de login (permissão 0600) |
| `ZFROG_K8S_NAMESPACE` | `default` | Namespace do operador |
| `ZFROG_K8S_WORKER_IMAGE` | `zfrog-worker:latest` | Imagem usada nos Jobs criados |
| `ZFROG_K8S_API_SERVER` | `None` | API do cluster (fora do cluster) |
| `ZFROG_SESSIONS_KEY_FILE` | `sessions/.key` | Chave AES-GCM das sessões (0600) |
| `ZFROG_IPFS_ENABLED` | `false` | Ligar publicação no IPFS |
| `ZFROG_IPFS_API_URL` | `http://127.0.0.1:5001` | HTTP API do nó Kubo |
| `ZFROG_SAFETY_ENABLED` | `true` | Varredura de segurança a cada job |
| `ZFROG_AUDIT_LOG` | `audit.log` | Trilha de auditoria (JSONL, 0600) |
| `ZFROG_METRICS_DB` | `metrics.db` | Métricas por motor |
| `ZFROG_MAX_PARALLEL_STEPS` | `4` | Passos simultâneos num fluxo |
| `ZFROG_SIGNIFICANCE_THRESHOLD` | `0.35` | Nota a partir da qual a mudança é relevante |
| `ZFROG_TRANSLATION_TARGET` | `pt` | Idioma de destino padrão |
| `ZFROG_VIDEO_MAX_BYTES` | `500000000` | Limite de download de vídeo |
| `ZFROG_VIDEO_MAX_SEGMENTS` | `5000` | Limite de segmentos de vídeo |
| `ZFROG_COST_PER_GB_TRANSFER` | `0` | Tarifa por GB transferido |
| `ZFROG_COST_PER_CPU_HOUR` | `0` | Tarifa por hora de CPU |
| `ZFROG_COST_PER_GB_MONTH` | `0` | Tarifa por GB-mês armazenado |
| `ZFROG_COST_CURRENCY` | `BRL` | Moeda dos custos |
| `ZFROG_AUTH_ENABLED` | `false` | Exigir chave de API |
| `ZFROG_API_KEYS_FILE` | `api_keys.json` | Chaves (hash, modo 0600) |
| `ZFROG_REGION` | `local` | Região local |
| `ZFROG_WORKER_REGIONS` | `` | Regiões e latência (ex.: `sa-east:20:4`) |
| `ZFROG_MARKETPLACE_DIR` | `marketplace` | Itens publicados |
| `ZFROG_INTEGRATIONS_DIR` | `integrations` | Destinos de saída (modo 0600) |
| `ZFROG_REGIONS` | | |
| `ZFROG_USERS_FILE` | `users.json` | Usuários (0600) |
| `ZFROG_ORGS_FILE` | `orgs.json` | Organizações (0600) |
| `ZFROG_DEFAULT_ORG` | `default` | Organização padrão |
| `ZFROG_OIDC_ISSUER` | `` | Emissor OpenID Connect |
| `ZFROG_OIDC_CLIENT_ID` | `` | Client ID do SSO |
| `ZFROG_OIDC_CLIENT_SECRET` | `` | Client secret do SSO |
| `ZFROG_OIDC_REDIRECT_URI` | `http://localhost:8000/auth/callback` | Redirect do SSO |
| `ZFROG_OIDC_GROUP_ROLE_MAP` | `` | Grupos → papéis (`admins=admin`) |
| `ZFROG_ANNOTATIONS_DIR` | `annotations` | Comentários |
| `ZFROG_DOMAIN_PROFILES_DIR` | `domains` | Perfis de domínio |
| `ZFROG_SEARCH_BACKEND` | `sqlite` | `sqlite`, `meilisearch` ou `elasticsearch` |
| `ZFROG_MEILISEARCH_URL` | `http://127.0.0.1:7700` | Servidor Meilisearch |
| `ZFROG_ELASTICSEARCH_URL` | `http://127.0.0.1:9200` | Servidor Elasticsearch |
| `ZFROG_WORKERS_HEARTBEAT_TTL_S` | `60` | Validade da batida de um worker |
| `ZFROG_WORKER_ID` | `` | Identidade deste worker |
| `ZFROG_WORKER_API_PORT` | `8000` | Porta da API de um worker |
| `ZFROG_DISPATCH_TIMEOUT_S` | `30` | Timeout ao enviar um job a um worker |
| `ZFROG_PRICE_ALERT_DROP_PCT` | `5` | Queda (%) que dispara alerta de preço |
| `ZFROG_PRICE_ALERT_RISE_PCT` | `5` | Alta (%) que dispara alerta de preço |
| `ZFROG_PRICE_CURRENCY_HINT` | `BRL` | Moeda quando o símbolo é ambíguo |
| `ZFROG_TOTP_DIGITS` | `6` | Dígitos do código de dois fatores |
| `ZFROG_FINETUNE_DIR` | `finetune` | Datasets gerados |
| `ZFROG_ANALYSIS_DIR` | `analysis` | Preços e análises |
| `ZFROG_MARKETPLACE_PORT` | `8200` | Porta do servidor de marketplace |
| `ZFROG_ARWEAVE_ENABLED` | `false` | Ligar arquivamento permanente |
| `ZFROG_ARWEAVE_WALLET_FILE` | `arweave-wallet.json` | Carteira Arweave (0600) |
| `ZFROG_ROI_HOURLY_RATE` | `0` | Valor da sua hora (premissa do ROI) |
| `ZFROG_ROI_MANUAL_MINUTES_PER_PAGE` | `2` | Minutos por página (premissa do ROI) |

### Arquivo .env

```bash
cp .env.example .env
# Editar conforme necessário
```

## API Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/` | Info da API |
| POST | `/jobs` | Criar job |
| GET | `/jobs` | Listar jobs |
| GET | `/jobs/{id}` | Status do job |
| POST | `/jobs/{id}/cancel` | Cancelar job |
| DELETE | `/jobs` | Limpar a lista (mantém o que ainda vai rodar) |
| GET | `/jobs/{id}/result` | Resultado do job |
| GET | `/jobs/{id}/download` | Download ZIP |
| GET | `/jobs/{id}/pdf` | Baixar PDF (modo `pdf`) |
| GET | `/snapshots` | Listar snapshots |
| GET | `/snapshots/{slug}/{file}` | Baixar snapshot (JSON) |
| POST | `/diff` | Comparar dois snapshots |
| GET | `/versions` | Listar versões de um site |
| POST | `/versions/rollback` | Restaurar uma versão |
| POST | `/versions/branches` | Criar um ramo |
| GET/POST | `/schedules` | Listar / criar agendamentos |
| DELETE | `/schedules/{id}` | Remover agendamento |
| POST | `/schedules/{id}/run` | Rodar agendamento agora |
| POST | `/search` | Buscar (texto ou semântico) |
| GET/DELETE | `/sessions` | Listar / apagar sessões salvas |
| GET/POST | `/workflows` | Listar / salvar fluxos |
| DELETE | `/workflows/{id}` | Remover fluxo |
| POST | `/workflows/{id}/run` | Executar fluxo |
| GET | `/extract/page` | Página higienizada p/ o seletor visual |
| POST | `/extract/preview` | Pré-visualizar um seletor CSS |
| GET | `/analytics/engines` | Desempenho por motor |
| GET | `/analytics/totals` | Totais de execuções |
| GET | `/audit` | Trilha de auditoria |
| POST | `/safety/scan` | Verificar riscos de segurança |
| POST | `/ipfs/publish` | Publicar um clone no IPFS |
| POST | `/graphql` | Consulta GraphQL (somente leitura) |
| GET | `/graphql/schema` | Schema GraphQL (SDL) |
| POST/GET | `/chat` | Perguntar / listar conversas |
| GET | `/chat/{id}` | Ler uma conversa |
| POST | `/tos/check` | Checar robots.txt e termos |
| POST | `/watermark` | Marcar procedência |
| POST | `/watermark/verify` | Verificar procedência |
| POST | `/graph` | Montar grafo de relacionamentos |
| GET | `/analytics/cost` | Custo estimado por motor |
| GET/DELETE | `/webhooks` | Listar / remover webhooks |
| GET/POST | `/marketplace` | Listar / publicar itens |
| POST | `/marketplace/{id}/install` | Instalar item |
| POST | `/marketplace/{id}/rate` | Avaliar item |
| POST | `/workflows/preview` | Explicar um fluxo e apontar problemas |
| GET/POST | `/keys` | Listar / criar chaves de API |
| DELETE | `/keys/{id}` | Revogar chave |
| GET/POST | `/integrations` | Listar / salvar destinos |
| POST | `/integrations/{name}/push` | Enviar registros |
| GET | `/regions` | Regiões e decisão de roteamento |
| GET/POST | `/users` | Listar / criar usuários |
| GET/POST | `/orgs` | Listar / criar organizações |
| POST | `/orgs/{id}/members` | Adicionar membro |
| GET/POST | `/annotations` | Listar / criar comentários |
| PATCH | `/annotations/{id}` | Editar comentário |
| POST | `/annotations/{id}/resolve` | Resolver / reabrir |
| POST | `/annotations/{id}/replies` | Responder |
| DELETE | `/annotations/{id}` | Excluir comentário |
| GET | `/annotations/export` | Exportar em Markdown |
| GET/POST | `/domains` | Perfis de domínio |
| GET/POST | `/workers` | Listar / registrar workers |
| POST | `/workers/heartbeat` | Batida de coração |
| GET | `/workers/assign` | Onde um site seria processado |
| GET | `/marketplace/index` | Índice publicável |
| POST | `/marketplace/sync` | Importar índice remoto |
| GET | `/auth/config` | SSO configurado? |
| GET | `/auth/login` | Iniciar login SSO |
| GET | `/auth/callback` | Concluir login SSO |
| GET | `/timeline` | Versões de um site |
| GET | `/timeline/resolve` | Versão de uma data |
| GET | `/timeline/pages` | Páginas de uma versão |
| GET | `/timeline/page` | Metadados de uma página |
| GET | `/timeline/content` | HTML arquivado (para o visualizador) |
| GET | `/prices` | Histórico de preços |
| GET | `/prices/changes` | Variações de preço |
| POST | `/prices/watch` | Registrar preços do último snapshot |
| GET | `/roi` | Retorno do trabalho automatizado |
| GET/POST | `/totp` | Contas de dois fatores |
| GET | `/totp/{name}/code` | Código atual |
| DELETE | `/totp/{name}` | Remover conta |
| POST | `/datasets` | Montar dataset de fine-tuning |
| POST | `/datasets/export` | Exportar dataset (JSONL) |
| POST | `/analysis/competitive` | Comparar clones |
| POST | `/analysis/trends` | Tendências de termos |
| GET | `/dispatch/plan` | Para onde um job iria |
| POST | `/dispatch` | Enviar jobs a workers |
| GET | `/arweave/status` | Arquivamento configurado? |
| POST | `/arweave/publish` | Publicar no Arweave |
| GET | `/probe/{url}` | Analisar URL |
| GET | `/health` | Health check |
| GET | `/metrics` | Métricas |
| GET | `/stats` | Estatísticas |
| GET | `/config` | Configuração atual |
| POST | `/config/rate-limit` | Atualizar rate limit |
| POST | `/webhooks` | Registrar webhook |

## Production Features

### Rate Limiting
- Token bucket global com 1 req/s sustained, burst de 5
- Configurável via `--rate-limit` no CLI e `POST /config/rate-limit`
- Limite de concorrência global, para os jobs não abrirem navegadores sem fim

### Retry
- Exponential backoff com jitter (`@retry` em `utils/rate_limit.py`)
- Retry em erros HTTP 429, 500, 502, 503, 504

### Respeito à web
- User-agent simples e headers básicos: a captura de design não precisa se disfarçar
- Delay educado entre requisições (rate limiter) e `robots.txt` respeitado no motor wget
  (`--no-robots` desliga)

### Observabilidade
- `GET /health` — checa o store de jobs (Redis) e o volume de estado e reporta o uso de
  memória; responde 503 quando algum dos dois falha, para o healthcheck do container valer
- `GET /metrics` — métricas por motor, lidas do store de analytics
- `GET /stats` — estatísticas do sistema
- `zfrog audit` — trilha de auditoria em JSONL

### Limpeza Automática
- Jobs antigos removidos após 24h
- Output files limpos automaticamente
- Configurável via `JobCleanup`

## Estrutura do Projeto

```
zfrog/
├── src/zfrog/
│   ├── __init__.py
│   ├── __main__.py
│   ├── api.py              # FastAPI application
│   ├── cli.py              # CLI Typer
│   ├── config.py           # Settings Pydantic
│   ├── models.py           # Schemas
│   ├── orchestrator.py     # Core logic: probe → motor → pipeline
│   ├── probe.py            # Auto-detecção (sugere o motor)
│   ├── tokens.py           # Extração de design tokens de uma página
│   ├── components.py       # Extração de um componente (HTML + CSS computado)
│   ├── catalog.py          # Catálogo de referências (cards, tags, cores)
│   ├── visual_search.py    # Busca por descrição sobre o catálogo
│   ├── queue.py            # Celery tasks
│   ├── engines/
│   │   ├── base.py         # Interface abstrata
│   │   ├── playwright.py   # Captura visual (padrão)
│   │   ├── scrapy.py       # Descoberta
│   │   ├── static_file.py  # Página leve
│   │   ├── wget.py         # Assets
│   │   ├── jump.py         # Referência: screenshot + tokens + card
│   │   ├── tongue.py       # Componente: HTML + CSS computado
│   ├── pipeline/
│   │   ├── link_rewriter.py
│   │   ├── privacy_cleaner.py
│   │   ├── screenshot.py
│   │   ├── safety.py
│   │   └── packager.py
│   ├── storage/
│   │   ├── local.py
│   │   ├── sqlite.py
│   │   ├── ipfs.py
│   │   ├── arweave.py
│   │   └── redis_store.py
│   └── utils/
│       ├── http.py
│       ├── rate_limit.py
│       ├── cleanup.py
│       ├── webhooks.py
│       ├── stealth.py      # UA, viewport e locale estáveis
│       └── resources.py
├── dashboard/              # TUI Dashboard (Vite + React 19 + TanStack Router)
├── deploy/k8s/             # Operator + CRD (ZfrogJob)
├── sdk/                    # Clientes JS e Go
├── tests/                  # 80 módulos de teste
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Desenvolvimento

```bash
pip install -e ".[dev]"

# A suíte inteira. O Redis é opcional: sem ele os testes que dependem do broker
# se pulam sozinhos (ZFROG_REDIS_URL aponta para onde ele estiver).
pytest tests/ -q

# Com Redis, os pulados também rodam:
ZFROG_REDIS_URL=redis://127.0.0.1:6379/0 pytest tests/ -q
```

O que o CI roda, e o que se espera de cada passo:

 | Passo | Comando | Estado |
 |---|---|---|
 | Lockfile | `uv lock --check` | verde |
 | Lint | `ruff check . --select F821,F811,F402,E9` | verde |
 | Testes | `pytest tests/ -q` | verde (1713) |
 | Tipos do painel | `tsc --noEmit` (Vite + TanStack) | verde |
 | Build do painel | `vite build` (27 rotas) | verde |

**Sobre o lint:** o gate cobre só as regras de **correção** — `F821` (nome indefinido),
`F811` (redefinição), `F402` (import encoberto por variável de laço) e `E9` (sintaxe).
São as que pegam bug, e foi assim que apareceram um `new_script` usado sem ser criado em
`engines/static_file.py` (o `except Exception` em volta escondia o `NameError` e registrava
só "Failed to inline JS") e três `Optional[...]` sem import em `ai/extraction.py` — que eram
`NameError` em tempo de execução graças ao `from __future__ import annotations`.

As regras de estilo do `pyproject.toml` (`E501` comprimento de linha, `I001` ordem de
import, `UP0xx` modernização) somam ~450 violações no código existente. Ligá-las hoje
abriria o CI vermelho e ninguém confiaria no gate; apertar isso é trabalho de continuação,
não um esquecimento. Enquanto isso:

```bash
# Ver tudo o que o estilo apontaria (não é o gate)
uvx ruff@0.16.9 check . --statistics

# Só os arquivos que você mexeu, para não piorar o placar
uvx ruff@0.16.9 check <arquivos>
```

O arquivo que mudou precisa passar nas regras de correção — o gate garante isso.

## Licença

Apache License 2.0 — veja [LICENSE](LICENSE).

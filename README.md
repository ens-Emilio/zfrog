# Zfrog - Design Reference Engine

<img src="docs/mascot.png" alt="Zfrog mascot: a little frog with a magnifying glass and a blank sheet of paper" width="140" align="right">

Tool for collecting, organizing, and adapting web design references. Capture
any page, save its look as an offline reference, and browse what you've captured
afterwards.

## Features

- **4 engines with distinct roles**: Playwright (visual capture, the default), Scrapy
  (discovery), StaticFile (lightweight pages), wget (assets)
- **Auto-detection**: chooses the engine depending on whether the page needs JavaScript
- **Visual capture**: full-page screenshot of each captured page
- **Complete pipeline**: link rewriting, tracker cleanup, ZIP packaging
- **API REST**: endpoints for jobs, probe, download, health check, metrics
- **Dashboard UI**: web interface to manage jobs
- **Production**: rate limiting, retry with circuit breaker, automatic cleanup, webhooks

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd zfrog

# Create a virtual environment and install dependencies
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Install the Playwright browser
.venv/bin/playwright install chromium
```

The repository ships a `./zfrog` launcher at the root that uses the project's virtualenv, so
**you don't need to activate the venv** to run commands:

```bash
./zfrog dev
```

To use it as `zfrog` (without `./`), add the project root to your `PATH` or create an alias:

```bash
# Option 1: shell alias (~/.bashrc, ~/.zshrc)
alias zfrog="$PWD/zfrog"

# Option 2: symlink in a directory on PATH
ln -s "$PWD/zfrog" ~/.local/bin/zfrog
```

Alternatively, activate the venv and use the installed command:

```bash
source .venv/bin/activate
zfrog dev
```

## Quick Start

### All together (API + Dashboard)

```bash
./zfrog dev
```

Starts the API (`http://127.0.0.1:8000`) and the dashboard (`http://localhost:3000`) with a single
command. Each service's output is prefixed (`api` / `web` / `worker`). Ctrl+C stops all;
if one crashes, the others are terminated automatically.

With Redis available, a Celery worker starts alongside. It is not optional: the API dispatches
to the queue and returns `pending` immediately, so without a consumer every extraction
started in the dashboard stays "queued" forever with no explanation. Without Redis, jobs
run inside the API process and there is no worker.

```bash
./zfrog dev --api-port 9000 --web-port 4000   # custom ports
./zfrog dev --no-reload                       # without API auto-reload
./zfrog dev --no-install                      # skip npm install
```

### CLI

```bash
# Auto capture (default): probe picks the engine
zfrog clone https://example.com

# Capture a design reference: screenshot + tokens + catalog card
zfrog jump https://stripe.com
zfrog jump https://stripe.com --breakpoint mobile --tag fintech

# Extract a component: the element's HTML and its computed CSS
zfrog tongue https://stripe.com ".hero"

# The collection: list, filter, and search by visual description
zfrog pond                                   # todas as referências
zfrog pond --tag fintech                     # by tag
zfrog pond --color "#635BFF"                 # by color
zfrog pond --search "layouts escuros com cards arredondados"
zfrog show 9cc7eb98                          # detalhes de uma referência
zfrog export 9cc7eb98 --format html          # mini style guide

# Clone a static site
zfrog clone https://example.com --mode singlepage

# Mirror site recursively
zfrog clone https://example.com --mode mirror --depth 2

# Clone an SPA (React/Vue/Next.js)
zfrog clone https://nextjs.org --mode scrape

# Extract structured data
zfrog clone https://products.com --mode extract --depth 1

# Render page as PDF
zfrog clone https://example.com --mode pdf

# Render PDF with a custom filename
zfrog clone https://example.com --mode pdf --pdf-filename relatorio

# Summarize the page with AI
zfrog clone https://example.com --mode summarize

# Analyze a URL
zfrog probe https://example.com

# Save a versioned copy (history with rollback)
zfrog clone https://example.com --mode mirror --versioned
zfrog versions https://example.com
zfrog rollback https://example.com HEAD --dest ./restaurado

# Download only what changed since the last copy
zfrog clone https://example.com --mode delta

# Schedule recurring copies
zfrog schedule add https://example.com --cron "0 2 * * *"
zfrog scheduler                      # daemon que executa os agendamentos

# Search inside downloaded content
zfrog search "política de privacidade" --dir output
zfrog search "preço do produto" --semantic

# Ask across multiple sites at once (with citations)
zfrog chat "quanto custa?" --site lojaA=output/lojaA --site lojaB=output/lojaB

# Log into a site and save the session (login-required sites)
zfrog login https://site-com-login.com
zfrog sessions

# Saved step sequences
zfrog workflow list
zfrog workflow run <id>

# List jobs
zfrog jobs

# Quality & compliance
zfrog safety output/meusite            # sinais de página perigosa
zfrog analytics                        # qual motor funciona melhor
zfrog audit --limit 20                 # quem fez o quê
zfrog ipfs output/meusite              # publicar no IPFS
zfrog tos https://exemplo.com.br       # robots.txt e termos
zfrog watermark output/meusite         # marcar procedência
zfrog cost                             # custo estimado
zfrog key create painel -r operator    # chave de API
zfrog market list                      # itens compartilhados

# Cancel a job
zfrog cancel <job-id>

# Show configuration
zfrog config
```

### API

```bash
# Start server
zfrog serve

# Create job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","mode":"mirror","max_depth":2}'

# Check status
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

Recommended way — start API and dashboard together:

```bash
zfrog dev
# API:       http://127.0.0.1:8000
# Dashboard: http://localhost:3000
```

Manually (two terminals):

```bash
# Terminal 1
zfrog serve

# Terminal 2
cd dashboard
npm install
npm run dev
```

 **Dashboard pages (27 routes):** `execuções` (`/`), `coleção` (`/colecao`), `extrair` (`/probe`), `captura` (`/captura`), `busca` (`/busca`), `fluxos` (`/fluxos`), `chat` (`/chat`), `comparar` (`/comparar`), `grafo` (`/grafo`), `precos` (`/precos`), `datasets` (`/datasets`), `graphql` (`/graphql`), `qualidade` (`/qualidade`), `analytics` (`/analytics`), `stats` (`/stats`), `timeline` (`/timeline`), `snapshots` (`/snapshots`), `workers` (`/workers`), `revisao` (`/revisao`), `roi` (`/roi`), `equipe` (`/equipe`), `config` (`/config`), `ajuda` (`/ajuda`), `webhooks` (`/webhooks`), `marketplace` (`/marketplace`), `design` (`/design`). Every CLI operation has an equivalent in the dashboard; remaining routes are reachable via palette `ctrl+k`.
 
 **Design system (TUI):** terminal-native tokens in `dashboard/src/styles/tui.css` (`#f4f2ec` paper, `#4f6b3a` / `#93b27b` accent, Iosevka 400/500, hairline 1px, radius 0) wired via `dashboard/src/routes/__root.tsx` + `globals.css`. Primitives in `dashboard/src/components/ui/tui.tsx` (`Gut`, `Sym`, `Spinner`, `Swatch`, `DetailLine`, `CodeBlock`, `Prompt`, `TuiModal`) and typed API client in `dashboard/src/lib/api.ts`. The `/design` page documents tokens, typography and all components.

> The dashboard requires CORS enabled on the API (already configured via `CORSMiddleware`).

### Docker

```bash
# Subir tudo (Redis + Worker + API)
docker compose up -d

# Ver logs
docker compose logs -f

# Parar
docker compose down
```

## Engines

Each engine has a distinct role and does not compete with the others.

| Engine | Role | When to use | Mode |
|-------|-------|-------------|------|
| **jump** | Reference: renders the page, takes a full-page screenshot and extracts design tokens | When the target is a visual reference | `jump` |
| **tongue** | Component: returns the HTML and computed CSS for a selector | To inspect a specific card, navbar or button | `tongue` |
| **Playwright** | Visual capture: renders and saves the rendered HTML + CSS/JS/images the browser loaded | Always. This is the default engine. | `scrape` |
| **Scrapy** | Discovery: maps which pages exist on the site | Entire site or batch of URLs | `extract` |
| **StaticFile** | Lightweight capture: single page with embedded assets | When the page does not depend on JavaScript | `singlepage` |
| **wget** | Assets: downloads images, CSS, fonts and icons | Companion for offline browsing | `mirror` |

Mode `auto` (the default) doesn't pick an engine on its own: it runs the probe and lets the
decision above happen. Without a mode, `zfrog clone <url>` captures visually.

Capture flow:

```
Usuário informa URL
       │
       ├─ Modo auto (padrão) ──► probe ──► Playwright (JS) ou StaticFile (página pronta)
       │
       └─ Site inteiro ──► Scrapy mapeia ──► Playwright captura cada página
                                                   │
                                              wget baixa os assets
```

Beyond the four capture engines, Zfrog also provides analysis and export engines:

| Engine | Mode | What it does |
|-------|------|-----------|
| **Analyze** | `analyze` | Technical audit (SEO, accessibility, performance) |
| **Compare** | `compare` | Fidelity Score between clone and original |
| **Ask** | `ask` | Natural-language question about the page |
| **PDF** | `pdf` | PDF rendering (A4) |
| **Summarize** | `summarize` | AI summary of the page |
| **Delta** | `delta` | Download only pages that changed |
| **Entities** | `entities` | Names of people, companies, places, dates, products |
| **Enrich** | `enrich`, `sentiment`, `tags` | Text sentiment and main topics |
| **Translate** | `translate` | Translate content |
| **Video** | `video` | HLS/DASH: detect and download video |
| **API Discovery** | `api_discovery` | Discover REST/GraphQL endpoints |

`zfrog engines` lists available engines with their origin (built-in, entry point
or local plugin).

### Engine Plugins

Any package can publish an engine: just declare the entry point
`[project.entry-points."zfrog.engines"]` pointing to an `EngineAdapter` subclass
(`name`, `execute`, `can_handle`) — Zfrog discovers and registers it on import. For local plugins,
put `.py` files in `plugins/` (or point `ZFROG_PLUGINS_DIR` elsewhere
directory); every `EngineAdapter` subclass in the file is registered. A broken plugin or
duplicate name is ignored with a warning — it never crashes Zfrog.

### Auto-Detection

The probe analyzes the page and suggests the capture engine:

- Presence of JS frameworks (React, Vue, Next, Nuxt, Angular)
- HTML size vs loaded scripts
- Body with little text and many scripts (SPA that only renders on the client)
- Returned content type

The decision is simple: **JavaScript detected → Playwright**; **simple page → StaticFile**.
A page the probe couldn't read also goes to Playwright — losing the rendering
loses the design, losing the shortcut only costs time. Scrapy kicks in when the target is the entire site
(`--mode extract`), and wget when the target is assets (`--mode mirror`).

The probe also records whether `robots.txt` restricts the URL (`robots_restricted`). The wget engine
respects `respect_robots` (default `true`; disable with `--no-robots`).

## Design References

The flow that gives the project its name: capture a page as a visual reference,
store it in a catalog and find it afterwards.

```bash
zfrog jump https://stripe.com --tag fintech --breakpoint desktop
zfrog jump https://stripe.com --viewport-only --format webp   # mais leve
```

This renders the page, takes a full-page screenshot and extracts its design
tokens — palette (with dominant color and each color's role), typography
(family, sizes, weights), scale (padding, margin, radii, shadows) and key assets.
The result becomes a **card** in the catalog, with the screenshot, source URL,
date, and tags you defined.

A specific component, instead of the whole page:

```bash
zfrog tongue https://stripe.com ".hero"
```

Returns the element's HTML and the **CSS the browser resolved for it**,
grouped into layout, color and typography — plus the box and direct children. The HTML
is sanitized (scripts, `onclick` and `javascript:` removed).

The catalog:

```bash
zfrog pond --tag fintech               # by tag
zfrog pond --color "#635BFF"           # by color dominante
zfrog pond --site stripe.com           # by site
zfrog pond --search "escuro com cards arredondados"
zfrog show <id>                        # detalhe, com a paleta
zfrog export <id> --format html        # mini style guide autocontido
```

The default capture also produces design: `zfrog clone <url>` runs token extraction
alongside the screenshot, in the same browser visit, and registers a card — for
page-capturing modes (`auto`, `mirror`, `scrape`, `singlepage`, `delta`).
Text-analysis engines are excluded, because a palette from them would be
noise.

In the dashboard, the **New extraction** screen offers *Design reference* mode (with
resolution, format, full-page or viewport, and tags) and *Extract component*
(with the CSS selector field).

**How description search works, and what it doesn't.** Each card is
described in words from the measured tokens — lightness and hue of
colors, corner rounding, shadow vocabulary, serif or not. This
description is embedded and ranking is by cosine similarity. This answers
"dark layouts with rounded cards" because extraction measured exactly
those attributes. It does **not** embed pixels: it won't find "the one with a dog photo".
For that, `visual_search.describe()` is the only point to change.

Without a configured embedding model, search falls back to word matching
— it degrades to something useful, not to nothing. Configure `ZFROG_AI_EMBEDDING` (and run
`zfrog pond --reindex`) to use vectors. Via the API, `POST /catalog/reindex` does
the same and reports how many vectors it wrote; without a model it responds `indexed: 0` with the
reason, instead of failing.

In the dashboard, the **Collection** route is the moodboard: screenshots in a grid, filters by
tag, color and site, description search, and a detail panel with palette,
typography, tags and notes.

## Change Detection

`mirror` and `scrape` jobs write a versioned snapshot to
`output/snapshots/<url_slug>/<timestamp>.json` (URL, date, engine and, per page, hash
SHA-256, size, title and extracted text). The `snapshots/` directory lives outside
job directories, so it survives the automatic 24h cleanup.

```bash
zfrog snapshots                          # listar todos os snapshots
zfrog snapshots https://example.com      # só os de uma URL
zfrog diff <snap-a.json> <snap-b.json>   # comparar (markdown)
zfrog diff <snap-a.json> <snap-b.json> --json   # relatório em JSON
```

The diff shows added, removed, changed (with the number of lines that changed)
and unchanged pages, plus the change ratio. Change is not an error: the command exits with
code 0.

When the ratio of changed pages reaches `ZFROG_CHANGE_ALERT_THRESHOLD`
(default `0.1`, (i.e. 10%), the job fires the `site.changed` webhook with `url`,
`change_ratio`, `added`, `removed`, `changed` and the snapshot path. Register the webhook
with `POST /webhooks` including `site.changed` in `events`.

## Versioning

`zfrog clone --versioned` stores each copy as a version in history (blobs with dedup
by SHA-256 in `versions/`, metadata per version). Default branch: `main`.

```bash
zfrog versions https://example.com              # lista (mais nova primeiro, marca HEAD)
zfrog branches https://example.com              # ramos
zfrog branch https://example.com experimental   # novo ramo a partir do HEAD
zfrog rollback https://example.com HEAD --dest ./saida
zfrog rollback https://example.com bfa11d2d9bc2
```

`ref` accepts `HEAD`, branch name, full id or id prefix (≥ 4 characters).

## Delta Crawling

`--mode delta` revalidates known pages with conditional requests (`If-None-Match` /
`If-Modified-Since`) and downloads only what changed. The first run downloads everything; subsequent runs
reuse validators stored in the previous snapshot.

The result is stored in `delta_report.json` (`added`, `changed`, `unchanged`, `removed`,
`bytes_saved`, `pages_written`). Pages revalidated with HTTP 304 don't produce a file, but
remain in the snapshot — otherwise the next run couldn't revalidate them.

## Scheduling

```bash
zfrog schedule add https://example.com --cron "0 2 * * *" --mode mirror --depth 1
zfrog schedule list
zfrog schedule run <id>      # roda agora
zfrog schedule remove <id>
zfrog scheduler --interval 30
```

5-field cron, with `*`, `*/n`, `a`, `a-b`, `a-b/n` and lists. When day-of-month and
day-of-week are both restricted, the classic "or" applies (either matching is enough). Schedules
are stored in `ZFROG_SCHEDULES_FILE` (default `schedules.json`).

## Search

SQLite index (FTS5) with text and semantic search:

```bash
zfrog search "frete grátis" --dir output --reindex
zfrog search "prazo de entrega" --semantic
```

`fulltext` uses FTS5 with BM25 ranking; `semantic` uses embeddings when an AI model is
configured and returns an empty list otherwise. Text extraction is lossless — lists and
tables are indexed (trafilatura's "article" extraction discarded entire `<ul>` elements).

## Multi-Site RAG

```bash
zfrog chat "qual o prazo de devolução?" --site lojaA=output/lojaA --site lojaB=output/lojaB
```

One question, multiple sites, answer with citations (`site`, `url`, `path`, excerpt). Citations
come from retrieved passages, not generated text — so they appear even without an AI model.

## Sessions (sites with login)

```bash
zfrog login https://site-com-login.com   # abre o navegador; entre e aperte Enter
zfrog sessions
zfrog logout site-com-login.com
```

The Playwright/PDF engines reuse the saved domain session automatically. Files
live in `ZFROG_SESSIONS_DIR` with `0600` permissions — protected only by file permissions
(not encrypted) and **must never** be committed to version control.

## Workflows (pipelines)

```bash
zfrog workflow list
zfrog workflow show <id>
zfrog workflow run <id>
```

Available steps: `probe`, `clone`, `summarize`, `analyze`, `extract`, `compare`, `pdf`,
`search`, `commit`.  `clone` defines the output directory that subsequent steps use. A
failing step stops the workflow and remaining steps are marked as skipped. In the dashboard,
the **Workflows** page builds and runs sequences; **Capture** builds the selector by clicking on the page.

## Kubernetes Operator

`deploy/k8s/` ships the `ZfrogJob` CRD (group `zfrog.io`, version `v1alpha1`), RBAC, the
operator Deployment and an example. The operator creates a Kubernetes Job per `ZfrogJob` and mirrors
the state (`Pending`/`Running`/`Succeeded`/`Failed`) in the resource `status`.

```bash
kubectl apply -f deploy/k8s/crd.yaml -f deploy/k8s/rbac.yaml -f deploy/k8s/operator.yaml
kubectl apply -f deploy/k8s/example-job.yaml
zfrog operator          # fora do cluster (usa ZFROG_K8S_API_SERVER)
```

## Quality and Compliance

**Security**: looks for miners, hidden iframes, obfuscated code, forms that send passwords
to another site, `javascript:`/`data:text/html` and executable downloads.

```bash
zfrog safety output/meusite
```

Jobs run this scan automatically (`ZFROG_SAFETY_ENABLED`); a finding becomes a log warning, never
fails the job.

## Engine Performance

```bash
zfrog analytics
```

Stores, per execution, the engine, result, duration and size — enough to answer which
engine works best on which type of site. Collection is automatic on every job.

## Audit

State-changing actions (create/cancel job, rollback, branch, schedule, workflow) are recorded in
JSONL, with origin derived from `X-Forwarded-For` → `X-Real-IP` → `User-Agent`.

```bash
zfrog audit --limit 20
zfrog audit --action version.rollback
```

## IPFS

```bash
zfrog ipfs output/meusite
```

Publishes via the HTTP API of a Kubo node (`ZFROG_IPFS_API_URL`) and returns the CID. Requires
`ZFROG_IPFS_ENABLED=true`; the content-addressable store already deduplicates files before sending.

## Session Encryption

With the `cryptography` package installed, session files are encrypted at rest with AES-GCM (key
in `ZFROG_SESSIONS_KEY_FILE`, mode `0600`). Without it, Zfrog warns **once per process** that the session
is in plaintext and keeps working — visible, not silent degradation. File tampering is
detected and treated as a missing session.

## Workflows with Dependencies

Steps can declare their dependencies:

```json
[{"id": "step-0", "type": "probe", "params": {"url": "https://x.com"}, "needs": []},
 {"id": "step-1", "type": "clone", "params": {"mode": "mirror"}, "needs": ["step-0"]}]
```

`needs` absent keeps the classic linear behavior (waits for the previous step) — so workflows
saved before this change keep working. `needs: []` means "I wait for no one" and allows
parallel execution, limited by `ZFROG_MAX_PARALLEL_STEPS`. A failing step marks dependents
as skipped and doesn't block independent branches.

## Chat with Cloned Content

```bash
zfrog chat ask "qual o prazo de entrega?" --site loja=output/loja --site blog=output/blog
zfrog chat ask "e a garantia?" --conversation <id> --history   # continua a conversa
zfrog chat list
```

The conversation keeps history: follow-up questions ("and the second one?") work because previous
turns are included in context. Citations come from retrieved passages, not generated text — they appear even
without an AI model. History is stored in `output/chats/<id>.json` (mode 0600).

## Relationship Graph

```bash
zfrog graph output/loja              # resumo + graph.json
zfrog graph output/loja --dot        # saída Graphviz
```

Extracts entities from pages and links what appears together: `co_occurrence` (same page) and `located_in`
(location mentioned in the same sentence as an organization).

## Quality and Compliance (continued)

```bash
zfrog tos https://exemplo.com.br                 # robots.txt + Termos de Uso
```

`tos` reads robots.txt and the terms page and returns `clear` / `caution` / `restricted` with the
exact excerpt as evidence. **This is automated reading, not legal advice.**

## Provenance (watermark)

```bash
zfrog watermark output/loja --source https://exemplo.com.br
zfrog watermark output/loja --verify
```

Inserts invisible metadata (meta tag, attribute, comment and zero-width marker in text) to
track the origin of a copy. **Visible text does not change.** This is provenance metadata — not DRM and not
proof of ownership: anyone can remove it.

## Costs

```bash
zfrog cost
```

Combines configured rates with what has been measured per execution: transfer (GB), compute
(CPU hours) and storage (GB-month). Without configured rates values stay at zero — Zfrog doesn't
make up money.

## Marketplace

```bash
zfrog market list
zfrog market install workflow-backup-diario
```

Workflows, engine plugins and templates published in `ZFROG_MARKETPLACE_DIR`. Installing a plugin writes the
file to `plugins/`, and the engine registry loads it next time — verified. Validation happens
on publish **and** on install, so a hand-edited file won't install broken content.

## Regions (edge)

```bash
zfrog regions https://loja.example.com.br/carrinho
```

Chooses where to process based on latency, available workers and data residency by domain, and
explains the decision. Configuration: `ZFROG_WORKER_REGIONS=sa-east:20:4,us-east:180:2`.

## Authentication and Roles

```bash
zfrog key create painel -r operator
zfrog key list
zfrog key revoke <id>
```

Three roles: `viewer` (read-only), `operator` (+ create/cancel jobs), `admin` (everything, including keys and
schedules). The secret is shown **once** — only the hash stays in the file (mode 0600). With
`ZFROG_AUTH_ENABLED=true`, both reads and writes require a key (`Authorization: Bearer` or
`X-API-Key`); without a key the response is 401, with insufficient role it is 403. `/health` stays open for
probes. The default is off, so nothing changes for existing users.

What each action requires beyond `read:jobs` (`viewer` is enough to read):

| Route | Action | Why |
|---|---|---|
| `POST /jobs`, `POST /jobs/{id}/cancel`, `DELETE /jobs` | `job:create` / `job:cancel` | consumes server bandwidth and disk |
| `POST /watermark` | `version:manage` | rewrites stored files |
| `POST /ipfs/publish` | `admin:all` | sends the copy to third parties |
| `POST /webhooks`, `DELETE /webhooks/{id}` | `admin:all` | the registry is global and the server will POST to the chosen URL |
| `DELETE /sessions/{domain}` | `admin:all` | the file holds valid cookies for a site |
| `POST /config/rate-limit` | `admin:all` | the limit is process-wide |
| `POST /extract/preview` | `read:jobs` | server-side fetch of chosen URL, but doesn't store anything |

`tests/test_route_auth.py` walks the FastAPI route table and fails if any state-changing route
is left without credentials — including a new WebSocket. The allowlist of public routes (`/`, `/health`,
`/auth/*`, docs) is checked so a mutating route can't be hidden.

**In the dashboard:** with authentication enabled, the dashboard uses a **signed cookie session** — no API
key in the browser.

1. The gate calls `GET /auth/config` to check whether the installation requires login.
2. With SSO configured, the button goes to `/auth/login`; the provider returns the browser to
   `/auth/callback`, which validates the ID token and **sets the** `zfrog_session` **cookie**
   (`HttpOnly`, `SameSite=Lax`, `Secure` when login came over https) and redirects to
   `ZFROG_POST_LOGIN_REDIRECT`.
3. Without SSO, the gate accepts a pasted API key, stored in `localStorage` — the path for
   those without an identity provider.
4. In both cases the gate confirms by requesting `GET /config`, which requires `read:jobs`: a 200 proves
   the credential is valid, rather than assuming.

The cookie is **signed, not encrypted** — there is no secret inside, only the user id and
expiry. Role and organization are **not** in the cookie: they are read from the users file on every
request, so deactivating someone or changing a role takes effect immediately, without waiting for cookie expiry.
The signing key lives in `ZFROG_WEBSESSION_KEY_FILE` (mode `0600`, created on first login).

Cookie sessions require `ZFROG_CORS_ORIGINS` with explicit origins — the browser only sends the cookie
when the response names the exact origin, and the spec forbids matching credentials with `*`. With the
default `*`, the API still works, but only via API key.

**WebSocket:** the browser sends the cookie on handshake, so the dashboard puts no credentials in the
URL. The server also checks `Origin` (without it, any site the user visited could
open a socket as them — *Cross-Site WebSocket Hijacking*). Script clients, which have no cookie,
send the key as a subprotocol: `Sec-WebSocket-Protocol: zfrog.v1, zfrog.key.<secret>`. It's a
header, not a query string — so it won't end up in a reverse proxy's access log.

## Outbound Integrations

```bash
zfrog integrations list
zfrog integrations push planilha dados.json
```

Sends records to Google Sheets, Airtable or Notion via each service's HTTP APIs. Failure in one batch doesn't
bring down the others: errors are returned in the result. Tokens are stored in a 0600 file and appear redacted in
listings.

## GraphQL

```bash
curl -X POST localhost:8000/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ jobs(limit: 5) { id url status } engines { name } }"}'
curl localhost:8000/graphql/schema      # SDL
```

 **read-only** API over the same data as the REST API: `jobs`, `job`, `snapshots`, `versions`, `schedules`,
`engines`, `analytics`, `search`, `sites`, `conversations`. It respects the requested selection (doesn't return fields
you didn't ask for) and returns per-field `errors` as the spec requires. Mutations are rejected.

## SDKs

```bash
cd sdk/js && bun test     # 22 testes
cd sdk/go && go test ./... # 12 testes (5 subtestes em TestEndpointsUseTheDocumentedRequests)
```

Clients for JavaScript/TypeScript (`sdk/js`, zero dependencies) and Go (`sdk/go`, stdlib only). They cover the
same REST endpoints, with typed errors (`ZfrogError` / `*APIError`) carrying status and `detail`.

## Teams: Users, Organizations and SSO

```bash
zfrog user create ana@empresa.com -r operator -p senha-inicial
zfrog org create "Acme Corp" --owner <user-id>
zfrog org add-member acme-corp <user-id> --role operator
zfrog user list
```

Passwords use PBKDF2-HMAC-SHA256 (200k iterations, per-user salt) and the file is `0600`. The password is
shown **once**; only the hash is stored.

**SSO (OpenID Connect)** — configure `ZFROG_OIDC_ISSUER` and `ZFROG_OIDC_CLIENT_ID` and login becomes
available at `GET /auth/login`. ID token signature verification is real (RS256/ES256 with
`cryptography`, key chosen by JWKS `kid`): issuer, audience, expiry and `nonce` are checked.
`state` is single-use and `nonce` must match what was sent at the start — without it a token
issued for another flow would be accepted.

**How SSO becomes a credential:** the callback authenticates with the provider, creates/updates the local user and
**sets the session cookie** described in *Authentication and Roles*. SSO doesn't need an API key
para o painel; a chave continua existindo para scripts e para those without an identity provider.

## Organization Isolation

Each organization has its own data: clones, versions, schedules, search, metrics, audit and
sessions live under `output/orgs/<slug>/`. The organization comes from the **caller's API key**, never from the request
body — a client can't write into another's space. Without an organization, everything stays in the
shared directory as before.

```bash
zfrog clone https://example.com --mode mirror --org acme-corp
```

## Review: Comments on Copies

```bash
zfrog annotate <job-id> index.html "o preço mudou aqui" --selector ".preco" --tag preco
zfrog annotations <job-id> --open
```

Comments accept a CSS selector (validated), tags and replies, and can be resolved. Export
produces Markdown for team review. In the dashboard, the **Review** page does the same via UI.

## Domain Profiles

```bash
zfrog domain list
zfrog domain suggest https://tribunal.jus.br/processo
```

Three built-in profiles — legal, e-commerce and news — with vocabulary, examples and entity types.
This specializes **the instructions given to the model** (terminology and examples), not the weights: it's
domain prompt engineering, not a trained model. Be clear about this difference before promising accuracy.

## Search Backends

`ZFROG_SEARCH_BACKEND` chooses between `sqlite` (default, embedded FTS5), `meilisearch` and `elasticsearch`.
The HTTP backends speak the real APIs; a network failure degrades to an empty result with a warning, never
crashing the request.

## Workers and Regions

```bash
zfrog worker run --region sa-east --capacity 4
zfrog worker list
zfrog worker assign https://loja.com.br
```

A worker registers, sends heartbeats and reports how many jobs it is processing. Assignment uses
the region decision (`zfrog regions`) and picks whoever has the most free capacity; without a live worker in the chosen
region, it falls back to another and explains why.

## Remote Marketplace

```bash
zfrog market-index build -o index.json --source "time interno"
zfrog market-index sync https://exemplo.com/index.json
```

The index carries a checksum per item, so you can tell whether what's installed matches what the index advertises.
Sync validates each payload before writing: an invalid item is counted as skipped, with the reason,
and **is not** written.

## Time Machine

```bash
zfrog timeline https://exemplo.com.br                       # lista as versões
zfrog timeline https://exemplo.com.br --when 2026-09-01     # a versão daquela data
zfrog timeline https://exemplo.com.br --ref 8cdd77f3 --page index.html
zfrog timeline https://exemplo.com.br --restore ./saida
```

`--when` accepts `2026-09-01`, `2026-09-01T12:00` or `2026-09-01 12:00`. Without a time, the whole day counts (the
last version until end of that day). `--page` returns the stored **original HTML** — not the extracted
text — and the dashboard opens the page in a viewer, making clear it's an archived copy not the
live site.

## Price Monitoring

```bash
zfrog price watch https://loja.com.br/produto
zfrog price changes https://loja.com.br/produto
```

Recognizes `R$ 1.234,56`, `$1,234.56`, `€ 89,90` and `1234 reais`. The separator convention comes from the **last**
separator in the number, so `1.234,56` is one thousand two hundred thirty-four point five six — and a
number without a currency sign (`2026`) is not a price. The alert fires when the change exceeds
`ZFROG_PRICE_ALERT_DROP_PCT` / `ZFROG_PRICE_ALERT_RISE_PCT`.

## Competitive Analysis and Trends

```bash
zfrog compare-sites -s lojaA=output/lojaA -s lojaB=output/lojaB --markdown
zfrog trends https://exemplo.com.br -t preco -t frete
```

The comparison puts clones side by side: pages, words, prices per item (with the cheapest), entities
in common, what each has uniquely, and real gaps. Trends count a term over
history and tell the direction — with "not enough history" when applicable, instead of guessing.

## Two-Factor Auth (TOTP)

```bash
zfrog totp add email SEGREDO_BASE32
zfrog totp code email
```

Generates 6-digit codes (RFC 6238) to log into **your own account**. The secrets file is
`0600`, the secret never appears in listings or logs, and `repr` masks it. This does **not** solve CAPTCHAs
or bypass any anti-automation control — deliberately out of scope.

## Dataset for Fine-Tuning

```bash
zfrog dataset output/meusite --kind extraction --format chat
```

Generates instruction/response pairs in JSONL (`chat` or `alpaca`) from clones. Examples are
**derived from the page itself** (extraction, extractive summary, questions per heading), never hallucinated.
Training itself runs elsewhere — it needs a GPU and a trainer not included in this project.
`ai/domains.py` specializes the **prompt** at use time; this prepares data to specialize **weights**.

## Return on Investment (ROI)

```bash
zfrog roi
```

    value = pages × minutes-per-page ÷ 60 × hourly-rate
    cost = compute + transfer + storage
    balance = value − cost

The first two are **your assumptions** (`ZFROG_ROI_HOURLY_RATE`, `ZFROG_ROI_MANUAL_MINUTES_PER_PAGE`), not
measurements — and the report returns them alongside the number. Without cost, the ratio is `—`, not "infinite".
Page count is estimated from generated files, and the report says so.

## Marketplace Server

```bash
zfrog market-serve --port 8200 --token s3cret
```

Serves the index over HTTP: `GET /index.json`, `GET /assets`, `GET /verify/{id}` and `POST /assets`. With
`--token`, publishing requires `Authorization: Bearer`; reads remain open (an index is meant to be
queried). `verify` compares the advertised checksum with the local file — that's what flags a tampered item.

## Dispatch Across Workers

```bash
zfrog dispatch --url https://exemplo.com --dry-run
zfrog dispatch --url https://exemplo.com --region sa-east
```

`--dry-run` shows which worker and region each job would go to, without sending anything. Without `--dry-run`, the job is
sent to the chosen worker's `/jobs` and the slot is marked as occupied — a response without `job_id` counts
as failure, not success.

## Permanent Archiving (Arweave)

```bash
zfrog arweave output/meusite
```

Packs the clone into tar.gz and publishes it in an Arweave transaction (ANS-104 format, RSA-PSS signature). Requires
`ZFROG_ARWEAVE_ENABLED=true` and a wallet at `ZFROG_ARWEAVE_WALLET_FILE`. **The protocol was implemented and
tested against a simulated gateway — never against the real network**, which requires paid AR.

## Running in Production

Zfrog was built to run locally. Running in production works, but requires four
adjustments — without them the system loses data or stays open.

**1. One volume, one `ZFROG_DATA_DIR`.** Everything Zfrog stores (API keys,
users, sessions, version history, indices) lives under this directory. Without it
each store writes inside the container's writable layer and **a restart wipes
everything**: you're locked out and need to re-login everywhere.

```bash
# docker-compose.prod.yml já faz isso
volumes:
  - zfrog-data:/app/data
environment:
  - ZFROG_DATA_DIR=/app/data
```

**2. Authentication on.** `ZFROG_AUTH_ENABLED=true` (the default is `false`, for
local use). With it off and the API exposed, anyone who can reach the port
can create jobs, publish to Arweave and read all clones. With it on, the dashboard
asks for the key once and stores it in the browser.

**3. Restricted CORS.** `ZFROG_CORS_ORIGINS=https://app.seudominio.com` instead of `*`.

**4. No access to the private network.** `ZFROG_ALLOW_PRIVATE_HOSTS=false`. Locally it's
`true` (you clone `localhost` and the LAN), but when exposed this turns the server into a
proxy to the private network: `POST /jobs {"url":"http://169.254.169.254/..."}` makes the
server read your cloud metadata.

```bash
docker compose -f docker-compose.prod.yml up -d
```

`api` runs with `--workers 2`: state that can't be per-process (jobs,
webhooks, SSO login) goes to Redis/valkey, so workers see each other. Without
Redis, use `--workers 1`.

### Known Limitations

- **SQLite with a single file per store, now with waiting.** `busy_timeout` (5s) and WAL
  are enabled in `storage/sqlite.py`, so dois workers concorrentes esperam a vez
  instead of getting `database is locked`. It is still SQLite: for many replicas the
  path is Postgres — stores have their own interface and `search_backends.py` already
  aceita Meilisearch ou Elasticsearch.
- **Versioned schema.** `PRAGMA user_version` plus an ordered list of migrations
  per store. The first entry is the original schema written with `IF NOT EXISTS`, so
  a database created before that migrates without breaking. When changing the format, **append** a
  entry; never edit one that already ran.
- **`/health` says "degraded" when it is.** It checks the broker and writes to the
  volume, and responds with 503 if either fails — before it always responded `healthy`, which
  that kept a broken instance in the load balancer. `/metrics` reads `analytics.py`
  (one line per engine execution); before it read an in-memory counter that nothing
  incremented and always returned `{}`.
- **Backup**: o volume inteiro. Guarde `sessions/.key` com cuidado — sem ele os
  encrypted cookies become unreadable even with a backup. The same goes for
  `websession.key`: losing it invalidates dashboard sessions (everyone logs in again),
  which is recoverable — but don't delete it expecting to keep sessions.
- **No built-in TLS.** Put nginx/Caddy in front; compose already listens on
  `127.0.0.1`.
- **The URL guard is not a sandbox.** It resolves the name before connecting, so
  a DNS that responds differently on the second lookup (rebinding) can still get through.

## Architecture

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

### Execution Flow

1. **Probe**: Analisa a URL e detecta tipo de site
2. **Route**: Select engine based on mode or detection
3. **Execute**: Download/process content
4. **Pipeline**: Reescreve links, remove trackers
5. **Package**: Gera ZIP para download

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-----------|
| `ZFROG_REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `ZFROG_OUTPUT_DIR` | `output` | Output directory |
| `ZFROG_MAX_CONCURRENT_JOBS` | `5` | Concurrent jobs |
| `ZFROG_WORKER_CONCURRENCY` | `2` | Celery workers |
| `ZFROG_PROXY_URL` | `None` | HTTP proxy |
| `ZFROG_HTTP_TIMEOUT_CONNECT` | `30` | Connection timeout (s) |
| `ZFROG_HTTP_TIMEOUT_READ` | `60` | Read timeout (s) |
| `ZFROG_PLUGINS_DIR` | `plugins` | Engine plugins directory |
| `ZFROG_CHANGE_ALERT_THRESHOLD` | `0.1` | Ratio of changed pages that triggers `site.changed` |
| `ZFROG_VERSIONS_DIR` | `versions` | Version history |
| `ZFROG_DELTA_MAX_PAGES` | `200` | Max pages revalidated per delta run |
| `ZFROG_SCHEDULES_FILE` | `schedules.json` | Saved schedules |
| `ZFROG_SCHEDULER_INTERVAL_S` | `30` | Scheduler check interval |
| `ZFROG_SEARCH_DB` | `search.db` | Search index |
| `ZFROG_SESSIONS_DIR` | `sessions` | Login sessions (0600 permissions) |
| `ZFROG_K8S_NAMESPACE` | `default` | Operator namespace |
| `ZFROG_K8S_WORKER_IMAGE` | `zfrog-worker:latest` | Image used for created Jobs |
| `ZFROG_K8S_API_SERVER` | `None` | Cluster API (outside cluster) |
| `ZFROG_SESSIONS_KEY_FILE` | `sessions/.key` | Sessions AES-GCM key (0600) |
| `ZFROG_IPFS_ENABLED` | `false` | Enable IPFS publishing |
| `ZFROG_IPFS_API_URL` | `http://127.0.0.1:5001` | Kubo node HTTP API |
| `ZFROG_SAFETY_ENABLED` | `true` | Security scan on each job |
| `ZFROG_AUDIT_LOG` | `audit.log` | Audit trail (JSONL, 0600) |
| `ZFROG_METRICS_DB` | `metrics.db` | Metrics por motor |
| `ZFROG_MAX_PARALLEL_STEPS` | `4` | Concurrent steps in a workflow |
| `ZFROG_SIGNIFICANCE_THRESHOLD` | `0.35` | Score above which a change is significant |
| `ZFROG_TRANSLATION_TARGET` | `pt` | Default target language |
| `ZFROG_VIDEO_MAX_BYTES` | `500000000` | Video download limit |
| `ZFROG_VIDEO_MAX_SEGMENTS` | `5000` | Video segments limit |
| `ZFROG_COST_PER_GB_TRANSFER` | `0` | Rate per GB transferred |
| `ZFROG_COST_PER_CPU_HOUR` | `0` | Rate per CPU hour |
| `ZFROG_COST_PER_GB_MONTH` | `0` | Rate per GB-month stored |
| `ZFROG_COST_CURRENCY` | `BRL` | Cost currency |
| `ZFROG_AUTH_ENABLED` | `false` | Require API key |
| `ZFROG_API_KEYS_FILE` | `api_keys.json` | Keys (hash, mode 0600) |
| `ZFROG_REGION` | `local` | Local region |
| `ZFROG_WORKER_REGIONS` | `` | Regions and latency (e.g. `sa-east:20:4`) |
| `ZFROG_MARKETPLACE_DIR` | `marketplace` | Published items |
| `ZFROG_INTEGRATIONS_DIR` | `integrations` | Outbound destinations (mode 0600) |
| `ZFROG_REGIONS` | | |
| `ZFROG_USERS_FILE` | `users.json` | Users (0600) |
| `ZFROG_ORGS_FILE` | `orgs.json` | Organizations (0600) |
| `ZFROG_DEFAULT_ORG` | `default` | Default organization |
| `ZFROG_OIDC_ISSUER` | `` | OpenID Connect issuer |
| `ZFROG_OIDC_CLIENT_ID` | `` | SSO client ID |
| `ZFROG_OIDC_CLIENT_SECRET` | `` | SSO client secret |
| `ZFROG_OIDC_REDIRECT_URI` | `http://localhost:8000/auth/callback` | SSO redirect |
| `ZFROG_OIDC_GROUP_ROLE_MAP` | `` | Groups → roles (`admins=admin`) |
| `ZFROG_ANNOTATIONS_DIR` | `annotations` | Comments |
| `ZFROG_DOMAIN_PROFILES_DIR` | `domains` | Domain profiles |
| `ZFROG_SEARCH_BACKEND` | `sqlite` | `sqlite`, `meilisearch` or `elasticsearch` |
| `ZFROG_MEILISEARCH_URL` | `http://127.0.0.1:7700` | Meilisearch server |
| `ZFROG_ELASTICSEARCH_URL` | `http://127.0.0.1:9200` | Elasticsearch server |
| `ZFROG_WORKERS_HEARTBEAT_TTL_S` | `60` | Worker heartbeat TTL |
| `ZFROG_WORKER_ID` | `` | This worker's identity |
| `ZFROG_WORKER_API_PORT` | `8000` | Worker API port |
| `ZFROG_DISPATCH_TIMEOUT_S` | `30` | Timeout dispatching a job to a worker |
| `ZFROG_PRICE_ALERT_DROP_PCT` | `5` | Drop (%) that triggers price alert |
| `ZFROG_PRICE_ALERT_RISE_PCT` | `5` | Rise (%) that triggers price alert |
| `ZFROG_PRICE_CURRENCY_HINT` | `BRL` | Currency when symbol is ambiguous |
| `ZFROG_TOTP_DIGITS` | `6` | Two-factor code digits |
| `ZFROG_FINETUNE_DIR` | `finetune` | Generated datasets |
| `ZFROG_ANALYSIS_DIR` | `analysis` | Prices and analyses |
| `ZFROG_MARKETPLACE_PORT` | `8200` | Marketplace server port |
| `ZFROG_ARWEAVE_ENABLED` | `false` | Enable permanent archiving |
| `ZFROG_ARWEAVE_WALLET_FILE` | `arweave-wallet.json` | Arweave wallet (0600) |
| `ZFROG_ROI_HOURLY_RATE` | `0` | Your hourly rate (ROI assumption) |
| `ZFROG_ROI_MANUAL_MINUTES_PER_PAGE` | `2` | Minutes per page (ROI assumption) |

### .env File

```bash
cp .env.example .env
# Editar conforme necessário
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-----------|
| GET | `/` | API info |
| POST | `/jobs` | Create job |
| GET | `/jobs` | List jobs |
| GET | `/jobs/{id}` | Job status |
| POST | `/jobs/{id}/cancel` | Cancel job |
| DELETE | `/jobs` | Clear list (keeps pending) |
| GET | `/jobs/{id}/result` | Job result |
| GET | `/jobs/{id}/download` | Download ZIP |
| GET | `/jobs/{id}/pdf` | Download PDF (`pdf` mode) |
| GET | `/snapshots` | List snapshots |
| GET | `/snapshots/{slug}/{file}` | Download snapshot (JSON) |
| POST | `/diff` | Compare two snapshots |
| GET | `/versions` | List site versions |
| POST | `/versions/rollback` | Restore a version |
| POST | `/versions/branches` | Create a branch |
| GET/POST | `/schedules` | List / create schedules |
| DELETE | `/schedules/{id}` | Remove schedule |
| POST | `/schedules/{id}/run` | Run schedule now |
| POST | `/search` | Search (text or semantic) |
| GET/DELETE | `/sessions` | List / delete saved sessions |
| GET/POST | `/workflows` | List / save workflows |
| DELETE | `/workflows/{id}` | Remove workflow |
| POST | `/workflows/{id}/run` | Run workflow |
| GET | `/extract/page` | Sanitized page for visual selector |
| POST | `/extract/preview` | Preview a CSS selector |
| GET | `/analytics/engines` | Engine performance |
| GET | `/analytics/totals` | Execution totals |
| GET | `/audit` | Audit trail |
| POST | `/safety/scan` | Scan for security risks |
| POST | `/ipfs/publish` | Publish a clone to IPFS |
| POST | `/graphql` | GraphQL query (read-only) |
| GET | `/graphql/schema` | GraphQL schema (SDL) |
| POST/GET | `/chat` | Ask / list conversations |
| GET | `/chat/{id}` | Read a conversation |
| POST | `/tos/check` | Check robots.txt and terms |
| POST | `/watermark` | Mark provenance |
| POST | `/watermark/verify` | Verify provenance |
| POST | `/graph` | Build relationship graph |
| GET | `/analytics/cost` | Estimated cost per engine |
| GET/DELETE | `/webhooks` | List / remove webhooks |
| GET/POST | `/marketplace` | List / publish items |
| POST | `/marketplace/{id}/install` | Install item |
| POST | `/marketplace/{id}/rate` | Rate item |
| POST | `/workflows/preview` | Explain a workflow and flag issues |
| GET/POST | `/keys` | List / create API keys |
| DELETE | `/keys/{id}` | Revoke key |
| GET/POST | `/integrations` | List / save destinations |
| POST | `/integrations/{name}/push` | Push records |
| GET | `/regions` | Regions and routing decision |
| GET/POST | `/users` | List / create users |
| GET/POST | `/orgs` | List / create organizations |
| POST | `/orgs/{id}/members` | Add member |
| GET/POST | `/annotations` | List / create comments |
| PATCH | `/annotations/{id}` | Edit comment |
| POST | `/annotations/{id}/resolve` | Resolve / reopen |
| POST | `/annotations/{id}/replies` | Reply |
| DELETE | `/annotations/{id}` | Delete comment |
| GET | `/annotations/export` | Export as Markdown |
| GET/POST | `/domains` | Domain profiles |
| GET/POST | `/workers` | List / register workers |
| POST | `/workers/heartbeat` | Heartbeat |
| GET | `/workers/assign` | Where a site would be processed |
| GET | `/marketplace/index` | Publishable index |
| POST | `/marketplace/sync` | Import remote index |
| GET | `/auth/config` | SSO configured? |
| GET | `/auth/login` | Start SSO login |
| GET | `/auth/callback` | Complete SSO login |
| GET | `/timeline` | Site versions |
| GET | `/timeline/resolve` | Version at a date |
| GET | `/timeline/pages` | Pages in a version |
| GET | `/timeline/page` | Page metadata |
| GET | `/timeline/content` | Archived HTML (for viewer) |
| GET | `/prices` | Price history |
| GET | `/prices/changes` | Price changes |
| POST | `/prices/watch` | Record prices from latest snapshot |
| GET | `/roi` | Return on automated work |
| GET/POST | `/totp` | Two-factor accounts |
| GET | `/totp/{name}/code` | Current code |
| DELETE | `/totp/{name}` | Remove account |
| POST | `/datasets` | Build fine-tuning dataset |
| POST | `/datasets/export` | Export dataset (JSONL) |
| POST | `/analysis/competitive` | Compare clones |
| POST | `/analysis/trends` | Term trends |
| GET | `/dispatch/plan` | Where a job would go |
| POST | `/dispatch` | Dispatch jobs to workers |
| GET | `/arweave/status` | Archiving configured? |
| POST | `/arweave/publish` | Publish to Arweave |
| GET | `/probe/{url}` | Analyze URL |
| GET | `/health` | Health check |
| GET | `/metrics` | Metrics |
| GET | `/stats` | Statistics |
| GET | `/config` | Current configuration |
| POST | `/config/rate-limit` | Update rate limit |
| POST | `/webhooks` | Register webhook |

## Production Features

### Rate Limiting
- Token bucket global com 1 req/s sustained, burst de 5
- Configurable via `--rate-limit` on the CLI and `POST /config/rate-limit`
- Global concurrency limit, so jobs don't spawn browsers endlessly

### Retry
- Exponential backoff com jitter (`@retry` em `utils/rate_limit.py`)
- Retry em erros HTTP 429, 500, 502, 503, 504

### Web Etiquette
- Simple User-Agent and basic headers: design capture doesn't need to masquerade
- Polite delay between requests (rate limiter) e `robots.txt` respeitado no motor wget
  (`--no-robots` desliga)

### Observability
- `GET /health` — checa o store de jobs (Redis) e o volume de estado e reporta o uso de
  memory; it responds with 503 when either fails, so the container healthcheck is meaningful
- `GET /metrics` — metrics per engine, read from the analytics store
- `GET /stats` — system statistics
- `zfrog audit` — trilha de auditoria em JSONL

### Automatic Cleanup
- Old jobs removed after 24h
- Output files cleaned automatically
- Configurable via `JobCleanup`

## Project Structure

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
│   ├── probe.py            # Auto-detection (suggests the engine)
│   ├── tokens.py           # Design-token extraction for a page
│   ├── components.py       # Component extraction (HTML + computed CSS)
│   ├── catalog.py          # Catálogo de referências (cards, tags, cores)
│   ├── visual_search.py    # Description search over the catalog
│   ├── queue.py            # Celery tasks
│   ├── engines/
│   │   ├── base.py         # Interface abstrata
│   │   ├── playwright.py   # Visual capture (default)
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
│       ├── stealth.py      # stable UA, viewport and locale
│       └── resources.py
├── dashboard/              # TUI Dashboard (Vite + React 19 + TanStack Router)
├── deploy/k8s/             # Operator + CRD (ZfrogJob)
├── tests/                  # 88 módulos (86 test_*.py + conftest + __init__)
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Development

```bash
pip install -e ".[dev]"

# Full suite. Redis is optional: without it the broker-dependent tests
# are skipped automatically (ZFROG_REDIS_URL points to wherever it lives).
pytest tests/ -q

# With Redis, the skipped ones also run:
ZFROG_REDIS_URL=redis://127.0.0.1:6379/0 pytest tests/ -q
```

What CI runs and what each step must satisfy:

| Step | Command | Status |
|---|---|---|
| Lockfile | `uv lock --check` | verde |
| Lint | `ruff check . --select F821,F811,F402,E9` | verde |
| Testes | `pytest tests/ -q` | verde (1721) |
| Tipos do painel | `tsc --noEmit` (Vite + TanStack) | verde |
| Build do painel | `vite build` (28 rotas, 27 sem __root) | verde |
**About linting:** the gate only covers **correctness** rules — `F821` (nome indefinido),
`F811` (redefinition), `F402` (import shadowed by loop variable) and `E9` (syntax).
These are the ones that catch bugs — and how a `new_script` used without being created in
`engines/static_file.py` was caught (the surrounding `except Exception` hid the `NameError` and logged
only "Failed to inline JS") and three `Optional[...]` without an import in `ai/extraction.py` — which were
`NameError` at runtime thanks to `from __future__ import annotations`.

Style rules in `pyproject.toml` (`E501` line length, `I001` import order,
import, `UP0xx` modernization) add up to ~450 violations in the existing codebase. Enabling them now
would turn CI red and no one would trust the gate; tightening this is follow-up work,
not an oversight. Meanwhile:

```bash
# See everything style rules would flag (not the gate)
uvx ruff@0.16.9 check . --statistics

# Only the files you touched, to avoid worsening the score
uvx ruff@0.16.9 check <arquivos>
```

Any changed file must pass the correctness rules — the gate ensures that.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

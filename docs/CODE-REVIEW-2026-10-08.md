# Code Review — zfrog — 2026-10-08

> Revisão completa em 5 slices: Backend Python, Frontend Dashboard+Landing, Tauri/Rust, Infra & Config, Tests+Docs. ~114 arquivos .py (~38k LOC), 27 rotas dashboard, 88 módulos de teste.

## Veredito

**Codebase maduro e defensivo, acima da média.** Padrões consistentes: escritas atômicas (`mkstemp+fsync+os.replace`) em ~90% dos stores, migrações SQLite `user_version`, PBKDF2-HMAC + TOTP RFC 6238, `url_guard` anti-SSRF, redação de credenciais, 0 TODO/FIXME, 0 segredo hard-coded, 0 pickle/eval fora de `marketplace.py` (admin-gated). **Mas há bugs de produção + highs que quebram runtime ou segurança — não é débito cosmético.**

**P0 — corrigir antes do próximo deploy:** XSS armazenado + ciclo de vida Tauri + 3 highs infra (Playwright quebrado no Docker, `.dockerignore` ausente vazando `sessions/.key` ao daemon, VPS prod com `AUTH_ENABLED=false`).

## Estatísticas

| Slice | Arquivos | LOC / nós | Notas |
|---|---|---|---|
| Backend `src/zfrog/` | 114 `.py` | ~38k LOC (~1.32 MB) | `api.py` 2704 linhas + `cli.py` 2728 linhas (god modules) |
| Tests | 88 módulos (86 `test_*.py` + conftest) | ~1721 nós coletados | `ruff E,F,I,UP` só; `pytest-cov` declarado mas nunca usado |
| Dashboard | 27 rotas, 14 componentes, 1 hook, 10 `lib/` | React 19 + Vite 7 + TanStack Router | `lib/api.ts` 1085 linhas / ~90 endpoints |
| Landing | 3 HTML | 820 linhas `index.html` | CSS/JS inline, tokens divergentes do dashboard |
| Tauri | 3 `.rs` + config | 289 linhas `lib.rs` | Tauri v2, sidecar `PyInstaller --onefile` |
| Infra | 2 workflows, 2 Dockerfiles, 3 compose, 5 manifests k8s | 98 `ZFROG_*` settings | 4 vars não documentadas em `.env.example` |
| Grep | 0 `except:` bare | ~74 `except Exception` (maioria intencional "nunca levantar") | 3 `print()` em lib, 10 `# noqa` justificadas |

## CRITICAL — corrigir obrigatório

| # | Onde | Evidência | Impacto |
|---|---|---|---|
| **C1 XSS armazenado** | `dashboard/src/routes/busca.tsx:204-214` + `src/zfrog/search.py:421-423` | `dangerouslySetInnerHTML={{__html: hit.snippet}}` — snippet vem de páginas de terceiros; `_clean_snippet` só faz `split/join+clip`, zero escape/sanitize | Site indexado injeta `<script>` → rouba `localStorage` (onde está `auth.ts` API key) |
| **C2 Tauri — token/URL stale** | `src-tauri/src/lib.rs:60-120` + `dashboard/src/lib/desktop.ts` | Rust gera `pick_unused_port()+generate_token()` a cada boot e expõe via `app.manage(SidecarReady)`; frontend cacheia em `localStorage` e reutiliza no próximo boot; `get_sidecar_config` responde antes do sidecar estar healthy (poll 16×500ms) | Após restart, frontend fala com porta/token mortos → dashboard offline; corrida `get_sidecar_config` → ~50% boots falham |
| **C3 `except: pass` silenciando patch de auth WS** | `src/zfrog/desktop_entry.py:84-118` | `try: _ws._may_watch = _desktop_may_watch; _ws._origin_allowed=... except Exception: pass` — monkeypatch de nomes privados | Se `ws.py` renomear `_may_watch`, sidecar sobe sem auth de WS e ninguém loga |

## HIGH

| # | Onde | Evidência | Fix sugerido |
|---|---|---|---|
| **H1 Redis síncrono no event loop** | `src/zfrog/storage/redis_store.py:20-34` + `src/zfrog/queue.py:114-128` + `src/zfrog/orchestrator.py:33-100` | `_get_redis() = redis.from_url(...)` (sync) criado por operação, nunca `close()`; `publish_job_event` abre `aioredis.from_url` + `close()` por evento (10+/job) | Singleton `redis.asyncio` com pool; `close()` só no shutdown |
| **H2 Redis por request em api.py** | `src/zfrog/api.py:255-259` | `r = redis.from_url(...); r.ping()` por `create_job` sem `close()` | Reusar client compartilhado; cachear `use_celery` |
| **H3 Playwright quebrado no Docker** | `Dockerfile:25,35` | `RUN playwright install --with-deps chromium` como `root` → `/root/.cache/ms-playwright`; runtime `USER zfrog` com `HOME=/app` | `PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright` + `chown` ou instalar como `zfrog` |
| **H4 Sem `.dockerignore` + `.dockerignore` gitignored** | `.gitignore:41` + ausência de `.dockerignore` | Todo repo (`sessions/.key`, `api_keys.json`, `users.json`, `*.db`, `output/`) enviado ao daemon | Criar `.dockerignore` real; remover linha do `.gitignore` |
| **H5 `websession.key` commitável** | `.gitignore` | `sessions/.key` / `*.key` não ignorados explicitamente | Adicionar `websession.key` + `*.key` |
| **H6 k8s Jobs não-funcionais** | `deploy/k8s/operator.yaml` + `src/zfrog/k8s/operator.py` | `ZFROG_JOB_URL/MODE/MAX_DEPTH` que nenhum código lê; `command` ausente; `Dockerfile.worker` inexistente | Alinhar env com `orchestrator` ou remover k8s até ter worker image |
| **H7 VPS prod sem auth** | `deploy/docker-compose.prod.vps.yml:34` | `ZFROG_AUTH_ENABLED=false` default em domínio público | Default `true`; `false` só com override local |
| **H8 Tauri `security.csp = null`** | `src-tauri/tauri.conf.json:24` | CSP desabilitada | `default-src 'self'; script-src 'self'` |
| **H9 Tauri token em argv** | `src-tauri/src/lib.rs:72` | `--auth-token <hex>` visível em `/proc/<pid>/cmdline` | Passar via `env` |
| **H10 WS reconexão infinita** | `dashboard/src/hooks/useWebSocket.ts` | `onclose → reconnect` sem checar `unmounted`; `callback` em deps → reconecta a cada render | `ref` para callback + `aborted` flag no cleanup |
| **H11 `design.tsx` diverge de `tui.css`** | `dashboard/src/routes/design.tsx` vs `src/styles/tui.css` | `COLOR_TOKENS` hardcoded com hex diferente de `--fg-muted/--fg-dim` | Derivar de `tui.css` ou remover specimen |

## MEDIUM

| Onde | Problema |
|---|---|
| `models.py:84` `api.py:270` `cleanup.py:116` | `datetime.utcnow()` deprecado (Python 3.12+) |
| `src/zfrog/versioning.py:99,116` | `_write_refs/_write_version` com `write_text` não-atômico (crash corrompe `refs.json`) |
| `orchestrator.py:36-100` | `except Exception: pass` sem log em 4 pontos Redis |
| `api.py` + `cli.py` | God modules sem decomposição (~200 endpoints num arquivo) |
| `models.py:22` `orchestrator.py:170` `workflows.py:49` | Taxonomia de modos triplicada (`Literal` + `if/elif` + `STEP_ENGINES`) |
| `config.py:118,175` | Segredos como `str` em vez de `SecretStr` |
| `orchestrator.py:213` | `asyncio.create_task` fire-and-forget sem referência (GC pode coletar) |
| `orchestrator.py:22` `cli.py:62` | Import de `_global_limiter/_global_concurrency` (privados) |
| `ai_config.yaml` | Montado nos composes mas nunca lido |
| `wrangler.jsonc` + `landing/` | Paleta `--papel/--tinta` divergente de `dashboard/tui.css` |
| `.github/workflows/ci.yml` | Lint gate só `F821,F811,F402,E9` (fração de `ruff E,F,I,UP`) |
| `tests/conftest.py` | `_ensure_fixtures()` escreve `fixtures/*.html` na árvore do repo no import |
| `docs/README.md` `README.md` `PLANO-*.md` | Contagens stale: "80 módulos / 21 JS tests / 1713 suite / 4 engines" vs realidade 114 / 27 rotas / 1721 / 6 engines |
| `scripts/build-sidecar.py` | `target_triple()` erra em `arm64/i686`; `matrix.target` em `desktop.yml` nunca usado |
| `Cargo.toml` | `serde_json` + `reqwest/json` declarados e não usados |
| `sdk/js` `sdk/go` | Suites nunca rodam no CI; guard `DOCUMENTED_ENDPOINTS` com 24 endpoints vs ~120 reais |

## LOW / INFO

`print()` em `cleanup.py:152,180` `webhooks.py:144` → `logger.warning`; `subprocess.run(["which",...])` em `api.py:2382` → `shutil.which`; `pip install -e .` em `Dockerfile:18` (editável em prod) → `pip install .`; defaults de `max_depth` inconsistentes (`models 3` vs `dispatch 1` vs `scheduler 1`); `desktop_entry.py` compara token com `!=` não constant-time → `hmac.compare_digest`; `src-tauri` `kill()` de `CommandChild` deixa filho Python de `PyInstaller --onefile` órfão.

Falsos-positivos: `search.py:452` `f"WHERE {where}"` é seguro (params via `?`); `auth.py:66` `SHA-256` sem salt é OK para API key de 256 bits (senhas usam PBKDF2).

## Arquitetura

`cli.py`/`api.py` → `orchestrator.run_job` (probe→route→engine→pipeline→package) → `engines/*` (playwright/wget/scrapy/static/pdf/video/analyze) → `pipeline/*` → `storage/sqlite` (WAL) + stores JSON atômicos + `versioning` content-addressed. Fila opcional `Celery`/`Redis`, `workers` registry + `dispatch` HTTP, `k8s operator` (CRD). Frontend: Vite SPA + TanStack Router (27 rotas) + TanStack Query (só 4 rotas usam) + `lib/api.ts` único. Tauri v2 sidecar loopback com token efêmero.

## Plano de ação

**P0 (hoje):** 1) Sanitizar snippet + remover `dangerouslySetInnerHTML`; 2) Tauri: `sessionStorage` só, `get_sidecar_config` aguardar `sidecar-ready`, token via `env`; 3) Docker: `.dockerignore`, `PLAYWRIGHT_BROWSERS_PATH`, `pip install .` não-editável. **P1 (semana):** Redis singleton, versioning atômico, `AUTH_ENABLED=true` default, `datetime.now(timezone.utc)`, WS hook fix. **P2 (mês):** Split `api.py`/`cli.py`, centralizar `MODE→engine`, CI `ruff` completo + cov + SDK jobs, unificar design tokens, decidir k8s.

> Preservar: escritas atômicas, `url_guard`, PBKDF2+TOTP, `Instructor` com fallback, `respx` wire assertions, `i18n` tipada.

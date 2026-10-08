# Plano: codebase em EN + front trilíngue (pt-BR / en / es)

Data: 2026-10-07. Status: Todas as fases concluídas (2026-10-07) — Fase 1 (dashboard), Fase 3 (landing), Fase 2 (Python), Fase 4 (docs):
- Dicionário inline pt/en/es (~50 chaves) + `data-i18n` / `data-i18n-aria` / `data-i18n-alt` / `data-i18n-meta`.
- `?lang=` → `localStorage` → `navigator.language` → fallback `pt`; botões PT/EN/ES no header; `hreflang` + `og:locale` dinâmico.
- PT é o HTML estático (no-JS mostra PT); comandos/identificadores/código intocados; botões copiar traduzidos.
- Verificado no browser nos 3 idiomas. `design-system.html` / `system-design.html` seguem só PT (docs internos).
Fase 2 (Python em EN) concluída (2026-10-07):
- ~70 arquivos: orquestrador/api/audit/url_guard/storage, ai/*, engines/*, cli, workers, integrations, pipeline, analysis, etc. migrados para EN (mensagens, helps, logs, docstrings, prompts).
- Verde: 1713 passed. Últimos 3 fix: visual_search (EN color/lightness/hue words, IndexResult reasons), catalog (docstring), lexical scorer substring collision (serif em sans-serif) → teste ajustado para 'georgia'.
- Restam 61 acentos intencionais: ai/domains.py (fixtures de domínio PT — dado, não UI) + analysis/trends.py (exemplos de folding 'Preço').
Fase 4 (Docs) concluída (2026-10-07):
- README.md → EN (prosa + headings + comentários de shell + árvore); README.pt-BR.md preservado verbatim em PT (1328 linhas, 122 fences, idêntico ao original).
- 6 acentos remanescentes no README EN são fixture data dentro de fences (queries exemplo: 'preço do produto', anotações) — prosa fora de fences 0 acentos.
- Código/landing/dashboard já EN; docs/PLANO-I18N.md atualizado.

## Fase 1 — resultado
- 1195 chaves × 3 idiomas (en/pt/es), paridade verificada por `dashboard/scripts/i18n-check.py` (`bun run i18n:check`).
- Convertidos: shell (`__root`), home, `jobs/$id`, AuthGate, TuiCombobox, STATUS_* + MODES em `lib/labels.ts`, `nav.ts` morto removido, todas as 27 rotas.
- `bunx tsc --noEmit` limpo; verificado no browser nos 3 idiomas (PT/EN/ES).
- Seletor PT/EN/ES no statusbar; `navigator.language` → `localStorage` → fallback `en`; `initLang()` no mount.
- Convenções: sem interpolação no `t()` — usar `.replace()` / splits; chaves `status.*`, `mode.<id>.*`, `palette.<slug>`, namespaces por rota.

## Estado inicial (levantamento)
- Dashboard: 0 infra de i18n, ~286 strings PT-BR hardcoded em ~30 arquivos (27 rotas + componentes).
- Python (`src/zfrog`): 70 arquivos com PT embutido (mensagens de job, erros de API, prompts de IA, helps da CLI, docstrings).
- Testes: 86 arquivos, nenhum assert em PT.
- Landing: 3 HTMLs estáticos PT-BR, sem infra de idioma.

## Decisões
| Camada | Decisão |
|---|---|
| Código, comentários, docstrings, logs, erros de API, mensagens de job | EN hardcoded |
| Dashboard (UI visível) | Chaves EN + dicionários `pt`/`en`/`es`, dicionário tipado próprio (sem lib externa) |
| Landing | 1 HTML + dicionário JS inline por página (`?lang=` + `navigator.language` + botões PT/EN/ES) |
| Detecção de idioma | `navigator.language` → `localStorage` override → fallback `en` |
| Idiomas futuros | +1 arquivo/dicionário por idioma, zero mudança de código |

## Fases
- **Fase 1 — Dashboard i18n**: `dashboard/src/lib/i18n.ts` (tipo `Lang`, dicionários tipados, `useLang()` + `t(key)` + seletor no header); converter rota por rota (`__root` → `index` → `jobs/$id` → resto por densidade); `pt` = strings atuais, `en`/`es` traduzidos por rota; verificação `tsc` + screenshot por rota/idioma.
- **Fase 2 — Python em EN**: `orchestrator.py`, `api.py`, `cli.py`, `utils/audit.py`, prompts `ai/*` (testar 1 chamada por prompt alterado); regra: grep em CI falha com PT em `src/` (exceto fixtures); verificação: suite + `ruff`.
- **Fase 3 — Landing trilíngue**: dict inline em `index.html` (~60 chaves); `design-system.html`/`system-design.html` depois; `og:locale` + `hreflang`; verificação: render nos 3 idiomas.
- **Fase 4 — Docs**: `README.md` → EN + `README.pt-BR.md`; comentários EN em quem tocar o arquivo.

## Não fazer
- Traduzir comandos (`jump/tongue/pond/export`), rotas de API, chaves de config, nomes de arquivos.
- Lib de i18n pesada no dashboard.
- Traduzir testes (nenhum assert em PT).

## Ordem
1 → 3 (landing pequena, valor cedo) → 2 → 4. Todas concluídas.

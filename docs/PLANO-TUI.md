# Plano de migração para a interface TUI

Complementa `DESIGN.md` e o documento de referências [CC]/Codex. Status: **CONCLUÍDO (100%)**.

---

## Estado atual (Concluído)

- **Fundação**: `dashboard/src/styles/tui.css` — tokens (papel claro principal `#f4f2ec`, acento pântano `#4f6b3a` / `#93b27b`, escuro derivado `#161512`), Iosevka 400/500, radius 0, sem glass/glow/gradiente. Hairlines de 1px.
- **Primitivos**: `dashboard/src/components/ui/tui.tsx` — Gut, Sym, Spinner, Swatch, DetailLine (⎿), CodeBlock, Prompt, TuiModal.
- **Shell**: `dashboard/src/routes/__root.tsx` — header minimalista de 1 linha com 5 abas principais (`execuções`, `coleção`, `busca`, `extrair`, `config`), resto acessível via paleta `ctrl+k` (20 rotas indexadas), status bar com health real, prompt de rodapé (`jump <url>`).
- **Sistema antigo removido**: 100% dos componentes legados do Pond Glass (`Card`, `Button`, `Input`, `Select`, `Badge`, `Skeleton`, `StatCard`, `ds-components.css`, `ds-tokens.css`, `Navbar.tsx`, `CommandPalette.tsx`) foram eliminados.

---

## Fase A — Decisões Fechadas (DESIGN.md §12) [CONCLUÍDO]

1. [x] **Acento**: Pântano do mascote mantido (`#4f6b3a` no tema claro / `#93b27b` no tema escuro).
2. [x] **Tema principal**: Papel quente claro (`#f4f2ec`) como primário, com tema escuro de alto contraste derivado via `data-theme="dark"`.
3. [x] **Navegação**: Header de 1 linha com 5 abas principais; todas as 20 rotas acessíveis via Command Palette (`ctrl+k`).
4. [x] **Tipografia**: Iosevka Mono como fonte universal (pesos 400 e 500, tamanhos 12px, 13px e 15px, ritmo vertical 1.5lh).

---

## Fase B — Migração das 20 Telas [CONCLUÍDO]

Todas as rotas foram convertidas para pura TUI, integradas à API real e validadas:

1. [x] **Execuções** (`routes/index.tsx`) — Log em grade com `j/k`, `enter` expande com ⎿, swatches reais, `/` filtra, prompt no rodapé.
2. [x] **Coleção** (`routes/colecao.tsx`) — Grid TUI de referências visuais com navegação por teclado (`j/k/setas`), `Enter` abre modal puro de inspeção completa com swatches e cópia de tokens CSS.
3. [x] **Nova extração / Probe** (`routes/probe.tsx`) — Lançador rápido com 17 modos zfrog (`jump`, `tongue`, `auto`…), diagnóstico de JS/SPA e histórico de probes.
4. [x] **Busca** (`routes/busca.tsx`) — Busca textual e semântica pura com filtros de modo, pontuação mono e stream de resultados.
5. [x] **Snapshots** (`routes/snapshots.tsx`) — Seletor de snapshots e stream de diff monospaçado com marcadores `+`, `-`, `~`, `=`.
6. [x] **Captura** (`routes/captura.tsx`) — Inspetor de blocos e extração via seletor CSS com iframe interativo.
7. [x] **Fluxos** (`routes/fluxos.tsx`) — Criador de workflows encadeados, logs de passos em terminal e agendador cron.
8. [x] **Revisão** (`routes/revisao.tsx`) — Caderno de anotações com filtros de autor/tag, criação inline e resolução toggleable.
9. [x] **Stats** (`routes/stats.tsx`) — Histograma de atividade em ASCII puro de 14 dias, métricas de capacidade e ranking de domínios.
10. [x] **Analytics** (`routes/analytics.tsx`) — Desempenho e latência por motor de extração, stream semanal e taxas de sucesso.
11. [x] **ROI** (`routes/roi.tsx`) — Painel financeiro com horas salvas, páginas automatizadas e economia monetária calculada.
12. [x] **Workers** (`routes/workers.tsx`) — Nós de execução, filtros por região, métricas de slots e status de liveness.
13. [x] **Qualidade** (`routes/qualidade.tsx`) — Auditoria de conformidade, PII e achados de segurança classificados por severidade.
14. [x] **Config** (`routes/config.tsx`) — Limites operacionais, cabeçalhos de requisição e alternância de temas e redução de movimento.
15. [x] **Webhooks** (`routes/webhooks.tsx`) — Registro de endpoints de integração e seletor de eventos suportados.
16. [x] **Equipe** (`routes/equipe.tsx`) — Tabela de usuários e organizações, atribuição de perfis de acesso (`admin`, `operator`, `viewer`).
17. [x] **Marketplace** (`routes/marketplace.tsx`) — Navegador de pacotes e extensões da comunidade com instalação/desinstalação direta.
18. [x] **Ajuda** (`routes/ajuda.tsx`) — Tabela de atalhos globais de teclado, matriz dos 17 modos de captura e comandos de terminal.
19. [x] **Máquina do Tempo** (`routes/timeline.tsx`) — Navegador de snapshots históricos e visualização de páginas arquivadas.
20. [x] **Detalhe da Execução** (`routes/jobs/$id.tsx`) — Monitor ao vivo com streaming de WebSocket, cancelamento e reexecução.

---

## Fase C — Remoção do Sistema Antigo [CONCLUÍDO]

Eliminados do repositório:
- `dashboard/src/ds-components.css`
- `dashboard/src/ds-tokens.css`
- `dashboard/src/routes/design.module.css`
- `dashboard/src/components/Navbar.tsx`
- `dashboard/src/components/CommandPalette.tsx`
- `dashboard/src/components/DetailRow.tsx`
- Componentes legados em `dashboard/src/components/ui/` (`card.tsx`, `button.tsx`, `input.tsx`, `select.tsx`, `modal.tsx`, `badge.tsx`, `ds.tsx`, `empty.tsx`, `skeleton.tsx`, `stat-card.tsx`).
- `AuthGate.tsx` e `ToastRegion.tsx` totalmente migrados para TUI.

---

## Fase D — Polimento & Validação [CONCLUÍDO]

- [x] `/design` reescrita como specimen vivo dos novos tokens TUI, demonstrando contraste WCAG AA, matriz de símbolos monospaçados, formulários e primitivos.
- [x] Contraste WCAG AA validado para todas as combinações de superfície e texto.
- [x] `prefers-reduced-motion` respeitado nos spinners e transições.
- [x] Testes de TypeScript (`npx tsc --noEmit`) aprovados com 0 erros em todo o dashboard.
- [x] Build de produção (`npm run build`) validado com sucesso.
 - [x] Suite de testes de backend (`uv run pytest tests/ -q`): 1713 testes passando (63 warnings).
- [x] Snapshots visuais gerados via Playwright em modo claro e escuro.

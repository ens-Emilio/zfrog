# Plano de Ação: 100% de Cobertura Funcional na UI do Zfrog

Este plano estabelece as etapas para atingir **100% de paridade funcional** entre o backend (`zfrog` CLI, motores de IA, pipelines, storage e API FastAPI) e o frontend TUI.

---

## 1. Diagnóstico de Gaps de Cobertura

Atualmente, o frontend cobre o fluxo primário de capturas, inspeção visual, catálogo de tokens, diffs, agendamentos, governança e métricas. Os seguintes subsistemas do backend ainda não possuem reflexo na interface:

```
┌───────────────────────────────────────┬────────────────────────────────────────┬────────────────────────────┐
│ Subsistema do Backend                 │ Endpoints / CLI                        │ Destino Proposto na UI     │
├───────────────────────────────────────┼────────────────────────────────────────┼────────────────────────────┤
│ 1. IA Conversacional (RAG de Sites)   │ POST /chat, GET /chat, zfrog ask       │ Nova rota: /chat           │
│ 2. Inteligência Competitiva           │ POST /analysis/competitive, zfrog comp │ Nova rota: /comparar       │
│ 3. Análise de Tendências Temporais    │ POST /analysis/trends, zfrog trends    │ Integrado em /comparar     │
│ 4. Datasets para Fine-Tuning          │ POST /datasets, POST /datasets/export  │ Nova rota: /datasets       │
│ 5. Grafo de Conhecimento / Entidades  │ POST /graph, zfrog graph               │ Nova rota: /grafo          │
│ 6. Monitor de Preços (E-commerce)     │ GET/POST /prices, POST /prices/watch   │ Nova rota: /precos         │
│ 7. Cofre TOTP / 2FA para Login        │ GET/POST/DELETE /totp, GET /totp/code  │ Expansão em /captura       │
│ 8. Armazenamento Web3 (Arweave)       │ GET /arweave/status, POST /publish     │ Expansão em /qualidade     │
│ 9. Modos Avançados de Extração        │ video, api_discovery, translate, etc.  │ Expansão em /probe         │
│ 10. Explorador Interativo GraphQL     │ POST /graphql, GET /graphql/schema     │ Nova rota: /graphql        │
│ 11. Multi-Region Job Dispatch         │ GET /dispatch/plan, POST /dispatch     │ Expansão em /workers       │
└───────────────────────────────────────┴────────────────────────────────────────┴────────────────────────────┘
```

---

## 2. Cronograma de Execução por Fases

### Fase 1: Contratos e Client de API (`dashboard/src/lib/api.ts`)
Implementar as tipagens e métodos no cliente TypeScript para todos os endpoints faltantes:
- **Chat:** `getChatConversations()`, `getChatHistory(id)`, `sendChatMessage(data)`.
- **Competitivo & Tendências:** `compareSites(sites, aspects)`, `analyzeTrends(url, windowDays)`.
- **Datasets:** `buildDataset(pages, kind)`, `exportDataset(format)`.
- **Grafo:** `generateKnowledgeGraph(dir, maxDepth, extractEntities)`.
- **Preços:** `getPrices(url)`, `getPriceChanges(url)`, `watchPrice(data)`.
- **TOTP / 2FA:** `listTotp()`, `addTotp(name, secret)`, `getTotpCode(name)`, `deleteTotp(name)`.
- **Arweave:** `getArweaveStatus()`, `publishArweave(dir, tags)`.
- **GraphQL:** `executeGraphQL(query, variables)`, `getGraphQLSchema()`.
- **Dispatch:** `getDispatchPlan(urls, regions)`, `dispatchJobs(urls, regions)`.

---

### Fase 2: Rota `/chat` (Chat com o Site / RAG Conversacional)
Criar [`dashboard/src/routes/chat.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/chat.tsx):
- **Layout TUI:**
  - Coluna lateral de sessões anteriores (`GET /chat`) com opção de nova conversa.
  - Seletor de contexto: site clonado específico ou índice geral.
  - Fluxo de mensagens no terminal:
    ```
    > usuário: quais são os principais termos de serviço citados na página de pricing?
    < zfrog: com base nos arquivos /pricing.html e /terms.html:
      1. Os planos anuais contam com renovação automática...
      [fontes: output/example.com/pricing.html:42, /terms.html:115]
    ```
  - Input de prompt com indicador de envio (`[enter]` para enviar, `shift+enter` para nova linha).
  - Exportação da conversa em Markdown.

---

### Fase 3: Rota `/comparar` (Inteligência Competitiva & Tendências)
Criar [`dashboard/src/routes/comparar.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/comparar.tsx):
- **Comparação Lado a Lado (`/analysis/competitive`):**
  - Seleção de 2 ou mais diretórios/sites clonados (ex.: `empresa-a.com` vs `empresa-b.com`).
  - Matriz comparativa TUI:
    - Volume de páginas e profundidade;
    - Tecnologias e bibliotecas detectadas;
    - Tom de voz e sentimento geral de conteúdo;
    - Cores primárias e tokens de design lado a lado.
- **Análise de Tendências Temporais (`/analysis/trends`):**
  - Rastreamento de palavras-chave e tópicos em diferentes versões arquivadas do mesmo site.
  - Gráficos de barras em caracteres de bloco ASCII (`██████░░░░ 60%`).

---

### Fase 4: Rota `/datasets` (Exportação para Fine-Tuning de IA)
Criar [`dashboard/src/routes/datasets.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/datasets.tsx):
- **Configurador de Datasets (`/datasets`):**
  - Seletor de diretório de origem.
  - Seleção de formato:
    - `ShareGPT` (conversas multiturno)
    - `Alpaca` (instruction / input / output)
    - `JSONL` (pares prompt/completion)
    - `Raw Text` (corpus limpo para pré-treino)
  - Limpeza de ruído: remoção de headers, footers, tags de script e cookies de rastreamento.
  - Preview ao vivo dos primeiros exemplos gerados em `<CodeBlock>`.
  - Botão de exportação e download do arquivo compilado (`/datasets/export`).

---

### Fase 5: Rota `/grafo` (Mapeamento de Grafo de Conhecimento)
Criar [`dashboard/src/routes/grafo.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/grafo.tsx):
- **Extração de Grafo (`/graph`):**
  - Mapeamento de nós (páginas, tópicos, pessoas, organizações mencionadas) e arestas (hiperlinks internos, referências cruzadas).
  - Visualização em lista/árvore hierárquica TUI:
    ```
    ┌─ Grafo de Entidades: example.com ─────────────────────────────┐
    │ ├─ [Página] /sobre-nos                                        │
    │ │  ├─ (Entidade) "Fundador Silva" [Pessoa]                   │
    │ │  └─ (Link) ──> /carreiras                                   │
    │ └─ [Página] /produtos                                         │
    │    └─ (Entidade) "Cloud Engine v2" [Produto]                 │
    └───────────────────────────────────────────────────────────────┘
    ```
  - Tabela com métricas de centralidade (páginas mais referenciadas, páginas órfãs).

---

### Fase 6: Rota `/precos` (Monitoramento de Preços em E-Commerce)
Criar [`dashboard/src/routes/precos.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/precos.tsx):
- **Vigilância de Preços (`/prices`, `/prices/changes`, `/prices/watch`):**
  - Adicionar nova URL de produto para vigilância periódica.
  - Tabela de preços detectados:
    - Produto / URL
    - Preço Atual
    - Preço Anterior
    - Variação percentual com símbolos (`▲ +12.5%` ou `▼ -8.0%`)
    - Data da última alteração
  - Histórico de preços por produto com timeline de valores.

---

### Fase 7: Expansão de Credenciais (`/captura`) e Web3 (`/qualidade`)
1. **Cofre TOTP / 2FA em [`/captura`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/captura.tsx):**
   - Nova aba/seção "Cofre TOTP (2FA)":
   - Cadastro de contas e segredos TOTP (`POST /totp`).
   - Geração de código de 6 dígitos em tempo real com barra regressiva de 30 segundos (`GET /totp/{name}/code`).
   - Remoção de contas (`DELETE /totp/{name}`).
2. **Armazenamento Arweave Permaweb em [`/qualidade`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/qualidade.tsx):**
   - Nova seção "Publicação Descentralizada":
   - Status da carteira Arweave (`GET /arweave/status`): status do gateway, carteira ativa, saldo em AR.
   - Publicação de clone no Permaweb (`POST /arweave/publish`) com tags customizadas e link direto para visualização imutável no gateway (`https://arweave.net/<id>`).

---

### Fase 8: Suporte Completo a Modos de IA no `/probe`
Atualizar [`dashboard/src/routes/probe.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/probe.tsx):
- Adicionar botões no grupo de modos para:
  - `entities`: Extração de entidades nomeadas via LLM
  - `sentiment`: Análise de sentimento do conteúdo
  - `translate`: Tradução automática multilíngue da estrutura
  - `tags`: Geração automática de taxonomia de tags
  - `video`: Extração e download de streams de vídeo
  - `api_discovery`: Descoberta de endpoints de API e schemas OpenAPI/Swagger
  - `summarize`: Resumo global do site em Markdown
- Campos contextuais no formulário de acordo com o modo selecionado (ex.: idioma de destino para `translate`).

---

### Fase 9: Rota `/graphql` (Console & Explorador GraphQL)
Criar [`dashboard/src/routes/graphql.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/graphql.tsx):
- Editor de query GraphQL integrado com temas monocromáticos TUI.
- Execução direta via `POST /graphql` com visualização de JSON formatado e tempo de resposta.
- Botão "Carregar Schema" para visualizar o SDL completo (`GET /graphql/schema`).
- Snippets de queries prontas para:
  - Listar Jobs com filtros
  - Consultar estatísticas de motores
  - Buscar referências no catálogo de design.

---

### Fase 10: Multi-Region Dispatch em `/workers`
Atualizar [`dashboard/src/routes/workers.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/workers.tsx):
- Adicionar ferramenta de simulação e execução de dispatch multirregional (`GET /dispatch/plan`, `POST /dispatch`).
- Permite submeter múltiplas URLs e visualizar para qual região ou worker cada uma será enviada.

---

### Fase 11: Navegação Global, Command Palette e Validação
1. **Menu & Command Palette:**
   - Adicionar as novas rotas ao menu superior em [`__root.tsx`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/__root.tsx):
     - Execuções (`/`)
     - Coleção (`/colecao`)
     - Busca (`/busca`)
     - Extrair (`/probe`)
     - Chat (`/chat`)
     - Comparar (`/comparar`)
     - Datasets (`/datasets`)
     - Grafo (`/grafo`)
     - Preços (`/precos`)
     - GraphQL (`/graphql`)
     - Config (`/config`)
   - Atualizar Command Palette (`ctrl+k`) com todos os comandos diretos e atalhos de navegação.
   - Atualizar a central de atalhos e documentação em [`/ajuda`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/routes/ajuda.tsx).
 2. **Validação & Testes:**
   - Verificação de tipos: `npm run typecheck` (0 erros).
   - Linter: `npm run lint` (0 erros).
   - Build de produção: `npm run build` (sucesso).
   - Testes de backend: `uv run pytest tests/ -q` (1713 testes passando).
   - Verificação em navegador via Playwright de todas as novas telas.

## 3. Critérios de Sucesso

1. **100% de Cobertura:** Todos os comandos de `src/zfrog/cli.py` e rotas de `src/zfrog/api.py` acessíveis pela UI ou pela barra de comandos interativa.
2. **Padrão TUI Preservado:** Tipografia Iosevka, caracteres Unicode/ASCII, paletas de alto contraste WCAG AA, sem bibliotecas pesadas de terceiros.
3. **Build & Testes Verificados:** Zero erros no TypeScript, ESLint e suíte de testes.

---

## 4. Status de Execução & Relatório de Verificação (100% Concluído)

- [x] **Fase 1 (API Client & Types):** Todos os métodos e interfaces implementados em [`dashboard/src/lib/api.ts`](file:///home/zens/allkodex/all-kode/all-kodez/ens-kody/ProjetosA/zfrog/dashboard/src/lib/api.ts).
- [x] **Fase 2 (RAG Chat `/chat`):** Rota implementada com sessões, contexto de site, exportação Markdown.
- [x] **Fase 3 (Competitivo & Tendências `/comparar`):** Benchmark multissite e evolução temporal com barras ASCII.
- [x] **Fase 4 (Datasets para Fine-Tuning `/datasets`):** Exportador para ShareGPT, Alpaca, JSONL e Raw Text com preview e download.
- [x] **Fase 5 (Grafo de Conhecimento `/grafo`):** Mapeamento de nós, arestas, grau de centralidade e entidades IA.
- [x] **Fase 6 (Monitor de Preços `/precos`):** Vigilância de ofertas e histórico de flutuação com deltas `▲ / ▼`.
- [x] **Fase 7 (Cofre TOTP 2FA `/captura`):** Gerador dinâmico de códigos 6 dígitos (30s) e sessões de cookie salvas.
- [x] **Fase 8 (Web3 IPFS/Arweave `/qualidade`):** Status de carteira JWK e publicação permanente permaweb.
- [x] **Fase 9 (15 Modos de Extração `/probe`):** jump, tongue, auto, scrape, mirror, singlepage, pdf, video, entities, summarize, sentiment, translate, tags, api discovery, delta.
- [x] **Fase 10 (Console GraphQL `/graphql`):** Query runner com temporizador, snippets e inspeção dinâmica de SDL.
- [x] **Fase 11 (Dispatch Multirregional `/workers`):** Simulador de rotas por região e despachante em lote.
- [x] **Navegação & Palette (`__root.tsx`, `ajuda.tsx`):** Todas as 11 novas abas e comandos indexados no `ctrl+k` e na documentação CLI.
- [x] **Validação TypeScript:** `npm run typecheck` (0 erros).
- [x] **Validação Linter:** `npx eslint src --quiet` (0 erros).
- [x] **Build de Produção:** `npm run build` (26 rotas compiladas com sucesso em 3.4s).
 - [x] **Suíte de Testes Backend:** `uv run pytest tests/ -q` (1713 testes passando, 0 falhas).
- [x] **Validação Visual Playwright:** Navegação real nas rotas `/chat`, `/comparar`, `/datasets`, `/grafo`, `/precos`, `/graphql`, `/probe`, `/captura`, `/qualidade`, `/workers` executadas com snapshots e screenshots salvos.


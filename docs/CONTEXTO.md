# Contexto do projeto zfrog — o que existe, o que falta

Registro vivo para não perder o fio entre sessões. Atualizado a cada entrega.

## O produto, em uma frase

zfrog é um **motor de referências de design**: captura, organiza e adapta
referências visuais da web. Não é uma plataforma genérica de scraping.

O plano original (o do sapo 🐸, revisão 2 → Pond Glass) tem seis seções. Este
documento diz, com honestidade, o que de cada uma está de pé.

## Estado por seção do plano

### ✅ §1 Reposicionamento
README, docs, CLI, API e branding como "Design Reference Engine". Marca `zfrog`
minúsculo, paleta Pond Glass (verde), sapo no `BrandMark`.

### ✅ §2 Remoções de escopo
Stealth agressivo (TLS fingerprinting, Canvas/WebGL), detecção de phishing e PII
redaction: código, rotas, CLI, testes e SDK removidos.

### ✅ §3 Motores
| Motor | Papel | Estado |
|---|---|---|
| Playwright | captura visual (padrão) | ✅ |
| Scrapy | descoberta | ✅ |
| StaticFile | captura leve | ✅ |
| wget | assets | ✅ |
| **jump** | referência: screenshot + tokens + card | ✅ novo |
| **tongue** | componente: HTML + CSS computado | ✅ novo |

Cada motor mora no próprio arquivo: `jump.py`, `tongue.py`. Um arquivo com dois motores é problema de navegação, não economia.
| Auto-detecção | probe escolhe o motor | ✅ (modo `auto` é o padrão) |

### ✅ §4.1 Captura visual
`jump` faz screenshot em três resoluções (desktop 1440×900, tablet 834×1112,
mobile 390×844) via `--breakpoint`, em página inteira ou só o viewport
(`--viewport-only`), em PNG ou WebP (`--format`).

### ✅ §4.2 Extração de design tokens — **`src/zfrog/tokens.py`**
Paleta (contagem por cor, HEX, papel heurístico), tipografia (família, tamanhos,
pesos, onde é usada), escala (tamanhos, pesos, padding, margin, raios, sombras),
assets (imagens com dimensões e alt, backgrounds).

Duas decisões que valem lembrar:
- **Papel é heurística rotulada**: mais usada = `primary`; a mais saturada que não
  é a primária = `accent`; a seguinte = `secondary`. Neutros nunca viram accent.
- **Cor ilegível é contada, não adivinhada**: `color(srgb …)` entra em
  `unreadable_colors` em vez de virar um cinza plausível.

### ✅ §4.3 Extração de componente (`tongue`) — **`src/zfrog/engines/tongue.py`** + **`src/zfrog/components.py`**
HTML sanitizado do elemento + CSS computado agrupado em layout / cor / tipografia
+ caixa + filhos diretos. Filtra valores default (não mostra `position: static`
como se fosse decisão) mas mantém o `computed` completo no JSON.

### ✅ §4.4 Mapeamento de site
Scrapy mapeia; `--mode extract`.

### ✅ §4.5 Organização e catálogo — **`src/zfrog/catalog.py`**
Card = screenshot + tokens + URL + data + tags + nota. SQLite com tabelas de
índice (`card_tags`, `card_colors`, `card_embedding`) para filtrar por tag, cor,
site e data sem varrer tudo.

### ✅ §4.6 Busca semântica — **`src/zfrog/visual_search.py`**
Descrição textual determinística dos atributos visuais (luminosidade, matiz,
vivacidade, arredondamento, sombras, serifa), embedada e ranqueada por cosseno.

**Limite declarado**: não embeda os pixels. Responde "layouts escuros com cards
arredondados" porque a extração já mediu isso; **não** acha "a que tem foto de
cachorro". Para isso, `describe()` é o único ponto que muda.

Fallback: sem modelo configurado, ranqueia por sobreposição de palavras — a
feature degrada para algo útil em vez de para nada. `embeddings_configured()`
existe porque `is_available()` só diz que o litellm está instalado, o que é
verdade em toda instalação e imprimia a lista de providers no stderr.

### ✅ §9 Fluxo de captura do plano
A captura padrão produz design: `clone` (modos `auto`, `mirror`, `scrape`,
`singlepage`, `delta`) roda a extração de tokens junto do screenshot, na mesma
visita ao navegador, e registra um card. `jump` faz o mesmo dedicadamente, sem
baixar o site. Análise de texto (analyze, compare, ask…) fica de fora de propósito.

### ✅ §5.1 CLI
`jump`, `tongue`, `pond` (com `--search` e `--reindex`), `show`, `export`
(json/md/html) — mais os ~45 comandos que já existiam.

### ✅ §5.2 Dashboard
Rota `/colecao`: moodboard com os screenshots como protagonistas, filtros por
etiqueta/cor/site, busca por descrição, painel de detalhe com paleta, tipografia,
tags e nota.

### ✅ §5.3 API REST
10 endpoints `/catalog*`, incluindo `/catalog/{id}/screenshot` (serve a imagem
com verificação de contenção no diretório de mídia).

### ✅ §6 Complementares
delta ✅, versionamento ✅, PDF ✅, agendamento ✅, resumo IA ✅.

### ✅ Painel e CLI com os modos de design
`JobMode` do painel tem `jump` e `tongue`. O `/probe` oferece *Referência de
design* (resolução, formato, página inteira ou viewport, etiquetas) e *Extrair
componente* (campo do seletor CSS). Na CLI, `jump` aceita `--viewport-only` e
`--format png|webp`.

### ✅ API de indexação
`POST /catalog/reindex` constrói os vetores e responde `indexed` + `reason`. O
motivo distingue três situações que pedem ações diferentes: catálogo vazio, tudo
já indexado, e modelo quebrado.

### ⬜ Não feito
- **Clonagem delta visual** (comparar screenshots) — o delta existente é de páginas.
- **Versionamento de referências** (múltiplas versões de uma captura no tempo).
- **PDF de um conjunto de referências** (mini style guide de várias, não de uma).
- **Mascote desenhado** — só o ícone SVG derivado do design system.

## Decisões arquiteturais que não devem ser revertidas

1. **Navegador separado da interpretação.** `collect_snapshot`/
   `collect_component` só agregam no DOM; `extract_tokens`/`build_extract` são
   puros. É o que torna a parte que decide algo testável sem Chromium.
2. **`jump` lê o que outro motor baixou.** A extração de tokens não mora dentro
   de `engines/playwright.py`; um clone feito por `mirror` pode virar card depois.
3. **Falha de catálogo não perde a captura.** O `try` em volta do `save` existe
   para o screenshot em disco sobreviver a um catálogo indisponível.
4. **`@layer od-layout` vem primeiro** (declarado em `globals.css`). Sem isso as
   primitivas de estrutura vencem os utilitários do Tailwind — bug que já
   aconteceu uma vez e custou contorno manual numa tela.
5. **Cor transparente não é cor.** `rgba(0,0,0,0)` é filtrado tanto na extração
   quanto na exibição do componente.

## Armadilhas encontradas (para não repetir)

| Sintoma | Causa | Correção |
|---|---|---|
| `Failed to fetch` em todo request do painel, `curl` ok | `ZFROG_CORS_ORIGINS=*` no `dev`; navegador recusa credencial com origem curinga | `_run_dev` exporta as duas origens que imprime |
| Painel não hidratava em `127.0.0.1` | Next bloqueia recursos de dev fora de `allowedDevOrigins` | ambos os hosts listados |
| 16 campos sem nome acessível | `Input`/`Select`/`Textarea` com `<label>` sem `for` nem envolver o controle | o wrapper passou a ser o `<label>` |
| Campo com `display: block` apesar de `flex` | ordem de camada CSS | `@layer` declarado explicitamente |
| Texto de apoio ilegível | `--text-3` e `--accent-strong` abaixo de 4,5:1 | valores ajustados, medidos nos pixels |
| `run_job() got an unexpected keyword` | assinatura é `run_job(job)`; o progresso vem do engine | comandos novos chamam sem `on_progress` |
| `output_path` do `JobResult` é o ZIP | não é o diretório | helper `_job_dir()` na CLI |
| Screenshot 404 | path salvo relativo ao diretório do job, não à raiz de mídia | gravado relativo a `catalog_media_dir` |
| `TypeError: not 'NoneType'` no `/catalog` | `_scoped` devolve `None` na área compartilhada | traduzido para o default da setting |
| Ruído do litellm no `pond --search` e em todo `clone` | `is_available()` só diz que o litellm está instalado, o que é verdade sempre; o gate passou a exigir modelo nomeado | `can_call()` / `embedding_configured()` em `ai/client.py` |
| Testes escrevendo no catálogo real | o pipeline passou a registrar card em todo job, e o teste isolava só `output_dir` | fixture autouse no `conftest.py` aponta o catálogo para tmp |
| Modelo de embeddings mal configurado derrubava o `pond --reindex` | `embed_catalog` deixava a exceção subir | devolve `IndexResult` com o motivo; só a primeira linha do erro do provedor entra na mensagem |
| Banner "Provider List" do litellm no meio da saída | `litellm.suppress_debug_info` é atributo do módulo, não env var | `_litellm()` nas chamadas |
| `public/` vazio quebraria o build da imagem | git não versiona diretório vazio e o Dockerfile faz `COPY /app/public` | `public/.gitkeep` |

## Verificação

- `pytest tests/ -q` — 1715 testes (90 novos: tokens, componentes, catálogo,
  busca por descrição, captura→card, gates de IA).
- `npx tsc --noEmit` e `npx next build` verdes.
- `ruff check . --select F821,F811,F402,E9` verde (é o gate do CI).
- Smoke real: `jump` numa página, `tongue` num seletor, `pond`/`pond --search`,
  `/colecao` no navegador com screenshot, filtro por cor, etiqueta e painel de
  detalhe.

# Zfrog - Design Reference Engine

Ferramenta de coleta, organização e adaptação de referências de design da web.

## Instalação Rápida

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Uso

```bash
# Clonar site
zfrog clone https://example.com --mode singlepage

# Espelhar site
zfrog clone https://example.com --mode mirror --depth 2

# Clonar SPA
zfrog clone https://nextjs.org --mode scrape

# Gerar PDF da página
zfrog clone https://example.com --mode pdf --pdf-filename relatorio

# Resumir a página com IA
zfrog clone https://example.com --mode summarize

# Analisar URL
zfrog probe https://example.com

# Iniciar API
zfrog serve
```

## Modos

O modo padrão é `auto`: o probe olha a página e escolhe o motor de captura. Os quatro
motores de captura têm papéis distintos:

| Modo | Motor | Papel |
|------|-------|-------|
| `auto` | probe | Roda o probe e escolhe: Playwright (JS) ou StaticFile (página pronta). É o padrão. |
| `scrape` | Playwright | Captura visual: renderiza a página e guarda o HTML renderizado + CSS/JS/imagens. |
| `extract` | Scrapy | Descoberta: mapeia quais páginas existem no site e extrai os dados (JSON + CSV). |
| `singlepage` | StaticFile | Captura leve: uma página, com imagens e estilos embutidos, sem abrir navegador. |
| `mirror` | wget | Assets: baixa o site recursivamente para consulta offline. |

Motores de análise e exportação:

| Modo | O que faz |
|------|-----------|
| `analyze` | Auditoria técnica (SEO, acessibilidade, performance) |
| `compare` | Fidelity Score entre clone e original |
| `ask` | Pergunta em linguagem natural sobre a página |
| `pdf` | Salva a página renderizada como PDF (A4) |
| `summarize` | Resumo com IA (título, resumo, pontos-chave) |
| `delta` | Baixa só as páginas que mudaram |
| `entities` | Nomes de pessoas, empresas, lugares, datas, produtos |
| `enrich` | Tom do texto e assuntos principais |
| `translate` | Traduz o conteúdo |
| `video` | Detecta e baixa vídeo (HLS/DASH) |
| `api_discovery` | Descobre endpoints REST/GraphQL |

## Plugins de Engines

Motores de terceiros são descobertos automaticamente, sem editar o código do Zfrog:

- **Pacote instalado** — declare o entry point `zfrog.engines` apontando para uma
  subclasse de `EngineAdapter` (`name`, `execute`, `can_handle`):

  ```toml
  [project.entry-points."zfrog.engines"]
  meu_motor = "meu_pacote:MeuEngine"
  ```

- **Plugin local** — coloque arquivos `.py` em `plugins/` (ou aponte
  `ZFROG_PLUGINS_DIR` para outro diretório). Toda subclasse de `EngineAdapter`
  do arquivo é registrada.

```bash
zfrog engines    # lista os motores e a origem de cada um
```

Plugin quebrado ou com nome já usado é ignorado com warning — nunca derruba o Zfrog.

## Change Detection

Jobs `mirror` e `scrape` guardam uma versão do site em
`output/snapshots/<url_slug>/<timestamp>.json` (hash, tamanho, título e texto de
cada página). O diretório `snapshots/` é irmão dos diretórios de job, então
sobrevive à limpeza automática de 24h.

```bash
zfrog snapshots                          # listar versões
zfrog snapshots https://example.com      # só de um site
zfrog diff <versao-a.json> <versao-b.json>          # comparar (markdown)
zfrog diff <versao-a.json> <versao-b.json> --json   # comparar (JSON)
```

O diff mostra páginas adicionadas, removidas, alteradas (com a contagem de linhas
que mudaram) e inalteradas, além da proporção de mudança. Mudança não é erro: o
comando sai com código 0.

Quando a proporção de páginas alteradas atinge `ZFROG_CHANGE_ALERT_THRESHOLD`
(default `0.1`, ou seja 10%), o job dispara o webhook `site.changed` com `url`,
`change_ratio`, `added`, `removed`, `changed` e o caminho da versão nova.

## Dashboard

A página **Histórico** lista as versões guardadas e compara duas delas pela
interface. Jobs no modo `pdf` têm o botão **Abrir PDF** na tela de detalhes.

## SDKs

Clientes oficiais para a API REST, sem dependências além do próprio runtime:

```bash
cd sdk/js && bun test       # JavaScript/TypeScript (22 testes)
cd sdk/go && go test ./...  # Go, só stdlib (37 subtestes)
```

```ts
import { ZfrogClient } from "zfrog-sdk"

const client = new ZfrogClient({ baseUrl: "http://localhost:8000", apiKey: "zk_..." })
const job = await client.createJob({ url: "https://example.com", mode: "mirror" })
const report = await client.diff(a, b)
```

```go
client := zfrog.NewClient("http://localhost:8000", zfrog.WithAPIKey("zk_..."))
job, err := client.CreateJob(ctx, zfrog.CreateJobInput{URL: "https://example.com", Mode: "mirror"})
```

Erros são tipados: `ZfrogError` (status + `detail`) no JS e `*APIError` no Go. O teste
`tests/test_sdk.py` compara a lista de endpoints que cada SDK chama com a lista documentada, então um SDK
que fique para trás quebra a suíte do Python.

## GraphQL

```bash
curl -X POST localhost:8000/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ jobs(limit: 5) { id url status } }"}'
curl localhost:8000/graphql/schema
```

Somente leitura, sobre os mesmos dados do REST.

## Autenticação

```bash
zfrog key create painel -r operator
```

Papéis: `viewer` (leitura), `operator` (+ jobs), `admin` (tudo). Com `ZFROG_AUTH_ENABLED=true`, leitura e
escrita exigem chave. Desligado por padrão.

## Documentação

Consulte o [README.md](../README.md) para documentação completa.

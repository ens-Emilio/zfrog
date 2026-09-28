"use client"

import { useEffect, useRef, useState } from "react"
import { api, ExtractPage, ExtractPreview } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { ModeCard } from "@/components/ui/ds"
import { Icon, type IconName } from "@/lib/icons"
import { useToast } from "@/components/ToastRegion"
import { formatNumber } from "@/lib/utils"

/** Escape a value so it can be used as a CSS identifier (ids and class names). */
function escapeIdent(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, (character) => `\\${character}`)
}

/**
 * Build a CSS selector for a clicked element: an `#id` when the element — or one
 * of its ancestors — has one, otherwise `tag.class:nth-of-type(n)` segments
 * walking up to `<body>`, which keeps the selector stable when the page changes.
 */
function cssPath(element: Element): string {
  const segments: string[] = []
  let node: Element | null = element
  while (node !== null && node.nodeType === 1) {
    const self: Element = node
    const tag = self.tagName.toLowerCase()
    if (tag === "html") break

    if (self.id) {
      segments.unshift(`#${escapeIdent(self.id)}`)
      break
    }

    let segment = tag
    const classes: string[] = Array.from(self.classList).slice(0, 2)
    if (classes.length > 0) segment += "." + classes.map(escapeIdent).join(".")

    if (tag !== "body") {
      const parent: Element | null = self.parentElement
      if (parent !== null) {
        const siblings: Element[] = Array.from(parent.children).filter(
          (child) => child.tagName === self.tagName
        )
        if (siblings.length > 1) segment += `:nth-of-type(${siblings.indexOf(self) + 1})`
      }
    }

    segments.unshift(segment)
    if (tag === "body") break
    node = self.parentElement
  }
  return segments.join(" > ")
}

interface Block {
  id: string
  label: string
  icon: IconName
  /** Standard markup each block is recognised by, in the order it is tried. */
  selectors: string[]
}

/**
 * The parts of a page a capture can keep. Each one is a bundle of standard
 * selectors rather than a guess: the resulting selector is what gets tested
 * against the real page by `api.previewSelector`.
 */
const BLOCKS: Block[] = [
  { id: "header", label: "Cabeçalho", icon: "i-layers", selectors: ["header", "[role=banner]"] },
  { id: "nav", label: "Navegação", icon: "i-link", selectors: ["nav", "[role=navigation]"] },
  { id: "main", label: "Conteúdo", icon: "i-file", selectors: ["main", "[role=main]", "article"] },
  { id: "comments", label: "Comentários", icon: "i-message", selectors: ["#comments", ".comments", "[data-comments]"] },
  { id: "footer", label: "Rodapé", icon: "i-scale", selectors: ["footer", "[role=contentinfo]"] },
  { id: "images", label: "Imagens", icon: "i-eye", selectors: ["img", "picture"] },
  { id: "forms", label: "Formulários", icon: "i-type", selectors: ["form", "input", "textarea", "select"] },
  { id: "scripts", label: "Scripts", icon: "i-code", selectors: ["script", "link[rel=stylesheet]"] },
]

interface Preset {
  id: string
  label: string
  blocks: string[]
}

const PRESETS: Preset[] = [
  { id: "full", label: "Página completa", blocks: BLOCKS.map((block) => block.id) },
  { id: "article", label: "Só o artigo", blocks: ["main", "images"] },
  { id: "products", label: "Só produtos", blocks: ["main", "images", "forms"] },
]

const PRESET_STORAGE_KEY = "zfrog-capture-presets"

/** The comma-separated selector a set of blocks adds up to. */
function blocksToSelector(ids: string[]): string {
  const parts: string[] = []
  for (const block of BLOCKS) {
    if (ids.includes(block.id)) parts.push(...block.selectors)
  }
  return parts.join(", ")
}

/** The built-in preset a set of blocks matches exactly, if any. */
function matchingPreset(ids: string[]): string {
  const sorted = [...ids].sort().join(",")
  const match = PRESETS.find((preset) => [...preset.blocks].sort().join(",") === sorted)
  return match ? match.id : "custom"
}

export default function CapturaPage() {
  const toast = useToast()

  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState<ExtractPage | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [frameReady, setFrameReady] = useState(false)

  const [blocks, setBlocks] = useState<string[]>(BLOCKS.map((block) => block.id))
  const [presetId, setPresetId] = useState("full")
  const [presetName, setPresetName] = useState("")
  const [savedPresets, setSavedPresets] = useState<Preset[]>([])

  const [selector, setSelector] = useState(() => blocksToSelector(BLOCKS.map((block) => block.id)))
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<ExtractPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const iframeRef = useRef<HTMLIFrameElement | null>(null)

  // Saved presets live in the browser, so they survive a reload without a server
  // round trip. Read after mount: reading during render would break hydration.
  useEffect(() => {
    const raw = window.localStorage.getItem(PRESET_STORAGE_KEY)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw) as Preset[]
      setSavedPresets(Array.isArray(parsed) ? parsed : [])
    } catch {
      // A corrupt entry is not worth breaking the screen over.
      window.localStorage.removeItem(PRESET_STORAGE_KEY)
    }
  }, [])

  const applyBlocks = (next: string[]) => {
    setBlocks(next)
    setPresetId(matchingPreset(next))
    setSelector(blocksToSelector(next))
    setPreview(null)
    setPreviewError(null)
  }

  const handlePreset = (id: string) => {
    setPresetId(id)
    if (id === "custom") return
    const preset = PRESETS.find((item) => item.id === id) ?? savedPresets.find((item) => item.id === id)
    if (preset) applyBlocks(preset.blocks)
  }

  const handleSavePreset = () => {
    const name = presetName.trim()
    if (!name) {
      toast("Dê um nome ao preset antes de salvar.", "err")
      return
    }
    const entry: Preset = { id: `saved:${name}`, label: name, blocks }
    const next = [...savedPresets.filter((item) => item.id !== entry.id), entry]
    setSavedPresets(next)
    window.localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(next))
    setPresetName("")
    toast(`Preset “${name}” salvo neste navegador.`)
  }

  const handleLoad = async () => {
    const target = url.trim()
    if (!target) return
    setLoading(true)
    setLoadError(null)
    setPage(null)
    setPreview(null)
    setPreviewError(null)
    setFrameReady(false)
    try {
      setPage(await api.extractPage(target))
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const handleFrameLoad = () => {
    const doc = iframeRef.current?.contentDocument
    if (!doc) return
    setFrameReady(true)
    doc.addEventListener(
      "click",
      (event: MouseEvent) => {
        const target = event.target as Element | null
        if (!target || target.nodeType !== 1) return
        // Stop the loaded page from navigating away when a link is clicked.
        event.preventDefault()
        event.stopPropagation()
        setSelector(cssPath(target))
        setPreview(null)
        setPreviewError(null)
      },
      true
    )
  }

  const handlePreview = async () => {
    const target = page?.url || url.trim()
    const value = selector.trim()
    if (!target || !value) return
    setPreviewing(true)
    setPreviewError(null)
    setPreview(null)
    try {
      setPreview(await api.previewSelector(target, value))
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setPreviewing(false)
    }
  }

  const selectedLabels = BLOCKS.filter((block) => blocks.includes(block.id)).map((block) => block.label)
  const embedded = [
    blocks.includes("images") ? "imagens" : null,
    blocks.includes("scripts") ? "estilos" : null,
  ].filter((item): item is string => item !== null)

  return (
    <div className="view-grid">
      <Topbar
        title="Captura"
        description="Escolher o que pegar na página"
      />

      <div className="card">
        <div className="row-between" style={{ marginBottom: "var(--sp-3)" }}>
          <span className="label" id="blocks-legend">
            O que pegar na página
          </span>
          <span className="select-wrap" style={{ flex: "0 1 220px" }}>
            <select
              className="select"
              aria-label="Preset de captura"
              value={presetId}
              onChange={(event) => handlePreset(event.target.value)}
            >
              {PRESETS.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.label}
                </option>
              ))}
              {savedPresets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.label}
                </option>
              ))}
              <option value="custom">Personalizado</option>
            </select>
            <Icon name="i-chevron" />
          </span>
        </div>

        <div className="mode-grid" style={{ marginBottom: "var(--sp-3)" }} role="group" aria-labelledby="blocks-legend">
          {BLOCKS.map((block) => (
            <ModeCard
              key={block.id}
              active={blocks.includes(block.id)}
              label={block.label}
              icon={<Icon name={block.icon} size="lg" />}
              onClick={() =>
                applyBlocks(blocks.includes(block.id) ? blocks.filter((id) => id !== block.id) : [...blocks, block.id])
              }
            />
          ))}
        </div>

        <div className="mode-summary" aria-live="polite">
          <span>
            <strong>{presetId === "custom" ? "Personalizado" : (PRESETS.find((p) => p.id === presetId)?.label ?? presetId)}</strong>{" "}
            — marque os blocos que devem entrar na captura. O restante é descartado antes do download.
          </span>
          <span className="mode-out">
            Você recebe: uma captura contendo apenas os blocos escolhidos, filtrada pelo seletor gerado abaixo.
          </span>
        </div>
      </div>

      <div className="card stack-md">
        <h2 className="card-title">Resumo da captura</h2>
        <dl className="kv">
          <dt>Blocos incluídos</dt>
          <dd>{selectedLabels.length > 0 ? selectedLabels.join(", ") : "Nenhum bloco marcado"}</dd>
          <dt>Ativos</dt>
          <dd>{embedded.length > 0 ? `${embedded.join(" e ")} embutidos` : "só a marcação e o texto"}</dd>
          <dt>Aplicar a</dt>
          <dd>Teste de pré-visualização e download desta página</dd>
          <dt>Seletor gerado</dt>
          <dd className="mono text-[var(--fs-12)]">{selector || "—"}</dd>
        </dl>
        <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
          <span className="od-field" style={{ "--od-gap": "2px", flex: "1 1 200px" } as React.CSSProperties}>
            <label className="label" htmlFor="preset-name">
              Nome do preset
            </label>
            <input
              id="preset-name"
              className="input"
              placeholder="Ex.: Blog com comentários"
              value={presetName}
              onChange={(event) => setPresetName(event.target.value)}
            />
          </span>
          <Button onClick={handleSavePreset} className="od-touch">
            Salvar preset
          </Button>
        </div>
        <p className="hint">Os presets ficam salvos neste navegador e aparecem no seletor acima.</p>
      </div>

      <div className="card">
        <h2 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
          Abrir a página
        </h2>
        <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
          Digite o endereço completo. A página é baixada pelo servidor e mostrada aqui em modo seguro, só para você
          escolher o que quer.
        </p>

        <div className="od-row" style={{ "--od-gap": "12px", alignItems: "flex-end", flexWrap: "wrap" } as React.CSSProperties}>
          <span className="od-field" style={{ "--od-gap": "6px", flex: "1 1 280px" } as React.CSSProperties}>
            <label className="label" htmlFor="captura-url">
              Endereço da página
            </label>
            <input
              id="captura-url"
              className="input input-mono"
              type="url"
              inputMode="url"
              placeholder="https://exemplo.com.br/produtos"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void handleLoad()
              }}
            />
          </span>
          <Button onClick={handleLoad} loading={loading} disabled={!url.trim()} className="od-touch">
            <Icon name="i-globe" size="sm" /> Carregar página
          </Button>
        </div>

        {loading && (
          <div className="od-stack" style={{ "--od-gap": "8px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
            <Skeleton className="h-[18px] w-[220px]" />
            <Skeleton className="h-[320px]" />
          </div>
        )}

        {loadError && (
          <div className="od-stack" style={{ "--od-gap": "8px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
            <Badge variant="danger">
              <span className="dot" aria-hidden="true" />
              Não foi possível abrir essa página
            </Badge>
            <p className="card-sub">{loadError}</p>
            <p className="hint">
              Confira se o endereço está completo (com <span className="mono">https://</span>) e se a página está
              acessível publicamente.
            </p>
            <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
              <Button size="sm" onClick={handleLoad} loading={loading}>
                Tentar de novo
              </Button>
            </div>
          </div>
        )}

        {page && (
          <div className="od-stack" style={{ "--od-gap": "12px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
            <div className="row-between">
              <span className="detail-url od-truncate">{page.url}</span>
              <span className="hint">{page.title || "Sem título"}</span>
            </div>

            <div style={{ position: "relative" }}>
              {/*
                O HTML já chega higienizado pelo servidor (scripts, atributos `on*` e
                endereços `javascript:` são removidos antes de sair da API), e é isso
                que torna seguro mostrá-lo aqui. O atributo `sandbox` fica de fora de
                propósito: o clique precisa de acesso ao documento do quadro para
                calcular o caminho CSS do elemento.
              */}
              <iframe
                ref={iframeRef}
                title="Página aberta para seleção"
                srcDoc={page.html}
                onLoad={handleFrameLoad}
                style={{ width: "100%", height: 520, borderRadius: "var(--r-card)", border: "1px solid var(--glass-border)", background: "#fff" }}
              />
              {!frameReady && (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "grid",
                    placeItems: "center",
                    borderRadius: "var(--r-card)",
                    background: "var(--glass-strong)",
                    fontSize: "var(--fs-13)",
                    color: "var(--text-2)",
                  }}
                >
                  A página ainda está carregando no quadro…
                </div>
              )}
            </div>

            <div className="od-row" style={{ "--od-gap": "8px", alignItems: "flex-start" } as React.CSSProperties}>
              <Icon name="i-mouse" size="sm" className="text-[var(--accent-strong)] mt-0.5" />
              <span className="hint">
                Clique em qualquer elemento dentro do quadro acima. O seletor é montado sozinho e pode ser editado à
                mão.
              </span>
            </div>
          </div>
        )}

        {!page && !loading && !loadError && (
          <div style={{ marginTop: "var(--sp-4)" }}>
            <EmptyState
              icon={<Icon name="i-globe" />}
              title="Nenhuma página aberta"
              description="Cole o endereço acima e carregue a página para clicar no que você quer pegar."
            />
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
          Testar seletor
        </h2>
        <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
          O seletor é a regra que diz quais elementos pegar. Ele vem dos blocos marcados ou do seu clique, mas você
          pode ajustá-lo.
        </p>

        <div className="od-row" style={{ "--od-gap": "12px", alignItems: "flex-end", flexWrap: "wrap" } as React.CSSProperties}>
          <span className="od-field" style={{ "--od-gap": "6px", flex: "1 1 280px" } as React.CSSProperties}>
            <label className="label" htmlFor="captura-selector">
              Seletor CSS
            </label>
            <input
              id="captura-selector"
              className="input input-mono"
              placeholder="Clique na página acima ou digite, ex.: #preco"
              value={selector}
              onChange={(event) => {
                setSelector(event.target.value)
                setPreview(null)
                setPreviewError(null)
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") void handlePreview()
              }}
            />
            <span className="hint">Exemplos: .titulo, #conteudo p, article h2</span>
          </span>
          <Button
            onClick={handlePreview}
            loading={previewing}
            disabled={!selector.trim() || !(page?.url || url.trim())}
            className="od-touch"
          >
            <Icon name="i-target" size="sm" /> Testar seletor
          </Button>
        </div>

        {!page && !loading && (
          <p className="hint" style={{ marginTop: "var(--sp-3)" }}>
            Abra uma página acima para poder clicar e testar. Sem isso, o seletor não tem onde ser aplicado.
          </p>
        )}

        {previewError && (
          <div className="od-stack" style={{ "--od-gap": "8px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
            <Badge variant="danger">
              <span className="dot" aria-hidden="true" />
              O seletor não pôde ser testado
            </Badge>
            <p className="card-sub">{previewError}</p>
            <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
              <Button size="sm" onClick={handlePreview} loading={previewing}>
                Tentar de novo
              </Button>
            </div>
          </div>
        )}

        {preview && (
          <div className="od-stack" style={{ "--od-gap": "12px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
            <div className="row-between">
              <span className="label">
                {formatNumber(preview.count)} {preview.count === 1 ? "elemento encontrado" : "elementos encontrados"}
              </span>
              <Badge variant="success">
                <span className="dot" aria-hidden="true" />
                Seletor válido
              </Badge>
            </div>
            <p className="hint mono od-truncate">{preview.selector}</p>

            {preview.count === 0 ? (
              <EmptyState
                icon={<Icon name="i-alert" />}
                title="O seletor está certo, mas não achou nada"
                description="Tente um seletor mais curto, ou clique de novo em outro ponto da página."
              />
            ) : (
              <div className="job-list">
                {preview.elements.map((element) => (
                  <article
                    key={element.index}
                    className="job-row"
                    style={{ gridTemplateColumns: "minmax(0, 1fr)" }}
                  >
                    <div className="job-meta">
                      <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
                        <Badge variant="neutral" className="mono">
                          {element.tag}
                        </Badge>
                        <span className="job-url od-truncate">
                          {element.text || <span className="hint">(sem texto)</span>}
                        </span>
                      </div>
                      <details>
                        <summary className="hint">Ver HTML</summary>
                        <pre
                          className="mono"
                          style={{
                            marginTop: "var(--sp-2)",
                            maxWidth: 520,
                            overflowX: "auto",
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-all",
                            padding: "var(--sp-3)",
                            borderRadius: "var(--r-control)",
                            border: "1px solid var(--glass-border)",
                            background: "var(--glass)",
                            fontSize: "var(--fs-11)",
                            color: "var(--text-2)",
                          }}
                        >
                          {element.html}
                        </pre>
                      </details>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

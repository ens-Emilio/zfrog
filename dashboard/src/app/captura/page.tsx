"use client"
import { useRef, useState } from "react"
import { api, ExtractPage, ExtractPreview } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Globe,
  MousePointerClick,
  Crosshair,
  Check,
  AlertTriangle,
  Code2,
  Link2,
  Table,
} from "lucide-react"

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

export default function CapturaPage() {
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState<ExtractPage | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [frameReady, setFrameReady] = useState(false)

  const [selector, setSelector] = useState("")
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<ExtractPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const iframeRef = useRef<HTMLIFrameElement | null>(null)

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

  return (
    <div className="space-y-6 max-w-[1200px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Extrair clicando na página"
        description="Abra a página aqui dentro, clique no que você quer pegar e o seletor é montado sozinho. Depois é só testar."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-4 w-4" /> Passo 1 — Abrir a página
          </CardTitle>
          <CardDescription>
            Digite o endereço completo. A página é baixada pelo servidor e mostrada aqui em modo seguro, só para você
            escolher o que quer.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Endereço da página"
                placeholder="https://exemplo.com.br/produtos"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleLoad()}
                leftIcon={<Globe className="h-4 w-4" />}
              />
            </div>
            <Button onClick={handleLoad} loading={loading} disabled={!url.trim()}>
              <Globe className="h-4 w-4" /> Carregar página
            </Button>
          </div>

          {loadError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível abrir essa página.</p>
              <p className="mt-1">{loadError}</p>
              <p className="mt-1 text-muted-foreground">
                Confira se o endereço está completo (com <span className="font-mono">https://</span>) e se a página
                está acessível publicamente.
              </p>
            </div>
          )}

          {page && (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3 text-[12.5px]">
                <span className="inline-flex items-center gap-1.5 text-muted-foreground truncate">
                  <Link2 className="h-3.5 w-3.5 shrink-0" />
                  <span className="font-mono truncate">{page.url}</span>
                </span>
                <span className="shrink-0 font-medium truncate" title={page.title}>
                  {page.title || "Sem título"}
                </span>
              </div>

              <div className="relative">
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
                  className="w-full h-[520px] rounded-[12px] border bg-white"
                />
                {!frameReady && (
                  <div className="absolute inset-0 flex items-center justify-center rounded-[12px] bg-background/80 text-[13px] text-muted-foreground">
                    A página ainda está carregando no quadro…
                  </div>
                )}
              </div>

              <div className="flex items-start gap-2 rounded-[10px] bg-secondary/60 border p-3 text-[12.5px] text-muted-foreground">
                <MousePointerClick className="h-4 w-4 shrink-0 mt-0.5 text-primary" />
                <span>
                  Clique em qualquer elemento dentro do quadro acima. O seletor aparece no passo 2 e pode ser
                  editado à mão se você quiser.
                </span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Crosshair className="h-4 w-4" /> Passo 2 — Seletor e teste
          </CardTitle>
          <CardDescription>
            O seletor é a regra que diz quais elementos pegar. Ele é montado pelo clique, mas você pode ajustá-lo.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Seletor CSS"
                placeholder="Clique na página acima ou digite, ex.: #preco"
                value={selector}
                onChange={(e) => setSelector(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handlePreview()}
                leftIcon={<Code2 className="h-4 w-4" />}
                hint="Exemplos: .titulo, #conteudo p, article h2"
              />
            </div>
            <Button
              onClick={handlePreview}
              loading={previewing}
              disabled={!selector.trim() || !(page?.url || url.trim())}
            >
              <Crosshair className="h-4 w-4" /> Testar seletor
            </Button>
          </div>

          {!page && !loading && (
            <p className="text-[12.5px] text-muted-foreground">
              Abra uma página no passo 1 para poder clicar e testar. Sem isso, o seletor não tem onde ser aplicado.
            </p>
          )}

          {page && !frameReady && (
            <p className="text-[12.5px] text-muted-foreground">
              O quadro do passo 1 ainda está carregando. Se ele demorar, você pode digitar o seletor à mão e testar
              assim mesmo.
            </p>
          )}

          {previewError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">O seletor não pôde ser testado.</p>
              <p className="mt-1">{previewError}</p>
            </div>
          )}

          {preview && (
            <div className="space-y-4 animate-[scale-in_0.2s_ease]">
              <div className="rounded-[12px] border bg-secondary/40 p-4 flex items-center gap-4">
                <div className="h-12 w-12 rounded-[14px] bg-primary/10 flex items-center justify-center shrink-0">
                  <Table className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <p className="text-[26px] font-semibold leading-none">{preview.count}</p>
                  <p className="text-[12.5px] text-muted-foreground mt-1">
                    {preview.count === 1
                      ? "elemento encontrado com o seletor"
                      : "elementos encontrados com o seletor"}{" "}
                    <span className="font-mono">{preview.selector}</span>
                  </p>
                </div>
                <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-2.5 py-1 text-[11px] font-medium ring-1 ring-emerald-500/20 shrink-0">
                  <Check className="h-3 w-3" /> seletor válido
                </span>
              </div>

              {preview.count === 0 ? (
                <div className="rounded-[12px] border border-dashed p-8 text-center">
                  <AlertTriangle className="h-7 w-7 mx-auto text-muted-foreground/40 mb-2" />
                  <p className="text-[13px] font-medium">O seletor está certo, mas não achou nada.</p>
                  <p className="text-[12.5px] text-muted-foreground mt-1">
                    Tente um seletor mais curto, ou clique de novo em outro ponto da página.
                  </p>
                </div>
              ) : (
                <div className="rounded-[12px] border overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead>
                        <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                          <th className="px-4 py-2.5 font-medium w-24">Elemento</th>
                          <th className="px-4 py-2.5 font-medium">Texto</th>
                          <th className="px-4 py-2.5 font-medium w-40">HTML</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.elements.map((element) => (
                          <tr key={element.index} className="border-b last:border-0 align-top">
                            <td className="px-4 py-2.5">
                              <span className="inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-[11.5px] font-mono">
                                {element.tag}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-[12.5px]">
                              {element.text || <span className="text-muted-foreground">(sem texto)</span>}
                            </td>
                            <td className="px-4 py-2.5">
                              <details>
                                <summary className="text-[12px] text-muted-foreground cursor-pointer hover:text-foreground">
                                  ver HTML
                                </summary>
                                <pre className="mt-2 max-w-[420px] overflow-x-auto rounded-[10px] bg-secondary/60 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                  {element.html}
                                </pre>
                              </details>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {preview.count > preview.elements.length && (
                    <p className="px-4 py-2.5 text-[11.5px] text-muted-foreground border-t bg-muted/20">
                      Mostrando os primeiros {preview.elements.length} de {preview.count} elementos.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

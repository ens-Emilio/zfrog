"use client"
import { useState } from "react"
import { api, ArchivedPage, TimelineEntry } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { DetailGrid, DetailRow } from "@/components/DetailRow"
import { formatBytes } from "@/lib/utils"
import {
  Clock,
  Globe,
  RefreshCw,
  ExternalLink,
  CalendarClock,
  FileText,
  AlertTriangle,
  Info,
  MousePointerClick,
} from "lucide-react"

/** Data e hora no formato que as pessoas leem, com o valor original como reserva. */
function formatMoment(value: string): string {
  const parsed = new Date(value)
  if (isNaN(parsed.getTime())) return value || "—"
  return parsed.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
}

export default function TimelinePage() {
  const [url, setUrl] = useState("")
  const [site, setSite] = useState("")
  const [branch, setBranch] = useState("main")
  const [summary, setSummary] = useState("")
  const [entries, setEntries] = useState<TimelineEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [selectedRef, setSelectedRef] = useState("")
  const [pages, setPages] = useState<ArchivedPage[]>([])
  const [pagesLoading, setPagesLoading] = useState(false)
  const [pagesError, setPagesError] = useState<string | null>(null)

  const [selectedPath, setSelectedPath] = useState("")
  const [selectedPage, setSelectedPage] = useState<ArchivedPage | null>(null)
  const [pageLoading, setPageLoading] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)

  const [whenDate, setWhenDate] = useState("")
  const [whenTime, setWhenTime] = useState("")
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const loadPages = async (target: string, ref: string) => {
    setSelectedRef(ref)
    setPages([])
    setPagesError(null)
    setSelectedPath("")
    setSelectedPage(null)
    setPageError(null)
    setPagesLoading(true)
    try {
      setPages(await api.getTimelinePages(target, ref))
    } catch (e) {
      setPagesError(e instanceof Error ? e.message : String(e))
    } finally {
      setPagesLoading(false)
    }
  }

  /** Carrega a lista de versões; `preferredRef` mantém a versão escolhida quando ela existe. */
  const loadSite = async (target: string, preferredRef?: string) => {
    const clean = target.trim()
    if (!clean) return
    setLoading(true)
    setError(null)
    setNotice(null)
    setResolveError(null)
    setEntries([])
    setSummary("")
    setSelectedRef("")
    setPages([])
    setPagesError(null)
    setSelectedPath("")
    setSelectedPage(null)
    setPageError(null)
    try {
      const data = await api.getTimeline(clean)
      setSite(clean)
      setBranch(data.branch || "main")
      setSummary(data.summary)
      setEntries(data.entries)
      const wanted =
        preferredRef && data.entries.some((entry) => entry.ref === preferredRef)
          ? preferredRef
          : data.entries.length
            ? data.entries[data.entries.length - 1].ref
            : ""
      if (wanted) await loadPages(clean, wanted)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const selectPage = async (path: string) => {
    setSelectedPath(path)
    setSelectedPage(null)
    setPageError(null)
    setPageLoading(true)
    try {
      setSelectedPage(await api.getTimelinePage(site, selectedRef, path))
    } catch (e) {
      setPageError(e instanceof Error ? e.message : String(e))
    } finally {
      setPageLoading(false)
    }
  }

  const handleResolve = async () => {
    const clean = url.trim()
    // Sem a hora, o valor enviado é só a data: a API entende o dia inteiro.
    const when = whenDate ? (whenTime ? `${whenDate}T${whenTime}` : whenDate) : ""
    if (!clean || !when) return
    setResolving(true)
    setResolveError(null)
    setNotice(null)
    try {
      const found = await api.resolveTimelineDate(clean, when)
      await loadSite(clean, found.ref)
      setNotice(
        `Mostrando a versão de ${formatMoment(found.captured_at)}` +
          (found.message ? ` — ${found.message}` : "")
      )
    } catch (e) {
      setResolveError(e instanceof Error ? e.message : String(e))
    } finally {
      setResolving(false)
    }
  }

  const selectedEntry = entries.find((entry) => entry.ref === selectedRef) ?? null
  const selectedFromList = pages.find((page) => page.path === selectedPath) ?? null
  const originalUrl = selectedPage?.url || selectedFromList?.url || ""
  const hasVersions = entries.length > 0

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Máquina do tempo"
        description="Abra um site como ele estava numa data passada. As versões são as cópias guardadas no modo Site completo ou Site com JavaScript."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-4 w-4" /> Qual site
          </CardTitle>
          <CardDescription>
            Escreva o endereço do site que você já copiou antes. Depois escolha uma versão da lista ou peça a data
            desejada.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Endereço do site"
                placeholder="https://exemplo.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && url.trim() && loadSite(url)}
                leftIcon={<Globe className="h-4 w-4" />}
                hint="O mesmo endereço usado na extração."
              />
            </div>
            <Button onClick={() => loadSite(url)} loading={loading} disabled={!url.trim()}>
              <RefreshCw className="h-4 w-4" /> Carregar
            </Button>
          </div>

          <div className="rounded-[12px] border bg-secondary/40 p-4 space-y-3">
            <p className="flex items-center gap-2 text-[13px] font-medium">
              <CalendarClock className="h-4 w-4" /> Ver como estava numa data
            </p>
            <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
              <div className="flex-1">
                <Input
                  type="date"
                  label="Data"
                  value={whenDate}
                  onChange={(e) => setWhenDate(e.target.value)}
                />
              </div>
              <div className="flex-1">
                <Input
                  type="time"
                  label="Hora (opcional)"
                  value={whenTime}
                  onChange={(e) => setWhenTime(e.target.value)}
                />
              </div>
              <Button
                onClick={handleResolve}
                loading={resolving}
                disabled={!url.trim() || !whenDate}
                variant="secondary"
              >
                <Clock className="h-4 w-4" /> Ver como estava
              </Button>
            </div>
            <p className="text-[11.5px] text-muted-foreground">
              Sem a hora, a data vale o dia inteiro — é usada a última versão guardada até o fim desse dia. Com a hora,
              vale a última versão guardada até aquele instante.
            </p>
          </div>

          {notice && (
            <div className="rounded-[12px] bg-emerald-500/10 border border-emerald-500/20 p-3 text-[13px] text-emerald-700 dark:text-emerald-400">
              <p className="flex items-center gap-1.5 font-medium">
                <Clock className="h-3.5 w-3.5" /> {notice}
              </p>
            </div>
          )}

          {resolveError && (
            <div className="rounded-[12px] bg-amber-500/10 border border-amber-500/20 p-3 text-[13px] text-amber-700 dark:text-amber-400">
              <p className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="h-3.5 w-3.5" /> Não há nenhuma versão guardada até essa data.
              </p>
              <p className="mt-1">{resolveError}</p>
              <p className="mt-1 text-muted-foreground">
                Escolha uma data depois da primeira cópia ou faça uma nova extração em{" "}
                <strong className="text-foreground">Nova extração</strong>.
              </p>
            </div>
          )}

          {error && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível carregar as versões desse site.</p>
              <p className="mt-1">{error}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {!loading && !error && site && !hasVersions && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <Clock className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">Nenhuma versão guardada — use --versioned no clone</h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
              Sem versões não há o que revisitar: cada cópia feita com o histórico ligado vira uma versão desta linha do
              tempo. Confira também se o endereço está escrito igual ao da extração.
            </p>
          </CardContent>
        </Card>
      )}

      {hasVersions && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="h-4 w-4" /> Versões guardadas
            </CardTitle>
            <CardDescription>
              {summary || `${entries.length} versão(ões) guardada(s).`} Ramo: {branch}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-[12px] border divide-y">
              {entries.map((entry) => {
                const active = entry.ref === selectedRef
                return (
                  <button
                    key={entry.ref}
                    type="button"
                    onClick={() => loadPages(site, entry.ref)}
                    className={`w-full text-left px-4 py-3 transition-colors ${
                      active ? "bg-primary/5 ring-1 ring-inset ring-primary/20" : "hover:bg-accent/50"
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-[13px] font-medium whitespace-nowrap">
                        {formatMoment(entry.captured_at)}
                      </span>
                      <Badge className="bg-secondary text-muted-foreground ring-1 ring-inset ring-border">
                        {entry.branch || "main"}
                      </Badge>
                      <span className="text-[12.5px] text-muted-foreground flex-1 min-w-[160px] truncate" title={entry.message}>
                        {entry.message || "Sem descrição"}
                      </span>
                      <span className="text-[12px] text-muted-foreground whitespace-nowrap">
                        {entry.pages} página(s)
                      </span>
                      <span className="text-[12px] text-muted-foreground whitespace-nowrap tabular-nums">
                        {formatBytes(entry.size_bytes)}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] font-mono text-muted-foreground truncate">{entry.ref}</p>
                  </button>
                )
              })}
            </div>
            <p className="text-[11.5px] text-muted-foreground">
              Clique numa versão para ver as páginas que ela guardou. A mais recente já vem aberta.
            </p>
          </CardContent>
        </Card>
      )}

      {selectedRef && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-4 w-4" /> Páginas dessa versão
            </CardTitle>
            <CardDescription>
              {selectedEntry ? `Cópia de ${formatMoment(selectedEntry.captured_at)}. ` : ""}
              {pages.length} página(s) guardada(s) nessa versão.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {pagesError && (
              <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                <p className="font-medium">Não foi possível listar as páginas dessa versão.</p>
                <p className="mt-1">{pagesError}</p>
              </div>
            )}

            {pagesLoading && <p className="text-[13px] text-muted-foreground">Carregando as páginas…</p>}

            {!pagesLoading && !pagesError && pages.length === 0 && (
              <p className="text-[13px] text-muted-foreground">
                Essa versão não guardou nenhuma página. Tente outra versão da lista.
              </p>
            )}

            {pages.length > 0 && (
              <div className="rounded-[12px] border divide-y max-h-[320px] overflow-y-auto">
                {pages.map((page) => {
                  const active = page.path === selectedPath
                  return (
                    <button
                      key={page.path}
                      type="button"
                      onClick={() => selectPage(page.path)}
                      className={`w-full text-left px-4 py-2.5 transition-colors ${
                        active ? "bg-primary/5 ring-1 ring-inset ring-primary/20" : "hover:bg-accent/50"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-[12.5px] font-mono truncate flex-1" title={page.path}>
                          {page.path}
                        </span>
                        <span className="text-[12.5px] truncate max-w-[240px] text-muted-foreground" title={page.title}>
                          {page.title || "Sem título"}
                        </span>
                        <span className="text-[12px] text-muted-foreground whitespace-nowrap tabular-nums">
                          {formatBytes(page.size_bytes)}
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {selectedRef && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MousePointerClick className="h-4 w-4" /> Como a página era
            </CardTitle>
            <CardDescription>
              {selectedPath
                ? "Confira abaixo a cópia guardada dessa página."
                : "Escolha uma página na lista acima para ver como ela estava nessa data."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!selectedPath && (
              <div className="rounded-[12px] border border-dashed p-10 text-center">
                <MousePointerClick className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
                <p className="text-[13px] font-medium">Nenhuma página escolhida</p>
                <p className="text-[12.5px] text-muted-foreground mt-1 max-w-md mx-auto">
                  Clique numa página da lista de páginas dessa versão para abrir a cópia arquivada.
                </p>
              </div>
            )}

            {selectedPath && (
              <>
                <div className="flex items-start gap-2 rounded-[10px] bg-secondary/60 border p-3 text-[12.5px] text-muted-foreground">
                  <Info className="h-4 w-4 shrink-0 mt-0.5 text-primary" />
                  <span>
                    Você está vendo uma cópia arquivada, não o site ao vivo. É o conteúdo guardado nessa data: scripts da
                    página não são executados aqui, e imagens ou estilos podem faltar.
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
                  <span className="font-mono truncate" title={selectedPath}>
                    {selectedPath}
                  </span>
                  {originalUrl && (
                    <a
                      href={originalUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-primary underline"
                    >
                      Abrir o endereço original <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>

                {pageError && (
                  <div className="rounded-[12px] bg-amber-500/10 border border-amber-500/20 p-3 text-[13px] text-amber-700 dark:text-amber-400">
                    <p className="flex items-center gap-1.5 font-medium">
                      <AlertTriangle className="h-3.5 w-3.5" /> Não foi possível ler os dados dessa página.
                    </p>
                    <p className="mt-1">{pageError}</p>
                    <p className="mt-1 text-muted-foreground">A cópia arquivada é mostrada mesmo assim.</p>
                  </div>
                )}

                {pageLoading && <p className="text-[13px] text-muted-foreground">Lendo a página guardada…</p>}

                <iframe
                  title={`Cópia arquivada de ${selectedPath}`}
                  src={api.timelinePageUrl(site, selectedRef, selectedPath)}
                  sandbox=""
                  className="w-full h-[560px] rounded-[12px] border bg-white"
                />
              </>
            )}

            {selectedPage && (
              <DetailGrid>
                <DetailRow label="Título" value={selectedPage.title || "Sem título"} />
                <DetailRow label="Endereço original" value={selectedPage.url} mono />
                <DetailRow label="Tamanho guardado" value={formatBytes(selectedPage.size_bytes)} />
                <DetailRow label="Assinatura do arquivo" value={selectedPage.sha256} mono hint="Confere se o arquivo não mudou desde a cópia." />
              </DetailGrid>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

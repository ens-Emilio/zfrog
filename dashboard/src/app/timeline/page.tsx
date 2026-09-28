"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { api, ArchivedPage, SnapshotEntry, TimelineEntry } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Input, Select } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { DetailGrid, DetailRow } from "@/components/DetailRow"
import { EmptyState } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Icon } from "@/lib/icons"
import { formatBytes, formatStamp } from "@/lib/utils"

/**
 * Máquina do tempo: abre um site como ele estava numa data passada.
 *
 * Os sites listados são os que já têm capturas guardadas. Cada captura vira um
 * ponto da linha do tempo; escolher um ponto lista as páginas daquela versão e
 * abre a cópia arquivada — os links internos levam para a versão arquivada, não
 * para o site ao vivo.
 */

/** Falha de leitura: diz o que aconteceu e oferece como tentar de novo. */
function ErrorBlock({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className="card stack-sm" style={{ borderColor: "var(--danger)" }}>
      <span className="badge badge-danger">
        <span className="dot" aria-hidden="true" />
        Erro
      </span>
      <h3 className="card-title">{title}</h3>
      <p className="card-sub">{message}</p>
      {onRetry && (
        <div>
          <Button variant="secondary" size="sm" className="od-touch" onClick={onRetry}>
            <Icon name="i-refresh" size="sm" />
            Tentar de novo
          </Button>
        </div>
      )}
    </div>
  )
}

/** A silhueta da tela enquanto os sites acompanhados chegam. */
function PageSkeleton() {
  return (
    <div className="stack-lg" aria-hidden="true">
      <div className="card">
        <Skeleton className="h-10 w-full max-w-[320px]" />
      </div>
      <div className="card stack-md">
        <Skeleton className="h-4 w-40" />
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-16 w-full" />
        ))}
      </div>
    </div>
  )
}

export default function TimelinePage() {
  const [sites, setSites] = useState<SnapshotEntry[]>([])
  const [sitesLoading, setSitesLoading] = useState(true)
  const [sitesError, setSitesError] = useState<string | null>(null)
  const [slug, setSlug] = useState("")

  const [summary, setSummary] = useState("")
  const [branch, setBranch] = useState("")
  const [entries, setEntries] = useState<TimelineEntry[]>([])
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [timelineError, setTimelineError] = useState<string | null>(null)

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

  const loadSites = useCallback(async () => {
    setSitesLoading(true)
    setSitesError(null)
    try {
      const data = await api.getSnapshots()
      setSites(data)
      const slugs = Array.from(new Set(data.map((entry) => entry.slug)))
      setSlug((current) => (current && slugs.includes(current) ? current : (slugs[0] ?? "")))
    } catch (e) {
      setSitesError(e instanceof Error ? e.message : String(e))
    } finally {
      setSitesLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSites()
  }, [loadSites])

  /** Um site por slug, com o endereço que aparece no seletor. */
  const siteOptions = useMemo(() => {
    const bySlug: Record<string, string> = {}
    for (const entry of sites) if (!bySlug[entry.slug]) bySlug[entry.slug] = entry.url || entry.slug
    return Object.entries(bySlug).map(([value, label]) => ({ value, label }))
  }, [sites])

  const siteUrl = useMemo(
    () => sites.find((entry) => entry.slug === slug)?.url ?? "",
    [sites, slug]
  )

  const loadPages = useCallback(async (url: string, ref: string) => {
    setSelectedRef(ref)
    setPages([])
    setPagesError(null)
    setSelectedPath("")
    setSelectedPage(null)
    setPageError(null)
    setPagesLoading(true)
    try {
      setPages(await api.getTimelinePages(url, ref))
    } catch (e) {
      setPagesError(e instanceof Error ? e.message : String(e))
    } finally {
      setPagesLoading(false)
    }
  }, [])

  /** Carrega a linha do tempo; `preferredRef` mantém a versão escolhida quando ela ainda existe. */
  const loadTimeline = useCallback(
    async (url: string, preferredRef?: string) => {
      setTimelineLoading(true)
      setTimelineError(null)
      setResolveError(null)
      setSummary("")
      setBranch("")
      setEntries([])
      setSelectedRef("")
      setPages([])
      setPagesError(null)
      setSelectedPath("")
      setSelectedPage(null)
      setPageError(null)
      try {
        const data = await api.getTimeline(url)
        setSummary(data.summary)
        setBranch(data.branch)
        setEntries(data.entries)
        const newest = [...data.entries].sort(
          (a, b) => new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime()
        )
        const wanted =
          preferredRef && newest.some((entry) => entry.ref === preferredRef) ? preferredRef : (newest[0]?.ref ?? "")
        if (wanted) await loadPages(url, wanted)
      } catch (e) {
        setTimelineError(e instanceof Error ? e.message : String(e))
      } finally {
        setTimelineLoading(false)
      }
    },
    [loadPages]
  )

  useEffect(() => {
    if (siteUrl) void loadTimeline(siteUrl)
  }, [siteUrl, loadTimeline])

  /** Versões da mais recente para a mais antiga, que é a ordem da linha do tempo. */
  const ordered = useMemo(
    () =>
      [...entries].sort(
        (a, b) => new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime()
      ),
    [entries]
  )

  const openPage = async (path: string) => {
    setSelectedPath(path)
    setSelectedPage(null)
    setPageError(null)
    setPageLoading(true)
    try {
      setSelectedPage(await api.getTimelinePage(siteUrl, selectedRef, path))
    } catch (e) {
      setPageError(e instanceof Error ? e.message : String(e))
    } finally {
      setPageLoading(false)
    }
  }

  /** Traduz a data escolhida na captura guardada até aquele instante. */
  const resolveDate = async () => {
    const when = whenDate ? (whenTime ? `${whenDate}T${whenTime}` : whenDate) : ""
    if (!siteUrl || !when) return
    setResolving(true)
    setResolveError(null)
    setNotice(null)
    try {
      const found = await api.resolveTimelineDate(siteUrl, when)
      await loadTimeline(siteUrl, found.ref)
      setNotice(`Mostrando a captura de ${formatStamp(found.captured_at)}${found.message ? ` — ${found.message}` : ""}`)
    } catch (e) {
      setResolveError(e instanceof Error ? e.message : String(e))
    } finally {
      setResolving(false)
    }
  }

  const selectedEntry = ordered.find((entry) => entry.ref === selectedRef) ?? null

  return (
    <div className="view-grid">
      <Topbar
        title="Máquina do tempo"
        description="Abra um site como ele estava numa data passada. As versões são as capturas guardadas nos modos Site completo ou Site com JavaScript."
        action={
          <Button
            variant="secondary"
            size="sm"
            className="od-touch"
            loading={sitesLoading}
            onClick={() => void loadSites()}
          >
            <Icon name="i-refresh" size="sm" />
            Atualizar
          </Button>
        }
      />

      {sitesLoading && <PageSkeleton />}

      {!sitesLoading && sitesError && (
        <ErrorBlock
          title="Não foi possível carregar os sites acompanhados."
          message={sitesError}
          onRetry={() => void loadSites()}
        />
      )}

      {!sitesLoading && !sitesError && siteOptions.length === 0 && (
        <EmptyState
          icon={<Icon name="i-clock" size="lg" />}
          title="Nenhum site acompanhado ainda"
          description="Sem capturas guardadas não há o que revisitar: cada cópia feita nos modos Site completo ou Site com JavaScript vira uma versão desta linha do tempo."
          href={{ label: "Ir para Nova extração", href: "/" }}
        />
      )}

      {!sitesLoading && !sitesError && siteOptions.length > 0 && (
        <>
          <div className="card">
            <div className="od-field" style={{ ["--od-gap" as string]: "6px", maxWidth: "320px" }}>
              <Select
                label="Site acompanhado"
                value={slug}
                onChange={(event) => {
                  setNotice(null)
                  setResolveError(null)
                  setSlug(event.target.value)
                }}
              >
                {siteOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Escolha uma data
            </h3>
            <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
              {summary || "Cada ponto é uma captura guardada deste site."}
              {branch ? ` Ramo: ${branch}.` : ""}
            </p>

            <div className="toolbar" style={{ marginBottom: "var(--sp-4)" }}>
              <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
                <Input
                  type="date"
                  label="Data desejada"
                  value={whenDate}
                  onChange={(event) => setWhenDate(event.target.value)}
                  hint="Sem hora, vale o dia inteiro."
                />
              </div>
              <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
                <Input
                  type="time"
                  label="Hora (opcional)"
                  value={whenTime}
                  onChange={(event) => setWhenTime(event.target.value)}
                  hint="Vale a captura até aquele instante."
                />
              </div>
              <Button
                variant="secondary"
                className="od-touch"
                loading={resolving}
                disabled={!whenDate || timelineLoading}
                onClick={() => void resolveDate()}
              >
                <Icon name="i-clock" size="sm" />
                Ver como estava
              </Button>
            </div>

            {notice && (
              <p className="card-sub" style={{ marginBottom: "var(--sp-4)", color: "var(--success)" }}>
                {notice}
              </p>
            )}

            {resolveError && (
              <div className="stack-sm" style={{ marginBottom: "var(--sp-4)" }}>
                <span className="error-text">
                  <Icon name="i-alert" size="sm" />
                  Não há nenhuma captura guardada até essa data: {resolveError}
                </span>
                <span className="hint">
                  Escolha uma data depois da primeira cópia ou faça uma nova extração em Nova extração.
                </span>
              </div>
            )}

            {timelineError && (
              <div className="stack-sm" style={{ marginBottom: "var(--sp-4)" }}>
                <span className="error-text">
                  <Icon name="i-alert" size="sm" />
                  {timelineError}
                </span>
                <div>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="od-touch"
                    onClick={() => void loadTimeline(siteUrl)}
                  >
                    <Icon name="i-refresh" size="sm" />
                    Tentar de novo
                  </Button>
                </div>
              </div>
            )}

            {timelineLoading && (
              <div className="stack-md" aria-hidden="true">
                {[0, 1, 2].map((row) => (
                  <Skeleton key={row} className="h-16 w-full" />
                ))}
              </div>
            )}

            {!timelineLoading && !timelineError && ordered.length === 0 && (
              <p className="card-sub">Nenhuma versão guardada para este site.</p>
            )}

            {!timelineLoading && ordered.length > 0 && (
              <div className="timeline">
                {ordered.map((entry, index) => {
                  const isSelected = entry.ref === selectedRef
                  return (
                    <div key={entry.ref} className={isSelected ? "tl-item is-selected" : "tl-item"}>
                      <button
                        type="button"
                        className="tl-btn od-touch"
                        aria-pressed={isSelected}
                        onClick={() => {
                          setNotice(null)
                          void loadPages(siteUrl, entry.ref)
                        }}
                      >
                        <span className="od-row" style={{ ["--od-gap" as string]: "8px", flexWrap: "wrap" }}>
                          <strong style={{ fontSize: "var(--fs-14)" }}>{formatStamp(entry.captured_at)}</strong>
                          {index === 0 && <Badge variant="accent">atual</Badge>}
                          <Badge variant="neutral">{entry.branch || branch || "main"}</Badge>
                        </span>
                        <span className="job-sub">
                          <span className="od-truncate" title={entry.message}>
                            {entry.message || "Sem descrição"}
                          </span>
                          <span aria-hidden="true">·</span>
                          <span>
                            {entry.pages} {entry.pages === 1 ? "página" : "páginas"}
                          </span>
                          <span aria-hidden="true">·</span>
                          <span>{formatBytes(entry.size_bytes)}</span>
                        </span>
                      </button>
                    </div>
                  )
                })}
              </div>
            )}

            <p className="hint" style={{ marginTop: "var(--sp-4)" }}>
              A captura abre como era na data escolhida — links internos apontam para a versão arquivada.
            </p>
          </div>

          {selectedRef && (
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
                Páginas dessa captura
              </h3>
              <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
                {selectedEntry ? `Cópia de ${formatStamp(selectedEntry.captured_at)}. ` : ""}
                {pages.length} {pages.length === 1 ? "página guardada" : "páginas guardadas"} nessa versão.
              </p>

              {pagesError && (
                <div className="stack-sm" style={{ marginBottom: "var(--sp-3)" }}>
                  <span className="error-text">
                    <Icon name="i-alert" size="sm" />
                    Não foi possível listar as páginas dessa versão: {pagesError}
                  </span>
                  <div>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="od-touch"
                      onClick={() => void loadPages(siteUrl, selectedRef)}
                    >
                      <Icon name="i-refresh" size="sm" />
                      Tentar de novo
                    </Button>
                  </div>
                </div>
              )}

              {pagesLoading && (
                <div className="stack-sm" aria-hidden="true">
                  {[0, 1, 2].map((row) => (
                    <Skeleton key={row} className="h-14 w-full" />
                  ))}
                </div>
              )}

              {!pagesLoading && !pagesError && pages.length === 0 && (
                <p className="card-sub">Essa versão não guardou nenhuma página. Escolha outra data na linha do tempo.</p>
              )}

              {pages.length > 0 && (
                <div className="job-list">
                  {pages.map((page) => {
                    const active = page.path === selectedPath
                    return (
                      <button
                        key={page.path}
                        type="button"
                        className="job-row od-touch"
                        aria-pressed={active}
                        style={{
                          width: "100%",
                          textAlign: "left",
                          background: active ? "var(--accent-soft)" : undefined,
                          borderColor: active ? "var(--accent-line)" : undefined,
                        }}
                        onClick={() => void openPage(page.path)}
                      >
                        <span className="job-favicon">
                          <Icon name="i-file" />
                        </span>
                        <span className="job-meta">
                          <span className="detail-url od-truncate" title={page.path}>
                            {page.path}
                          </span>
                          <span className="job-sub od-truncate">{page.title || "Sem título"}</span>
                        </span>
                        <span className="job-actions mono" style={{ fontSize: "var(--fs-12)" }}>
                          {formatBytes(page.size_bytes)}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {selectedRef && (
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
                Como a página era
              </h3>
              <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
                {selectedPath
                  ? "Confira abaixo a cópia guardada dessa página, como ela estava nessa data."
                  : "Escolha uma página na lista acima para ver como ela estava nessa data."}
              </p>

              {!selectedPath && (
                <p className="card-sub">Você está vendo uma cópia arquivada, não o site ao vivo.</p>
              )}

              {selectedPath && (
                <div className="stack-md">
                  <div className="od-row" style={{ ["--od-gap" as string]: "8px", flexWrap: "wrap" }}>
                    <span className="detail-url od-truncate" title={selectedPath}>
                      {selectedPath}
                    </span>
                    <a
                      href={api.timelinePageUrl(siteUrl, selectedRef, selectedPath)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-sm"
                    >
                      <Icon name="i-link" size="sm" />
                      Abrir em nova aba
                    </a>
                  </div>

                  {pageError && (
                    <span className="error-text">
                      <Icon name="i-alert" size="sm" />
                      Não foi possível ler os dados dessa página: {pageError} A cópia arquivada é mostrada mesmo assim.
                    </span>
                  )}

                  {pageLoading && <Skeleton className="h-4 w-52" />}

                  <iframe
                    title={`Cópia arquivada de ${selectedPath}`}
                    src={api.timelinePageUrl(siteUrl, selectedRef, selectedPath)}
                    sandbox=""
                    style={{
                      width: "100%",
                      height: "560px",
                      borderRadius: "var(--r-card)",
                      border: "1px solid var(--glass-border)",
                      background: "var(--bg-1)",
                    }}
                  />

                  {selectedPage && (
                    <DetailGrid>
                      <DetailRow label="Título" value={selectedPage.title || "Sem título"} />
                      <DetailRow label="Endereço original" value={selectedPage.url} mono />
                      <DetailRow label="Tamanho guardado" value={formatBytes(selectedPage.size_bytes)} />
                      <DetailRow
                        label="Assinatura do arquivo"
                        value={selectedPage.sha256}
                        mono
                        hint="Confere se o arquivo não mudou desde a cópia."
                      />
                    </DetailGrid>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

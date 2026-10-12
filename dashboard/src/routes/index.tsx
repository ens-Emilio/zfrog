import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"
import { api, Job, JobStatus } from "@/lib/api"
import { useT, type I18nKey } from "@/lib/i18n"
import { useToast } from "@/components/ToastRegion"
import { Spinner } from "@/components/ui/tui"

const inFlight: JobStatus[] = ["pending", "probing", "processing", "running"]

type FilterKey = "todas" | "ok" | "rodando" | "falhas"
const FILTERS: FilterKey[] = ["todas", "ok", "rodando", "falhas"]

const FILTER_LABELS: Record<FilterKey, I18nKey> = {
  todas: "home.filterAll",
  ok: "home.filterDone",
  rodando: "home.filterRunning",
  falhas: "home.filterFailed",
}

function bucketOf(status: JobStatus): FilterKey {
  if (status === "completed") return "ok"
  if (status === "failed" || status === "cancelled") return "falhas"
  if (inFlight.includes(status)) return "rodando"
  return "todas"
}

function hostOf(url: string) {
  try {
    return new URL(url).host
  } catch {
    return url.replace(/^https?:\/\//, "").split("/")[0]
  }
}

function clockOf(iso: string) {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}

function durOf(job: Job, files: number | undefined, failedShort: string, filesUnit: string): string {
  if (job.status === "failed") return job.error ? job.error.slice(0, 40) : failedShort
  if (inFlight.includes(job.status)) return ""
  const secs = (new Date(job.updated_at).getTime() - new Date(job.created_at).getTime()) / 1000
  const bp = files !== undefined ? `${files} ${filesUnit} ` : ""
  return secs >= 60 ? `${bp}${Math.floor(secs / 60)}m${String(Math.round(secs % 60)).padStart(2, "0")}s` : `${bp}${secs.toFixed(1)}s`
}

const VERBS: Partial<Record<string, string>> = {
  jump: "jump",
  tongue: "tongue",
  pond: "pond",
  mirror: "mirror",
  scrape: "scrape",
  singlepage: "jump",
  extract: "tongue",
}

function RunsPage() {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { q: urlQuery, view } = Route.useSearch()

  useEffect(() => {
    if (!urlQuery && !view) {
      navigate({ to: "/chat", replace: true }).catch(() => {})
    }
  }, [urlQuery, view, navigate])

  const [filter, setFilter] = useState<FilterKey>("todas")
  const [query, setQuery] = useState(urlQuery ?? "")
  const [sel, setSel] = useState(-1)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [live, setLive] = useState(true)

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: async () => {
      const data = await api.getJobs()
      return data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    },
    refetchInterval: live ? 5000 : false,
  })
  const jobs = jobsQuery.data ?? []
  const loading = jobsQuery.isLoading
  const error = jobsQuery.error instanceof Error ? jobsQuery.error.message : jobsQuery.error ? String(jobsQuery.error) : null

  const catalogQuery = useQuery({
    queryKey: ["catalog-palettes"],
    queryFn: () => api.getCatalog({ limit: 100 }),
    staleTime: 60_000,
    retry: false,
  })
  const palettes = useMemo(() => {
    const out: Record<string, string[]> = {}
    for (const card of catalogQuery.data?.cards ?? []) {
      const host = hostOf(card.url)
      if (!out[host]) out[host] = card.palette
    }
    return out
  }, [catalogQuery.data])

  const resultsQuery = useQuery({
    queryKey: ["job-results", jobs.filter((j) => j.status === "completed").map((j) => j.id)],
    queryFn: async () => {
      const ids = jobs.filter((j) => j.status === "completed").map((j) => j.id)
      const rows = await Promise.all(
        ids.map(async (id) => {
          try {
            return [id, await api.getJobResult(id)] as const
          } catch {
            return null
          }
        }),
      )
      const out: Record<string, number> = {}
      for (const row of rows) if (row) out[row[0]] = row[1].files_count
      return out
    },
    enabled: jobs.some((j) => j.status === "completed"),
    staleTime: Infinity,
  })
  const filesOf = resultsQuery.data ?? {}

  const cancelMutation = useMutation({
    mutationFn: (job: Job) => api.cancelJob(job.id),
    onSuccess: () => {
      toast(t("common.cancelledToast"))
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), "err"),
  })

  const rows = useMemo(
    () =>
      jobs.filter((j) => {
        if (filter !== "todas" && bucketOf(j.status) !== filter) return false
        if (!query) return true
        const host = hostOf(j.url).toLowerCase()
        const needle = query.toLowerCase()
        return j.url.toLowerCase().includes(needle) || host.includes(needle) || j.mode.includes(needle)
      }),
    [jobs, filter, query],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setSel((i) => Math.min(i + 1, rows.length - 1)) }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setSel((i) => Math.max(i - 1, 0)) }
      else if (e.key === "Enter") {
        const row = rows[sel]
        if (row) setExpanded((cur) => (cur === row.id ? null : row.id))
      } else if (e.key === "Escape") {
        if (expanded) setExpanded(null)
        else if (query) { setQuery(""); setSel(-1) }
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [rows, sel, expanded, query])

  useEffect(() => {
    if (sel >= rows.length) setSel(rows.length - 1)
  }, [rows.length, sel])

  const expandedJob = expanded ? jobs.find((j) => j.id === expanded) : null
  const expandedResult = useQuery({
    queryKey: ["job-result", expanded],
    queryFn: () => api.getJobResult(expanded!),
    enabled: !!expanded && expandedJob?.status === "completed",
    retry: false,
  })
  const expandedTokens = useQuery({
    queryKey: ["catalog-tokens", expandedJob ? hostOf(expandedJob.url) : ""],
    queryFn: () => api.getCatalogCard(catalogQuery.data!.cards.find((c) => hostOf(c.url) === hostOf(expandedJob!.url))!.id),
    enabled: !!expandedJob && !!catalogQuery.data?.cards.some((c) => hostOf(c.url) === hostOf(expandedJob.url)),
    staleTime: 60_000,
  })

  const expandedCode = useMemo(() => {
    const card = expandedJob ? catalogQuery.data?.cards.find((c) => hostOf(c.url) === hostOf(expandedJob.url)) : null
    if (!card?.palette.length) return null
    const prefix = hostOf(card.url).replace(/[^a-z0-9]/gi, "").slice(0, 8).toLowerCase() || "site"
    return card.palette.slice(0, 5).map((hex, i) => `--${prefix}-${i + 1}: ${hex};`)
  }, [expandedJob, catalogQuery.data])

  if (loading) {
    return (
      <div className="zf-view">
        <p className="zf-meta"><Spinner /> {t("home.loading")}</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="zf-view">
        <p className="zf-meta">{t("home.apiDown")} <b>./zfrog dev</b></p>
      </div>
    )
  }

  return (
    <div className="zf-view">
      <div className="zf-head">
        <h1 className="zf-title">{t("home.title")}</h1>
        <span className="zf-meta">{jobs.length} jobs · {rows.length} visíveis</span>
        <span className="spacer" />
        <button className="zf-btn zf-btn--ghost" aria-pressed={live} onClick={() => setLive((v) => !v)} style={{ fontSize: 12 }}>
          <span className={`zf-dot ${live ? "" : "zf-dot--idle"}`} /> {live ? t("common.liveOn") : t("common.liveOff")}
        </button>
      </div>

      <div className="zf-filters">
        <div role="group" aria-label="filtro de status" style={{ display: "flex", gap: "var(--s1)", flexWrap: "wrap" }}>
          {FILTERS.map((f) => (
            <button
              key={f}
              className="zf-pill"
              aria-pressed={filter === f}
              onClick={() => { setFilter(f); setSel(-1) }}
            >
              {t(FILTER_LABELS[f])}
            </button>
          ))}
        </div>
        <span className="zf-spacer" />
        <label className="zf-prompt" style={{ minWidth: 220 }}>
          <span className="caret">/</span>
          <input
            type="text"
            value={query}
            placeholder={t("home.filterPlaceholder")}
            aria-label={t("home.filterAria")}
            onChange={(e) => { setQuery(e.target.value); setSel(-1) }}
          />
        </label>
        <span className="zf-count">{rows.length} / {jobs.length}</span>
      </div>

      {!rows.length && jobs.length === 0 && (
        <div className="zf-panel" style={{ padding: "var(--s6)", maxWidth: 680 }}>
          <p className="zf-h2" style={{ color: "var(--accent)", marginBottom: "var(--s3)" }}>{t("home.emptyTitle")}</p>
          <p className="zf-meta" style={{ marginBottom: "var(--s4)" }}>O <b>zfrog</b> {t("home.emptyBody")}</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, color: "var(--muted)" }}>
            <div>• {t("home.emptyHint1")} <code className="zf-code" style={{ padding: "0 4px" }}>jump https://exemplo.com</code></div>
            <div>• {t("home.emptyHint2")}</div>
            <div>• {t("home.emptyHint3")}</div>
          </div>
          <div className="zf-row" style={{ marginTop: "var(--s5)" }}>
            <Link to="/probe" className="zf-btn zf-btn--primary" style={{ textDecoration: "none" }}>{t("home.emptyCta")}</Link>
            <Link to="/colecao" className="zf-btn" style={{ textDecoration: "none" }}>{t("home.emptyCollection")}</Link>
            <Link to="/design" className="zf-btn zf-btn--ghost" style={{ textDecoration: "none" }}>{t("home.emptyGuide")}</Link>
          </div>
        </div>
      )}

      {!rows.length && jobs.length > 0 && (
        <div className="zf-empty">{t("home.emptyFilter")} ({t(FILTER_LABELS[filter])}).</div>
      )}

      {!!rows.length && (
        <div className="zf-rows">
          {rows.map((job, i) => {
            const host = hostOf(job.url)
            const verb = VERBS[job.mode] ?? job.mode
            const isSel = i === sel
            const isOpen = expanded === job.id
            const pal = palettes[host] ?? []
            const dur = durOf(job, filesOf[job.id], t("home.failedShort"), t("home.filesUnit"))
            const running = inFlight.includes(job.status)
            const statusFlag =
              job.status === "completed" ? "--ok" :
              job.status === "failed" ? "--err" :
              running ? "--run" : "--warn"
            return (
              <div key={job.id}>
                <button
                  className="zf-run"
                  aria-selected={isSel}
                  aria-expanded={isOpen}
                  onClick={() => setExpanded(isOpen ? null : job.id)}
                  onMouseEnter={() => setSel(i)}
                >
                  <span className="gutter">{isSel ? "▍" : ""}</span>
                  <span className="zf-num" style={{ color: "var(--muted)" }}>{clockOf(job.created_at)}</span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    {running ? <Spinner /> : <span className={`zf-dot ${statusFlag === "--err" ? "zf-dot--err" : statusFlag === "--warn" ? "zf-dot--idle" : statusFlag === "--run" ? "" : ""}`} style={statusFlag === "--run" ? { background: "var(--run)" } : undefined} />}
                    <span className={`zf-flag ${statusFlag === "--ok" ? "zf-flag--ok" : statusFlag === "--err" ? "zf-flag--err" : statusFlag === "--run" ? "zf-flag--run" : "zf-flag--warn"}`} style={{ padding: "0 5px", fontSize: 10 }}>{job.status.slice(0, 3).toUpperCase()}</span>
                  </span>
                  <span className="cmd">{verb}</span>
                  <span className="dom" title={job.url}>{host}</span>
                  <span style={{ display: "flex", gap: 3 }}>
                    {pal.slice(0, 4).map((c, idx) => (
                      <i key={idx} style={{ width: 10, height: 10, borderRadius: 2, background: c, border: "1px solid var(--border)", display: "inline-block" }} />
                    ))}
                  </span>
                  <span className="zf-num" style={{ textAlign: "right", color: running ? "var(--run)" : "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{running ? job.status : dur}</span>
                </button>
                {running && (
                  <div className="zf-progress" style={{ margin: "0 var(--s4)" }}><i style={{ width: "38%" }} /></div>
                )}
                {isOpen && (
                  <div className="zf-run-detail">
                    <dl className="zf-kv">
                      <dt>url</dt><dd>{job.url}</dd>
                      <dt>modo</dt><dd><code>{job.mode}</code></dd>
                      <dt>status</dt><dd>{job.status}</dd>
                      <dt>profundidade</dt><dd>{job.max_depth} {t("home.levels")}</dd>
                      {job.error && (<><dt>erro</dt><dd style={{ color: "var(--error)" }}>{job.error}</dd></>)}
                      {!running && job.status !== "failed" && (<><dt>{t("home.files")}</dt><dd>{filesOf[job.id] ?? "…"} {t("home.files")}</dd></>)}
                    </dl>
                    {running && (
                      <div className="zf-row">
                        <button className="zf-btn zf-btn--ghost" style={{ color: "var(--warn)" }} onClick={(e) => { e.stopPropagation(); cancelMutation.mutate(job) }}>
                          {t("home.interrupt")}
                        </button>
                      </div>
                    )}
                    {expandedCode && (
                      <pre className="zf-code">{expandedCode.map((l) => l).join("\n")}</pre>
                    )}
                    <div className="zf-row">
                      {job.status === "completed" && (
                        <>
                          <a href={api.downloadUrl(job.id)} download className="zf-btn zf-btn--primary" onClick={(e) => e.stopPropagation()}>{t("common.downloadZip")}</a>
                          <Link to="/jobs/$id" params={{ id: job.id }} className="zf-btn" onClick={(e) => e.stopPropagation()}>{t("common.details")}</Link>
                          <Link to="/colecao" className="zf-btn zf-btn--ghost">{t("common.viewInCollection")}</Link>
                        </>
                      )}
                      <button className="zf-btn zf-btn--ghost" onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(job.id); toast(t("ajuda.copiedToast") ?? "copiado") }}>
                        copiar id
                      </button>
                      {job.status === "failed" && (
                        <Link to="/jobs/$id" params={{ id: job.id }} className="zf-btn">{t("common.details")}</Link>
                      )}
                      {expandedResult.data && <span className="zf-meta">{filesOf[job.id] ?? "…"} {t("home.files")}</span>}
                      {expandedTokens.data && <span className="zf-meta">{expandedTokens.data.tokens.fonts?.length ?? 0} fonte(s) · {expandedTokens.data.tokens.palette?.length ?? 0} cor(es)</span>}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export const Route = createFileRoute("/")({
  validateSearch: (search: Record<string, unknown>): { q?: string; view?: string } => ({
    q: "q" in search && typeof search.q === "string" ? search.q : undefined,
    view: "view" in search && typeof search.view === "string" ? search.view : undefined,
  }),
  component: RunsPage,
})

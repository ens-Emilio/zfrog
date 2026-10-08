import { createFileRoute, Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"
import { api, Job, JobStatus } from "@/lib/api"
import { useT, type I18nKey } from "@/lib/i18n"
import { useToast } from "@/components/ToastRegion"
import { SYM, Spinner, Swatch, DetailLine, CodeBlock, Gut, TuiPanel } from "@/components/ui/tui"

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

/** duration in seconds, humanized: "1.2s" / "2m14s" */
function durOf(job: Job, files: number | undefined, failedShort: string, filesUnit: string): string {
  if (job.status === "failed") return job.error ? job.error.slice(0, 40) : failedShort
  if (inFlight.includes(job.status)) return ""
  const secs = (new Date(job.updated_at).getTime() - new Date(job.created_at).getTime()) / 1000
  const bp = files !== undefined ? `${files} ${filesUnit} ` : ""
  return secs >= 60 ? `${bp}${Math.floor(secs / 60)}m${String(Math.round(secs % 60)).padStart(2, "0")}s` : `${bp}${secs.toFixed(1)}s`
}

/** job mode → zfrog verb */
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
  const queryClient = useQueryClient()
  const { q: urlQuery } = Route.useSearch()
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

  // real palettes from the catalog: the content is the decoration (§4)
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

  // j/k navigation, enter expands (§5.7)
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
      <p className="empty">
        <Spinner /> {t("home.loading")}
      </p>
    )
  }

  if (error) {
    return (
      <p className="empty">
        {t("home.apiDown")} <b>./zfrog dev</b>
      </p>
    )
  }

  return (
    <TuiPanel
      title={t("home.title")}
      action={
        <button
          className="tgl"
          aria-pressed={live}
          onClick={() => setLive((v) => !v)}
          style={{ fontSize: 11 }}
        >
          {live ? t("common.liveOn") : t("common.liveOff")}
        </button>
      }
    >
      <div className="filters mt-2">
        <div className="toggles" role="group" aria-label="filtro de status">
          {FILTERS.map((f) => (
            <button
              key={f}
              className="tgl"
              aria-pressed={filter === f}
              onClick={() => {
                setFilter(f)
                setSel(-1)
              }}
            >
              {t(FILTER_LABELS[f])}
            </button>
          ))}
        </div>
        <span className="searchline" style={{ marginLeft: "auto" }}>
          <span className="slash">/</span>
          <input
            type="text"
            value={query}
            placeholder={t("home.filterPlaceholder")}
            aria-label={t("home.filterAria")}
            onChange={(e) => {
              setQuery(e.target.value)
              setSel(-1)
            }}
          />
        </span>
      </div>

      <div className="rows">
        {!rows.length && jobs.length === 0 && (
          <div className="tui-panel" style={{ padding: "16px 20px", margin: "16px 0", maxWidth: "680px" }}>
            <div style={{ color: "var(--accent)", fontWeight: "bold", marginBottom: "8px" }}>
              ┌─ {t("home.emptyTitle")} ──────────────────
            </div>
            <p style={{ margin: "6px 0", color: "var(--fg-dim)" }}>
              O <b>zfrog</b> {t("home.emptyBody")}
            </p>
            <div style={{ margin: "12px 0 16px 0", display: "flex", flexDirection: "column", gap: "6px", fontSize: 13 }}>
              <div>
                <span style={{ color: "var(--accent)" }}>•</span> {t("home.emptyHint1")} <code style={{ color: "var(--fg)", background: "var(--bg-panel)", padding: "1px 4px", border: "1px solid var(--border)" }}>jump https://exemplo.com</code>)
              </div>
              <div>
                <span style={{ color: "var(--accent)" }}>•</span> {t("home.emptyHint2")}
              </div>
              <div>
                <span style={{ color: "var(--accent)" }}>•</span> {t("home.emptyHint3")}
              </div>
            </div>
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "12px" }}>
              <Link to="/probe" className="tui-btn accent" style={{ textDecoration: "none" }}>
                {t("home.emptyCta")}
              </Link>
              <Link to="/colecao" className="tui-btn" style={{ textDecoration: "none" }}>
                {t("home.emptyCollection")}
              </Link>
              <Link to="/design" className="tui-btn" style={{ textDecoration: "none" }}>
                {t("home.emptyGuide")}
              </Link>
            </div>
            <div style={{ color: "var(--border)", marginTop: "12px" }}>
              └─────────────────────────────────────────────────────────────
            </div>
          </div>
        )}
        {!rows.length && jobs.length > 0 && (
          <p className="empty">
            {t("home.emptyFilter")} ({t(FILTER_LABELS[filter])}).
          </p>
        )}
        {rows.map((job, i) => {
          const host = hostOf(job.url)
          const verb = VERBS[job.mode] ?? job.mode
          const isSel = i === sel
          const isOpen = expanded === job.id
          const pal = palettes[host] ?? []
          const dur = durOf(job, filesOf[job.id], t("home.failedShort"), t("home.filesUnit"))
          return (
            <div key={job.id}>
              <button
                className={`runrow${job.status === "failed" ? " fail" : ""}${isSel ? " sel" : ""}`}
                aria-expanded={isOpen}
                onClick={() => setExpanded(isOpen ? null : job.id)}
                onMouseEnter={() => setSel(i)}
              >
                <Gut active={isSel} />
                <span className={`sym ${inFlight.includes(job.status) ? "run" : job.status === "completed" ? "ok" : "fail"}`}>
                  {inFlight.includes(job.status) ? "" : job.status === "completed" ? SYM.ok : SYM.fail}
                  {inFlight.includes(job.status) && <Spinner />}
                </span>
                <span className="t">{clockOf(job.created_at)}</span>
                <span className="cmd">{verb}</span>
                <span className="dom">{host}</span>
                <span className="sw">{job.status === "completed" && <Swatch colors={pal} />}</span>
                <span className="stat">{inFlight.includes(job.status) ? job.status : dur}</span>
              </button>
              {isOpen && (
                <div className="detail">
                  <DetailLine kind={job.status === "failed" ? "err" : undefined}>
                    {job.status === "failed"
                      ? job.error ?? t("home.failedShort")
                      : `${job.max_depth} ${t("home.levels")} · ${filesOf[job.id] ?? "…"} ${t("home.files")}`}
                  </DetailLine>
                  {inFlight.includes(job.status) && (
                    <DetailLine>
                      <button className="tgl" style={{ color: "var(--warn)" }} onClick={(e) => { e.stopPropagation(); cancelMutation.mutate(job) }}>
                        {t("home.interrupt")}
                      </button>
                    </DetailLine>
                  )}
                  {expandedCode && <CodeBlock code={expandedCode} />}
                  {job.status === "completed" && (
                    <DetailLine>
                      <a
                        href={api.downloadUrl(job.id)}
                        download
                        style={{ color: "var(--fg)" }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t("common.downloadZip")}
                      </a>
                      {" · "}
                      <Link to="/jobs/$id" params={{ id: job.id }} style={{ color: "var(--fg-muted)" }}>
                        {t("common.details")}
                      </Link>
                      {" · "}
                      <Link to="/colecao" style={{ color: "var(--fg-muted)" }}>
                        {t("common.viewInCollection")}
                      </Link>
                      {expandedResult.data && ` · ${filesOf[job.id] ?? "…"} ${t("home.files")}`}
                      {expandedTokens.data && ` · ${expandedTokens.data.tokens.fonts?.length ?? 0} fonte(s) · ${expandedTokens.data.tokens.palette?.length ?? 0} cor(es)`}
                    </DetailLine>
                  )}
                  {job.status !== "completed" && expandedResult.data && (
                    <DetailLine>
                      <Link to="/colecao" style={{ color: "var(--fg-muted)" }}>
                        {t("common.viewInCollection")}
                      </Link>
                      {expandedTokens.data && ` · ${expandedTokens.data.tokens.fonts?.length ?? 0} fonte(s) · ${expandedTokens.data.tokens.palette?.length ?? 0} cor(es)`}
                    </DetailLine>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </TuiPanel>
  )
}

export const Route = createFileRoute("/")({
  validateSearch: (search: Record<string, unknown>): { q?: string } =>
    "q" in search && typeof search.q === "string" ? { q: search.q } : {},
  component: RunsPage,
})

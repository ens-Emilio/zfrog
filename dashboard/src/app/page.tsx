"use client"
import { useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { api, Job, JobMode, JobStatus } from "@/lib/api"
import { MODES, STATUS_HELP, STATUS_LABELS } from "@/lib/labels"
import { usePolling } from "@/hooks/usePolling"
import { useToast } from "@/components/ToastRegion"
import { cn, faviconLetter, formatBytes, formatNumber, timeAgo } from "@/lib/utils"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/ds"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Modal } from "@/components/ui/modal"
import { StatusBadge } from "@/components/ui/badge"
import { Activity, AlertTriangle, Download, Eye, Filter, Play, RefreshCw, RotateCw, Search, SearchX, X } from "lucide-react"

/** The four filters of the prototype, each one a rank over the real statuses. */
type FilterKey = "all" | "done" | "active" | "failed"

const FILTERS: { key: FilterKey; label: string; dot?: string }[] = [
  { key: "all", label: "Todas" },
  { key: "done", label: "Concluídas", dot: "var(--success)" },
  { key: "active", label: "Em andamento", dot: "var(--accent)" },
  { key: "failed", label: "Falhas", dot: "var(--danger)" },
]

const inFlight: JobStatus[] = ["pending", "probing", "processing", "running"]

/** The host shown in a row; falls back to the raw string for a malformed URL. */
function hostOf(url: string) {
  try {
    return new URL(url).host
  } catch {
    return url.replace(/^https?:\/\//, "").split("/")[0]
  }
}

const DAY_MS = 86_400_000

export default function JobsPage() {
  const toast = useToast()
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState("")
  const [filter, setFilter] = useState<FilterKey>("all")
  const [polling, setPolling] = useState(true)
  const [confirming, setConfirming] = useState<Job | null>(null)
  /** Files and bytes per finished job, read once from the real result endpoint. */
  const [results, setResults] = useState<Record<string, { files: number; bytes: number }>>({})
  const askedResults = useRef<Set<string>>(new Set())

  const fetchJobs = async () => {
    try {
      const data = await api.getJobs()
      setJobs(data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setTimeout(fetchJobs, 0)
  }, [])

  usePolling(fetchJobs, 5000, polling)

  // The list endpoint carries no file count, so the totals come from the result
  // endpoint — once per job, never re-asked while the page is open.
  useEffect(() => {
    const missing = jobs.filter((j) => j.status === "completed" && !askedResults.current.has(j.id))
    if (!missing.length) return
    missing.forEach((j) => askedResults.current.add(j.id))
    let cancelled = false
    Promise.all(
      missing.map(async (j) => {
        try {
          const r = await api.getJobResult(j.id)
          return [j.id, { files: r.files_count, bytes: r.total_size_bytes }] as const
        } catch {
          return null
        }
      })
    ).then((rows) => {
      if (cancelled) return
      const known = rows.filter((row): row is readonly [string, { files: number; bytes: number }] => row !== null)
      if (!known.length) return
      setResults((prev) => {
        const next = { ...prev }
        for (const [id, value] of known) next[id] = value
        return next
      })
    })
    return () => {
      cancelled = true
    }
  }, [jobs])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return jobs.filter((j) => {
      if (filter !== "all") {
        const bucket: FilterKey =
          j.status === "completed" ? "done" : j.status === "failed" || j.status === "cancelled" ? "failed" : "active"
        if (bucket !== filter) return false
      }
      if (!needle) return true
      const host = hostOf(j.url).toLowerCase()
      return j.url.toLowerCase().includes(needle) || host.includes(needle) || j.id.toLowerCase().includes(needle)
    })
  }, [jobs, q, filter])

  const stats = useMemo(() => {
    const at = (job: Job) => new Date(job.created_at).getTime()
    const now = new Date()
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
    const yesterdayStart = todayStart - DAY_MS

    const today = jobs.filter((j) => at(j) >= todayStart).length
    const yesterday = jobs.filter((j) => at(j) >= yesterdayStart && at(j) < todayStart).length
    const delta = yesterday > 0 ? Math.round(((today - yesterday) / yesterday) * 100) : null

    const active = jobs.filter((j) => inFlight.includes(j.status))
    const breakdown = [
      { n: active.filter((j) => j.status === "running").length, what: "baixando" },
      { n: active.filter((j) => j.status === "processing").length, what: "organizando" },
      { n: active.filter((j) => j.status === "probing").length, what: "analisando" },
      { n: active.filter((j) => j.status === "pending").length, what: "na fila" },
    ].filter((part) => part.n > 0)

    const completed = jobs.filter((j) => j.status === "completed").length
    const files = jobs.reduce((sum, j) => sum + (results[j.id]?.files ?? 0), 0)

    const weekAgo = Date.now() - 7 * DAY_MS
    const settled = jobs.filter((j) => at(j) >= weekAgo && (j.status === "completed" || j.status === "failed"))
    const rate = settled.length ? settled.filter((j) => j.status === "completed").length / settled.length : null

    return {
      today,
      delta,
      yesterday,
      active: active.length,
      breakdown,
      completed,
      files,
      rate,
      settled: settled.length,
    }
  }, [jobs, results])

  const handleCancel = async (job: Job) => {
    try {
      await api.cancelJob(job.id)
      toast("Execução interrompida.")
      await fetchJobs()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err")
    }
  }

  const handleRerun = async (job: Job) => {
    try {
      await api.createJob({ url: job.url, mode: job.mode, max_depth: job.max_depth })
      toast("Nova execução criada.")
      await fetchJobs()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err")
    }
  }

  return (
    <div className="view-grid">
      <Topbar
        title="Execuções"
        description="Cada vez que você baixa um site ou extrai dados, aparece aqui. Clique em uma linha para ver os detalhes."
        action={
          <>
            <Button variant="secondary" size="sm" onClick={() => fetchJobs()} title="Buscar a lista novamente agora">
              <RefreshCw className="ic ic-sm" aria-hidden="true" /> Atualizar
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPolling((p) => !p)}
              aria-pressed={polling}
              title="Atualização automática da lista a cada 5 segundos"
            >
              <span
                className={cn("h-2 w-2 rounded-full", polling ? "bg-emerald-500 animate-pulse" : "bg-zinc-400")}
                aria-hidden="true"
              />
              {polling ? "Ao vivo" : "Pausado"}
            </Button>
            <Link href="/probe">
              <Button size="sm">
                <Play className="ic ic-sm" aria-hidden="true" /> Nova extração
              </Button>
            </Link>
          </>
        }
      />

      <StatStrip columns={4}>
        <StatCard
          label="Execuções hoje"
          value={formatNumber(stats.today)}
          trend={
            stats.delta === null
              ? stats.today > 0
                ? "nenhuma execução ontem"
                : undefined
              : `${stats.delta >= 0 ? "+" : ""}${stats.delta}% vs. ontem`
          }
          trendDirection={stats.delta === null ? undefined : stats.delta >= 0 ? "up" : "down"}
          icon={<Activity className="ic ic-sm" aria-hidden="true" />}
        />
        <StatCard
          label="Em andamento"
          value={formatNumber(stats.active)}
          trend={
            stats.breakdown.length
              ? stats.breakdown.map((part) => `${part.n} ${part.what}`).join(" · ")
              : "nada em andamento agora"
          }
        />
        <StatCard
          label="Concluídas"
          value={formatNumber(stats.completed)}
          trend={stats.files > 0 ? `${formatNumber(stats.files)} arquivos no total` : undefined}
        />
        <StatCard
          label="Taxa de sucesso"
          value={stats.rate === null ? "—" : `${Math.round(stats.rate * 100)}%`}
          trend={
            stats.settled === 0
              ? "últimos 7 dias · sem execuções concluídas"
              : `últimos 7 dias · ${stats.settled} execuções`
          }
        />
      </StatStrip>

      <div className="toolbar">
        <div className="search-wrap">
          <Search className="ic" aria-hidden="true" />
          <input
            className="input"
            id="job-search"
            type="search"
            placeholder="Buscar por URL ou domínio…"
            aria-label="Buscar execuções"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="filter-rail" role="group" aria-label="Filtrar por status">
          {FILTERS.map((f) => (
            <Chip key={f.key} active={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.dot ? (
                <span
                  className="dot"
                  style={{ width: 7, height: 7, borderRadius: "50%", background: f.dot, display: "inline-block" }}
                  aria-hidden="true"
                />
              ) : (
                <Filter className="ic" aria-hidden="true" />
              )}
              {f.label}
            </Chip>
          ))}
        </div>
      </div>

      <div className="list-meta">
        <span>
          {filtered.length} {filtered.length === 1 ? "execução" : "execuções"}
        </span>
        <span>As capturas ficam guardadas por 24 horas</span>
      </div>

      {loading ? (
        <div className="stack-sm" aria-hidden="true">
          <Skeleton className="h-[78px]" />
          <Skeleton className="h-[78px]" />
          <Skeleton className="h-[78px]" />
        </div>
      ) : error && jobs.length === 0 ? (
        <EmptyState
          icon={<AlertTriangle className="ic" aria-hidden="true" />}
          title="Não foi possível falar com o servidor"
          description={`${error} Verifique se a API está rodando (./zfrog dev) e tente de novo.`}
          action={{ label: "Tentar de novo", onClick: () => void fetchJobs() }}
        />
      ) : jobs.length === 0 ? (
        <EmptyState
          icon={<Play className="ic" aria-hidden="true" />}
          title="Nenhuma extração ainda"
          description="O zfrog copia sites para o seu computador e extrai dados de páginas. Comece informando o endereço de um site para ver a primeira execução aqui."
          href={{ label: "Nova extração", href: "/probe" }}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<SearchX className="ic" aria-hidden="true" />}
          title="Nenhuma execução encontrada"
          description="Ajuste a busca ou o filtro de status. Se ainda não há nada aqui, comece baixando um site."
          action={{
            label: "Limpar filtros",
            onClick: () => {
              setQ("")
              setFilter("all")
            },
          }}
        />
      ) : (
        <div className="job-list" role="list">
          {filtered.map((job) => {
            const host = hostOf(job.url)
            const mode = MODES[job.mode as JobMode]
            const result = results[job.id]
            const sub: React.ReactNode[] = [
              <span key="mode">{mode?.label ?? job.mode}</span>,
              <span key="depth">profundidade {job.max_depth}</span>,
            ]
            if (result) {
              sub.push(<span key="files">{formatNumber(result.files)} arquivos</span>)
              sub.push(<span key="size">{formatBytes(result.bytes)}</span>)
            }
            sub.push(<span key="when">{timeAgo(job.created_at)}</span>)
            const running = inFlight.includes(job.status)

            return (
              <article key={job.id} className="job-row" role="listitem">
                <div className="job-favicon" aria-hidden="true">
                  {faviconLetter(host)}
                </div>
                <div className="job-meta">
                  <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
                    <Link
                      href={`/jobs/${job.id}`}
                      className="job-url od-truncate"
                      style={{ flex: "1 1 240px" }}
                      title={`${job.url} · ${STATUS_HELP[job.status]}`}
                    >
                      {host}
                    </Link>
                    <StatusBadge status={job.status} />
                  </div>
                  <span className="job-sub">
                    {sub.flatMap((node, index) =>
                      index === 0 ? [node] : [<span key={`sep-${index}`} aria-hidden="true">·</span>, node]
                    )}
                  </span>
                </div>
                <div className="job-actions">
                  <Link href={`/jobs/${job.id}`}>
                    <Button size="sm" variant="secondary">
                      <Eye className="ic ic-sm" aria-hidden="true" /> Ver
                    </Button>
                  </Link>
                  {job.status === "completed" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="icon-btn"
                      aria-label={`Baixar pacote de ${host}`}
                      title="Baixar o pacote ZIP"
                      onClick={() => window.open(api.downloadUrl(job.id), "_blank")}
                    >
                      <Download className="ic ic-sm" aria-hidden="true" />
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="icon-btn"
                      aria-label={`Reexecutar ${host}`}
                      title="Reexecutar com o mesmo endereço e modo"
                      onClick={() => void handleRerun(job)}
                    >
                      <RotateCw className="ic ic-sm" aria-hidden="true" />
                    </Button>
                  )}
                  {running && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="icon-btn"
                      aria-label={`Interromper execução de ${host}`}
                      title={`Interromper — ${STATUS_LABELS[job.status]}`}
                      onClick={() => setConfirming(job)}
                    >
                      <X className="ic ic-sm" aria-hidden="true" />
                    </Button>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}

      <Modal
        open={confirming !== null}
        title="Interromper esta captura?"
        body={
          confirming
            ? `A execução de ${hostOf(confirming.url)} será cancelada e o que já foi baixado será descartado.`
            : ""
        }
        confirmLabel="Interromper"
        danger
        onConfirm={() => {
          const job = confirming
          setConfirming(null)
          if (job) void handleCancel(job)
        }}
        onClose={() => setConfirming(null)}
      />
    </div>
  )
}

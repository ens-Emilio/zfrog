import { createFileRoute, Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"
import { api, JobStatus } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { useWebSocket, WsEvent } from "@/hooks/useWebSocket"
import { useToast } from "@/components/ToastRegion"
import { formatBytes } from "@/lib/utils"
import { Spinner } from "@/components/ui/tui"

const inFlight: JobStatus[] = ["pending", "probing", "processing", "running"]

interface LogLine {
  ts: string
  lvl: "info" | "ok" | "warn" | "err"
  text: string
}

function nowClock() {
  return new Date().toLocaleTimeString("pt-BR", { hour12: false })
}

function JobDetailPage() {
  const { id } = Route.useParams()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [live, setLive] = useState(true)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const t = useT()
  const [logs, setLogs] = useState<LogLine[]>([])

  const jobQuery = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id),
    refetchInterval: live ? 5000 : false,
  })
  const job = jobQuery.data ?? null
  const loading = jobQuery.isLoading
  const error = jobQuery.error instanceof Error ? jobQuery.error.message : jobQuery.error ? String(jobQuery.error) : null

  const resultQuery = useQuery({
    queryKey: ["job-result", id],
    queryFn: () => api.getJobResult(id),
    enabled: job?.status === "completed",
    retry: false,
  })
  const result = resultQuery.data ?? null
  const refreshJob = () => queryClient.invalidateQueries({ queryKey: ["job", id] })

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelJob(id),
    onSuccess: () => { toast(t("common.cancelledToast")); refreshJob() },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), "err"),
  })

  const retryMutation = useMutation({
    mutationFn: () => job ? api.createJob({ url: job.url, mode: job.mode, max_depth: job.max_depth }) : Promise.reject(new Error(t("common.jobDataMissing"))),
    onSuccess: () => { toast(t("common.recreatedToast")); refreshJob() },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), "err"),
  })

  const onWsEvent = useCallback((ev: WsEvent) => {
    if (ev.type === "status" && ev.data?.job_id === id) {
      refreshJob()
      const st = String(ev.data.status ?? "")
      setLogs((cur) => [...cur, { ts: nowClock(), lvl: st === "failed" ? "err" : st === "completed" ? "ok" : "info", text: `status: ${st}${ev.data.error ? ` — ${ev.data.error}` : ""}` }])
    } else if (ev.type === "progress" && ev.data?.job_id === id) {
      setLogs((cur) => [...cur, { ts: nowClock(), lvl: "info", text: String(ev.data.message ?? ev.data.status ?? "progresso") }])
    }
  }, [id, refreshJob])

  useWebSocket(id, onWsEvent)

  if (loading) {
    return <div className="zf-view"><p className="zf-meta"><Spinner /> {t("job.loading")} <code>{id}</code>…</p></div>
  }

  if (error || !job) {
    return (
      <div className="zf-view">
        <div className="zf-panel" style={{ borderColor: "var(--error)" }}>
          <div className="zf-panel-bd">
            <p style={{ color: "var(--error)", fontSize: "var(--fs-meta)" }}>✗ {t("job.notFound")}: {error}</p>
            <Link to="/" className="zf-btn" style={{ marginTop: "var(--s3)" }}>{t("job.backToRuns")}</Link>
          </div>
        </div>
      </div>
    )
  }

  const isRunning = inFlight.includes(job.status)

  return (
    <div className="zf-view">
      <div className="zf-head">
        <Link to="/" style={{ color: "var(--muted)", fontSize: "var(--fs-meta)" }}>{t("job.back")}</Link>
        <span className="zf-meta">/</span>
        <h1 className="zf-title" style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-h2)" }}><code>{job.id}</code></h1>
        <span style={{ flex: 1 }} />
        {isRunning && <button type="button" className="zf-btn zf-btn--danger" onClick={() => setConfirmCancel(true)}>{t("job.cancelRun")}</button>}
        {job.status === "failed" && <button type="button" className="zf-btn zf-btn--primary" onClick={() => retryMutation.mutate()} disabled={retryMutation.isPending}>{t("job.retry")}</button>}
        <button type="button" className="zf-btn" onClick={() => setLive((v) => !v)}>{live ? t("common.liveActive") : t("common.paused")}</button>
      </div>

      <div className="zf-panel">
        <div className="zf-panel-hd">
          <span className="zf-label">{t("job.infoTitle")}</span>
          <span className={`zf-flag ${job.status === "completed" ? "zf-flag--ok" : job.status === "failed" ? "zf-flag--err" : "zf-flag--run"}`} style={{ marginLeft: "auto" }}>[{job.status.toUpperCase()}] {isRunning && <Spinner />}</span>
        </div>
        <div className="zf-panel-bd">
          <dl className="zf-kv">
            <div className="zf-kv-row"><dt>url</dt><dd><a href={job.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>{job.url}</a></dd></div>
            <div className="zf-kv-row"><dt>modo</dt><dd><code>{job.mode}</code></dd></div>
            <div className="zf-kv-row"><dt>{t("job.depth")}</dt><dd>{job.max_depth} {t("home.levels")}</dd></div>
            <div className="zf-kv-row"><dt>{t("job.createdAt")}</dt><dd>{job.created_at}</dd></div>
            <div className="zf-kv-row"><dt>{t("job.updatedAt")}</dt><dd>{job.updated_at}</dd></div>
            {job.error && <div className="zf-kv-row"><dt>{t("job.error")}</dt><dd style={{ color: "var(--error)" }}>{job.error}</dd></div>}
            {job.output_path && <div className="zf-kv-row"><dt>{t("job.output")}</dt><dd><code>{job.output_path}</code></dd></div>}
          </dl>
        </div>
      </div>

      {result && (
        <div className="zf-panel" style={{ borderColor: "var(--ok)" }}>
          <div className="zf-panel-hd"><span className="zf-label">✓ {t("job.resultTitle")}</span></div>
          <div className="zf-panel-bd">
            <dl className="zf-kv">
              <div className="zf-kv-row"><dt>{t("job.files")}</dt><dd>{result.files_count} arquivo(s)</dd></div>
              <div className="zf-kv-row"><dt>{t("job.totalSize")}</dt><dd>{formatBytes(result.total_size_bytes)}</dd></div>
              <div className="zf-kv-row"><dt>{t("job.duration")}</dt><dd>{result.duration_seconds.toFixed(2)}s</dd></div>
              <div className="zf-kv-row"><dt>{t("job.engineUsed")}</dt><dd><code>{result.engine_used}</code></dd></div>
              <div className="zf-kv-row"><dt>{t("job.diskPath")}</dt><dd><code>{result.output_path}</code></dd></div>
            </dl>
            <div className="zf-row">
              <a href={api.downloadUrl(job.id)} download className="zf-btn zf-btn--primary">{t("common.downloadZip")}</a>
              {job.mode === "pdf" && <a href={api.pdfUrl(job.id)} download className="zf-btn">{t("common.downloadPdf")}</a>}
              <Link to="/colecao" className="zf-btn">{t("common.viewCollection")}</Link>
            </div>
          </div>
        </div>
      )}

      <div className="zf-panel">
        <div className="zf-panel-hd"><span className="zf-label">{t("job.liveConsole")}</span><span className={`zf-dot ${isRunning ? "" : "zf-dot--idle"}`} style={{ marginLeft: 8, display: "inline-block" }} /></div>
        <div className="zf-panel-bd" style={{ padding: 0 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-meta)", background: "var(--bg)", padding: "var(--s4)", maxHeight: 220, overflowY: "auto" }}>
            {logs.length === 0 ? <span className="zf-meta">{t("job.waitingEvents")}</span>
            : logs.map((l, i) => (
              <div key={i} style={{ display: "flex", gap: "var(--s3)", color: l.lvl === "err" ? "var(--error)" : l.lvl === "ok" ? "var(--ok)" : "var(--fg)" }}>
                <span className="zf-micro">[{l.ts}]</span><span>{l.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {confirmCancel && (
        <dialog open className="zf-modal" onClose={() => setConfirmCancel(false)}>
          <div className="zf-modal-hd"><span style={{ fontWeight: 600 }}>{t("job.cancelTitle")}</span><span className="zf-spacer" /><button type="button" className="zf-btn zf-btn--ghost" onClick={() => setConfirmCancel(false)}>✗</button></div>
          <div className="zf-modal-bd"><p>{t("job.cancelBody")} <code>{job.id}</code>?</p></div>
          <div className="zf-modal-ft">
            <button type="button" className="zf-btn zf-btn--danger" onClick={() => { setConfirmCancel(false); cancelMutation.mutate() }}>{t("job.confirmCancel")}</button>
            <button type="button" className="zf-btn" onClick={() => setConfirmCancel(false)}>{t("job.goBack")}</button>
          </div>
        </dialog>
      )}
    </div>
  )
}

export const Route = createFileRoute("/jobs/$id")({
  component: JobDetailPage,
})

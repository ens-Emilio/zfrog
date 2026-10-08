import { createFileRoute, Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"
import { api, JobStatus } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { useWebSocket, WsEvent } from "@/hooks/useWebSocket"
import { useToast } from "@/components/ToastRegion"
import { formatBytes } from "@/lib/utils"
import { Spinner, SYM, TuiModal } from "@/components/ui/tui"

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
    onSuccess: () => {
      toast(t("common.cancelledToast"))
      refreshJob()
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), "err"),
  })

  const retryMutation = useMutation({
    mutationFn: () =>
      job
        ? api.createJob({ url: job.url, mode: job.mode, max_depth: job.max_depth })
        : Promise.reject(new Error(t("common.jobDataMissing"))),
    onSuccess: () => {
      toast(t("common.recreatedToast"))
      refreshJob()
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e), "err"),
  })

  const onWsEvent = useCallback(
    (ev: WsEvent) => {
      if (ev.type === "status" && ev.data?.job_id === id) {
        refreshJob()
        const st = String(ev.data.status ?? "")
        setLogs((cur) => [
          ...cur,
          {
            ts: nowClock(),
            lvl: st === "failed" ? "err" : st === "completed" ? "ok" : "info",
            text: `status: ${st}${ev.data.error ? ` — ${ev.data.error}` : ""}`,
          },
        ])
      } else if (ev.type === "progress" && ev.data?.job_id === id) {
        setLogs((cur) => [
          ...cur,
          { ts: nowClock(), lvl: "info", text: String(ev.data.message ?? ev.data.status ?? "progresso") },
        ])
      }
    },
    [id, refreshJob],
  )

  useWebSocket(id, onWsEvent)

  if (loading) {
    return (
      <p className="empty">
        <Spinner /> {t("job.loading")} <code>{id}</code>…
      </p>
    )
  }

  if (error || !job) {
    return (
      <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
        <p style={{ color: "var(--error)" }}>{SYM.fail} {t("job.notFound")}: {error}</p>
        <div style={{ marginTop: "0.5lh" }}>
          <Link to="/" className="tui-btn">
            {t("job.backToRuns")}
          </Link>
        </div>
      </div>
    )
  }

  const isRunning = inFlight.includes(job.status)

  return (
    <>
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-2">
          <Link to="/" style={{ color: "var(--fg-dim)", textDecoration: "none" }}>
            {t("job.back")}
          </Link>
          <span style={{ color: "var(--fg-dim)" }}>/</span>
          <h1><code>{job.id}</code></h1>
        </div>
        <div className="flex gap-2">
          {isRunning && (
            <button
              type="button"
              className="tui-btn danger"
              onClick={() => setConfirmCancel(true)}
              style={{ fontSize: 11 }}
            >
              {t("job.cancelRun")}
            </button>
          )}
          {job.status === "failed" && (
            <button
              type="button"
              className="tui-btn accent"
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              style={{ fontSize: 11 }}
            >
              {t("job.retry")}
            </button>
          )}
          <button
            type="button"
            className="tui-btn"
            onClick={() => setLive((v) => !v)}
            style={{ fontSize: 11 }}
          >
            {live ? t("common.liveActive") : t("common.paused")}
          </button>
        </div>
      </div>

      {/* Run metadata */}
      <div className="tui-panel" style={{ marginTop: "0.5lh" }}>
        <div className="tui-panel-head">
          <span className="tui-label">{t("job.infoTitle")}</span>
          <span
            style={{
              color: job.status === "completed" ? "var(--ok)" : job.status === "failed" ? "var(--error)" : "var(--warn)",
              fontWeight: 500,
            }}
          >
            [{job.status.toUpperCase()}] {isRunning && <Spinner />}
          </span>
        </div>

        <dl className="tui-kv">
          <dt>url</dt>
          <dd>
            <a href={job.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
              {job.url}
            </a>
          </dd>
          <dt>modo</dt>
          <dd><code>{job.mode}</code></dd>
          <dt>{t("job.depth")}</dt>
          <dd>{job.max_depth} {t("home.levels")}</dd>
          <dt>{t("job.createdAt")}</dt>
          <dd>{job.created_at}</dd>
          <dt>{t("job.updatedAt")}</dt>
          <dd>{job.updated_at}</dd>
          {job.error && (
            <>
              <dt>{t("job.error")}</dt>
              <dd style={{ color: "var(--error)" }}>{job.error}</dd>
            </>
          )}
          {job.output_path && (
            <>
              <dt>{t("job.output")}</dt>
              <dd><code>{job.output_path}</code></dd>
            </>
          )}
        </dl>
      </div>

      {/* Extraction result */}
      {result && (
        <div className="tui-panel" style={{ borderColor: "var(--ok)" }}>
          <span className="tui-label">{SYM.ok} {t("job.resultTitle")}</span>
          <dl className="tui-kv">
            <dt>{t("job.files")}</dt>
            <dd>{result.files_count} arquivo(s)</dd>
            <dt>{t("job.totalSize")}</dt>
            <dd>{formatBytes(result.total_size_bytes)}</dd>
            <dt>{t("job.duration")}</dt>
            <dd>{result.duration_seconds.toFixed(2)}s</dd>
            <dt>{t("job.engineUsed")}</dt>
            <dd><code>{result.engine_used}</code></dd>
            <dt>{t("job.diskPath")}</dt>
            <dd><code>{result.output_path}</code></dd>
          </dl>
          <div style={{ marginTop: "0.25lh", display: "flex", gap: "1ch" }}>
            <a
              href={api.downloadUrl(job.id)}
              download
              className="tui-btn accent"
              style={{ fontSize: 11, textDecoration: "none" }}
            >
              {t("common.downloadZip")}
            </a>
            {job.mode === "pdf" && (
              <a
                href={api.pdfUrl(job.id)}
                download
                className="tui-btn"
                style={{ fontSize: 11, textDecoration: "none" }}
              >
                {t("common.downloadPdf")}
              </a>
            )}
            <Link to="/colecao" className="tui-btn" style={{ fontSize: 11 }}>
              {t("common.viewCollection")}
            </Link>
          </div>
        </div>
      )}

      {/* Terminal de Logs ao Vivo */}
      <div className="tui-panel">
        <span className="tui-label">{t("job.liveConsole")}</span>
        <div
          style={{
            fontFamily: "inherit",
            fontSize: 12,
            background: "var(--sel-bg)",
            padding: "0.5lh 1ch",
            maxHeight: "220px",
            overflowY: "auto",
            marginTop: "0.25lh",
          }}
        >
          {logs.length === 0 ? (
            <span style={{ color: "var(--fg-dim)" }}>{t("job.waitingEvents")}</span>
          ) : (
            logs.map((l, i) => (
              <div key={i} style={{ display: "flex", gap: "1ch", color: l.lvl === "err" ? "var(--error)" : l.lvl === "ok" ? "var(--ok)" : "var(--fg)" }}>
                <span style={{ color: "var(--fg-dim)" }}>[{l.ts}]</span>
                <span>{l.text}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {confirmCancel && (
        <TuiModal open={true} title={t("job.cancelTitle")} onClose={() => setConfirmCancel(false)}>
          <p>{t("job.cancelBody")} <code>{job.id}</code>?</p>
          <div className="flex justify-end gap-2" style={{ marginTop: "0.5lh" }}>
            <button
              type="button"
              className="tui-btn danger"
              onClick={() => {
                setConfirmCancel(false)
                cancelMutation.mutate()
              }}
            >
              {t("job.confirmCancel")}
            </button>
            <button type="button" className="tui-btn" onClick={() => setConfirmCancel(false)}>
              {t("job.goBack")}
            </button>
          </div>
        </TuiModal>
      )}
    </>
  )
}

export const Route = createFileRoute("/jobs/$id")({
  component: JobDetailPage,
})

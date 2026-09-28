"use client"
import { use, useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { api, Job, JobMode, JobResult, JobStatus } from "@/lib/api"
import { MODES, STATUS_HELP, STATUS_LABELS } from "@/lib/labels"
import { usePolling } from "@/hooks/usePolling"
import { useWebSocket, WsEvent } from "@/hooks/useWebSocket"
import { useToast } from "@/components/ToastRegion"
import { cn, faviconLetter, formatBytes, formatClock, formatNumber, formatStamp } from "@/lib/utils"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Modal } from "@/components/ui/modal"
import { Progress, Stepper } from "@/components/ui/ds"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { StatusBadge } from "@/components/ui/badge"
import { AlertTriangle, ArrowLeft, Copy, Download, FileText, RefreshCw, RotateCw, X } from "lucide-react"

/** The four stages of the pipeline, in the wording of the prototype. */
const STEP_LABELS = ["Fila", "Análise", "Baixando", "Pronto"]

/** Pipeline position of each status, as an index into `STEP_LABELS`. */
const STEP_INDEX: Record<JobStatus, number> = {
  pending: 0,
  probing: 1,
  running: 2,
  processing: 2,
  completed: 3,
  failed: 2,
  cancelled: 2,
}

/**
 * How full the progress bar is for each stage.
 *
 * The API exposes no percentage for a running job, so the bar shows the stage the
 * worker has reached — never a number invented per second.
 */
const STEP_PROGRESS: Record<JobStatus, number> = {
  pending: 10,
  probing: 30,
  running: 65,
  processing: 88,
  completed: 100,
  failed: 65,
  cancelled: 65,
}

const settled: JobStatus[] = ["completed", "failed", "cancelled"]

interface LogLine {
  ts: string
  lvl: "info" | "ok" | "warn" | "err"
  text: string
}

function nowClock() {
  return new Date().toLocaleTimeString("pt-BR", { hour12: false })
}

function hostOf(url: string) {
  try {
    return new URL(url).host
  } catch {
    return url.replace(/^https?:\/\//, "").split("/")[0]
  }
}

export default function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const toast = useToast()
  const [job, setJob] = useState<Job | null>(null)
  const [result, setResult] = useState<JobResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState(true)
  const [confirming, setConfirming] = useState(false)
  const [logs, setLogs] = useState<LogLine[]>([])
  const [rerunning, setRerunning] = useState(false)

  const fetchJob = useCallback(async () => {
    try {
      const data = await api.getJob(id)
      setJob(data)
      setError(null)
      if (data.status === "completed") {
        try {
          setResult(await api.getJobResult(id))
        } catch {
          // o resultado ainda não está disponível
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    setTimeout(fetchJob, 0)
  }, [fetchJob])

  usePolling(fetchJob, 5000, live && (job ? !settled.includes(job.status) : true))

  // Every event the worker publishes lands in the console, in arrival order.
  const onEvent = useCallback((event: WsEvent) => {
    const at = nowClock()
    const push = (lvl: LogLine["lvl"], text: string) =>
      setLogs((prev) => [...prev.slice(-199), { ts: at, lvl, text }])

    if (event.type === "progress" && typeof event.data?.message === "string") {
      push("info", event.data.message)
    } else if (event.type === "status" && typeof event.data?.status === "string") {
      const status = event.data.status as JobStatus
      push(status === "completed" ? "ok" : "info", `Etapa: ${STATUS_LABELS[status] ?? status}`)
    } else if (event.type === "error") {
      push("err", typeof event.data?.error === "string" ? event.data.error : "Erro reportado pelo worker")
    }
  }, [])

  const { connected } = useWebSocket(id, onEvent)

  const handleCancel = async () => {
    try {
      await api.cancelJob(id)
      toast("Execução interrompida.")
      await fetchJob()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err")
    }
  }

  const handleRerun = async () => {
    if (!job) return
    setRerunning(true)
    try {
      const created = await api.createJob({ url: job.url, mode: job.mode, max_depth: job.max_depth })
      toast(`Nova execução criada: ${created.id.slice(0, 8)}.`)
      setLogs([])
      await fetchJob()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err")
    } finally {
      setRerunning(false)
    }
  }

  if (loading) {
    return (
      <div className="view-grid">
        <Skeleton className="h-[64px]" />
        <Skeleton className="h-[220px]" />
        <Skeleton className="h-[280px]" />
      </div>
    )
  }

  if (error || !job) {
    return (
      <div className="view-grid">
        <Topbar
          title="Detalhes da execução"
          description="Acompanhe o andamento, veja os logs do worker e baixe o pacote quando terminar."
          action={
            <Link href="/">
              <Button variant="secondary" size="sm">
                <ArrowLeft className="ic ic-sm" aria-hidden="true" /> Voltar
              </Button>
            </Link>
          }
        />
        <EmptyState
          icon={<AlertTriangle className="ic" aria-hidden="true" />}
          title="Não foi possível carregar esta extração"
          description={`${error || "Extração não encontrada."} Ela pode ter sido removida na limpeza automática, que apaga as capturas depois de 24 horas.`}
          action={{ label: "Tentar de novo", onClick: () => void fetchJob() }}
        />
        <div>
          <Link href="/" className="hint">
            Ver todas as execuções
          </Link>
        </div>
      </div>
    )
  }

  const host = hostOf(job.url)
  const mode = MODES[job.mode as JobMode]
  const current = STEP_INDEX[job.status]
  const progress = STEP_PROGRESS[job.status]
  const isActive = !settled.includes(job.status)
  const failed = job.status === "failed" || job.status === "cancelled"
  const probe = job.probe

  const statusLine: LogLine | null =
    job.status === "completed"
      ? { ts: "", lvl: "ok", text: "Execução finalizada com sucesso" }
      : job.status === "failed"
        ? { ts: "", lvl: "err", text: job.error || "Execução interrompida por erro" }
        : job.status === "cancelled"
          ? { ts: "", lvl: "warn", text: "Interrompida por você · o que já tinha sido capturado foi descartado" }
          : null
  const consoleLines = statusLine && !logs.some((l) => l.text === statusLine.text) ? [...logs, statusLine] : logs

  return (
    <div className="view-grid">
      <Topbar
        title="Detalhes da execução"
        description="Acompanhe o andamento, veja os logs do worker e baixe o pacote quando terminar."
        action={
          <>
            <Link href="/">
              <Button variant="secondary" size="sm">
                <ArrowLeft className="ic ic-sm" aria-hidden="true" /> Voltar
              </Button>
            </Link>
            <Button variant="secondary" size="sm" onClick={() => fetchJob()} title="Buscar esta execução novamente agora">
              <RefreshCw className="ic ic-sm" aria-hidden="true" /> Atualizar
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setLive((v) => !v)}
              aria-pressed={live}
              title="Atualização automática a cada 5 segundos"
            >
              <span
                className={cn("h-2 w-2 rounded-full", live ? "bg-emerald-500 animate-pulse" : "bg-zinc-400")}
                aria-hidden="true"
              />
              {live ? "Ao vivo" : "Pausado"}
            </Button>
            {isActive && (
              <Button variant="destructive" size="sm" onClick={() => setConfirming(true)}>
                <X className="ic ic-sm" aria-hidden="true" /> Interromper
              </Button>
            )}
          </>
        }
      />

      <Card>
        <div className="detail-head">
          <span className="job-favicon" aria-hidden="true">
            {faviconLetter(host)}
          </span>
          <div className="grow">
            <div className="od-row" style={{ "--od-gap": "12px", flexWrap: "wrap" } as React.CSSProperties}>
              <h2 className="section-title">{host}</h2>
              <StatusBadge status={job.status} />
            </div>
            <span className="detail-url">{job.url}</span>
            <span className="hint">{STATUS_HELP[job.status]}</span>
          </div>
          <div className="od-row detail-actions" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
            <Button size="sm" variant="secondary" onClick={() => void handleRerun()} loading={rerunning}>
              <RotateCw className="ic ic-sm" aria-hidden="true" /> Reexecutar
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="icon-btn"
              aria-label="Copiar link da execução"
              title="Copiar link da execução"
              onClick={() => {
                void navigator.clipboard.writeText(window.location.href)
                toast("Link copiado.")
              }}
            >
              <Copy className="ic ic-sm" aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              disabled={job.status !== "completed"}
              title={job.status === "completed" ? "Baixar o pacote ZIP" : "O pacote fica disponível quando a execução termina"}
              onClick={() => window.open(api.downloadUrl(job.id), "_blank")}
            >
              <Download className="ic ic-sm" aria-hidden="true" />
              {job.status === "completed" ? "Baixar pacote" : "Pacote indisponível"}
            </Button>
            {job.mode === "pdf" && job.status === "completed" && (
              <Button size="sm" variant="secondary" onClick={() => window.open(api.pdfUrl(job.id), "_blank")}>
                <FileText className="ic ic-sm" aria-hidden="true" /> Abrir PDF
              </Button>
            )}
          </div>
        </div>

        <div className="stack-sm" style={{ marginTop: "var(--sp-5)" }}>
          <Progress
            value={progress}
            state={job.status === "completed" ? "done" : failed ? "error" : "running"}
            label={`Progresso da execução — etapa ${current + 1} de ${STEP_LABELS.length} (${STEP_LABELS[current]})`}
          />
          <div className="row-between">
            <span className="hint">
              {progress}% · {STATUS_LABELS[job.status]} · etapa {current + 1} de {STEP_LABELS.length}
            </span>
            <span className="hint">{live && isActive ? "Atualizado automaticamente" : "Atualização pausada"}</span>
          </div>
          <Stepper steps={STEP_LABELS} current={current} />
        </div>

        <div style={{ marginTop: "var(--sp-5)" }}>
          <StatStrip columns={5}>
            <StatCard label="Profundidade" value={formatNumber(job.max_depth)} trend="níveis a partir da página inicial" />
            <StatCard
              label="Arquivos"
              value={result ? formatNumber(result.files_count) : "—"}
              trend={result ? undefined : "aguardando resultado"}
            />
            <StatCard
              label="Tamanho"
              value={result ? formatBytes(result.total_size_bytes) : "—"}
              trend={result ? undefined : "aguardando resultado"}
            />
            <StatCard
              label="Tempo"
              value={result ? formatClock(result.duration_seconds) : "—"}
              trend={result ? undefined : "aguardando resultado"}
            />
            <StatCard
              label="Erros"
              value={job.error ? 1 : 0}
              trend={job.error ? "motivo no console abaixo" : "nenhum erro registrado"}
            />
          </StatStrip>
        </div>
      </Card>

      {job.error && (
        <Card className="border-destructive/20">
          <div className="section-head">
            <h3 className="card-title od-row" style={{ "--od-gap": "8px" } as React.CSSProperties}>
              <AlertTriangle className="ic ic-sm" aria-hidden="true" /> O que deu errado
            </h3>
            <span className="hint">Mensagem técnica do servidor, útil ao pedir ajuda</span>
          </div>
          <pre className="console" style={{ marginTop: "var(--sp-3)", whiteSpace: "pre-wrap" }}>{job.error}</pre>
        </Card>
      )}

      <div className="two-col">
        <Card>
          <div className="section-head" style={{ marginBottom: "var(--sp-3)" }}>
            <h3 className="card-title">Console do worker</h3>
            <span className="hint od-row" style={{ "--od-gap": "6px" } as React.CSSProperties}>
              <span
                className={cn("h-2 w-2 rounded-full", connected ? "bg-emerald-500 animate-pulse" : "bg-zinc-400")}
                aria-hidden="true"
              />
              {connected ? "conectado" : "desconectado"}
            </span>
          </div>
          <div className="console" role="log" aria-label="Logs da execução" tabIndex={0}>
            {consoleLines.map((line, index) => (
              <div className="line" key={index}>
                {line.ts && <span className="ts">{line.ts}</span>}
                <span className={`lvl lvl-${line.lvl}`}>{line.lvl.toUpperCase()}</span>
                <span>{line.text}</span>
              </div>
            ))}
          </div>
          {consoleLines.length === 0 && (
            <p className="card-sub" style={{ marginTop: "var(--sp-3)" }}>
              Nenhum evento recebido ainda. Os logs aparecem aqui enquanto o worker trabalha.
            </p>
          )}
        </Card>

        <div className="stack-md">
          <Card>
            <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
              Detalhes
            </h3>
            <dl className="kv">
              <dt>Modo</dt>
              <dd>
                {mode?.label ?? job.mode}
                {mode?.what ? <span className="hint"> · {mode.what}</span> : null}
              </dd>
              <dt>Profundidade</dt>
              <dd>{job.max_depth} nível(is)</dd>
              <dt>Iniciado</dt>
              <dd>{formatStamp(job.created_at)}</dd>
              <dt>Última atualização</dt>
              <dd>{formatStamp(job.updated_at)}</dd>
              <dt>Identificador</dt>
              <dd className="mono">{job.id}</dd>
              <dt>Robots.txt</dt>
              <dd>
                {probe ? (probe.robots_restricted ? "Restrito pelo site" : "Permitido") : "não analisado nesta extração"}
              </dd>
              {probe && (
                <>
                  <dt>Navegador necessário</dt>
                  <dd>{probe.suggested_engine === "playwright" ? "Sim" : "Não"}</dd>
                  <dt>Tecnologia</dt>
                  <dd>{probe.framework || "site comum"}</dd>
                  <dt>Tipo de conteúdo</dt>
                  <dd className="mono">{probe.content_type || "—"}</dd>
                  <dt>Resposta do site</dt>
                  <dd>{probe.status_code ?? "—"}</dd>
                  <dt>Endereço final</dt>
                  <dd className="mono">{probe.final_url || probe.url}</dd>
                </>
              )}
              {result && (
                <>
                  <dt>Motor usado</dt>
                  <dd>{result.engine_used}</dd>
                  <dt>Salvo em</dt>
                  <dd className="mono">{result.output_path}</dd>
                </>
              )}
            </dl>
          </Card>

          <Card>
            <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Próximo passo
            </h3>
            <p className="card-sub">
              Ao concluir, o botão “Baixar pacote” libera o ZIP com todos os arquivos organizados. Você também pode
              reprocessar só o que mudou escolhendo o modo <strong>Só o que mudou</strong> na próxima extração.
            </p>
            {result && (
              <details style={{ marginTop: "var(--sp-3)" }}>
                <summary className="hint" style={{ cursor: "pointer" }}>
                  Detalhes técnicos do resultado
                </summary>
                <pre className="console" style={{ marginTop: "var(--sp-2)" }}>
                  {JSON.stringify(result, null, 2)}
                </pre>
              </details>
            )}
          </Card>
        </div>
      </div>

      <Modal
        open={confirming}
        title="Interromper esta captura?"
        body={`A execução de ${host} será cancelada e o que já foi baixado será descartado.`}
        confirmLabel="Interromper"
        danger
        onConfirm={() => {
          setConfirming(false)
          void handleCancel()
        }}
        onClose={() => setConfirming(false)}
      />
    </div>
  )
}

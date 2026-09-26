"use client"
import { use, useEffect, useState } from "react"
import Link from "next/link"
import { api, Job, JobResult, JobMode, JobStatus } from "@/lib/api"
import { MODES, STATUS_HELP, STATUS_SHORT } from "@/lib/labels"
import { usePolling } from "@/hooks/usePolling"
import { useWebSocket, WsEvent } from "@/hooks/useWebSocket"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { StatusBadge } from "@/components/ui/badge"
import { DetailRow } from "@/components/DetailRow"
import { Skeleton } from "@/components/ui/skeleton"
import { formatBytes, formatDuration } from "@/lib/utils"
import {
  ArrowLeft,
  Download,
  FileText,
  X,
  Globe,
  Cpu,
  Layers,
  Clock,
  HardDrive,
  Timer,
  AlertTriangle,
  CheckCircle2,
  Copy,
} from "lucide-react"

const steps: JobStatus[] = ["pending", "probing", "processing", "running", "completed"]
const settled: JobStatus[] = ["completed", "failed", "cancelled"]

export default function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [job, setJob] = useState<Job | null>(null)
  const [result, setResult] = useState<JobResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const fetchJob = async () => {
    try {
      const data = await api.getJob(id)
      setJob(data)
      setError(null)
      if (data.status === "completed") {
        try {
          setResult(await api.getJobResult(id))
        } catch {
          // resultado ainda não disponível
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setTimeout(fetchJob, 0) }, [id])

  usePolling(fetchJob, 5000, job ? !settled.includes(job.status) : true)

  const [wsProgress, setWsProgress] = useState<string | null>(null)
  const [wsLogs, setWsLogs] = useState<string[]>([])
  const { connected, events } = useWebSocket(id, (event: WsEvent) => {
    if (event.type === "progress" && typeof event.data?.message === "string") {
      setWsProgress(event.data.message)
    }
    if (event.type === "progress" && typeof event.data?.log === "string") {
      setWsLogs((prev) => [...prev.slice(-19), event.data.log as string])
    }
    // Re-fetch job when status changes
    if (event.type === "status") {
      fetchJob()
    }
  })

  const handleCancel = async () => {
    if (!confirm("Interromper esta extração? O que já foi baixado será descartado.")) return
    try {
      await api.cancelJob(id)
      fetchJob()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const copyId = async () => {
    await navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-40" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (error || !job) {
    return (
      <div className="space-y-4">
        <Link href="/" className="inline-flex items-center gap-2 text-[13px] text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Voltar para as execuções
        </Link>
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive mx-auto mb-2" />
            <p className="text-[14px] font-medium">Não foi possível carregar esta extração</p>
            <p className="text-[13px] text-muted-foreground mt-1">{error || "Extração não encontrada."}</p>
            <p className="text-[12.5px] text-muted-foreground mt-2">
              Ela pode ter sido removida na limpeza automática.{" "}
              <Link href="/" className="text-primary underline">
                Ver todas
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const currentStepIdx = steps.indexOf(job.status)
  const isActive = !settled.includes(job.status)
  const failed = job.status === "failed" || job.status === "cancelled"
  const modeInfo = MODES[job.mode as JobMode]

  return (
    <div className="space-y-6 max-w-[960px] animate-[slide-in_0.3s_ease]">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Voltar para as execuções
      </Link>

      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
        <div className="space-y-2 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-[22px] font-semibold tracking-tight font-mono">{job.id.slice(0, 16)}</h1>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={copyId} title="Copiar identificador completo">
              <Copy className="h-3.5 w-3.5" />
            </Button>
            {copied && <span className="text-[11px] text-emerald-600">copiado</span>}
            <StatusBadge status={job.status} />
          </div>
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <Globe className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate max-w-[520px]" title={job.url}>
              {job.url}
            </span>
          </div>
          <p className="text-[12.5px] text-muted-foreground">{STATUS_HELP[job.status]}</p>
        </div>

        <div className="flex gap-2 shrink-0">
          {isActive && (
            <Button variant="outline" size="sm" onClick={handleCancel}>
              <X className="h-4 w-4" /> Interromper
            </Button>
          )}
          {job.status === "completed" && (
            <>
              <Button size="sm" onClick={() => window.open(api.downloadUrl(job.id), "_blank")}>
                <Download className="h-4 w-4" /> Baixar ZIP
              </Button>
              {job.mode === "pdf" && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => window.open(api.pdfUrl(job.id), "_blank")}
                >
                  <FileText className="h-4 w-4" /> Abrir PDF
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Andamento */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <span className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground">Andamento</span>
            {isActive && (
              <span className="ml-auto text-[11px] px-2 py-1 rounded-full bg-amber-500/10 text-amber-600 animate-pulse">
                atualizando sozinho
              </span>
            )}
            {failed && (
              <span className="ml-auto text-[11px] px-2 py-1 rounded-full bg-red-500/10 text-red-600">
                parou aqui
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {steps.map((s, idx) => {
              const done = currentStepIdx >= idx && !failed
              const active = job.status === s
              return (
                <div key={s} className="flex items-center gap-2 flex-1">
                  <div className="flex flex-col items-center gap-1.5">
                    <div
                      className={`h-8 w-8 rounded-full flex items-center justify-center text-[11px] font-medium border transition-all ${
                        done ? "bg-primary text-primary-foreground border-primary shadow-sm shadow-primary/20" : "bg-secondary border"
                      } ${active ? "ring-2 ring-primary/20 scale-110" : ""}`}
                    >
                      {done && job.status !== s ? <CheckCircle2 className="h-4 w-4" /> : idx + 1}
                    </div>
                    <span
                      className={`text-[10px] uppercase tracking-wide font-medium ${
                        active ? "text-foreground" : "text-muted-foreground"
                      }`}
                    >
                      {STATUS_SHORT[s]}
                    </span>
                  </div>
                  {idx < steps.length - 1 && (
                    <div
                      className={`h-[2px] flex-1 rounded-full transition-all ${
                        idx < currentStepIdx && !failed ? "bg-primary" : "bg-border"
                      }`}
                    />
                  )}
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Live progress */}
      {isActive && (wsProgress || wsLogs.length > 0) && (
        <Card className="border-amber-500/20">
          <CardContent className="p-5">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="h-4 w-4 text-amber-500 animate-pulse" />
              <span className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground">
                Progresso ao vivo
              </span>
              <span className={`ml-auto h-2 w-2 rounded-full ${connected ? "bg-emerald-500 animate-pulse" : "bg-zinc-400"}`} title={connected ? "Conectado" : "Desconectado"} />
            </div>
            {wsProgress && (
              <p className="text-[13px] font-medium mb-2">{wsProgress}</p>
            )}
            {wsLogs.length > 0 && (
              <div className="rounded-[10px] bg-secondary p-3 max-h-[160px] overflow-y-auto">
                {wsLogs.map((log, i) => (
                  <p key={i} className="text-[11px] font-mono text-muted-foreground leading-relaxed">{log}</p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="h-4 w-4" /> O que foi pedido
            </CardTitle>
          </CardHeader>
          <CardContent className="px-5">
            <DetailRow label="Endereço" value={<span className="break-all">{job.url}</span>} />
            <DetailRow
              label="Modo"
              value={
                <span className="text-[12px] font-medium">
                  {modeInfo?.icon} {modeInfo?.label ?? job.mode}
                </span>
              }
              hint={modeInfo?.what}
            />
            <DetailRow
              label="Páginas percorridas"
              value={job.max_depth}
              hint="Quantos links a partir da página inicial o Zfrog seguiu."
            />
            <DetailRow label="Iniciado em" value={new Date(job.created_at).toLocaleString("pt-BR")} />
            <DetailRow label="Última atualização" value={new Date(job.updated_at).toLocaleString("pt-BR")} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-4 w-4" /> Análise do site
            </CardTitle>
            <CardDescription>O que o Zfrog descobriu antes de baixar</CardDescription>
          </CardHeader>
          <CardContent className="px-5">
            {job.probe ? (
              <>
                <DetailRow
                  label="Precisou de navegador"
                  value={job.probe.suggested_engine === "playwright" ? "Sim" : "Não"}
                  hint={
                    job.probe.suggested_engine === "playwright"
                      ? "O conteúdo só aparece depois que o JavaScript roda."
                      : "O conteúdo já vem pronto na resposta do site."
                  }
                />
                <DetailRow
                  label="Tecnologia"
                  value={job.probe.framework || "Site comum"}
                  hint="Biblioteca usada para construir o site, quando identificada."
                />
                <DetailRow
                  label="Tipo de conteúdo"
                  value={<span className="font-mono text-[11px]">{job.probe.content_type || "—"}</span>}
                />
                <DetailRow
                  label="Resposta do site"
                  value={job.probe.status_code ?? "—"}
                  hint={job.probe.status_code === 200 ? "O site respondeu normalmente." : undefined}
                />
                <DetailRow
                  label="Endereço final"
                  value={<span className="font-mono text-[11px] break-all">{job.probe.final_url || job.probe.url}</span>}
                  hint={job.probe.final_url !== job.url ? "O site redirecionou para outro endereço." : undefined}
                />
              </>
            ) : (
              <p className="text-[13px] text-muted-foreground py-4">
                Esta extração não passou pela análise — o modo escolhido não precisa dela.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {job.error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-4 w-4" /> O que deu errado
            </CardTitle>
            <CardDescription>Mensagem técnica do servidor, útil ao pedir ajuda</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="text-[12px] font-mono bg-card border rounded-[10px] p-3 overflow-auto whitespace-pre-wrap break-words">
              {job.error}
            </pre>
          </CardContent>
        </Card>
      )}

      {result && (
        <Card className="border-emerald-500/20">
          <div className="h-[1px] bg-gradient-to-r from-emerald-500/0 via-emerald-500/40 to-emerald-500/0" />
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-600" /> Resultado
            </CardTitle>
            <CardDescription>Pronto para baixar</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-[12px] bg-secondary p-3">
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground uppercase tracking-wide">
                  <Cpu className="h-3 w-3" /> Método
                </div>
                <div className="mt-1 text-[13px] font-medium">{result.engine_used}</div>
              </div>
              <div className="rounded-[12px] bg-secondary p-3">
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground uppercase tracking-wide">
                  <HardDrive className="h-3 w-3" /> Arquivos
                </div>
                <div className="mt-1 text-[13px] font-medium">{result.files_count}</div>
              </div>
              <div className="rounded-[12px] bg-secondary p-3">
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground uppercase tracking-wide">
                  <Timer className="h-3 w-3" /> Levou
                </div>
                <div className="mt-1 text-[13px] font-medium">{formatDuration(result.duration_seconds)}</div>
              </div>
            </div>

            <div className="text-[12.5px] text-muted-foreground">
              Tamanho total: <span className="font-medium text-foreground">{formatBytes(result.total_size_bytes)}</span>
              <span className="mx-2">·</span>
              Salvo em <span className="font-mono">{result.output_path}</span>
            </div>

            <Button onClick={() => window.open(api.downloadUrl(job.id), "_blank")} className="w-full md:w-auto">
              <Download className="h-4 w-4" /> Baixar ZIP ({formatBytes(result.total_size_bytes)})
            </Button>

            <details>
              <summary className="text-[12px] text-muted-foreground cursor-pointer hover:text-foreground">
                Detalhes técnicos
              </summary>
              <pre className="mt-2 text-[11px] font-mono bg-secondary rounded-[10px] p-3 overflow-auto max-h-[240px] border">
                {JSON.stringify(result, null, 2)}
              </pre>
            </details>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

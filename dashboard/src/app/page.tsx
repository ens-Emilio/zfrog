"use client"
import { useEffect, useState, useMemo } from "react"
import Link from "next/link"
import { api, Job, JobStatus, JobMode } from "@/lib/api"
import { MODES, STATUS_HELP } from "@/lib/labels"
import { usePolling } from "@/hooks/usePolling"
import { cn, timeAgo } from "@/lib/utils"
import { Topbar } from "@/components/Navbar"
import { StatusBadge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { StatCard } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Search,
  Download,
  X,
  ExternalLink,
  Layers,
  CheckCircle2,
  Clock3,
  AlertCircle,
  Play,
  SearchX,
  RefreshCw,
  Globe,
  ArrowRight,
} from "lucide-react"

const statusFilters: (JobStatus | "all")[] = ["all", "running", "pending", "completed", "failed"]
const filterLabels: Record<JobStatus | "all", string> = {
  all: "Todas",
  running: "Baixando",
  pending: "Na fila",
  probing: "Analisando",
  processing: "Organizando",
  completed: "Concluídas",
  failed: "Falhas",
  cancelled: "Canceladas",
}
const inFlight: JobStatus[] = ["running", "pending", "probing", "processing"]

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState("")
  const [status, setStatus] = useState<JobStatus | "all">("all")
  const [polling, setPolling] = useState(true)

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

  const filtered = useMemo(
    () =>
      jobs.filter((j) => {
        if (status !== "all" && j.status !== status) return false
        if (q && !j.url.toLowerCase().includes(q.toLowerCase()) && !j.id.toLowerCase().includes(q.toLowerCase()))
          return false
        return true
      }),
    [jobs, q, status]
  )

  const stats = useMemo(
    () => ({
      total: jobs.length,
      running: jobs.filter((j) => inFlight.includes(j.status)).length,
      completed: jobs.filter((j) => j.status === "completed").length,
      failed: jobs.filter((j) => j.status === "failed").length,
    }),
    [jobs]
  )

  const handleCancel = async (id: string) => {
    if (!confirm("Interromper esta extração? O que já foi baixado será descartado.")) return
    try {
      await api.cancelJob(id)
      fetchJobs()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-6 animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Execuções"
        description="Cada vez que você baixa um site ou extrai dados, aparece aqui. Clique em uma linha para ver os detalhes."
        action={
          <>
            <Button variant="outline" size="sm" onClick={() => fetchJobs()} title="Buscar a lista novamente agora">
              <RefreshCw className="h-3.5 w-3.5" /> Atualizar
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPolling((p) => !p)}
              title="Atualização automática da lista a cada 5 segundos"
            >
              <div className={cn("h-2 w-2 rounded-full", polling ? "bg-emerald-500 animate-pulse" : "bg-zinc-400")} />
              {polling ? "Ao vivo" : "Pausado"}
            </Button>
            <Link href="/probe">
              <Button size="sm">
                <Play className="h-3.5 w-3.5" /> Nova extração
              </Button>
            </Link>
          </>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Total" value={stats.total} icon={<Layers className="h-4 w-4" />} />
        <StatCard
          label="Em andamento"
          value={stats.running}
          icon={<Clock3 className="h-4 w-4" />}
          className={stats.running ? "ring-1 ring-amber-500/20" : ""}
        />
        <StatCard label="Concluídas" value={stats.completed} icon={<CheckCircle2 className="h-4 w-4" />} />
        <StatCard
          label="Falhas"
          value={stats.failed}
          icon={<AlertCircle className="h-4 w-4" />}
          className={stats.failed ? "ring-1 ring-red-500/20" : ""}
        />
      </div>

      {jobs.length > 0 && (
        <Card>
          <CardContent className="p-4 flex flex-col md:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                placeholder="Buscar por endereço ou identificador…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="h-9 w-full rounded-[10px] border bg-background pl-9 pr-3 text-[13.5px] focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div className="flex gap-1.5 overflow-auto">
              {statusFilters.map((s) => (
                <button
                  key={s}
                  onClick={() => setStatus(s)}
                  className={cn(
                    "h-9 px-3 rounded-[10px] text-[12.5px] font-medium whitespace-nowrap border transition-all",
                    status === s ? "bg-primary text-primary-foreground border-primary shadow-sm" : "bg-card hover:bg-accent"
                  )}
                >
                  {filterLabels[s]}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="overflow-hidden">
        {loading ? (
          <div className="p-4 space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : error && jobs.length === 0 ? (
          <div className="p-8 text-center">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-destructive/10 text-destructive mb-3">
              <AlertCircle className="h-5 w-5" />
            </div>
            <p className="text-[14px] font-medium">Não foi possível falar com o servidor</p>
            <p className="text-[13px] text-muted-foreground mt-1">{error}</p>
            <p className="text-[12.5px] text-muted-foreground mt-2">
              Verifique se a API está rodando (<span className="font-mono">./zfrog dev</span>).
            </p>
            <Button size="sm" variant="outline" className="mt-4" onClick={fetchJobs}>
              Tentar de novo
            </Button>
          </div>
        ) : jobs.length === 0 ? (
          <FirstRun />
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center">
            <SearchX className="h-6 w-6 text-muted-foreground mx-auto mb-2" />
            <p className="text-[14px] font-medium">Nenhuma execução encontrada</p>
            <p className="text-[13px] text-muted-foreground mt-1">
              Nada corresponde a esse filtro ou busca.
            </p>
            <Button
              size="sm"
              variant="outline"
              className="mt-4"
              onClick={() => {
                setQ("")
                setStatus("all")
              }}
            >
              Limpar filtros
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                  <th className="px-4 py-3 font-medium">Identificador</th>
                  <th className="px-4 py-3 font-medium">Endereço</th>
                  <th className="px-4 py-3 font-medium">Modo</th>
                  <th className="px-4 py-3 font-medium">Situação</th>
                  <th className="px-4 py-3 font-medium">Quando</th>
                  <th className="px-4 py-3 font-medium text-right">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {filtered.map((job) => (
                  <tr key={job.id} className="group hover:bg-accent/50 transition-colors">
                    <td className="px-4 py-3">
                      <Link
                        href={`/jobs/${job.id}`}
                        className="font-mono text-[12.5px] font-medium bg-secondary px-2 py-1 rounded-[8px] group-hover:bg-primary group-hover:text-primary-foreground transition-colors"
                        title={job.id}
                      >
                        {job.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="px-4 py-3 max-w-[320px]">
                      <div className="flex items-center gap-2">
                        <Globe className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <span className="text-[13px] truncate" title={job.url}>
                          {job.url.length > 48 ? job.url.slice(0, 48) + "…" : job.url}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="inline-flex items-center gap-1.5 rounded-[8px] bg-secondary px-2 py-1 text-[11px] font-medium whitespace-nowrap"
                        title={MODES[job.mode as JobMode]?.what}
                      >
                        {MODES[job.mode as JobMode]?.icon} {MODES[job.mode as JobMode]?.label ?? job.mode}
                      </span>
                    </td>
                    <td className="px-4 py-3" title={STATUS_HELP[job.status]}>
                      <StatusBadge status={job.status} size="sm" />
                    </td>
                    <td className="px-4 py-3 text-[12.5px] text-muted-foreground whitespace-nowrap">
                      {timeAgo(job.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        {job.status === "completed" && (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => window.open(api.downloadUrl(job.id), "_blank")}
                            title="Baixar o arquivo ZIP"
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                        )}
                        {inFlight.includes(job.status) && (
                          <Button variant="ghost" size="icon" onClick={() => handleCancel(job.id)} title="Interromper">
                            <X className="h-4 w-4" />
                          </Button>
                        )}
                        <Link href={`/jobs/${job.id}`}>
                          <Button variant="ghost" size="icon" title="Ver detalhes">
                            <ExternalLink className="h-4 w-4" />
                          </Button>
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function FirstRun() {
  const steps = [
    {
      n: 1,
      title: "Informe o endereço do site",
      body: "Cole o link da página que você quer copiar, começando com https://.",
    },
    {
      n: 2,
      title: "Escolha o que quer receber",
      body: "Site completo, página única, site com JavaScript ou tabela de dados.",
    },
    {
      n: 3,
      title: "Baixe o resultado",
      body: "Quando terminar, o botão de download aparece nesta lista.",
    },
  ]

  return (
    <div className="p-8">
      <div className="text-center mb-6">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-[14px] bg-primary/10 text-primary mb-3">
          <Play className="h-6 w-6" />
        </div>
        <h3 className="text-[16px] font-semibold">Nenhuma extração ainda</h3>
        <p className="text-[13.5px] text-muted-foreground mt-1 max-w-md mx-auto">
          O Zfrog copia sites para o seu computador e extrai dados de páginas. Veja como começar:
        </p>
      </div>

      <div className="grid md:grid-cols-3 gap-3 max-w-3xl mx-auto">
        {steps.map((s) => (
          <div key={s.n} className="rounded-[12px] border bg-card/50 p-4">
            <div className="h-7 w-7 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-[12px] font-semibold mb-2">
              {s.n}
            </div>
            <p className="text-[13px] font-medium">{s.title}</p>
            <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">{s.body}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mt-6">
        <Link href="/probe">
          <Button>
            Começar primeira extração <ArrowRight className="h-4 w-4" />
          </Button>
        </Link>
        <Link href="/ajuda">
          <Button variant="outline">Ver o guia</Button>
        </Link>
      </div>
    </div>
  )
}

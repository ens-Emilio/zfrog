"use client"
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react"
import { api, AnalyticsTotals, Job, SystemStats } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Button } from "@/components/ui/button"
import { Icon } from "@/lib/icons"
import { formatBytes, formatClock, formatNumber } from "@/lib/utils"

/** Quantas colunas o gráfico de requisições por dia mostra. */
const DAYS = 14

/** Quantos domínios a lista de mais capturados mostra. */
const TOP_DOMAINS = 6

type DayBucket = {
  /** Chave ISO curta (AAAA-MM-DD) usada para casar a data da execução. */
  key: string
  /** Rótulo curto do eixo (DD/MM). */
  label: string
  value: number
  today: boolean
}

function pad(value: number): string {
  return String(value).padStart(2, "0")
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/**
 * Conta as execuções de cada um dos últimos 14 dias, do mais antigo para hoje.
 * Uma execução com data ilegível é ignorada em vez de virar um dia inventado.
 */
function countByDay(jobs: Job[]): DayBucket[] {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const buckets: DayBucket[] = []
  for (let offset = DAYS - 1; offset >= 0; offset--) {
    const date = new Date(today)
    date.setDate(today.getDate() - offset)
    buckets.push({
      key: dayKey(date),
      label: `${pad(date.getDate())}/${pad(date.getMonth() + 1)}`,
      value: 0,
      today: offset === 0,
    })
  }
  const index = new Map(buckets.map((bucket, i) => [bucket.key, i]))
  for (const job of jobs) {
    const created = new Date(job.created_at)
    if (Number.isNaN(created.getTime())) continue
    const position = index.get(dayKey(created))
    if (position !== undefined) buckets[position].value += 1
  }
  return buckets
}

/** Domínios mais capturados, do maior para o menor, com a contagem de execuções. */
function countByDomain(jobs: Job[]): { host: string; value: number }[] {
  const counts = new Map<string, number>()
  for (const job of jobs) {
    let host: string
    try {
      host = new URL(job.url).host
    } catch {
      // Uma URL que o navegador não consegue ler aparece como veio, em vez de sumir da lista.
      host = job.url
    }
    if (!host) continue
    counts.set(host, (counts.get(host) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([host, value]) => ({ host, value }))
    .sort((a, b) => b.value - a.value || a.host.localeCompare(b.host))
    .slice(0, TOP_DOMAINS)
}

/** A frase lida por leitores de tela: o que o gráfico mostra e onde está o pico. */
function chartLabel(buckets: DayBucket[]): string {
  if (buckets.length === 0) return "Gráfico de requisições por dia sem dados."
  const peak = buckets.reduce((best, bucket) => (bucket.value > best.value ? bucket : best), buckets[0])
  const total = buckets.reduce((sum, bucket) => sum + bucket.value, 0)
  if (total === 0) {
    return `Gráfico de barras com requisições por dia nos últimos ${DAYS} dias. Não houve execuções no período.`
  }
  return (
    `Gráfico de barras com requisições por dia nos últimos ${DAYS} dias, ` +
    `de ${buckets[0].label} a ${buckets[buckets.length - 1].label}. ` +
    `O maior valor foi ${peak.value} em ${peak.label}; o total do período foi ${total}.`
  )
}

export default function StatsPage() {
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [totals, setTotals] = useState<AnalyticsTotals | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [system, analytics, jobList] = await Promise.all([
        api.getStats(),
        api.getAnalyticsTotals(),
        api.getJobs(),
      ])
      setStats(system)
      setTotals(analytics)
      setJobs(jobList)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const buckets = useMemo(() => countByDay(jobs), [jobs])
  const domains = useMemo(() => countByDomain(jobs), [jobs])

  const total = stats?.total_jobs ?? 0
  const completed = stats?.completed ?? 0
  const successRate = total > 0 ? Math.round((completed / total) * 100) : 0
  const avgSeconds = totals?.avg_duration_s ?? 0
  const capturedBytes = totals?.bytes ?? 0
  const periodTotal = buckets.reduce((sum, bucket) => sum + bucket.value, 0)
  const peak = buckets.reduce((best, bucket) => (bucket.value > best.value ? bucket : best), buckets[0])
  const chartMax = peak?.value ?? 0
  const domainMax = domains.reduce((max, domain) => Math.max(max, domain.value), 0)

  return (
    <div className="view-grid">
      <Topbar
        title="Estatísticas"
        description="Volume, dados capturados e desempenho das execuções."
        action={
          <Button variant="secondary" size="sm" onClick={() => void load()} loading={loading}>
            <Icon name="i-refresh" size="sm" />
            Atualizar
          </Button>
        }
      />

      {error && (
        <div className="card">
          <div className="od-row" style={{ "--od-gap": "12px" } as CSSProperties}>
            <span className="badge badge-danger">
              <span className="dot" />
              Falha ao carregar
            </span>
            <span className="od-truncate text-[var(--text-2)]">{error}</span>
          </div>
          <div className="od-row" style={{ marginTop: "var(--sp-3)" }}>
            <Button variant="primary" size="sm" onClick={() => void load()}>
              Tentar de novo
            </Button>
          </div>
        </div>
      )}

      {loading && !stats && (
        <>
          <StatStrip>
            {[0, 1, 2, 3].map((i) => (
              <div className="stat" key={i}>
                <Skeleton className="h-6 w-20" />
                <Skeleton className="h-3 w-24" />
              </div>
            ))}
          </StatStrip>
          <div className="card">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="mt-4 h-[172px] w-full" />
          </div>
        </>
      )}

      {stats && (
        <>
          <StatStrip>
            <StatCard label="Requisições" value={formatNumber(total)} />
            <StatCard label="Dados capturados" value={formatBytes(capturedBytes)} />
            <StatCard label="Taxa de sucesso" value={`${successRate}%`} />
            <StatCard label="Tempo médio" value={formatClock(avgSeconds)} />
          </StatStrip>

          <div className="card">
            <div className="section-head" style={{ marginBottom: "var(--sp-2)" }}>
              <h3 className="card-title">Requisições por dia</h3>
              <span className="hint">últimos {DAYS} dias</span>
            </div>
            {periodTotal === 0 ? (
              <EmptyState
                icon={<Icon name="i-stats" size="lg" />}
                title="Sem execuções no período"
                description={`Nenhuma requisição registrada nos últimos ${DAYS} dias.`}
                href={{ label: "Nova extração", href: "/probe" }}
              />
            ) : (
              <div className="chart" role="img" aria-label={chartLabel(buckets)}>
                {buckets.map((bucket) => (
                  <div className="col" key={bucket.key}>
                    <span className="v">{bucket.value}</span>
                    <span
                      className={bucket.today ? "bar is-today" : "bar"}
                      style={{ height: `${chartMax > 0 ? Math.round((bucket.value / chartMax) * 100) : 0}%` }}
                      title={`${bucket.label} · ${bucket.value} requisições`}
                    />
                    <span className="x">{bucket.label}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
              Domínios mais capturados
            </h3>
            {domains.length === 0 ? (
              <EmptyState
                icon={<Icon name="i-globe" size="lg" />}
                title="Nenhum domínio ainda"
                description="Assim que houver execuções, os sites mais capturados aparecem aqui."
                href={{ label: "Nova extração", href: "/probe" }}
              />
            ) : (
              <div className="od-stack" style={{ "--od-gap": "2px" } as CSSProperties}>
                {domains.map((domain) => (
                  <div className="bar-row" key={domain.host}>
                    <span className="od-truncate">{domain.host}</span>
                    <span className="bar-track">
                      <span
                        className="bar-fill"
                        style={{ width: `${domainMax > 0 ? Math.round((domain.value / domainMax) * 100) : 0}%` }}
                      />
                    </span>
                    <span className="val">{formatNumber(domain.value)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

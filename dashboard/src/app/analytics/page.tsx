"use client"
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react"
import { api, AnalyticsTotals, EngineStats, Job } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Button } from "@/components/ui/button"
import { Icon } from "@/lib/icons"
import { formatClock, formatNumber } from "@/lib/utils"

/** Nome amigável e uma frase sobre o que cada motor faz. */
const ENGINE_INFO: Record<string, { label: string; what: string }> = {
  wget: { label: "Baixador rápido", what: "Copia sites comuns página por página, sem abrir um navegador." },
  playwright: { label: "Navegador", what: "Abre o site como um navegador de verdade, para páginas que só aparecem com JavaScript." },
  static_file: { label: "Página única", what: "Guarda uma página só, com o conteúdo já embutido." },
  scrapy: { label: "Rastreador de dados", what: "Percorre várias páginas e separa os dados encontrados." },
  analyze: { label: "Auditoria", what: "Confere SEO, acessibilidade e desempenho da página." },
  compare: { label: "Comparação", what: "Mede o quanto a cópia ficou parecida com o original." },
  ask: { label: "Pergunta à IA", what: "Responde perguntas sobre o conteúdo já baixado." },
  pdf: { label: "PDF", what: "Gera um PDF da página." },
  summarize: { label: "Resumo com IA", what: "Escreve um resumo curto do conteúdo." },
  delta: { label: "Só o que mudou", what: "Compara com a última cópia e baixa apenas as páginas alteradas." },
}

/** Quantas semanas o gráfico de sucesso mostra, contando a semana atual. */
const WEEKS = 8

type WeekBucket = {
  key: string
  label: string
  total: number
  completed: number
  current: boolean
}

function pad(value: number): string {
  return String(value).padStart(2, "0")
}

/** Início da semana (segunda-feira) que contém a data, à meia-noite local. */
function weekStart(date: Date): Date {
  const start = new Date(date)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  return start
}

function weekKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/**
 * Taxa de sucesso de cada uma das últimas 8 semanas, medida direto nas execuções
 * registradas: concluídas ÷ total daquela semana.
 */
function weekBuckets(jobs: Job[]): WeekBucket[] {
  const thisWeek = weekStart(new Date())
  const buckets: WeekBucket[] = []
  for (let offset = WEEKS - 1; offset >= 0; offset--) {
    const start = new Date(thisWeek)
    start.setDate(thisWeek.getDate() - offset * 7)
    buckets.push({
      key: weekKey(start),
      label: `S${WEEKS - offset}`,
      total: 0,
      completed: 0,
      current: offset === 0,
    })
  }
  const index = new Map(buckets.map((bucket, i) => [bucket.key, i]))
  for (const job of jobs) {
    const created = new Date(job.created_at)
    if (Number.isNaN(created.getTime())) continue
    const position = index.get(weekKey(weekStart(created)))
    if (position === undefined) continue
    buckets[position].total += 1
    if (job.status === "completed") buckets[position].completed += 1
  }
  return buckets
}

/** Taxa da semana em pontos percentuais, ou `null` quando a semana não teve execução. */
function weekRate(bucket: WeekBucket): number | null {
  if (bucket.total === 0) return null
  return Math.round((bucket.completed / bucket.total) * 100)
}

/** A frase lida por leitores de tela: o intervalo medido e as semanas sem execução. */
function weekChartLabel(buckets: WeekBucket[]): string {
  const rates = buckets
    .map((bucket) => weekRate(bucket))
    .filter((rate): rate is number => rate !== null)
  if (rates.length === 0) {
    return `Gráfico de barras da taxa de sucesso semanal: nenhuma execução nas últimas ${WEEKS} semanas.`
  }
  const empty = buckets.length - rates.length
  const emptyNote = empty > 0 ? ` ${empty} das ${WEEKS} semanas não tiveram execução.` : ""
  return (
    `Gráfico de barras da taxa de sucesso por semana nas últimas ${WEEKS} semanas. ` +
    `A taxa ficou entre ${Math.min(...rates)}% e ${Math.max(...rates)}%.${emptyNote}`
  )
}

export default function AnalyticsPage() {
  const [totals, setTotals] = useState<AnalyticsTotals | null>(null)
  const [engines, setEngines] = useState<EngineStats[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [analytics, perEngine, jobList] = await Promise.all([
        api.getAnalyticsTotals(),
        api.getEngineStats(),
        api.getJobs(),
      ])
      setTotals(analytics)
      setEngines(perEngine)
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

  const weeks = useMemo(() => weekBuckets(jobs), [jobs])

  const runs = totals?.runs ?? 0
  const succeeded = totals?.succeeded ?? 0
  const failed = totals?.failed ?? 0
  const avgSeconds = totals?.avg_duration_s ?? 0
  const overallRate = runs > 0 ? Math.round((succeeded / runs) * 100) : 0

  const ordered = useMemo(() => [...engines].sort((a, b) => b.runs - a.runs), [engines])
  const engineMax = ordered.reduce((max, engine) => Math.max(max, engine.runs), 0)

  const measured = weeks.map(weekRate).filter((rate): rate is number => rate !== null)

  return (
    <div className="view-grid">
      <Topbar
        title="Analytics"
        description="Como cada motor se comporta ao longo do tempo."
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

      {loading && !totals && (
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

      {totals && (
        <>
          <StatStrip>
            <StatCard
              label="Execuções registradas"
              value={formatNumber(runs)}
              trend={`${formatNumber(succeeded)} concluídas · ${formatNumber(failed)} falhas`}
            />
            <StatCard label="Sucesso médio" value={`${overallRate}%`} trend="todos os motores" />
            <StatCard label="Tempo médio" value={formatClock(avgSeconds)} trend="por execução" />
            <StatCard
              label="Motores ativos"
              value={formatNumber(engines.length)}
              trend={engines.length === 1 ? "1 motor com execuções" : `${engines.length} motores com execuções`}
            />
          </StatStrip>

          <div className="card">
            <div className="section-head" style={{ marginBottom: "var(--sp-3)" }}>
              <h3 className="card-title">Execuções por motor</h3>
              <span className="hint">barra proporcional ao motor que mais rodou</span>
            </div>
            {ordered.length === 0 ? (
              <EmptyState
                icon={<Icon name="i-layers" size="lg" />}
                title="Nenhum motor registrou execução"
                description="As estatísticas por motor aparecem depois da primeira execução."
                href={{ label: "Nova extração", href: "/probe" }}
              />
            ) : (
              <div className="od-stack" style={{ "--od-gap": "2px" } as CSSProperties}>
                {ordered.map((engine) => {
                  const info = ENGINE_INFO[engine.engine]
                  const ok = Math.round(engine.success_rate * 100)
                  return (
                    <div className="bar-row" key={engine.engine}>
                      <span className="od-truncate" title={info?.what ?? engine.engine}>
                        {info?.label ?? engine.engine}
                      </span>
                      <span className="bar-track">
                        <span
                          className="bar-fill"
                          style={{ width: `${engineMax > 0 ? Math.round((engine.runs / engineMax) * 100) : 0}%` }}
                        />
                      </span>
                      <span className="val">
                        {formatNumber(engine.runs)} · {ok}% ok
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div className="card">
            <div className="section-head" style={{ marginBottom: "var(--sp-2)" }}>
              <h3 className="card-title">Taxa de sucesso por semana</h3>
              <span className="hint">últimas {WEEKS} semanas</span>
            </div>
            {measured.length === 0 ? (
              <EmptyState
                icon={<Icon name="i-trending" size="lg" />}
                title="Sem execuções no período"
                description={`Nenhuma execução registrada nas últimas ${WEEKS} semanas.`}
                href={{ label: "Nova extração", href: "/probe" }}
              />
            ) : (
              <div className="chart" role="img" aria-label={weekChartLabel(weeks)}>
                {weeks.map((bucket) => {
                  const rate = weekRate(bucket)
                  // A altura é a própria taxa: uma semana sem execução fica sem barra
                  // e mostra "—" no lugar do número, em vez de fingir 0% de sucesso.
                  return (
                    <div className="col" key={bucket.key}>
                      <span className="v">{rate === null ? "—" : `${rate}%`}</span>
                      <span
                        className={bucket.current ? "bar is-today" : "bar"}
                        style={{ height: `${rate ?? 0}%` }}
                        title={
                          rate === null
                            ? `${bucket.label} · sem execuções`
                            : `${bucket.label} · ${rate}% em ${bucket.total} execuções`
                        }
                      />
                      <span className="x">{bucket.label}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

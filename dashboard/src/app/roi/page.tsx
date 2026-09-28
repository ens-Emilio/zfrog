"use client"
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react"
import { api, Job, RoiResult } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Button } from "@/components/ui/button"
import { DetailGrid, DetailRow } from "@/components/DetailRow"
import { Icon } from "@/lib/icons"
import { formatBytes, formatClock, formatNumber } from "@/lib/utils"

/** Nome em português de cada motor, igual ao usado na tela de Analytics. */
const ENGINE_LABELS: Record<string, string> = {
  wget: "Baixador rápido",
  playwright: "Navegador",
  static_file: "Página única",
  scrapy: "Rastreador de dados",
  extract: "Dados em tabela",
  analyze: "Auditoria",
  compare: "Comparação",
  ask: "Pergunta à IA",
  pdf: "PDF",
  summarize: "Resumo com IA",
  delta: "Só o que mudou",
  entities: "Nomes e dados",
  translate: "Traduzir",
  sentiment: "Tom do texto",
  tags: "Assuntos",
  video: "Vídeo e transmissões",
  api_discovery: "Descobrir API",
}

/** O traço que substitui qualquer número que não deu para calcular. */
const NOT_AVAILABLE = "—"

/** Quantas semanas o gráfico de economia mostra, contando a semana atual. */
const WEEKS = 8

type WeekBucket = {
  key: string
  label: string
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

/** Execuções concluídas em cada uma das últimas 8 semanas, da mais antiga para a atual. */
function completedByWeek(jobs: Job[]): WeekBucket[] {
  const thisWeek = weekStart(new Date())
  const buckets: WeekBucket[] = []
  for (let offset = WEEKS - 1; offset >= 0; offset--) {
    const start = new Date(thisWeek)
    start.setDate(thisWeek.getDate() - offset * 7)
    buckets.push({
      key: weekKey(start),
      label: `S${WEEKS - offset}`,
      completed: 0,
      current: offset === 0,
    })
  }
  const index = new Map(buckets.map((bucket, i) => [bucket.key, i]))
  for (const job of jobs) {
    if (job.status !== "completed") continue
    const created = new Date(job.created_at)
    if (Number.isNaN(created.getTime())) continue
    const position = index.get(weekKey(weekStart(created)))
    if (position !== undefined) buckets[position].completed += 1
  }
  return buckets
}

/** Dinheiro na moeda informada; uma moeda desconhecida cai no número puro, sem quebrar a tela. */
function formatMoney(value: number | null, currency: string): string {
  if (value === null || !Number.isFinite(value)) return NOT_AVAILABLE
  const code = (currency || "").trim().toUpperCase()
  if (code) {
    try {
      return new Intl.NumberFormat("pt-BR", { style: "currency", currency: code }).format(value)
    } catch {
      // Código de moeda que o navegador não conhece: mostra o número e o código como vieram.
      return `${formatNumber(value)} ${code}`
    }
  }
  return formatNumber(value)
}

/** O retorno (valor ÷ custo) como "2,50×", ou "—" quando não existe (custo ou valor zero). */
function formatRatio(ratio: number | null): string {
  if (ratio === null || !Number.isFinite(ratio)) return NOT_AVAILABLE
  return `${ratio.toFixed(2).replace(".", ",")}×`
}

/** Lê um campo numérico de uma linha da API; o que não for número vira nulo. */
function rowNumber(row: Record<string, unknown>, key: string): number | null {
  const value = row[key]
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/** Horas economizadas como texto curto: "112 h", "1,5 h". */
function formatHours(hours: number): string {
  if (!Number.isFinite(hours)) return NOT_AVAILABLE
  const rounded = hours >= 10 ? Math.round(hours) : Math.round(hours * 10) / 10
  return `${formatNumber(rounded)} h`
}

export default function RoiPage() {
  const [roi, setRoi] = useState<RoiResult | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [report, jobList] = await Promise.all([api.getRoi(), api.getJobs()])
      setRoi(report)
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

  const weeks = useMemo(() => completedByWeek(jobs), [jobs])

  const runs = roi?.runs ?? 0
  const pages = roi?.pages ?? 0
  const value = roi?.value ?? 0
  const cost = roi?.cost ?? 0
  const net = roi?.net ?? 0
  const currency = roi?.currency ?? ""
  const hourlyRate = roi?.inputs.hourly_rate ?? 0
  const minutesPerPage = roi?.inputs.minutes_per_page ?? 0
  const savedHours = hourlyRate > 0 ? value / hourlyRate : null

  // A distribuição semanal usa a parcela das execuções concluídas em cada semana:
  // o total de horas é real, a divisão por semana é proporcional a elas.
  const windowCompleted = weeks.reduce((sum, bucket) => sum + bucket.completed, 0)
  const hoursPerWeek = weeks.map((bucket) =>
    savedHours === null || windowCompleted === 0
      ? null
      : (savedHours * bucket.completed) / windowCompleted
  )
  const measuredHours = hoursPerWeek.filter((hours): hours is number => hours !== null)
  const hoursMax = measuredHours.length > 0 ? Math.max(...measuredHours) : 0

  const engines = useMemo(() => {
    const rows = (roi?.per_engine ?? [])
      .map((row) => ({
        engine: String(row.engine ?? ""),
        value: rowNumber(row, "value") ?? 0,
        cost: rowNumber(row, "cost") ?? 0,
        runs: rowNumber(row, "runs") ?? 0,
      }))
      .filter((row) => row.engine !== "" && row.value > 0)
    return rows.sort((a, b) => b.value - a.value)
  }, [roi])

  const engineMax = engines.reduce((max, engine) => Math.max(max, engine.value), 0)

  // A semana de maior economia, para a frase lida por leitores de tela.
  // `indexOf` aqui é seguro: `hoursMax` sempre veio de uma posição de `hoursPerWeek`.
  const peakWeek = windowCompleted > 0 && savedHours !== null ? weeks[hoursPerWeek.indexOf(hoursMax)] : null

  // A barra de cada semana é a parcela das horas totais proporcional às execuções
  // concluídas naquela semana, então o total do gráfico bate com o relatório.
  const weekChartLabelText =
    peakWeek === null
      ? `Gráfico de barras de horas economizadas por semana nas últimas ${WEEKS} semanas: sem dados.`
      : `Gráfico de barras de horas economizadas por semana nas últimas ${WEEKS} semanas. ` +
        `A semana de maior economia foi ${peakWeek.label} com ${formatHours(hoursMax)}; ` +
        `o total do período é ${formatHours(savedHours ?? 0)}.`

  return (
    <div className="view-grid">
      <Topbar
        title="ROI"
        description="Quanto tempo e dinheiro as capturas automáticas pouparam."
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

      {loading && !roi && (
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

      {roi && (
        <>
          <StatStrip>
            <StatCard
              label="Trabalho economizado"
              value={savedHours === null ? NOT_AVAILABLE : formatHours(savedHours)}
              trend="estimativa do período"
            />
            <StatCard
              label="Valor estimado"
              value={formatMoney(value, currency)}
              trend={hourlyRate > 0 ? `a ${formatMoney(hourlyRate, currency)} por hora` : "valor da hora não configurado"}
            />
            <StatCard
              label="Capturas automáticas"
              value={formatNumber(runs)}
              trend="que substituiriam cópias manuais"
            />
            <StatCard
              label="Por tarefa evitada"
              value={`${formatNumber(minutesPerPage)} min`}
              trend="minutos por página, premissa informada"
            />
          </StatStrip>

          <div className="card">
            <div className="section-head" style={{ marginBottom: "var(--sp-2)" }}>
              <h3 className="card-title">Economia por semana</h3>
              <span className="hint">últimas {WEEKS} semanas</span>
            </div>
            {windowCompleted === 0 || savedHours === null ? (
              <EmptyState
                icon={<Icon name="i-trending" size="lg" />}
                title={savedHours === null ? "Valor da hora não configurado" : "Sem execuções no período"}
                description={
                  savedHours === null
                    ? "Defina o valor da hora nas configurações para o cálculo de economia por semana."
                    : `Nenhuma execução concluída nas últimas ${WEEKS} semanas.`
                }
                href={savedHours === null ? { label: "Abrir configurações", href: "/config" } : { label: "Nova extração", href: "/probe" }}
              />
            ) : (
              <>
                <div
                  className="chart"
                  role="img"
                  aria-label={weekChartLabelText}
                >
                  {weeks.map((bucket, i) => {
                    const hours = hoursPerWeek[i]
                    return (
                      <div className="col" key={bucket.key}>
                        <span className="v">{hours === null ? NOT_AVAILABLE : formatHours(hours)}</span>
                        <span
                          className={bucket.current ? "bar is-today" : "bar"}
                          style={{ height: `${hoursMax > 0 && hours !== null ? Math.max(4, Math.round((hours / hoursMax) * 100)) : 0}%` }}
                          title={`${bucket.label} · ${bucket.completed} execuções concluídas`}
                        />
                        <span className="x">{bucket.label}</span>
                      </div>
                    )
                  })}
                </div>
                <p className="hint" style={{ marginTop: "var(--sp-3)" }}>
                  As horas por semana seguem a parcela das execuções concluídas em cada semana — o total do
                  período vem do relatório de ROI.
                </p>
              </>
            )}
          </div>

          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
              Onde o tempo foi economizado
            </h3>
            {engines.length === 0 ? (
              <EmptyState
                icon={<Icon name="i-layers" size="lg" />}
                title="Nenhum motor economizou tempo ainda"
                description="A economia por motor aparece depois das primeiras execuções registradas."
                href={{ label: "Nova extração", href: "/probe" }}
              />
            ) : (
              <div className="od-stack" style={{ "--od-gap": "2px" } as CSSProperties}>
                {engines.map((engine) => (
                  <div className="bar-row" key={engine.engine}>
                    <span className="od-truncate">{ENGINE_LABELS[engine.engine] ?? engine.engine}</span>
                    <span className="bar-track">
                      <span
                        className="bar-fill"
                        style={{ width: `${engineMax > 0 ? Math.round((engine.value / engineMax) * 100) : 0}%` }}
                      />
                    </span>
                    <span className="val">
                      {hourlyRate > 0 ? formatHours(engine.value / hourlyRate) : formatMoney(engine.value, currency)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="hint" style={{ marginTop: "var(--sp-3)" }}>
              {roi.note}
            </p>
            <p className="hint">
              É uma estimativa baseada em tarefas equivalentes manuais informadas pela equipe — não é medida
              direta.
            </p>
          </div>

          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Custo e retorno
            </h3>
            <p className="card-sub" style={{ marginBottom: "var(--sp-3)" }}>
              O que as capturas geraram, o que custaram e a diferença entre os dois.
            </p>
            <DetailGrid>
              <DetailRow label="Páginas estimadas" value={formatNumber(pages)} hint="Soma dos arquivos gerados em cada execução, usada como proxy de páginas." />
              <DetailRow label="Execuções no cálculo" value={formatNumber(runs)} />
              <DetailRow label="Dados capturados" value={formatBytes(roi.bytes)} />
              <DetailRow label="Tempo de máquina" value={formatClock(roi.duration_s)} />
              <DetailRow label="Valor gerado" value={formatMoney(value, currency)} />
              <DetailRow label="Custo" value={formatMoney(cost, currency)} />
              <DetailRow label="Líquido" value={formatMoney(net, currency)} />
              <DetailRow label="Retorno" value={formatRatio(roi.ratio)} hint="Valor gerado dividido pelo custo; sem custo registrado não existe retorno calculável." />
              <DetailRow label="Moeda" value={currency || "não configurada"} />
            </DetailGrid>
          </div>
        </>
      )}
    </div>
  )
}

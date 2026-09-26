"use client"
import { useEffect, useState } from "react"
import { api, RoiResult } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { StatCard } from "@/components/ui/stat-card"
import { DetailGrid, DetailRow } from "@/components/DetailRow"
import { formatDuration } from "@/lib/utils"
import { RefreshCw, Coins, Calculator, AlertTriangle, BarChart3, TrendingUp, Gauge } from "lucide-react"

/** Nome em português de cada motor, igual ao usado na tela de Desempenho. */
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

/** O "—" que substitui qualquer número que não deu para calcular. */
const NOT_AVAILABLE = "—"

/** Dinheiro na moeda informada; uma moeda desconhecida cai no número puro, sem quebrar a tela. */
function formatMoney(value: number | null, currency: string): string {
  if (value === null || !Number.isFinite(value)) return NOT_AVAILABLE
  const code = (currency || "").trim().toUpperCase()
  if (code) {
    try {
      return new Intl.NumberFormat("pt-BR", { style: "currency", currency: code }).format(value)
    } catch {
      // Código de moeda que o navegador não conhece: mostra o número com o código ao lado.
    }
  }
  return `${value.toFixed(2)}${code ? ` ${code}` : ""}`
}

/** O retorno (valor ÷ custo) como "2,50×", ou "—" quando não existe (custo ou valor zero). */
function formatRatio(ratio: number | null): string {
  if (ratio === null || !Number.isFinite(ratio)) return NOT_AVAILABLE
  return `${ratio.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×`
}

/** Lê um campo numérico de uma linha da API; o que não for número vira "não disponível". */
function rowNumber(row: Record<string, unknown>, key: string): number | null {
  const value = row[key]
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

export default function RoiPage() {
  const [data, setData] = useState<RoiResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchRoi = async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await api.getRoi())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRoi()
  }, [])

  const currency = data?.currency || data?.inputs.currency || ""
  const runs = data?.runs ?? 0
  const hasData = Boolean(data) && runs > 0
  const net = data?.net ?? 0
  const perEngine = data?.per_engine ?? []

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Retorno"
        description="O que o trabalho automatizado evitou de trabalho manual e quanto custou rodar. Os dois lados aparecem separados para você julgar."
        action={
          <Button onClick={fetchRoi} loading={loading} size="sm" variant="outline">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      {error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar os números de retorno.</p>
            <p className="mt-1">{error}</p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && !hasData && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <Coins className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">Nada medido ainda</h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
              Os números aparecem depois das primeiras extrações: cada execução registra páginas, tempo e custo, e é
              disso que o retorno é calculado. Faça uma cópia em{" "}
              <strong className="text-foreground">Nova extração</strong> e volte aqui.
            </p>
          </CardContent>
        </Card>
      )}

      {data && hasData && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard
              label="Valor gerado"
              value={formatMoney(data.value, currency)}
              icon={<Coins className="h-4 w-4" />}
              trend={`${data.pages} página(s) evitadas`}
            />
            <StatCard
              label="Custo"
              value={formatMoney(data.cost, currency)}
              icon={<Calculator className="h-4 w-4" />}
              trend="de processamento, tráfego e armazenamento"
            />
            <StatCard
              label="Saldo"
              value={formatMoney(net, currency)}
              icon={<TrendingUp className="h-4 w-4" />}
              trend="valor − custo"
              className={net >= 0 ? "ring-1 ring-emerald-500/20" : "ring-1 ring-red-500/20"}
            />
            <StatCard
              label="Retorno"
              value={formatRatio(data.ratio)}
              icon={<Gauge className="h-4 w-4" />}
              trend={
                data.ratio === null
                  ? "sem custo ou sem valor para comparar"
                  : "de valor para cada 1 de custo"
              }
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Calculator className="h-4 w-4" /> Premissas do cálculo
              </CardTitle>
              <CardDescription>
                O valor do trabalho manual evitado sai destes dois números, que você configura. Eles não são medidos: são
                uma estimativa do tempo que uma pessoa levaria.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <DetailGrid>
                <DetailRow
                  label="Valor da hora"
                  value={formatMoney(data.inputs.hourly_rate, data.inputs.currency || currency)}
                  hint="Quanto custa uma hora de trabalho manual, na moeda configurada."
                />
                <DetailRow
                  label="Minutos por página"
                  value={`${data.inputs.minutes_per_page.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} min`}
                  hint="Tempo estimado para uma pessoa copiar e organizar uma página à mão."
                />
                <DetailRow label="Moeda" value={currency || "não configurada"} />
                <DetailRow
                  label="Execuções consideradas"
                  value={`${data.runs} execução(ões) · ${data.pages} página(s) · ${formatDuration(data.duration_s)}`}
                  hint="Tudo o que já está registrado no histórico de execuções."
                />
              </DetailGrid>

              <div className="rounded-[12px] border bg-secondary/40 p-4 space-y-2">
                <p className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground">
                  Como o número foi montado
                </p>
                <p className="text-[13px] leading-relaxed">{data.note}</p>
              </div>

              <div className="flex items-start gap-2 rounded-[10px] bg-secondary/60 border p-3 text-[12.5px] text-muted-foreground">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
                <span>
                  O valor é uma estimativa baseada nas premissas configuradas acima, não uma economia medida.
                </span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4" /> Por motor
              </CardTitle>
              <CardDescription>
                Quanto cada forma de baixar ou analisar contribuiu para o valor e para o custo. A lista vem do que custou
                mais para o que custou menos.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {perEngine.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">
                  Nenhuma execução foi registrada por motor ainda.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                        <th className="px-4 py-3 font-medium">Motor</th>
                        <th className="px-4 py-3 font-medium text-right">Execuções</th>
                        <th className="px-4 py-3 font-medium text-right">Custo</th>
                        <th className="px-4 py-3 font-medium text-right">Valor</th>
                        <th className="px-4 py-3 font-medium text-right">Saldo</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/60">
                      {perEngine.map((row, index) => {
                        const engine = typeof row.engine === "string" && row.engine ? row.engine : NOT_AVAILABLE
                        const rowNet = rowNumber(row, "net")
                        return (
                          <tr key={`${engine}-${index}`} className="hover:bg-accent/50 transition-colors">
                            <td className="px-4 py-3">
                              <div className="flex flex-col gap-0.5 min-w-[170px]">
                                <span className="text-[13px] font-medium">{ENGINE_LABELS[engine] ?? engine}</span>
                                <span className="text-[11px] font-mono text-muted-foreground">{engine}</span>
                              </div>
                            </td>
                            <td className="px-4 py-3 text-right text-[13px] tabular-nums">
                              {rowNumber(row, "runs") ?? NOT_AVAILABLE}
                            </td>
                            <td className="px-4 py-3 text-right text-[13px] tabular-nums whitespace-nowrap">
                              {formatMoney(rowNumber(row, "cost"), currency)}
                            </td>
                            <td className="px-4 py-3 text-right text-[13px] tabular-nums whitespace-nowrap">
                              {formatMoney(rowNumber(row, "value"), currency)}
                            </td>
                            <td
                              className={`px-4 py-3 text-right text-[13px] tabular-nums whitespace-nowrap ${
                                rowNet === null
                                  ? "text-muted-foreground"
                                  : rowNet >= 0
                                    ? "text-emerald-600 dark:text-emerald-400"
                                    : "text-red-600 dark:text-red-400"
                              }`}
                            >
                              {formatMoney(rowNet, currency)}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Gauge className="h-4 w-4" /> Como ler esses números
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-[13px] text-muted-foreground leading-relaxed">
                O custo é calculado pelo que foi gasto de processamento, tráfego e armazenamento, e o valor pelo tempo
                manual que a automação evitou. Um retorno sem número significa que um dos dois lados ficou zerado — sem
                custo não existe comparação, e sem valor não há economia a medir. O valor da hora e os minutos por página
                vêm da configuração do sistema (<span className="font-mono text-[12px]">roi_hourly_rate</span> e{" "}
                <span className="font-mono text-[12px]">roi_manual_minutes_per_page</span>), e mudá-los muda a
                estimativa, não o trabalho já feito.
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

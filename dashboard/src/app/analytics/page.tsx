"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { api, AnalyticsTotals, EngineStats } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { StatCard } from "@/components/ui/stat-card"
import { formatBytes, formatDuration } from "@/lib/utils"
import { RefreshCw, Gauge, CheckCircle2, HardDrive, Clock3, BarChart3, Layers, Coins } from "lucide-react"

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

/**
 * As taxas chegam da API como fração (0 a 1). Um valor que já venha em pontos
 * percentuais é mantido como está, para a tela nunca mostrar 9330%.
 */
function successPercent(rate: number): number {
  if (!Number.isFinite(rate) || rate <= 0) return 0
  return Math.min(100, Math.round(rate <= 1 ? rate * 100 : rate))
}

/** Cor da barra conforme a taxa: verde quando quase tudo dá certo. */
function rateBar(pct: number): string {
  if (pct >= 90) return "bg-emerald-500"
  if (pct >= 60) return "bg-amber-500"
  return "bg-red-500"
}

export default function AnalyticsPage() {
  const [engines, setEngines] = useState<EngineStats[]>([])
  const [totals, setTotals] = useState<AnalyticsTotals | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchAnalytics = async () => {
    setLoading(true)
    setError(null)
    try {
      const [engineRows, overall] = await Promise.all([api.getEngineStats(), api.getAnalyticsTotals()])
      setEngines(engineRows)
      setTotals(overall)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAnalytics()
  }, [])

  const runs = totals?.runs ?? 0
  const succeeded = totals?.succeeded ?? 0
  const failed = totals?.failed ?? 0
  const overallRate = successPercent(totals?.success_rate ?? 0)
  const hasData = runs > 0 || engines.length > 0

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Desempenho"
        description="Quantas vezes cada motor de extração rodou, quantas deram certo, quanto tempo levou e quanto baixou."
        action={
          <>
            <Link href="/roi">
              <Button size="sm" variant="outline">
                <Coins className="h-4 w-4" /> Ver retorno
              </Button>
            </Link>
            <Button onClick={fetchAnalytics} loading={loading} size="sm" variant="outline">
              <RefreshCw className="h-4 w-4" /> Atualizar
            </Button>
          </>
        }
      />

      {error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar os números de desempenho.</p>
            <p className="mt-1">{error}</p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && !hasData && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <Gauge className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">Ainda não há números</h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
              Os números aparecem depois da primeira extração. Faça uma cópia em{" "}
              <strong className="text-foreground">Nova extração</strong> e volte aqui para comparar os motores.
            </p>
          </CardContent>
        </Card>
      )}

      {totals && hasData && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard label="Extrações" value={runs} icon={<Layers className="h-4 w-4" />} trend="no total" />
            <StatCard
              label="Taxa de sucesso"
              value={`${overallRate}%`}
              icon={<CheckCircle2 className="h-4 w-4" />}
              trend={`${succeeded} certas · ${failed} com falha`}
              className="ring-1 ring-emerald-500/20"
            />
            <StatCard
              label="Tamanho baixado"
              value={formatBytes(totals.bytes)}
              icon={<HardDrive className="h-4 w-4" />}
              trend="somando tudo"
            />
            <StatCard
              label="Duração média"
              value={formatDuration(totals.avg_duration_s)}
              icon={<Clock3 className="h-4 w-4" />}
              trend="por extração"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BarChart3 className="h-4 w-4" /> Por motor
              </CardTitle>
              <CardDescription>
                Cada motor é a forma como o Zfrog baixa ou analisa um site. A lista vem do que mais rodou para o que
                menos rodou.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {engines.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">
                  Nenhuma extração foi registrada por motor ainda.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                        <th className="px-4 py-3 font-medium">Motor</th>
                        <th className="px-4 py-3 font-medium text-right">Extrações</th>
                        <th className="px-4 py-3 font-medium text-right">Certas</th>
                        <th className="px-4 py-3 font-medium text-right">Falhas</th>
                        <th className="px-4 py-3 font-medium">Taxa de sucesso</th>
                        <th className="px-4 py-3 font-medium text-right">Duração média</th>
                        <th className="px-4 py-3 font-medium text-right">Tamanho médio</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/60">
                      {engines.map((row) => {
                        const info = ENGINE_INFO[row.engine]
                        const pct = successPercent(row.success_rate)
                        return (
                          <tr key={row.engine} className="hover:bg-accent/50 transition-colors">
                            <td className="px-4 py-3">
                              <div className="flex flex-col gap-0.5 min-w-[170px]">
                                <span className="text-[13px] font-medium">{info?.label ?? row.engine}</span>
                                <span className="text-[11px] font-mono text-muted-foreground" title={info?.what}>
                                  {row.engine}
                                </span>
                              </div>
                            </td>
                            <td className="px-4 py-3 text-right text-[13px] tabular-nums">{row.runs}</td>
                            <td className="px-4 py-3 text-right text-[13px] tabular-nums text-emerald-600 dark:text-emerald-400">
                              {row.succeeded}
                            </td>
                            <td
                              className={`px-4 py-3 text-right text-[13px] tabular-nums ${
                                row.failed ? "text-red-600 dark:text-red-400" : "text-muted-foreground"
                              }`}
                            >
                              {row.failed}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-2 min-w-[130px]">
                                <div className="h-1.5 flex-1 rounded-full bg-secondary overflow-hidden">
                                  <div
                                    className={`h-full rounded-full ${rateBar(pct)}`}
                                    style={{ width: `${pct}%` }}
                                  />
                                </div>
                                <span className="text-[12px] font-medium tabular-nums w-9 text-right">{pct}%</span>
                              </div>
                            </td>
                            <td className="px-4 py-3 text-right text-[13px] tabular-nums whitespace-nowrap">
                              {formatDuration(row.avg_duration_s)}
                            </td>
                            <td className="px-4 py-3 text-right text-[13px] tabular-nums whitespace-nowrap">
                              {formatBytes(row.avg_bytes)}
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
                <Gauge className="h-4 w-4" /> Para que serve isso
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-[13px] text-muted-foreground leading-relaxed">
                Serve para escolher melhor: se um site comum aparece com muitas falhas no Baixador rápido, tente o
                Navegador; se as falhas se concentram em um motor só, é sinal de que aquele tipo de site precisa de
                outra forma de baixar.
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

"use client"
import { useState } from "react"
import Link from "next/link"
import { api, SystemStats } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { StatCard } from "@/components/ui/stat-card"
import { RefreshCw, Layers, CheckCircle2, Clock3, AlertCircle, BarChart3, TrendingUp } from "lucide-react"

export default function StatsPage() {
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchStats = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getStats()
      setStats(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const total = stats ? stats.total_jobs : 0
  const completed = stats?.completed || 0
  const running = stats?.running || 0
  const failed = stats?.failed || 0
  const other = Math.max(0, total - completed - running - failed)
  const successRate = total ? Math.round((completed / total) * 100) : 0

  return (
    <div className="space-y-6 animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Estatísticas"
        description="Resumo do que o Zfrog já fez. Os números são carregados quando você clica em Atualizar."
        action={
          <Button onClick={fetchStats} loading={loading} size="sm" variant="outline">
            <RefreshCw className="h-4 w-4" />
            Atualizar
          </Button>
        }
      />

      {!stats && !loading && !error && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <BarChart3 className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">Nada carregado ainda</h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-sm mx-auto">
              Clique em Atualizar para ver quantas extrações foram feitas e quantas deram certo.
            </p>
            <Button size="sm" className="mt-4" onClick={fetchStats}>
              Carregar estatísticas
            </Button>
          </CardContent>
        </Card>
      )}

      {error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar os números.</p>
            <p className="mt-1">{error}</p>
          </CardContent>
        </Card>
      )}

      {stats && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard label="Total" value={total} icon={<Layers className="h-4 w-4" />} trend="desde o início" />
            <StatCard
              label="Concluídas"
              value={completed}
              icon={<CheckCircle2 className="h-4 w-4" />}
              trend={`${successRate}% de sucesso`}
              className="ring-1 ring-emerald-500/20"
            />
            <StatCard
              label="Em andamento"
              value={running}
              icon={<Clock3 className="h-4 w-4" />}
              trend="agora"
              className={running ? "ring-1 ring-amber-500/20" : ""}
            />
            <StatCard
              label="Falhas"
              value={failed}
              icon={<AlertCircle className="h-4 w-4" />}
              trend={`${total ? Math.round((failed / total) * 100) : 0}% do total`}
              className={failed ? "ring-1 ring-red-500/20" : ""}
            />
          </div>

          <div className="grid lg:grid-cols-3 gap-6">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4" /> Distribuição
                </CardTitle>
                <CardDescription>Proporção de cada situação no total de extrações</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {[
                  { label: "Concluídas", value: completed, color: "bg-emerald-500" },
                  { label: "Em andamento", value: running, color: "bg-amber-500" },
                  { label: "Falhas", value: failed, color: "bg-red-500" },
                  { label: "Outras (na fila ou canceladas)", value: other, color: "bg-zinc-400" },
                ].map((row) => {
                  const pct = total ? (row.value / total) * 100 : 0
                  return (
                    <div key={row.label} className="space-y-1.5">
                      <div className="flex justify-between text-[12.5px]">
                        <span className="font-medium">{row.label}</span>
                        <span className="text-muted-foreground">
                          {row.value} · {pct.toFixed(1)}%
                        </span>
                      </div>
                      <div className="h-2 rounded-full bg-secondary overflow-hidden">
                        <div
                          className={`h-full ${row.color} rounded-full transition-all duration-700`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Saúde do sistema</CardTitle>
                <CardDescription>Capacidade disponível neste momento</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-[12px] bg-secondary p-3 flex items-center justify-between">
                  <span className="text-[13px]">Taxa de sucesso</span>
                  <span className="text-[18px] font-semibold">{successRate}%</span>
                </div>
                <div className="rounded-[12px] bg-secondary p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px]">Agora</span>
                    <span
                      className={`text-[12px] px-2 py-1 rounded-full font-medium ${
                        running ? "bg-amber-500/10 text-amber-600" : "bg-zinc-500/10 text-zinc-500"
                      }`}
                    >
                      {running ? `${running} baixando` : "ocioso"}
                    </span>
                  </div>
                  <p className="text-[11.5px] text-muted-foreground mt-1.5 leading-snug">
                    {running
                      ? "Há extrações rodando neste instante."
                      : "Nenhuma extração rodando. O servidor está livre."}
                  </p>
                </div>
                <div className="rounded-[12px] bg-secondary p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px]">Vagas livres</span>
                    <span className="text-[13px] font-mono font-medium">{stats.concurrent_slots_available}</span>
                  </div>
                  <p className="text-[11.5px] text-muted-foreground mt-1.5 leading-snug">
                    Quantas extrações ainda podem começar sem esperar na fila. Ajuste em{" "}
                    <Link href="/config" className="text-primary underline">
                      Configurações
                    </Link>
                    .
                  </p>
                </div>
                <div className="rounded-[12px] bg-secondary p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px]">Velocidade atual</span>
                    <span className="text-[13px] font-mono font-medium">{stats.rate_limit_rps} pedidos/s</span>
                  </div>
                  <p className="text-[11.5px] text-muted-foreground mt-1.5 leading-snug">
                    Ritmo com que o Zfrog faz pedidos aos sites.
                  </p>
                </div>
                <details className="rounded-[12px] bg-secondary p-3">
                  <summary className="text-[11.5px] text-muted-foreground cursor-pointer hover:text-foreground">
                    Ver dados brutos
                  </summary>
                  <pre className="mt-2 text-[11px] font-mono bg-card border rounded-[8px] p-2.5 overflow-auto max-h-[180px]">
                    {JSON.stringify(stats, null, 2)}
                  </pre>
                </details>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

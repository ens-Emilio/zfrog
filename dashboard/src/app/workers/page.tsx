"use client"
import { useEffect, useState } from "react"
import { api, WorkerInfo, WorkerStats } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { StatCard } from "@/components/ui/stat-card"
import { timeAgo } from "@/lib/utils"
import {
  Cpu,
  Wifi,
  WifiOff,
  Boxes,
  Activity,
  Gauge,
  Server,
  Compass,
  Globe2,
  RefreshCw,
  AlertTriangle,
} from "lucide-react"

/**
 * Máquinas que processam as cópias e as regiões onde elas ficam. Quando há mais
 * de uma máquina, a região do site decide qual delas pega o trabalho.
 */

/**
 * A API manda `by_region` como um resumo por região (quantas máquinas, quanta
 * capacidade). O tipo compartilhado declara só números, então os dois formatos
 * são aceitos e o que faltar vira zero.
 */
type RegionBucket = { workers?: number; capacity?: number; running?: number; free?: number }

type RegionRow = { region: string; workers: number; capacity: number; free: number }

/** Uma linha por região, da que tem mais máquinas para a que tem menos. */
function regionRows(byRegion: Record<string, number | RegionBucket>): RegionRow[] {
  return Object.entries(byRegion)
    .map(([region, value]) =>
      typeof value === "number"
        ? { region, workers: value, capacity: 0, free: 0 }
        : {
            region,
            workers: value.workers ?? 0,
            capacity: value.capacity ?? 0,
            free: value.free ?? 0,
          }
    )
    .sort((a, b) => b.workers - a.workers || a.region.localeCompare(b.region))
}

export default function WorkersPage() {
  const [stats, setStats] = useState<WorkerStats | null>(null)
  const [workers, setWorkers] = useState<WorkerInfo[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [region, setRegion] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [url, setUrl] = useState("")
  const [assignRegion, setAssignRegion] = useState("")
  const [assigning, setAssigning] = useState(false)
  const [assignError, setAssignError] = useState<string | null>(null)
  const [assignment, setAssignment] = useState<{ worker: string | null; region: string; reason: string } | null>(
    null
  )

  /** Busca as máquinas; o primeiro carregamento já nasce com o indicador ligado. */
  const loadWorkers = async (targetRegion: string) => {
    try {
      const data = await api.getWorkers(targetRegion.trim() || undefined)
      setStats(data.stats)
      setWorkers(data.workers)
      // As regiões conhecidas só crescem: filtrar por uma delas não pode fazer
      // o botão dela desaparecer da lista.
      const known = [...Object.keys(data.stats.by_region ?? {}), ...data.workers.map((worker) => worker.region)]
      setRegions((current) => Array.from(new Set([...current, ...known])).sort((a, b) => a.localeCompare(b)))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const fetchWorkers = async (targetRegion: string) => {
    setLoading(true)
    await loadWorkers(targetRegion)
  }

  useEffect(() => {
    void (async () => {
      await fetchWorkers("")
    })()
  }, [])

  const handleAssign = async () => {
    if (!url.trim()) return
    setAssigning(true)
    setAssignError(null)
    setAssignment(null)
    try {
      setAssignment(await api.assignWorker(url.trim(), assignRegion.trim() || undefined))
    } catch (e) {
      setAssignError(e instanceof Error ? e.message : String(e))
    } finally {
      setAssigning(false)
    }
  }

  const rows = stats ? regionRows(stats.by_region) : []

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Workers"
        description="Um worker é uma máquina que processa as cópias; a região dele decide onde os dados são tratados."
        action={
          <Button onClick={() => fetchWorkers(region)} loading={loading} size="sm" variant="outline">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      <datalist id="worker-regions">
        {regions.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      {error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar os workers.</p>
            <p className="mt-1">{error}</p>
            <p className="mt-1 text-muted-foreground">
              Confira se o sistema está no ar e clique em <strong className="text-foreground/80">Atualizar</strong>.
            </p>
          </CardContent>
        </Card>
      )}

      {stats && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <StatCard
              label="Workers"
              value={stats.workers}
              icon={<Cpu className="h-4 w-4" />}
              trend="registrados"
            />
            <StatCard
              label="Vivos"
              value={stats.alive}
              icon={<Wifi className="h-4 w-4" />}
              trend="respondendo"
              className={stats.alive > 0 ? "ring-1 ring-emerald-500/20" : undefined}
            />
            <StatCard
              label="Capacidade"
              value={stats.capacity}
              icon={<Boxes className="h-4 w-4" />}
              trend="vagas no total"
            />
            <StatCard
              label="Em uso"
              value={stats.running}
              icon={<Activity className="h-4 w-4" />}
              trend="rodando agora"
            />
            <StatCard
              label="Livres"
              value={stats.free}
              icon={<Gauge className="h-4 w-4" />}
              trend="vagas sobrando"
              className={stats.free > 0 ? "ring-1 ring-emerald-500/20" : undefined}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Compass className="h-4 w-4" /> Por região
              </CardTitle>
              <CardDescription>
                Quantas máquinas vivas cada região tem e quantas vagas ainda sobram nelas. A capacidade que aparece
                aqui é só das máquinas que estão respondendo.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {rows.length === 0 ? (
                <div className="rounded-[12px] border border-dashed p-8 text-center">
                  <Compass className="h-7 w-7 mx-auto text-muted-foreground/40 mb-2" />
                  <p className="text-[13px] font-medium">Nenhuma região com máquina viva</p>
                  <p className="text-[12.5px] text-muted-foreground mt-1">
                    Assim que uma máquina se registrar e mandar sinal de vida, a região dela aparece aqui.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                  {rows.map((row) => (
                    <div key={row.region} className="rounded-[12px] border bg-secondary/40 p-3">
                      <p className="text-[11px] uppercase tracking-widest text-muted-foreground font-medium break-all">
                        {row.region}
                      </p>
                      <p className="text-[20px] font-semibold tabular-nums">{row.workers}</p>
                      <p className="text-[11.5px] text-muted-foreground">
                        {row.capacity > 0
                          ? `${row.free} de ${row.capacity} vagas livres`
                          : `${row.workers === 1 ? "máquina viva" : "máquinas vivas"}`}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4" /> Máquinas
          </CardTitle>
          <CardDescription>
            {region
              ? `Mostrando só a região ${region}. Os números do topo continuam sendo do sistema inteiro.`
              : "Todas as máquinas registradas. As que param de mandar sinal de vida ficam marcadas em vermelho."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {[{ value: "", label: "Todas" }, ...regions.map((name) => ({ value: name, label: name }))].map(
              (option) => (
                <button
                  key={option.value || "all"}
                  type="button"
                  onClick={() => {
                    setRegion(option.value)
                    fetchWorkers(option.value)
                  }}
                  aria-pressed={region === option.value}
                  className={`rounded-[10px] border px-3 py-1.5 text-[12.5px] font-medium transition-all ${
                    region === option.value
                      ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                      : "text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {option.label}
                </button>
              )
            )}
          </div>

          {!loading && !error && workers.length === 0 && (
            <div className="rounded-[12px] border border-dashed p-12 text-center">
              <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
                <Cpu className="h-6 w-6 text-muted-foreground" />
              </div>
              <h3 className="text-[15px] font-semibold">
                {region ? "Nenhum worker nessa região" : "Nenhum worker registrado"}
              </h3>
              <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
                {region
                  ? "Troque o filtro para ver as outras regiões, ou registre uma máquina nessa região."
                  : "Nenhuma máquina se apresentou ao sistema ainda. Sem worker, as cópias são processadas no próprio servidor."}
              </p>
            </div>
          )}

          {workers.length > 0 && (
            <div className="overflow-x-auto rounded-[12px] border">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Id</th>
                    <th className="px-4 py-3 font-medium">Região</th>
                    <th className="px-4 py-3 font-medium">Situação</th>
                    <th className="px-4 py-3 font-medium">Sinal de vida</th>
                    <th className="px-4 py-3 font-medium">Versão</th>
                    <th className="px-4 py-3 font-medium">Visto por último</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {workers.map((worker) => {
                    const free = Math.max(0, worker.capacity - worker.running)
                    return (
                      <tr key={worker.id} className="hover:bg-accent/50">
                        <td className="px-4 py-3 text-[12.5px] font-mono break-all">{worker.id}</td>
                        <td className="px-4 py-3 text-[12.5px]">{worker.region || "—"}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span
                              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap ${
                                free > 0
                                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
                                  : "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20"
                              }`}
                            >
                              {free > 0 ? "Livre" : "Ocupado"}
                            </span>
                            <span className="text-[12px] text-muted-foreground tabular-nums">
                              {worker.running}/{worker.capacity}
                            </span>
                            {!worker.enabled && (
                              <span
                                className="text-[11px] text-muted-foreground"
                                title="Desativado: não recebe novas cópias."
                              >
                                desativado
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-1.5 text-[12.5px] whitespace-nowrap ${
                              worker.alive ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
                            }`}
                            title={
                              worker.alive
                                ? "Mandou sinal de vida há pouco."
                                : "Parou de mandar sinal de vida; não recebe novas cópias."
                            }
                          >
                            <span
                              className={`h-2 w-2 rounded-full shrink-0 ${
                                worker.alive ? "bg-emerald-500" : "bg-red-500"
                              }`}
                            />
                            {worker.alive ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
                            {worker.alive ? "vivo" : "sem resposta"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[12px] font-mono text-muted-foreground">
                          {worker.version || "—"}
                        </td>
                        <td className="px-4 py-3 text-[12.5px] text-muted-foreground whitespace-nowrap">
                          <span title={new Date(worker.last_seen).toLocaleString("pt-BR")}>
                            {worker.last_seen ? timeAgo(worker.last_seen) : "nunca"}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {loading && workers.length === 0 && !error && (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <Cpu className="h-6 w-6 mx-auto text-muted-foreground/40 mb-2 animate-pulse" />
              <p className="text-[13px] text-muted-foreground">Carregando as máquinas…</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Compass className="h-4 w-4" /> Onde este site seria processado?
          </CardTitle>
          <CardDescription>
            Mostra qual máquina pegaria o trabalho de um site, em qual região e por quê. A escolha sai da região do
            site; se lá não houver máquina livre, o sistema usa outra e diz o motivo.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Endereço do site"
                placeholder="https://exemplo.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAssign()}
                leftIcon={<Globe2 className="h-4 w-4" />}
                hint="O mesmo endereço que você usaria em Nova extração."
              />
            </div>
            <div className="sm:w-[220px]">
              <Input
                label="Região (opcional)"
                placeholder="ex.: br"
                list="worker-regions"
                value={assignRegion}
                onChange={(e) => setAssignRegion(e.target.value)}
                hint="Em branco, a região vem do próprio site."
              />
            </div>
            <Button onClick={handleAssign} loading={assigning} disabled={!url.trim()}>
              <Compass className="h-4 w-4" /> Ver
            </Button>
          </div>

          {assignError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível descobrir onde este site seria processado.</p>
              <p className="mt-1">{assignError}</p>
            </div>
          )}

          {assignment && (
            <div
              className={`rounded-[12px] border p-4 text-[13px] ${
                assignment.worker
                  ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-700 dark:text-emerald-400"
                  : "bg-amber-500/10 border-amber-500/20 text-amber-700 dark:text-amber-400"
              }`}
            >
              <p className="flex items-center gap-1.5 font-medium">
                {assignment.worker ? (
                  <>
                    <Server className="h-4 w-4" /> Seria processado por {assignment.worker}
                  </>
                ) : (
                  <>
                    <AlertTriangle className="h-4 w-4" /> Nenhum worker disponível agora
                  </>
                )}
              </p>
              <p className="mt-1">
                Região: <span className="font-mono">{assignment.region || "—"}</span>
              </p>
              <p className="mt-0.5">Motivo: {assignment.reason}</p>
              {!assignment.worker && (
                <p className="mt-1 text-muted-foreground">
                  Sem máquina livre, a cópia roda no próprio servidor até alguém registrar um worker.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

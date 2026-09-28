"use client"

import { useEffect, useState, type CSSProperties } from "react"
import { api, WorkerInfo, WorkerStats } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Chip } from "@/components/ui/ds"
import { Icon } from "@/lib/icons"
import { timeAgo } from "@/lib/utils"

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

/**
 * A situação de uma máquina, na ordem em que ela importa: uma máquina desligada
 * está em manutenção mesmo que ainda esteja respondendo, e uma que parou de
 * responder não recebe trabalho nem tem vagas para oferecer.
 */
type WorkerState = { label: string; variant: "accent" | "success" | "warning" | "danger"; help: string }

function workerState(worker: WorkerInfo): WorkerState {
  if (!worker.enabled) {
    return {
      label: "Manutenção",
      variant: "warning",
      help: "Desativada de propósito: não recebe novas cópias.",
    }
  }
  if (!worker.alive) {
    return {
      label: "Sem resposta",
      variant: "danger",
      help: "Parou de mandar sinal de vida; não recebe novas cópias.",
    }
  }
  if (Math.max(0, worker.capacity - worker.running) === 0) {
    return {
      label: "Ocupado",
      variant: "accent",
      help: "Todas as vagas estão em uso agora.",
    }
  }
  return {
    label: "Livre",
    variant: "success",
    help: "Respondendo e com vaga sobrando.",
  }
}

/** Data e hora completas, para o `title` e para o painel de detalhes. */
function fullStamp(value: string): string {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("pt-BR")
}

export default function WorkersPage() {
  const [stats, setStats] = useState<WorkerStats | null>(null)
  const [workers, setWorkers] = useState<WorkerInfo[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [region, setRegion] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

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
  const maintenance = workers.filter((worker) => !worker.enabled).length
  const occupancy = stats && stats.capacity > 0 ? Math.round((stats.running / stats.capacity) * 100) : 0

  return (
    <div className="view-grid">
      <Topbar
        title="Workers"
        description="Um worker é uma máquina que processa as cópias; a região dele decide onde os dados são tratados."
        action={
          <Button variant="secondary" size="sm" onClick={() => fetchWorkers(region)} loading={loading}>
            <Icon name="i-refresh" size="sm" />
            Atualizar
          </Button>
        }
      />

      <datalist id="worker-regions">
        {regions.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      {error && (
        <div className="card" role="alert">
          <h3 className="card-title">Não foi possível carregar os workers.</h3>
          <p className="card-sub" style={{ marginTop: "var(--sp-2)" }}>
            {error}
          </p>
          <div className="od-row" style={{ marginTop: "var(--sp-4)" }}>
            <Button size="sm" onClick={() => fetchWorkers(region)} loading={loading}>
              <Icon name="i-refresh" size="sm" />
              Tentar de novo
            </Button>
          </div>
        </div>
      )}

      {!stats && !error && (
        <StatStrip>
          {[0, 1, 2, 3].map((index) => (
            <div className="stat" key={index}>
              <Skeleton className="h-7 w-16" />
              <Skeleton className="h-3 w-24" style={{ marginTop: "var(--sp-2)" }} />
            </div>
          ))}
        </StatStrip>
      )}

      {stats && (
        <>
          <StatStrip>
            <StatCard
              label="Workers"
              value={stats.workers}
              trend={rows.length === 1 ? "1 região" : `${rows.length} regiões`}
            />
            <StatCard
              label="Execuções rodando"
              value={stats.running}
              trend={`${stats.free} ${stats.free === 1 ? "vaga livre" : "vagas livres"}`}
            />
            <StatCard
              label="Ocupação média"
              value={`${occupancy}%`}
              trend={`${stats.alive} ${stats.alive === 1 ? "máquina viva" : "máquinas vivas"}`}
            />
            <StatCard
              label="Em manutenção"
              value={maintenance}
              trend={maintenance > 0 ? "fora da fila" : "nenhuma parada"}
            />
          </StatStrip>

          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Por região
            </h3>
            <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
              Quantas máquinas vivas cada região tem e quantas vagas ainda sobram nelas. A capacidade aqui é só das
              máquinas que estão respondendo.
            </p>
            {rows.length === 0 ? (
              <EmptyState
                icon={<Icon name="i-globe" size="lg" />}
                title="Nenhuma região com máquina viva"
                description="Assim que uma máquina se registrar e mandar sinal de vida, a região dela aparece aqui."
              />
            ) : (
              <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
                {rows.map((row) => (
                  <div className="stat" key={row.region}>
                    <span className="stat-value">{row.workers}</span>
                    <span className="stat-label mono od-truncate" title={row.region}>
                      {row.region || "sem região"}
                    </span>
                    <span className="stat-trend">
                      {row.capacity > 0
                        ? `${row.free} de ${row.capacity} vagas livres`
                        : `${row.workers === 1 ? "máquina viva" : "máquinas vivas"}`}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      <div className="card">
        <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
          Máquinas
        </h3>
        <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
          {region
            ? `Mostrando só a região ${region}. Os números do topo continuam sendo do sistema inteiro.`
            : "Todas as máquinas registradas. Uma máquina parada de responder fica marcada como sem resposta."}
        </p>

        <div className="filter-rail" style={{ marginBottom: "var(--sp-4)" }}>
          {[{ value: "", label: "Todas" }, ...regions.map((name) => ({ value: name, label: name }))].map((option) => (
            <Chip
              key={option.value || "all"}
              active={region === option.value}
              onClick={() => {
                setRegion(option.value)
                void fetchWorkers(option.value)
              }}
            >
              {option.label}
            </Chip>
          ))}
        </div>

        {loading && workers.length === 0 && !error && (
          <div className="job-list">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-[78px] w-full" />
            ))}
          </div>
        )}

        {!loading && !error && workers.length === 0 && (
          <EmptyState
            icon={<Icon name="i-server" size="lg" />}
            title={region ? "Nenhum worker nessa região" : "Nenhum worker registrado"}
            description={
              region
                ? "Troque o filtro para ver as outras regiões, ou registre uma máquina nessa região."
                : "Nenhuma máquina se apresentou ao sistema ainda. Sem worker, as cópias são processadas no próprio servidor."
            }
            action={region ? { label: "Ver todas as regiões", onClick: () => { setRegion(""); void fetchWorkers("") } } : undefined}
          />
        )}

        {workers.length > 0 && (
          <div className="job-list">
            {workers.map((worker) => {
              const free = Math.max(0, worker.capacity - worker.running)
              const state = workerState(worker)
              const open = expanded === worker.id
              const detailsId = `worker-details-${worker.id}`
              return (
                <article
                  key={worker.id}
                  className="job-row"
                  style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}
                >
                  <div className="job-meta">
                    <div className="od-row" style={{ "--od-gap": "8px" } as CSSProperties}>
                      <span className="job-url mono od-truncate" title={worker.id}>
                        {worker.id}
                      </span>
                      <Badge variant={state.variant} className="od-fixed" title={state.help}>
                        <span className="dot" aria-hidden="true" />
                        {state.label}
                      </Badge>
                    </div>
                    <span className="job-sub">
                      <span>{worker.region || "sem região"}</span>
                      <span aria-hidden="true">·</span>
                      <span>
                        {worker.running} de {worker.capacity} em uso
                      </span>
                      <span aria-hidden="true">·</span>
                      <span title={fullStamp(worker.last_seen)}>
                        {worker.alive ? `visto ${timeAgo(worker.last_seen)}` : `sem sinal desde ${timeAgo(worker.last_seen)}`}
                      </span>
                    </span>
                  </div>

                  <div className="job-actions">
                    <Button
                      variant="secondary"
                      size="sm"
                      aria-expanded={open}
                      aria-controls={open ? detailsId : undefined}
                      onClick={() => setExpanded(open ? null : worker.id)}
                    >
                      {open ? "Fechar" : "Detalhes"}
                    </Button>
                  </div>

                  {open && (
                    <dl className="kv" id={detailsId} style={{ gridColumn: "1 / -1" }}>
                      <dt>Situação</dt>
                      <dd>{state.label} — {state.help}</dd>
                      <dt>Região</dt>
                      <dd className="mono">{worker.region || "—"}</dd>
                      <dt>Capacidade</dt>
                      <dd>
                        {worker.capacity} {worker.capacity === 1 ? "execução ao mesmo tempo" : "execuções ao mesmo tempo"}
                      </dd>
                      <dt>Em uso</dt>
                      <dd>
                        {worker.running} em andamento · {free} {free === 1 ? "vaga livre" : "vagas livres"}
                      </dd>
                      <dt>Versão</dt>
                      <dd className="mono">{worker.version || "—"}</dd>
                      <dt>Etiquetas</dt>
                      <dd>{worker.tags.length > 0 ? worker.tags.join(", ") : "—"}</dd>
                      <dt>Registrada em</dt>
                      <dd>{fullStamp(worker.started_at)}</dd>
                      <dt>Último sinal de vida</dt>
                      <dd>{worker.last_seen ? fullStamp(worker.last_seen) : "nunca"}</dd>
                      <dt>Recebe novas cópias</dt>
                      <dd>{worker.enabled ? "sim" : "não"}</dd>
                    </dl>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
          Onde este site seria processado?
        </h3>
        <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
          Mostra qual máquina pegaria o trabalho de um site, em qual região e por quê. A escolha sai da região do site;
          se lá não houver máquina livre, o sistema usa outra e diz o motivo.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Endereço do site"
            placeholder="https://exemplo.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void handleAssign()}
            leftIcon={<Icon name="i-globe" size="sm" />}
            hint="O mesmo endereço que você usaria em Nova extração."
          />
          <Input
            label="Região (opcional)"
            placeholder="ex.: br"
            list="worker-regions"
            value={assignRegion}
            onChange={(e) => setAssignRegion(e.target.value)}
            hint="Em branco, a região vem do próprio site."
          />
        </div>

        <div className="od-row" style={{ marginTop: "var(--sp-4)" }}>
          <Button onClick={() => void handleAssign()} loading={assigning} disabled={!url.trim()}>
            <Icon name="i-target" size="sm" />
            Ver
          </Button>
        </div>

        {assignError && (
          <div className="od-stack" style={{ marginTop: "var(--sp-4)", "--od-gap": "4px" } as CSSProperties}>
            <p className="error-text">
              <Icon name="i-alert" size="sm" />
              Não foi possível descobrir onde este site seria processado.
            </p>
            <p className="hint">{assignError}</p>
          </div>
        )}

        {assignment && (
          <div className="od-stack" style={{ marginTop: "var(--sp-4)", "--od-gap": "6px" } as CSSProperties}>
            <div className="od-cluster" style={{ "--od-gap": "var(--sp-2)" } as CSSProperties}>
              <Badge variant={assignment.worker ? "success" : "warning"}>
                <span className="dot" aria-hidden="true" />
                {assignment.worker ? "Com worker" : "Sem worker livre"}
              </Badge>
              <span className="mono text-[var(--fs-13)] text-[var(--text-2)]">
                {assignment.worker ?? "processado no próprio servidor"}
              </span>
            </div>
            <p className="hint">
              Região: <span className="mono">{assignment.region || "—"}</span> · Motivo: {assignment.reason}
            </p>
            {!assignment.worker && (
              <p className="hint">
                Sem máquina livre, a cópia roda no próprio servidor até alguém registrar um worker.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, WorkerInfo, WorkerStats, DispatchPlanItem, DispatchResponse } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { timeAgo } from "@/lib/utils"
import { Spinner, SYM } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

function WorkersPage() {
  const t = useT()
  const toast = useToast()

  const [stats, setStats] = useState<WorkerStats | null>(null)
  const [workers, setWorkers] = useState<WorkerInfo[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [region, setRegion] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [siteUrl, setSiteUrl] = useState("")
  const [assignRegion, setAssignRegion] = useState("")
  const [assigning, setAssigning] = useState(false)

  // Dispatch state
  const [dispatchUrls, setDispatchUrls] = useState("")
  const [dispatchPlan, setDispatchPlan] = useState<DispatchPlanItem[] | null>(null)
  const [dispatchResult, setDispatchResult] = useState<DispatchResponse | null>(null)
  const [planning, setPlanning] = useState(false)
  const [dispatching, setDispatching] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.getWorkers(region || undefined)
      setStats(res.stats)
      setWorkers(res.workers)
      const regList = Object.keys(res.stats.by_region || {})
      setRegions(regList)
      if (regList.length > 0 && !assignRegion) {
        setAssignRegion(regList[0])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [region])

  const toggleWorker = async (w: WorkerInfo) => {
    toast(t("workers.keptByCluster").replace("{{id}}", w.id))
  }

  const handleAssign = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!siteUrl.trim() || !assignRegion) return
    setAssigning(true)
    try {
      await api.assignWorker(siteUrl.trim(), assignRegion)
      toast(t("workers.regionAssigned").replace("{{region}}", assignRegion).replace("{{url}}", siteUrl), "ok")
      setSiteUrl("")
    } catch (e) {
      toast(e instanceof Error ? e.message : t("workers.assignFailed"), "err")
    } finally {
      setAssigning(false)
    }
  }

  const handlePlanDispatch = async () => {
    const urls = dispatchUrls.split("\n").map((u) => u.trim()).filter(Boolean)
    if (!urls.length) return
    setPlanning(true)
    setDispatchPlan(null)
    try {
      const items: DispatchPlanItem[] = []
      for (const u of urls) {
        const plan = await api.getDispatchPlan(u)
        items.push(...plan)
      }
      setDispatchPlan(items)
      toast(t("workers.planReady"), "ok")
    } catch (e) {
      toast(e instanceof Error ? e.message : t("workers.planFailed"), "err")
    } finally {
      setPlanning(false)
    }
  }

  const handleExecuteDispatch = async () => {
    const urls = dispatchUrls.split("\n").map((u) => u.trim()).filter(Boolean)
    if (!urls.length) return
    setDispatching(true)
    try {
      const res = await api.dispatchJobs(urls)
      setDispatchResult(res)
      toast(t("workers.dispatchedOk").replace("{{count}}", String(res.results.length)), "ok")
    } catch (e) {
      toast(e instanceof Error ? e.message : t("workers.dispatchFailed"), "err")
    } finally {
      setDispatching(false)
    }
  }

  return (
    <>
      <div className="flex items-baseline justify-between">
        <div>
          <h1>{t("workers.title")}</h1>
          <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
            {t("workers.subtitle")}
          </span>
        </div>
        <button type="button" className="tui-btn" onClick={() => void load()}>
          {t("workers.refresh")}
        </button>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)", marginTop: "0.5lh" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("workers.readFailed")}: {error}</p>
        </div>
      )}

      {loading ? (
        <p className="empty"><Spinner /> {t("workers.checkingNodes")}</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1lh", marginTop: "0.5lh" }}>
          {/* Worker metrics */}
          <div className="tui-panel">
            <span className="tui-label">{t("workers.activeCapacity")}</span>
            <dl className="tui-kv">
              <dt>{t("workers.totalWorkers")}</dt>
              <dd>{stats?.workers ?? workers.length}</dd>
              <dt>{t("workers.aliveWorkers")}</dt>
              <dd style={{ color: "var(--ok)" }}>{stats?.alive ?? 0}</dd>
              <dt>{t("workers.slotCapacity")}</dt>
              <dd>{stats?.capacity ?? 0} {t("workers.concurrent")}</dd>
              <dt>{t("workers.runningJobs")}</dt>
              <dd style={{ color: "var(--warn)" }}>{stats?.running ?? 0}</dd>
            </dl>
          </div>

          {/* Region filter */}
          {regions.length > 0 && (
            <div className="filters">
              <span className="tui-label">{t("workers.filterByRegion")}</span>
              <div className="toggles" role="group" aria-label={t("workers.filterRegionAria")}>
                <button
                  type="button"
                  className="tgl"
                  aria-pressed={region === ""}
                  onClick={() => setRegion("")}
                >
                  {t("workers.all")}
                </button>
                {regions.map((r) => (
                  <button
                    key={r}
                    type="button"
                    className="tgl"
                    aria-pressed={region === r}
                    onClick={() => setRegion(r)}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Worker list */}
          <div>
            <span className="tui-label">{t("workers.registeredNodes").replace("{{count}}", String(workers.length))}</span>
            {workers.length === 0 ? (
              <p className="empty">{t("workers.noWorkers")}</p>
            ) : (
              <div className="rows" style={{ marginTop: "0.25lh" }}>
                {workers.map((w) => (
                  <div
                    key={w.id}
                    className="flex items-center justify-between"
                    style={{
                      borderBottom: "1px solid var(--line)",
                      padding: "0.5lh 0",
                    }}
                  >
                    <div className="flex flex-col gap-1">
                      <div className="flex items-baseline gap-2">
                        <span
                          style={{
                            color: w.alive ? "var(--ok)" : "var(--error)",
                            fontWeight: "bold",
                          }}
                        >
                          {w.alive ? SYM.ok : SYM.fail}
                        </span>
                        <span style={{ fontWeight: 500 }}>{w.id}</span>
                        <span style={{ color: "var(--fg-dim)", fontSize: 11 }}>
                          [{w.region || "global"}]
                        </span>
                      </div>
                      <span style={{ color: "var(--fg-muted)", fontSize: 12 }}>
                        {t("workers.capacity")}: {w.capacity} · {t("workers.runningJobsShort")}: {w.running} · {t("workers.lastSeen")}{" "}
                        {timeAgo(w.last_seen)}
                      </span>
                    </div>

                    <button
                      type="button"
                      className="tui-btn"
                      onClick={() => void toggleWorker(w)}
                      style={{ fontSize: 11 }}
                    >
                      {w.enabled ? t("workers.disable") : t("workers.enable")}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Assign region to a domain */}
          {regions.length > 0 && (
            <form onSubmit={handleAssign} className="tui-panel">
              <span className="tui-label">{t("workers.bindDomainRegion")}</span>
              <div className="flex gap-2 flex-wrap items-baseline" style={{ marginTop: "0.25lh" }}>
                <input
                  className="tui-input"
                  value={siteUrl}
                  placeholder={t("workers.sitePlaceholder")}
                  onChange={(e) => setSiteUrl(e.target.value)}
                  style={{ minWidth: "26ch" }}
                />
                <select
                  className="tui-select"
                  value={assignRegion}
                  onChange={(e) => setAssignRegion(e.target.value)}
                  style={{ width: "auto" }}
                >
                  {regions.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  className="tui-btn accent"
                  disabled={assigning || !siteUrl.trim()}
                >
                  {assigning ? <Spinner /> : t("workers.bind")}
                </button>
              </div>
            </form>
          )}

          {/* Multi-region dispatcher */}
          <div className="tui-panel" style={{ padding: "16px" }}>
            <span className="tui-label">{t("workers.dispatcherTitle")}</span>
            <p style={{ color: "var(--fg-dim)", fontSize: 12, margin: "6px 0 10px 0" }}>
              {t("workers.dispatcherDesc")}
            </p>

            <textarea
              className="tui-input w-full font-mono text-[11px] h-20 p-2 mb-2"
              placeholder="https://exemplo1.com&#10;https://exemplo2.com.br&#10;https://exemplo3.jp"
              value={dispatchUrls}
              onChange={(e) => setDispatchUrls(e.target.value)}
            />

            <div className="flex gap-2">
              <button
                type="button"
                className="tui-btn"
                onClick={handlePlanDispatch}
                disabled={planning || !dispatchUrls.trim()}
              >
                {planning ? <Spinner /> : t("workers.simulatePlan")}
              </button>
              <button
                type="button"
                className="tui-btn accent"
                onClick={handleExecuteDispatch}
                disabled={dispatching || !dispatchUrls.trim()}
              >
                {dispatching ? <Spinner /> : SYM.ok} {t("workers.dispatchBatch")}
              </button>
            </div>

            {/* Dispatch plan */}
            {dispatchPlan && (
              <div style={{ marginTop: "12px", borderTop: "1px solid var(--border)", paddingTop: "10px" }}>
                <span className="tui-label">{t("workers.planCalculated")}</span>
                <div className="space-y-1 font-mono text-[11px]" style={{ marginTop: "6px" }}>
                  {dispatchPlan.map((p, i) => (
                    <div key={i} className="flex justify-between p-1.5 bg-[var(--bg-panel)] border border-[var(--border)]">
                      <span className="truncate">{p.url}</span>
                      <span className="text-[var(--accent)] font-semibold shrink-0 ml-2">
                        ➔ {p.worker || t("workers.auto")} [{p.region || t("workers.default")}]
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Dispatch result */}
            {dispatchResult && (
              <div style={{ marginTop: "12px", borderTop: "1px solid var(--border)", paddingTop: "10px" }}>
                <span className="tui-label" style={{ color: "var(--ok)" }}>{t("workers.dispatchedTasks")}</span>
                <div className="space-y-1 font-mono text-[11px]" style={{ marginTop: "6px" }}>
                  {dispatchResult.results.map((r, i) => (
                    <div key={i} className="flex justify-between p-1.5 bg-[var(--bg-panel)] border border-[var(--ok)]">
                      <span className="truncate">{r.url}</span>
                      <span className="text-[var(--ok)] font-semibold shrink-0 ml-2">
                        {r.region} ({r.job_id || t("workers.sent")})
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/workers")({
  component: WorkersPage,
})

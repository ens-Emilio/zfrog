import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, WorkerInfo, WorkerStats, DispatchPlanItem, DispatchResponse } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { timeAgo } from "@/lib/utils"
import { Spinner } from "@/components/ui/tui"
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
      if (regList.length > 0 && !assignRegion) setAssignRegion(regList[0])
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
    <div className="zf-view">
      <div className="zf-head">
        <h1 className="zf-title">{t("workers.title")}</h1>
        <span className="zf-meta">{t("workers.subtitle")}</span>
        <span style={{ flex: 1 }} />
        <button type="button" className="zf-btn" onClick={() => void load()}>{t("workers.refresh")}</button>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)" }}>
          <div className="zf-panel-bd"><p style={{ color: "var(--error)", fontSize: "var(--fs-meta)" }}>✗ {t("workers.readFailed")}: {error}</p></div>
        </div>
      )}

      {loading ? (
        <p className="zf-meta"><Spinner /> {t("workers.checkingNodes")}</p>
      ) : (
        <div className="zf-stack">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "var(--s3)" }}>
            <div className="zf-stat"><span className="v">{stats?.workers ?? workers.length}</span><span className="l">{t("workers.totalWorkers")}</span></div>
            <div className="zf-stat"><span className="v" style={{ color: "var(--ok)" }}>{stats?.alive ?? 0}</span><span className="l">{t("workers.aliveWorkers")}</span></div>
            <div className="zf-stat"><span className="v">{stats?.capacity ?? 0}</span><span className="l">{t("workers.slotCapacity")}</span><span className="m">{t("workers.concurrent")}</span></div>
            <div className="zf-stat"><span className="v" style={{ color: "var(--warn)" }}>{stats?.running ?? 0}</span><span className="l">{t("workers.runningJobs")}</span></div>
          </div>

          {regions.length > 0 && (
            <div className="zf-filters">
              <span className="zf-label">{t("workers.filterByRegion")}</span>
              <div style={{ display: "flex", gap: "var(--s1)", flexWrap: "wrap" }} role="group" aria-label={t("workers.filterRegionAria")}>
                <button type="button" className="zf-pill" aria-pressed={region === ""} onClick={() => setRegion("")}>{t("workers.all")}</button>
                {regions.map((r) => (
                  <button key={r} type="button" className="zf-pill" aria-pressed={region === r} onClick={() => setRegion(r)}>{r}</button>
                ))}
              </div>
            </div>
          )}

          <div className="zf-panel">
            <div className="zf-panel-hd">
              <span className="zf-label">{t("workers.registeredNodes").replace("{{count}}", String(workers.length))}</span>
            </div>
            {workers.length === 0 ? (
              <div className="zf-panel-bd"><p className="zf-meta">{t("workers.noWorkers")}</p></div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="zf-table">
                  <thead><tr><th>status</th><th>id</th><th>região</th><th className="num-col">{t("workers.capacity")}</th><th className="num-col">rodando</th><th>visto</th><th></th></tr></thead>
                  <tbody>
                    {workers.map((w) => (
                      <tr key={w.id}>
                        <td><span className={`zf-dot ${w.alive ? "" : "zf-dot--err"}`} style={{ display: "inline-block" }} /></td>
                        <td style={{ fontWeight: 550 }}>{w.id}</td>
                        <td className="zf-micro">[{w.region || "global"}]</td>
                        <td className="num-col">{w.capacity}</td>
                        <td className="num-col">{w.running}</td>
                        <td className="zf-micro">{timeAgo(w.last_seen)}</td>
                        <td style={{ textAlign: "right" }}><button type="button" className="zf-btn" onClick={() => void toggleWorker(w)}>{w.enabled ? t("workers.disable") : t("workers.enable")}</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {regions.length > 0 && (
            <form onSubmit={handleAssign} className="zf-panel">
              <div className="zf-panel-hd"><span className="zf-label">{t("workers.bindDomainRegion")}</span></div>
              <div className="zf-panel-bd" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "end" }}>
                <label className="zf-field" style={{ flex: "1 1 260px" }}>
                  <span className="zf-label">{t("workers.sitePlaceholder")}</span>
                  <input className="zf-input" value={siteUrl} placeholder={t("workers.sitePlaceholder")} onChange={(e) => setSiteUrl(e.target.value)} />
                </label>
                <label className="zf-field" style={{ minWidth: 160 }}>
                  <span className="zf-label">região</span>
                  <select className="zf-input" value={assignRegion} onChange={(e) => setAssignRegion(e.target.value)}>
                    {regions.map((r) => (<option key={r} value={r}>{r}</option>))}
                  </select>
                </label>
                <button type="submit" className="zf-btn zf-btn--primary" disabled={assigning || !siteUrl.trim()}>{assigning ? <Spinner /> : t("workers.bind")}</button>
              </div>
            </form>
          )}

          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-label">{t("workers.dispatcherTitle")}</span></div>
            <div className="zf-panel-bd">
              <p className="zf-meta">{t("workers.dispatcherDesc")}</p>
              <label className="zf-field">
                <span className="zf-label">URLs (uma por linha)</span>
                <textarea className="zf-input" style={{ minHeight: 84, fontFamily: "var(--font-mono)", fontSize: "var(--fs-meta)" }} placeholder="https://exemplo1.com&#10;https://exemplo2.com.br" value={dispatchUrls} onChange={(e) => setDispatchUrls(e.target.value)} />
              </label>
              <div className="zf-row">
                <button type="button" className="zf-btn" onClick={handlePlanDispatch} disabled={planning || !dispatchUrls.trim()}>{planning ? <Spinner /> : t("workers.simulatePlan")}</button>
                <button type="button" className="zf-btn zf-btn--primary" onClick={handleExecuteDispatch} disabled={dispatching || !dispatchUrls.trim()}>{dispatching ? <Spinner /> : "✓"} {t("workers.dispatchBatch")}</button>
              </div>
              {dispatchPlan && (
                <div className="zf-panel" style={{ background: "var(--bg)" }}>
                  <div className="zf-panel-hd"><span className="zf-label">{t("workers.planCalculated")}</span></div>
                  <div className="zf-list">
                    {dispatchPlan.map((p, i) => (
                      <div key={i} style={{ justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: "var(--fs-meta)" }}>
                        <span className="truncate" style={{ minWidth: 0 }}>{p.url}</span>
                        <span className="zf-flag zf-flag--run" style={{ marginLeft: "var(--s3)", flex: "none" }}>→ {p.worker || t("workers.auto")} [{p.region || t("workers.default")}]</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {dispatchResult && (
                <div className="zf-panel" style={{ borderColor: "var(--ok)" }}>
                  <div className="zf-panel-hd"><span className="zf-label" style={{ color: "var(--ok)" }}>{t("workers.dispatchedTasks")}</span></div>
                  <div className="zf-list">
                    {dispatchResult.results.map((r, i) => (
                      <div key={i} style={{ justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: "var(--fs-meta)" }}>
                        <span className="truncate" style={{ minWidth: 0 }}>{r.url}</span>
                        <span className="zf-flag zf-flag--ok" style={{ marginLeft: "var(--s3)", flex: "none" }}>{r.region} ({r.job_id || t("workers.sent")})</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export const Route = createFileRoute("/workers")({
  component: WorkersPage,
})

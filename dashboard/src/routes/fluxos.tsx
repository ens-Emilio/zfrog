import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import {
  api,
  Schedule,
  Workflow,
  WorkflowRunResult,
  WorkflowStep,
} from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner } from "@/components/ui/tui"
import { useT, type I18nKey } from "@/lib/i18n"

const STEP_TYPES = [
  "probe",
  "clone",
  "summarize",
  "analyze",
  "extract",
  "compare",
  "pdf",
  "search",
  "commit",
] as const

type StepType = (typeof STEP_TYPES)[number]

const STEP_INFO: Record<StepType, { label: I18nKey; what: I18nKey }> = {
  probe: { label: "fluxos.stepProbe", what: "fluxos.stepProbeWhat" },
  clone: { label: "fluxos.stepClone", what: "fluxos.stepCloneWhat" },
  summarize: { label: "fluxos.stepSummarize", what: "fluxos.stepSummarizeWhat" },
  analyze: { label: "fluxos.stepAnalyze", what: "fluxos.stepAnalyzeWhat" },
  extract: { label: "fluxos.stepExtract", what: "fluxos.stepExtractWhat" },
  compare: { label: "fluxos.stepCompare", what: "fluxos.stepCompareWhat" },
  pdf: { label: "fluxos.stepPdf", what: "fluxos.stepPdfWhat" },
  search: { label: "fluxos.stepSearch", what: "fluxos.stepSearchWhat" },
  commit: { label: "fluxos.stepCommit", what: "fluxos.stepCommitWhat" },
}

function FluxosPage() {
  const t = useT()
  const toast = useToast()
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<"fluxos" | "novo" | "agendamentos">("fluxos")
  const [runningId, setRunningId] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<WorkflowRunResult | null>(null)
  const [name, setName] = useState("")
  const [desc, setDesc] = useState("")
  const [steps, setSteps] = useState<WorkflowStep[]>([
    { type: "probe", params: { url: "" } },
    { type: "clone", params: { url: "", mode: "jump" } },
  ])
  const [savingFlow, setSavingFlow] = useState(false)
  const [schedCron, setSchedCron] = useState("0 2 * * *")
  const [schedWorkflowId, setSchedWorkflowId] = useState("")
  const [savingSched, setSavingSched] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<{ type: "flow" | "sched"; id: string; name: string } | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [wList, sList] = await Promise.all([api.getWorkflows(), api.getSchedules()])
      setWorkflows(wList)
      setSchedules(sList)
      if (wList.length > 0 && !schedWorkflowId) setSchedWorkflowId(wList[0].id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const handleRun = async (wf: Workflow) => {
    setRunningId(wf.id)
    setRunResult(null)
    try {
      const result = await api.runWorkflow(wf.id)
      setRunResult(result)
      toast(`${wf.name} ${t("fluxos.runOkSuffix")}`)
    } catch (e) {
      toast(e instanceof Error ? e.message : t("fluxos.runFailed"), "err")
    } finally {
      setRunningId(null)
    }
  }

  const handleDelete = async () => {
    if (!confirmDelete) return
    const { type, id } = confirmDelete
    setConfirmDelete(null)
    try {
      if (type === "flow") { await api.deleteWorkflow(id); toast(t("fluxos.flowDeleted")) }
      else { await api.removeSchedule(id); toast(t("fluxos.schedCancelled")) }
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("fluxos.removeFailed"), "err")
    }
  }

  const handleSaveFlow = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSavingFlow(true)
    try {
      await api.saveWorkflow({ name: name.trim(), steps })
      toast(t("fluxos.flowCreated"))
      setName(""); setDesc(""); setActiveTab("fluxos")
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("fluxos.createFlowFailed"), "err")
    } finally { setSavingFlow(false) }
  }

  const handleSaveSched = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!schedWorkflowId || !schedCron.trim()) return
    setSavingSched(true)
    try {
      await api.addSchedule({ cron: schedCron.trim(), url: schedWorkflowId, mode: "jump", max_depth: 1 })
      toast(t("fluxos.schedRegistered"))
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("fluxos.createSchedFailed"), "err")
    } finally { setSavingSched(false) }
  }

  return (
    <div className="zf-view">
      <div className="zf-head">
        <h1 className="zf-title">{t("fluxos.title")}</h1>
        <span className="zf-meta">{workflows.length} {t("fluxos.flowsCount")} · {schedules.length} {t("fluxos.schedsCount")}</span>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)" }}><div className="zf-panel-bd"><p style={{ color: "var(--error)", fontSize: "var(--fs-meta)" }}>✗ {t("fluxos.error")}{error}</p></div></div>
      )}

      <div className="zf-tabs" role="tablist">
        <button type="button" className="zf-tab" aria-selected={activeTab === "fluxos"} onClick={() => setActiveTab("fluxos")}>{t("fluxos.tabSaved")} ({workflows.length})</button>
        <button type="button" className="zf-tab" aria-selected={activeTab === "novo"} onClick={() => setActiveTab("novo")}>{t("fluxos.tabNew")}</button>
        <button type="button" className="zf-tab" aria-selected={activeTab === "agendamentos"} onClick={() => setActiveTab("agendamentos")}>{t("fluxos.tabScheds")} ({schedules.length})</button>
      </div>

      {runResult && (
        <div className="zf-panel" style={{ borderColor: "var(--ok)" }}>
          <div className="zf-panel-hd"><span className="zf-label">✓ {t("fluxos.runResult")}</span><span className="zf-meta" style={{ marginLeft: "auto" }}>{runResult.steps.length} {t("fluxos.stepsDone")}</span></div>
          <div className="zf-list">
            {runResult.steps.map((st, i) => (
              <div key={i} style={{ justifyContent: "space-between" }}>
                <span className={`zf-flag ${st.status === "failed" ? "zf-flag--err" : "zf-flag--ok"}`}>{st.status === "failed" ? "✗" : "✓"}</span>
                <span style={{ fontWeight: 550 }}>{t("fluxos.step")} {i + 1} ({st.type})</span>
                <span className="zf-meta" style={{ marginLeft: "auto" }}>{st.detail || st.output || t("fluxos.ok")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === "fluxos" && (
        <div>
          {loading ? <p className="zf-meta"><Spinner /> {t("fluxos.loadingFlows")}</p>
          : workflows.length === 0 ? <p className="zf-meta">{t("fluxos.emptyFlowsPrefix")}<b>{t("fluxos.tabNew")}</b>{t("fluxos.emptyFlowsSuffix")}</p>
          : (
            <div className="zf-list" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
              {workflows.map((wf) => (
                <div key={wf.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <div className="zf-row" style={{ justifyContent: "space-between", width: "100%" }}>
                    <div className="zf-row">
                      <span style={{ fontWeight: 550 }}>{wf.name}</span>
                      <span className="zf-meta">({wf.steps.length} {t("fluxos.steps")})</span>
                    </div>
                    <div className="zf-row">
                      <button type="button" className="zf-btn zf-btn--primary" onClick={() => void handleRun(wf)} disabled={runningId === wf.id}>{runningId === wf.id ? <Spinner /> : t("fluxos.runBtn")}</button>
                      <button type="button" className="zf-btn" onClick={() => { const json = JSON.stringify(wf, null, 2); navigator.clipboard?.writeText(json); toast(t("fluxos.copied")) }}>{t("fluxos.exportBtn")}</button>
                      <button type="button" className="zf-btn zf-btn--danger" onClick={() => setConfirmDelete({ type: "flow", id: wf.id, name: wf.name })}>{t("fluxos.deleteBtn")}</button>
                    </div>
                  </div>
                  <div className="zf-chips" style={{ marginTop: "var(--s2)" }}>
                    {wf.steps.map((st, i) => (<span key={i} className="zf-chip" style={{ cursor: "default" }}>{i + 1}. {st.type}</span>))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "novo" && (
        <form onSubmit={handleSaveFlow} className="zf-panel">
          <div className="zf-panel-hd"><span className="zf-label">{t("fluxos.newFlowTitle")}</span></div>
          <div className="zf-panel-bd">
            <label className="zf-field" htmlFor="flow-name"><span className="zf-label">{t("fluxos.flowNameLabel")}</span><input id="flow-name" className="zf-input" value={name} placeholder={t("fluxos.flowNamePlaceholder")} onChange={(e) => setName(e.target.value)} required autoFocus /></label>
            <label className="zf-field" htmlFor="flow-desc"><span className="zf-label">{t("fluxos.flowDescLabel")}</span><input id="flow-desc" className="zf-input" value={desc} placeholder={t("fluxos.flowDescPlaceholder")} onChange={(e) => setDesc(e.target.value)} /></label>
            <div>
              <div className="zf-row" style={{ justifyContent: "space-between" }}>
                <span className="zf-label">{t("fluxos.steps")} ({steps.length})</span>
                <button type="button" className="zf-btn" onClick={() => setSteps([...steps, { type: "analyze", params: { url: "" } }])}>{t("fluxos.addStep")}</button>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)", marginTop: "var(--s3)" }}>
                {steps.map((step, idx) => (
                  <div key={idx} className="zf-panel" style={{ background: "var(--bg)" }}>
                    <div className="zf-panel-bd">
                      <div className="zf-row" style={{ justifyContent: "space-between" }}>
                        <div className="zf-row">
                          <span style={{ fontWeight: 550 }}>{t("fluxos.step")} {idx + 1}:</span>
                          <select className="zf-input" style={{ width: "auto" }} value={step.type} onChange={(e) => { const nextType = e.target.value as StepType; const nextSteps = [...steps]; nextSteps[idx] = { type: nextType, params: { url: "" } }; setSteps(nextSteps) }}>
                            {STEP_TYPES.map((ty) => (<option key={ty} value={ty}>{ty} ({t(STEP_INFO[ty].label)})</option>))}
                          </select>
                        </div>
                        {steps.length > 1 && <button type="button" className="zf-btn zf-btn--danger" onClick={() => setSteps(steps.filter((_, i) => i !== idx))}>{t("fluxos.stepRemove")}</button>}
                      </div>
                      <input className="zf-input" placeholder={t("fluxos.urlPlaceholder")} value={typeof step.params?.url === "string" ? step.params.url : ""} onChange={(e) => { const nextSteps = [...steps]; nextSteps[idx] = { ...step, params: { ...step.params, url: e.target.value } }; setSteps(nextSteps) }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="zf-row" style={{ justifyContent: "flex-end" }}>
              <button type="submit" className="zf-btn zf-btn--primary" disabled={savingFlow || !name.trim()}>{savingFlow ? <Spinner /> : t("fluxos.saveFlow")}</button>
              <button type="button" className="zf-btn" onClick={() => setActiveTab("fluxos")}>{t("fluxos.cancel")}</button>
            </div>
          </div>
        </form>
      )}

      {activeTab === "agendamentos" && (
        <div className="zf-stack">
          {workflows.length > 0 && (
            <form onSubmit={handleSaveSched} className="zf-panel">
              <div className="zf-panel-hd"><span className="zf-label">{t("fluxos.newSchedTitle")}</span></div>
              <div className="zf-panel-bd" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "end" }}>
                <label className="zf-field" style={{ minWidth: 200, flex: "1 1 auto" }}>
                  <span className="zf-label">workflow</span>
                  <select className="zf-input" value={schedWorkflowId} onChange={(e) => setSchedWorkflowId(e.target.value)}>{workflows.map((w) => (<option key={w.id} value={w.id}>{w.name}</option>))}</select>
                </label>
                <label className="zf-field"><span className="zf-label">cron</span><input className="zf-input" value={schedCron} placeholder={t("fluxos.cronPlaceholder")} onChange={(e) => setSchedCron(e.target.value)} style={{ width: "20ch" }} /></label>
                <button type="submit" className="zf-btn zf-btn--primary" disabled={savingSched}>{savingSched ? <Spinner /> : t("fluxos.schedBtn")}</button>
              </div>
            </form>
          )}
          {schedules.length === 0 ? <p className="zf-meta">{t("fluxos.emptyScheds")}</p> : (
            <div className="zf-list" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
              {schedules.map((sc) => (
                <div key={sc.id} style={{ justifyContent: "space-between" }}>
                  <span className="zf-dot" style={{ display: "inline-block" }} />
                  <span style={{ fontWeight: 550 }}>{sc.url}</span>
                  <span className="zf-meta">{t("fluxos.cronLabel")}<code>{sc.cron}</code></span>
                  <button type="button" className="zf-btn zf-btn--danger" onClick={() => setConfirmDelete({ type: "sched", id: sc.id, name: sc.url || sc.id })} style={{ marginLeft: "auto" }}>{t("fluxos.cancel")}</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {confirmDelete && (
        <dialog open className="zf-modal" onClose={() => setConfirmDelete(null)}>
          <div className="zf-modal-hd"><span style={{ fontWeight: 600 }}>{t("fluxos.confirmTitle")}</span><span className="zf-spacer" /><button type="button" className="zf-btn zf-btn--ghost" onClick={() => setConfirmDelete(null)}>✗</button></div>
          <div className="zf-modal-bd"><p>{t("fluxos.deleteBtn")} {confirmDelete.type === "flow" ? t("fluxos.deleteFlowWord") : t("fluxos.deleteSchedWord")} <b>{confirmDelete.name}</b>?</p></div>
          <div className="zf-modal-ft">
            <button type="button" className="zf-btn zf-btn--danger" onClick={() => void handleDelete()}>{t("fluxos.confirmDeleteBtn")}</button>
            <button type="button" className="zf-btn" onClick={() => setConfirmDelete(null)}>{t("fluxos.cancel")}</button>
          </div>
        </dialog>
      )}
    </div>
  )
}

export const Route = createFileRoute("/fluxos")({
  component: FluxosPage,
})

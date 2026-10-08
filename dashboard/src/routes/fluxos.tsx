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
import { Spinner, SYM, TuiModal } from "@/components/ui/tui"
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

  // Active run
  const [runningId, setRunningId] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<WorkflowRunResult | null>(null)

  // Flow creator
  const [name, setName] = useState("")
  const [desc, setDesc] = useState("")
  const [steps, setSteps] = useState<WorkflowStep[]>([
    { type: "probe", params: { url: "" } },
    { type: "clone", params: { url: "", mode: "jump" } },
  ])
  const [savingFlow, setSavingFlow] = useState(false)

  // Scheduler
  const [schedCron, setSchedCron] = useState("0 2 * * *")
  const [schedWorkflowId, setSchedWorkflowId] = useState("")
  const [savingSched, setSavingSched] = useState(false)

  const [confirmDelete, setConfirmDelete] = useState<{ type: "flow" | "sched"; id: string; name: string } | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [wList, sList] = await Promise.all([
        api.getWorkflows(),
        api.getSchedules(),
      ])
      setWorkflows(wList)
      setSchedules(sList)
      if (wList.length > 0 && !schedWorkflowId) {
        setSchedWorkflowId(wList[0].id)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

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
      if (type === "flow") {
        await api.deleteWorkflow(id)
        toast(t("fluxos.flowDeleted"))
      } else {
        await api.removeSchedule(id)
        toast(t("fluxos.schedCancelled"))
      }
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
      await api.saveWorkflow({
        name: name.trim(),
        steps,
      })
      toast(t("fluxos.flowCreated"))
      setName("")
      setDesc("")
      setActiveTab("fluxos")
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("fluxos.createFlowFailed"), "err")
    } finally {
      setSavingFlow(false)
    }
  }

  const handleSaveSched = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!schedWorkflowId || !schedCron.trim()) return
    setSavingSched(true)
    try {
      await api.addSchedule({
        cron: schedCron.trim(),
        url: schedWorkflowId,
        mode: "jump",
        max_depth: 1,
      })
      toast(t("fluxos.schedRegistered"))
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("fluxos.createSchedFailed"), "err")
    } finally {
      setSavingSched(false)
    }
  }

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("fluxos.title")}</h1>
        <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
          {workflows.length} {t("fluxos.flowsCount")} · {schedules.length} {t("fluxos.schedsCount")}
        </span>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("fluxos.error")}{error}</p>
        </div>
      )}

      {/* TUI tabs */}
      <div className="filters flex-wrap" style={{ gap: "1ch 1.5ch", marginTop: "0.5lh" }}>
        <div className="toggles">
          <button
            type="button"
            className="tgl"
            aria-pressed={activeTab === "fluxos"}
            onClick={() => setActiveTab("fluxos")}
          >
            {t("fluxos.tabSaved")} ({workflows.length})
          </button>
          <button
            type="button"
            className="tgl"
            aria-pressed={activeTab === "novo"}
            onClick={() => setActiveTab("novo")}
          >
            {t("fluxos.tabNew")}
          </button>
          <button
            type="button"
            className="tgl"
            aria-pressed={activeTab === "agendamentos"}
            onClick={() => setActiveTab("agendamentos")}
          >
            {t("fluxos.tabScheds")} ({schedules.length})
          </button>
        </div>
      </div>

      {/* Latest run result */}
      {runResult && (
        <div className="tui-panel" style={{ borderColor: "var(--ok)", marginTop: "0.5lh" }}>
          <div className="tui-panel-head">
            <span className="tui-label">{SYM.ok} {t("fluxos.runResult")}</span>
            <span style={{ fontSize: 12, color: "var(--fg-dim)" }}>
              {runResult.steps.length} {t("fluxos.stepsDone")}
            </span>
          </div>
          <div className="rows" style={{ marginTop: "0.25lh" }}>
            {runResult.steps.map((st, i) => (
              <div key={i} className="runrow" style={{ gridTemplateColumns: "2ch 16ch 1fr auto" }}>
                <span style={{ color: st.status === "failed" ? "var(--error)" : "var(--ok)" }}>
                  {st.status === "failed" ? SYM.fail : SYM.ok}
                </span>
                <span style={{ fontWeight: 500 }}>{t("fluxos.step")} {i + 1} ({st.type})</span>
                <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>{st.detail || st.output || t("fluxos.ok")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab: flow list */}
      {activeTab === "fluxos" && (
        <div style={{ marginTop: "0.5lh" }}>
          {loading ? (
            <p className="empty"><Spinner /> {t("fluxos.loadingFlows")}</p>
          ) : workflows.length === 0 ? (
            <p className="empty">
              {t("fluxos.emptyFlowsPrefix")}<b>{t("fluxos.tabNew")}</b>{t("fluxos.emptyFlowsSuffix")}
            </p>
          ) : (
            <div className="rows">
              {workflows.map((wf) => (
                <div
                  key={wf.id}
                  style={{
                    borderBottom: "1px solid var(--line)",
                    padding: "0.5lh 0",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.25lh",
                  }}
                >
                  <div className="flex items-baseline justify-between">
                    <div>
                      <span style={{ fontWeight: 500, color: "var(--fg)" }}>{wf.name}</span>
                      <span style={{ color: "var(--fg-dim)", fontSize: 12, marginLeft: "1ch" }}>
                        ({wf.steps.length} {t("fluxos.steps")})
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        className="tui-btn accent"
                        onClick={() => void handleRun(wf)}
                        disabled={runningId === wf.id}
                        style={{ fontSize: 11 }}
                      >
                        {runningId === wf.id ? <Spinner /> : t("fluxos.runBtn")}
                      </button>
                      <button
                        type="button"
                        className="tui-btn"
                        onClick={() => {
                          const json = JSON.stringify(wf, null, 2)
                          navigator.clipboard?.writeText(json)
                          toast(t("fluxos.copied"))
                        }}
                        style={{ fontSize: 11 }}
                      >
                        {t("fluxos.exportBtn")}
                      </button>
                      <button
                        type="button"
                        className="tui-btn danger"
                        onClick={() => setConfirmDelete({ type: "flow", id: wf.id, name: wf.name })}
                        style={{ fontSize: 11 }}
                      >
                        {t("fluxos.deleteBtn")}
                      </button>
                    </div>
                  </div>

                  <div className="tui-tags" style={{ marginTop: "0.125lh" }}>
                    {wf.steps.map((st, i) => (
                      <span key={i} className="tui-tag" style={{ cursor: "default" }}>
                        {i + 1}. {st.type}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab: new flow builder */}
      {activeTab === "novo" && (
        <form onSubmit={handleSaveFlow} className="tui-panel" style={{ marginTop: "0.5lh" }}>
          <span className="tui-label">{t("fluxos.newFlowTitle")}</span>
          <div className="tui-field" style={{ marginTop: "0.25lh" }}>
            <label className="tui-label" htmlFor="flow-name">{t("fluxos.flowNameLabel")}</label>
            <input
              id="flow-name"
              className="tui-input"
              value={name}
              placeholder={t("fluxos.flowNamePlaceholder")}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="tui-field">
            <label className="tui-label" htmlFor="flow-desc">{t("fluxos.flowDescLabel")}</label>
            <input
              id="flow-desc"
              className="tui-input"
              value={desc}
              placeholder={t("fluxos.flowDescPlaceholder")}
              onChange={(e) => setDesc(e.target.value)}
            />
          </div>

          {/* Steps */}
          <div style={{ marginTop: "0.5lh" }}>
            <div className="flex justify-between items-baseline">
              <span className="tui-label">{t("fluxos.steps")} ({steps.length})</span>
              <button
                type="button"
                className="tui-btn"
                onClick={() => setSteps([...steps, { type: "analyze", params: { url: "" } }])}
                style={{ fontSize: 11 }}
              >
                {t("fluxos.addStep")}
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.5lh", marginTop: "0.25lh" }}>
              {steps.map((step, idx) => (
                <div key={idx} className="tui-panel" style={{ margin: 0, padding: "0.5lh 1ch" }}>
                  <div className="flex justify-between items-baseline">
                    <div className="flex gap-2 items-baseline">
                      <span style={{ fontWeight: 500 }}>{t("fluxos.step")} {idx + 1}:</span>
                      <select
                        className="tui-select"
                        value={step.type}
                        onChange={(e) => {
                          const nextType = e.target.value as StepType
                          const nextSteps = [...steps]
                          nextSteps[idx] = { type: nextType, params: { url: "" } }
                          setSteps(nextSteps)
                        }}
                        style={{ width: "auto", padding: "0.1lh 0.75ch" }}
                      >
                        {STEP_TYPES.map((ty) => (
                          <option key={ty} value={ty}>
                            {ty} ({t(STEP_INFO[ty].label)})
                          </option>
                        ))}
                      </select>
                    </div>

                    {steps.length > 1 && (
                      <button
                        type="button"
                        className="tui-btn danger"
                        onClick={() => setSteps(steps.filter((_, i) => i !== idx))}
                        style={{ fontSize: 11 }}
                      >
                        {t("fluxos.stepRemove")}
                      </button>
                    )}
                  </div>

                  <div className="flex gap-2 items-baseline" style={{ marginTop: "0.25lh" }}>
                    <input
                      className="tui-input"
                      placeholder={t("fluxos.urlPlaceholder")}
                      value={typeof step.params?.url === "string" ? step.params.url : ""}
                      onChange={(e) => {
                        const nextSteps = [...steps]
                        nextSteps[idx] = { ...step, params: { ...step.params, url: e.target.value } }
                        setSteps(nextSteps)
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2" style={{ marginTop: "1lh" }}>
            <button type="submit" className="tui-btn accent" disabled={savingFlow || !name.trim()}>
              {savingFlow ? <Spinner /> : t("fluxos.saveFlow")}
            </button>
            <button type="button" className="tui-btn" onClick={() => setActiveTab("fluxos")}>
              {t("fluxos.cancel")}
            </button>
          </div>
        </form>
      )}

      {/* Tab: schedules */}
      {activeTab === "agendamentos" && (
        <div style={{ marginTop: "0.5lh" }}>
          {workflows.length > 0 && (
            <form onSubmit={handleSaveSched} className="tui-panel" style={{ marginBottom: "0.75lh" }}>
              <span className="tui-label">{t("fluxos.newSchedTitle")}</span>
              <div className="flex gap-2 flex-wrap items-baseline" style={{ marginTop: "0.25lh" }}>
                <select
                  className="tui-select"
                  value={schedWorkflowId}
                  onChange={(e) => setSchedWorkflowId(e.target.value)}
                  style={{ minWidth: "24ch" }}
                >
                  {workflows.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </select>
                <input
                  className="tui-input"
                  value={schedCron}
                  placeholder={t("fluxos.cronPlaceholder")}
                  onChange={(e) => setSchedCron(e.target.value)}
                  style={{ width: "20ch" }}
                />
                <button type="submit" className="tui-btn accent" disabled={savingSched}>
                  {savingSched ? <Spinner /> : t("fluxos.schedBtn")}
                </button>
              </div>
            </form>
          )}

          {schedules.length === 0 ? (
            <p className="empty">{t("fluxos.emptyScheds")}</p>
          ) : (
            <div className="rows">
              {schedules.map((sc) => (
                <div key={sc.id} className="runrow" style={{ gridTemplateColumns: "2ch 24ch 1fr auto" }}>
                  <span style={{ color: "var(--ok)" }}>{SYM.ok}</span>
                  <span style={{ fontWeight: 500 }}>{sc.url}</span>
                  <span style={{ color: "var(--fg-dim)", fontFamily: "inherit" }}>
                    {t("fluxos.cronLabel")}<code>{sc.cron}</code>
                  </span>
                  <button
                    type="button"
                    className="tui-btn danger"
                    onClick={() => setConfirmDelete({ type: "sched", id: sc.id, name: sc.url || sc.id })}
                    style={{ fontSize: 11 }}
                  >
                    {t("fluxos.cancel")}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {confirmDelete && (
        <TuiModal open={true} title={t("fluxos.confirmTitle")} onClose={() => setConfirmDelete(null)}>
          <p>
            {t("fluxos.deleteBtn")} {confirmDelete.type === "flow" ? t("fluxos.deleteFlowWord") : t("fluxos.deleteSchedWord")} <b>{confirmDelete.name}</b>?
          </p>
          <div className="flex justify-end gap-2" style={{ marginTop: "0.5lh" }}>
            <button type="button" className="tui-btn danger" onClick={() => void handleDelete()}>
              {t("fluxos.confirmDeleteBtn")}
            </button>
            <button type="button" className="tui-btn" onClick={() => setConfirmDelete(null)}>
              {t("fluxos.cancel")}
            </button>
          </div>
        </TuiModal>
      )}
    </>
  )
}

export const Route = createFileRoute("/fluxos")({
  component: FluxosPage,
})

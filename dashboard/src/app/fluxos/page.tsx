"use client"
import { useEffect, useRef, useState } from "react"
import {
  api,
  JobMode,
  Schedule,
  Workflow,
  WorkflowStep,
  WorkflowRunResult,
  WorkflowPreview,
} from "@/lib/api"
import { MODES, MODE_ORDER, RECOMMENDED_MODES, ADVANCED_MODES } from "@/lib/labels"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Chip, ModeCard, Stepper } from "@/components/ui/ds"
import { Modal } from "@/components/ui/modal"
import { useToast } from "@/components/ToastRegion"
import { Icon, type IconName } from "@/lib/icons"
import { faviconLetter, formatStamp } from "@/lib/utils"
import { ArrowDown, ArrowUp, Trash2, X } from "lucide-react"

/** The step types the backend accepts, in the order they usually make sense. */
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

/** Editable parameter names a step can carry. */
type ParamKey = "url" | "mode" | "max_depth" | "pdf_filename" | "message"

const STEP_INFO: Record<StepType, { label: string; icon: IconName; what: string }> = {
  probe: { label: "Analisar site", icon: "i-search", what: "Descobre como o site é feito antes de baixar." },
  clone: { label: "Baixar site", icon: "i-download", what: "Baixa o site no modo escolhido." },
  summarize: { label: "Resumir com IA", icon: "i-file", what: "Escreve um resumo curto da página." },
  analyze: { label: "Auditar", icon: "i-activity", what: "Checa SEO, acessibilidade e desempenho." },
  extract: { label: "Extrair dados", icon: "i-layers", what: "Separa título, texto, links e imagens." },
  compare: { label: "Comparar fidelidade", icon: "i-rotate", what: "Mede o quanto a cópia ficou fiel ao original." },
  pdf: { label: "Gerar PDF", icon: "i-file-down", what: "Salva a página como um arquivo PDF." },
  search: { label: "Indexar para busca", icon: "i-database", what: "Deixa o que foi baixado pesquisável." },
  commit: { label: "Guardar versão", icon: "i-history", what: "Salva o resultado como uma versão no histórico." },
}

/** Which parameters each step type accepts (the backend rejects anything else). */
const STEP_FIELDS: Record<StepType, ParamKey[]> = {
  probe: ["url"],
  clone: ["url", "mode", "max_depth"],
  summarize: ["url"],
  analyze: ["url"],
  extract: ["url", "max_depth"],
  compare: ["url"],
  pdf: ["url", "pdf_filename"],
  search: [],
  commit: ["message"],
}

/** How a finished step is shown in the run log, using the design system levels. */
const RUN_STATUS: Record<string, { label: string; className: string }> = {
  ok: { label: "OK", className: "lvl-ok" },
  failed: { label: "FALHOU", className: "lvl-err" },
  skipped: { label: "PULADO", className: "lvl-warn" },
}

/** Narrows a stored step type to one the palette knows, so its fields can be looked up. */
function isStepType(value: string): value is StepType {
  return (STEP_TYPES as readonly string[]).includes(value)
}

/**
 * A step as the editor keeps it. `uid` is a local label so that dependencies
 * survive a reorder or a removal; the id sent to the API is always `step-<index>`.
 */
type BuilderStep = {
  uid: string
  type: string
  params: WorkflowStep["params"]
  needs: string[]
}

/** A step as the API accepts it: the shared type plus the fields the backend matches on. */
type ApiStep = WorkflowStep & { id: string; needs: string[] }

/** A step as it comes back from the API, which round-trips `id` and `needs`. */
type StoredStep = WorkflowStep & { id?: string; needs?: string[] }

let uidSeq = 0

/** Fresh local label for a step in the editor. Never sent anywhere. */
function nextUid(): string {
  uidSeq += 1
  return `s${uidSeq}`
}

/** A new step of `type`, pre-filled with the values that make it runnable. */
function newStep(type: StepType): BuilderStep {
  const params: WorkflowStep["params"] = {}
  if (type === "clone") params.mode = "auto"
  return { uid: nextUid(), type, params, needs: [] }
}

/**
 * Rebuild the editor state from steps the API returned. Stored ids (`step-0`,
 * `step-1`, …) are mapped to fresh local labels so a dependency keeps pointing
 * at the same step after the sequence is reordered.
 */
function toBuilderSteps(stored: StoredStep[]): BuilderStep[] {
  const steps: BuilderStep[] = stored.map((step) => ({
    uid: nextUid(),
    type: step.type,
    params: { ...step.params },
    needs: [],
  }))
  const idToUid = new Map<string, string>()
  stored.forEach((step, index) => {
    const id = step.id || `step-${index}`
    if (!idToUid.has(id)) idToUid.set(id, steps[index].uid)
  })
  stored.forEach((step, index) => {
    steps[index].needs = (step.needs ?? [])
      .map((id) => idToUid.get(id))
      .filter((uid): uid is string => Boolean(uid))
  })
  return steps
}

/**
 * Turn the builder state into what the API accepts: an id for every step
 * (`step-<index>`), only the parameters the step type allows, no blanks,
 * `max_depth` as a whole number, and dependencies as step ids.
 */
function buildSteps(steps: BuilderStep[]): { steps: ApiStep[]; problem: string | null } {
  const ids = steps.map((_, index) => `step-${index}`)
  const uidToId = new Map(steps.map((step, index) => [step.uid, ids[index]]))
  const built: ApiStep[] = []
  for (let index = 0; index < steps.length; index++) {
    const step = steps[index]
    const params: WorkflowStep["params"] = {}
    const allowed = isStepType(step.type) ? STEP_FIELDS[step.type] : []
    for (const key of allowed) {
      const raw = step.params[key]
      if (raw === undefined || raw === null || raw === "") continue
      if (key === "max_depth") {
        const depth = typeof raw === "number" ? raw : Number(String(raw).trim())
        if (!Number.isFinite(depth) || depth < 0) {
          return {
            steps: built,
            problem: `Passo ${index + 1}: informe um número de páginas igual ou maior que zero.`,
          }
        }
        params[key] = Math.floor(depth)
        continue
      }
      params[key] = raw
    }
    if (step.type === "probe" && !params.url) {
      return { steps: built, problem: `Passo ${index + 1} (analisar site): informe o endereço do site.` }
    }
    built.push({
      id: ids[index],
      type: step.type,
      params,
      needs: step.needs.map((uid) => uidToId.get(uid)).filter((id): id is string => Boolean(id)),
    })
  }
  return { steps: built, problem: null }
}

/** One-line description of a saved flow, derived from the steps it actually has. */
function describeWorkflow(workflow: Workflow): string {
  if (workflow.steps.length === 0) {
    return "Sem passos ainda. Abra o fluxo para montar a sequência."
  }
  const labels = workflow.steps.map((step) => (isStepType(step.type) ? STEP_INFO[step.type].label : step.type))
  return `${workflow.steps.length} passo(s): ${labels.join(" → ")}.`
}

/** The stored step types, in order, the way the list shows them. */
function stepChain(workflow: Workflow): string {
  return workflow.steps.map((step) => step.type).join(" → ") || "sem passos"
}

/** Host of a URL, or the raw value when it cannot be parsed. */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

/** How many leading steps of a run finished well — the position the stepper marks. */
function completedLeadingSteps(result: WorkflowRunResult | null): number | null {
  if (!result || result.steps.length === 0) return null
  let done = 0
  for (const step of result.steps) {
    if (step.status !== "ok") break
    done += 1
  }
  return done
}

export default function FluxosPage() {
  const toast = useToast()
  const nameRef = useRef<HTMLInputElement>(null)

  const [steps, setSteps] = useState<BuilderStep[]>([])
  const [name, setName] = useState("")
  /** The step whose panel is open in the accordion; only one at a time. */
  const [openStep, setOpenStep] = useState<string | null>(null)

  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedName, setSavedName] = useState<string | null>(null)
  const [loadedId, setLoadedId] = useState<string | null>(null)

  const [runningId, setRunningId] = useState<string | null>(null)
  const [runWorkflowId, setRunWorkflowId] = useState<string | null>(null)
  const [runSignature, setRunSignature] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<WorkflowRunResult | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  const [deleting, setDeleting] = useState<Workflow | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)

  const [preview, setPreview] = useState<WorkflowPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  /** A sequência exata que foi pré-visualizada, para avisar quando ela mudar depois. */
  const [previewSignature, setPreviewSignature] = useState<string | null>(null)

  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [schedulesLoading, setSchedulesLoading] = useState(true)
  const [schedulesError, setSchedulesError] = useState<string | null>(null)
  const [schedCron, setSchedCron] = useState("0 8 * * *")
  const [schedUrl, setSchedUrl] = useState("")
  const [schedMode, setSchedMode] = useState<JobMode>("auto")
  const [schedDepth, setSchedDepth] = useState("3")
  const [schedSaving, setSchedSaving] = useState(false)
  const [schedFormError, setSchedFormError] = useState<string | null>(null)
  const [schedRunningId, setSchedRunningId] = useState<string | null>(null)
  const [schedRemoving, setSchedRemoving] = useState<Schedule | null>(null)
  const [schedRemovingId, setSchedRemovingId] = useState<string | null>(null)

  const fetchWorkflows = async () => {
    setListLoading(true)
    setListError(null)
    try {
      setWorkflows(await api.getWorkflows())
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e))
    } finally {
      setListLoading(false)
    }
  }

  const fetchSchedules = async () => {
    setSchedulesLoading(true)
    setSchedulesError(null)
    try {
      setSchedules(await api.getSchedules())
    } catch (e) {
      setSchedulesError(e instanceof Error ? e.message : String(e))
    } finally {
      setSchedulesLoading(false)
    }
  }

  useEffect(() => {
    fetchWorkflows()
    fetchSchedules()
  }, [])

  const addStep = (type: StepType) => {
    const created = newStep(type)
    setSteps((current) => [...current, created])
    setOpenStep(created.uid)
    setSavedName(null)
    setLoadedId(null)
  }

  const moveStep = (index: number, delta: number) => {
    setSteps((current) => {
      const target = index + delta
      if (target < 0 || target >= current.length) return current
      const next = [...current]
      const [moved] = next.splice(index, 1)
      next.splice(target, 0, moved)
      return next
    })
  }

  const removeStep = (index: number) => {
    setSteps((current) => {
      const removed = current[index]
      return current
        .filter((_, i) => i !== index)
        .map((step) =>
          step.needs.includes(removed.uid)
            ? { ...step, needs: step.needs.filter((uid) => uid !== removed.uid) }
            : step
        )
    })
  }

  /** Adds or removes a dependency on another step of the sequence. */
  const toggleNeed = (index: number, uid: string) => {
    setSteps((current) =>
      current.map((step, i) => {
        if (i !== index) return step
        const needs = step.needs.includes(uid)
          ? step.needs.filter((value) => value !== uid)
          : [...step.needs, uid]
        return { ...step, needs }
      })
    )
  }

  const updateParam = (index: number, key: ParamKey, value: string) => {
    setSteps((current) =>
      current.map((step, i) => {
        if (i !== index) return step
        const params = { ...step.params }
        if (value === "") {
          delete params[key]
        } else if (key === "max_depth") {
          const depth = Number(value)
          params[key] = Number.isFinite(depth) ? depth : value
        } else {
          params[key] = value
        }
        return { ...step, params }
      })
    )
  }

  const handleSave = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setSaveError("Dê um nome ao fluxo antes de salvar.")
      return
    }
    if (steps.length === 0) {
      setSaveError("Adicione pelo menos um passo ao fluxo.")
      return
    }
    const built = buildSteps(steps)
    if (built.problem) {
      setSaveError(built.problem)
      return
    }

    setSaving(true)
    setSaveError(null)
    setSavedName(null)
    try {
      const workflow = await api.saveWorkflow({ name: trimmed, steps: built.steps })
      setSteps(toBuilderSteps(workflow.steps))
      setName(workflow.name)
      setLoadedId(workflow.id)
      setSavedName(workflow.name)
      toast(`Fluxo “${workflow.name}” salvo.`)
      await fetchWorkflows()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleLoad = (workflow: Workflow) => {
    setSteps(toBuilderSteps(workflow.steps))
    setName(workflow.name)
    setLoadedId(workflow.id)
    setSavedName(null)
    setSaveError(null)
    setRunResult(null)
    setRunError(null)
    setOpenStep(null)
  }

  const handleRun = async (workflow: Workflow) => {
    setRunningId(workflow.id)
    setRunWorkflowId(workflow.id)
    setRunSignature(JSON.stringify(buildSteps(toBuilderSteps(workflow.steps)).steps))
    setRunResult(null)
    setRunError(null)
    try {
      const result = await api.runWorkflow(workflow.id)
      setRunResult(result)
      toast(
        result.status === "ok" ? `Fluxo “${workflow.name}” concluído.` : `Fluxo “${workflow.name}” terminou com falha.`,
        result.status === "ok" ? "ok" : "err"
      )
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e))
      toast("Não foi possível executar o fluxo.", "err")
    } finally {
      setRunningId(null)
    }
  }

  const handleDelete = async (workflow: Workflow) => {
    setRemovingId(workflow.id)
    setListError(null)
    try {
      await api.deleteWorkflow(workflow.id)
      if (loadedId === workflow.id) setLoadedId(null)
      if (runWorkflowId === workflow.id) setRunWorkflowId(null)
      toast(`Fluxo “${workflow.name}” excluído.`)
      await fetchWorkflows()
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e))
    } finally {
      setRemovingId(null)
    }
  }

  const handleAddSchedule = async () => {
    const cron = schedCron.trim()
    const url = schedUrl.trim()
    if (!cron) {
      setSchedFormError("Informe a frequência no formato cron de 5 campos.")
      return
    }
    if (!url) {
      setSchedFormError("Informe o endereço do site que deve ser capturado.")
      return
    }
    const depth = Number(schedDepth.trim() === "" ? "3" : schedDepth)
    if (!Number.isFinite(depth) || depth < 0) {
      setSchedFormError("Informe um número de páginas igual ou maior que zero.")
      return
    }

    setSchedSaving(true)
    setSchedFormError(null)
    try {
      const created = await api.addSchedule({ cron, url, mode: schedMode, max_depth: Math.floor(depth) })
      setSchedules((current) => [...current, created])
      setSchedUrl("")
      toast("Agendamento criado.")
      await fetchSchedules()
    } catch (e) {
      setSchedFormError(e instanceof Error ? e.message : String(e))
    } finally {
      setSchedSaving(false)
    }
  }

  const handleRunSchedule = async (schedule: Schedule) => {
    setSchedRunningId(schedule.id)
    setSchedulesError(null)
    try {
      const { job_id } = await api.runSchedule(schedule.id)
      toast(`Captura iniciada (${job_id}).`)
    } catch (e) {
      setSchedulesError(e instanceof Error ? e.message : String(e))
    } finally {
      setSchedRunningId(null)
    }
  }

  const handleRemoveSchedule = async (schedule: Schedule) => {
    setSchedRemovingId(schedule.id)
    setSchedulesError(null)
    try {
      await api.removeSchedule(schedule.id)
      setSchedules((current) => current.filter((item) => item.id !== schedule.id))
      toast("Agendamento removido.")
      await fetchSchedules()
    } catch (e) {
      setSchedulesError(e instanceof Error ? e.message : String(e))
    } finally {
      setSchedRemovingId(null)
    }
  }

  /**
   * Pede ao servidor o que a sequência atual vai fazer, passo a passo. Os
   * mesmos passos que seriam salvos são enviados, então os avisos valem para
   * aquilo que você está montando agora.
   */
  const handlePreview = async () => {
    const built = buildSteps(steps)
    if (built.problem) {
      setPreview(null)
      setPreviewSignature(null)
      setPreviewError(built.problem)
      return
    }
    setPreviewLoading(true)
    setPreviewError(null)
    try {
      const result = await api.previewWorkflow(built.steps)
      setPreview(result)
      setPreviewSignature(JSON.stringify(built.steps))
    } catch (e) {
      setPreview(null)
      setPreviewSignature(null)
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setPreviewLoading(false)
    }
  }

  const editorSignature = JSON.stringify(buildSteps(steps).steps)
  const previewOutdated = preview !== null && previewSignature !== editorSignature
  /** Quantos passos da sequência já terminaram na última execução desta mesma sequência. */
  const runStepsDone = runSignature === editorSignature ? completedLeadingSteps(runResult) : null
  const stepperCurrent = runStepsDone ?? -1
  return (
    <div className="view-grid">
      <Topbar
        title="Fluxos"
        description="Sequências de passos automáticas — por exemplo: analisar, baixar e guardar a versão. Um passo que depende de outro espera ele terminar; passos sem dependência entre si rodam ao mesmo tempo."
        action={
          <Button
            onClick={() => {
              void fetchWorkflows()
              void fetchSchedules()
            }}
            loading={listLoading || schedulesLoading}
            size="sm"
            variant="secondary"
          >
            <Icon name="i-refresh" size="sm" /> Atualizar
          </Button>
        }
      />

      <section aria-label="Fluxos salvos">
        <div className="section-head" style={{ marginBottom: "var(--sp-3)" }}>
          <h2 className="section-title">Fluxos salvos</h2>
          <span className="hint">
            {listLoading ? "Carregando…" : `${workflows.length} fluxo(s) salvo(s).`}
          </span>
        </div>
        {listError && (
          <Card>
            <CardContent>
              <p className="card-title">Não foi possível carregar os fluxos.</p>
              <p className="card-sub">{listError}</p>
              <Button size="sm" variant="secondary" onClick={() => void fetchWorkflows()}>
                <Icon name="i-refresh" size="sm" /> Tentar de novo
              </Button>
            </CardContent>
          </Card>
        )}
        {!listError && listLoading && (
          <div className="grid-cards" aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="card stack-sm">
                <Skeleton style={{ height: 18, width: "55%" }} />
                <Skeleton style={{ height: 14, width: "90%" }} />
                <Skeleton style={{ height: 12, width: "65%" }} />
                <div className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
                  <Skeleton style={{ height: 32, width: 76 }} />
                  <Skeleton style={{ height: 32, width: 130 }} />
                </div>
              </div>
            ))}
          </div>
        )}
        {!listError && !listLoading && workflows.length === 0 && (
          <EmptyState
            icon={<Icon name="i-repeat" size="lg" />}
            title="Nenhum fluxo salvo ainda"
            description="Monte uma sequência abaixo, dê um nome e clique em Salvar — ela aparece aqui como um cartão."
            action={{ label: "Montar meu primeiro fluxo", onClick: () => nameRef.current?.focus() }}
          />
        )}
        {!listError && !listLoading && workflows.length > 0 && (
          <div className="grid-cards">
            {workflows.map((workflow) => {
              const active = loadedId === workflow.id
              return (
                <article key={workflow.id} className="card stack-sm">
                  <div className="row-between">
                    <h3 className="card-title od-truncate">{workflow.name}</h3>
                    <Badge variant={active ? "accent" : "neutral"}>
                      {active ? <span className="dot" aria-hidden="true" /> : null}
                      {active ? "Aberto" : "Salvo"}
                    </Badge>
                  </div>
                  <p className="card-sub">{describeWorkflow(workflow)}</p>
                  <span className="hint mono">{stepChain(workflow)}</span>
                  <div className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
                    <Button size="sm" variant="secondary" onClick={() => handleLoad(workflow)}>
                      Abrir
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={runningId === workflow.id}
                      disabled={runningId !== null && runningId !== workflow.id}
                      onClick={() => void handleRun(workflow)}
                    >
                      {!runningId || runningId !== workflow.id ? <Icon name="i-play" size="sm" /> : null}
                      Executar agora
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={removingId === workflow.id}
                      disabled={runningId !== null}
                      onClick={() => setDeleting(workflow)}
                      aria-label={`Excluir o fluxo ${workflow.name}`}
                    >
                      <Trash2 className="ic ic-sm" aria-hidden="true" />
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>
      <Card>
        <CardHeader>
          <CardTitle>Montar fluxo</CardTitle>
          <CardDescription>
            Clique em um passo para acrescentá-lo ao fim da sequência. A ordem em que eles aparecem
            é a ordem em que começam quando não há dependência entre eles.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="filter-rail" role="group" aria-label="Passos disponíveis">
            {STEP_TYPES.map((type) => (
              <Chip key={type} onClick={() => addStep(type)} className="od-touch">
                <Icon name={STEP_INFO[type].icon} size="sm" /> {STEP_INFO[type].label}
              </Chip>
            ))}
          </div>
          <p className="hint">
            {steps.length === 0
              ? "Nenhum passo ainda. Escolha um passo acima para começar."
              : `${steps.length} passo(s). Um passo que depende de outro só começa depois que ele termina; passos sem dependência entre si rodam ao mesmo tempo.`}
          </p>

          {steps.length > 0 && (
            <div>
              <Stepper
                steps={steps.map((step, index) =>
                  isStepType(step.type) ? STEP_INFO[step.type].label : `Passo ${index + 1}`
                )}
                current={stepperCurrent}
              />
              <p className="hint" style={{ marginTop: "var(--sp-3)" }}>
                Fluxos encadeiam modos de extração com condições simples — construídos na tela Captura.
              </p>
            </div>
          )}

          {steps.length === 0 ? (
            <EmptyState
              icon={<Icon name="i-repeat" size="lg" />}
              title="Sequência vazia"
              description="Clique em um passo em Passos disponíveis para montar o fluxo."
            />
          ) : (
            <div className="stack-sm">
              {steps.map((step, index) => {
                const info = isStepType(step.type) ? STEP_INFO[step.type] : null
                const fields = isStepType(step.type) ? STEP_FIELDS[step.type] : []
                const open = openStep === step.uid
                return (
                  <div key={step.uid} className="accordion">
                    <button
                      type="button"
                      className="acc-trigger od-touch"
                      aria-expanded={open}
                      onClick={() => setOpenStep(open ? null : step.uid)}
                    >
                      <span className="badge badge-neutral">
                        passo {index + 1}
                      </span>
                      <Icon name={info?.icon ?? "i-repeat"} size="sm" />
                      <span className="od-truncate" style={{ fontWeight: 600 }}>
                        {info?.label ?? step.type}
                      </span>
                      <span className="hint mono od-nowrap">{step.type}</span>
                      {step.needs.length > 0 && (
                        <span className="badge badge-info">
                          <span className="dot" aria-hidden="true" />
                          espera {step.needs.length}
                        </span>
                      )}
                      <Icon name="i-chevron" size="sm" />
                    </button>
                    <div className="acc-panel" hidden={!open}>
                      <div className="stack-md">
                        <div className="row-between">
                          <span className="hint">{info?.what ?? "Passo do fluxo."}</span>
                          <span className="od-row" style={{ ["--od-gap" as string]: "4px" }}>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => moveStep(index, -1)}
                              disabled={index === 0}
                              aria-label={`Mover o passo ${index + 1} para cima`}
                            >
                              <ArrowUp className="ic ic-sm" aria-hidden="true" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => moveStep(index, 1)}
                              disabled={index === steps.length - 1}
                              aria-label={`Mover o passo ${index + 1} para baixo`}
                            >
                              <ArrowDown className="ic ic-sm" aria-hidden="true" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => removeStep(index)}
                              aria-label={`Remover o passo ${index + 1}`}
                            >
                              <X className="ic ic-sm" aria-hidden="true" />
                            </Button>
                          </span>
                        </div>

                        {fields.length === 0 ? (
                          <p className="hint">
                            Este passo não precisa de nenhuma informação sua — ele usa o que os
                            passos anteriores encontraram.
                          </p>
                        ) : (
                          <div className="od-grid" style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "12px" }}>
                            {fields.includes("url") && (
                              <Input
                                label="Endereço do site"
                                placeholder="https://exemplo.com.br"
                                value={String(step.params.url ?? "")}
                                onChange={(e) => updateParam(index, "url", e.target.value)}
                                hint="Em branco, usa o endereço do passo anterior."
                              />
                            )}
                            {fields.includes("max_depth") && (
                              <Input
                                label="Quantas páginas percorrer"
                                type="number"
                                min={0}
                                placeholder="3"
                                value={step.params.max_depth === undefined ? "" : String(step.params.max_depth)}
                                onChange={(e) => updateParam(index, "max_depth", e.target.value)}
                                hint="0 baixa só a página indicada. Em branco, o padrão é 3."
                              />
                            )}
                            {fields.includes("pdf_filename") && (
                              <Input
                                label="Nome do PDF"
                                placeholder="index"
                                value={String(step.params.pdf_filename ?? "")}
                                onChange={(e) => updateParam(index, "pdf_filename", e.target.value)}
                                hint="Opcional. Vira o nome do arquivo gerado."
                              />
                            )}
                            {fields.includes("message") && (
                              <Input
                                label="Mensagem da versão"
                                placeholder="cópia de setembro"
                                value={String(step.params.message ?? "")}
                                onChange={(e) => updateParam(index, "message", e.target.value)}
                                hint="Opcional. Aparece no histórico junto da versão."
                              />
                            )}
                          </div>
                        )}

                        {fields.includes("mode") && (
                          <div className="od-field" style={{ ["--od-gap" as string]: "8px" }}>
                            <span className="label" id={`mode-label-${step.uid}`}>
                              O que baixar
                            </span>
                            <div
                              className="mode-grid"
                              role="group"
                              aria-labelledby={`mode-label-${step.uid}`}
                            >
                              {RECOMMENDED_MODES.map((m) => (
                                <ModeCard
                                  key={m}
                                  active={String(step.params.mode ?? "auto") === m}
                                  icon={<Icon name={MODES[m].icon} />}
                                  label={MODES[m].label}
                                  onClick={() => updateParam(index, "mode", m)}
                                />
                              ))}
                            </div>
                            {ADVANCED_MODES.length > 0 && (
                              <Select
                                label="Mais modos"
                                value={ADVANCED_MODES.includes(String(step.params.mode ?? "") as JobMode) ? String(step.params.mode) : ""}
                                onChange={(value) => {
                                  if (value) updateParam(index, "mode", value)
                                }}
                                hint="Modos avançados para casos específicos."
                                placeholder="Usar um dos modos acima"
                                options={ADVANCED_MODES.map((m) => ({
                                  value: m,
                                  label: MODES[m].label,
                                  icon: MODES[m].icon,
                                }))}
                              />
                            )}
                            <p className="hint">{MODES[String(step.params.mode ?? "auto") as JobMode]?.what ?? ""}</p>
                          </div>
                        )}

                        <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
                          <span className="label">Depende de</span>
                          {steps.length < 2 ? (
                            <p className="hint">
                              Este é o único passo do fluxo, então não há de onde depender.
                            </p>
                          ) : (
                            <>
                              <div className="filter-rail">
                                {steps.map((other, otherIndex) =>
                                  otherIndex === index ? null : (
                                    <Chip
                                      key={other.uid}
                                      active={step.needs.includes(other.uid)}
                                      onClick={() => toggleNeed(index, other.uid)}
                                    >
                                      {step.needs.includes(other.uid) && <Icon name="i-check" size="sm" />}
                                      passo {otherIndex + 1}
                                    </Chip>
                                  )
                                )}
                              </div>
                              <span className="hint">
                                {step.needs.length === 0
                                  ? "Sem dependência: este passo pode rodar ao mesmo tempo que os outros."
                                  : "Este passo só começa depois que os passos marcados terminarem."}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div className="od-row-top" style={{ ["--od-gap" as string]: "12px" }}>
            <div className="od-fill">
              <Input
                ref={nameRef}
                label="Nome do fluxo"
                placeholder="ex.: backup diário do blog"
                value={name}
                onChange={(e) => setName(e.target.value)}
                hint="Salvar com um nome que já existe substitui o fluxo antigo."
              />
            </div>
            <Button
              onClick={() => void handleSave()}
              loading={saving}
              disabled={steps.length === 0 || !name.trim()}
              className="od-touch"
            >
              <Icon name="i-check" size="sm" /> Salvar
            </Button>
          </div>

          {saveError && (
            <div role="alert">
              <p className="card-title" style={{ color: "var(--danger)" }}>
                Não foi possível salvar.
              </p>
              <p className="card-sub">{saveError}</p>
            </div>
          )}

          {savedName && !saveError && (
            <p className="hint" role="status">
              Fluxo “{savedName}” salvo. Você já pode executá-lo na lista acima.
            </p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Pré-visualizar</CardTitle>
          <CardDescription>
            Mostra o que cada passo vai fazer antes de salvar ou executar, e aponta o que ainda
            falta — como um endereço de site em branco, ou um passo que precisa de outro que não
            está na sequência. Nada é baixado nem salvo aqui: é só uma conferida.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
            <Button onClick={() => void handlePreview()} loading={previewLoading} disabled={steps.length === 0}>
              <Icon name="i-eye" size="sm" /> Pré-visualizar
            </Button>
            {preview && (
              <span className="hint">{preview.total} passo(s) nesta sequência.</span>
            )}
          </div>

          {steps.length === 0 && (
            <p className="hint">
              Monte a sequência acima e clique em Pré-visualizar para ver o que vai acontecer.
            </p>
          )}

          {previewError && (
            <div role="alert">
              <p className="card-title" style={{ color: "var(--danger)" }}>
                Não foi possível pré-visualizar.
              </p>
              <p className="card-sub">{previewError}</p>
            </div>
          )}

          {preview && (
            <>
              {preview.warnings.length > 0 && (
                <div role="alert">
                  <p className="card-title" style={{ color: "var(--warning)" }}>
                    {preview.warnings.length} aviso(s) para conferir antes de rodar
                  </p>
                  <ul className="stack-sm" style={{ marginTop: "var(--sp-2)", paddingLeft: "var(--sp-4)", listStyle: "disc" }}>
                    {preview.warnings.map((warning, index) => (
                      <li key={index} className="card-sub">{warning}</li>
                    ))}
                  </ul>
                </div>
              )}

              {preview.steps.length === 0 ? (
                <p className="hint">Nenhum passo na sequência.</p>
              ) : (
                <div className="stack-sm">
                  {preview.steps.map((step, position) => {
                    const info = isStepType(step.type) ? STEP_INFO[step.type] : null
                    return (
                      <div key={`${step.type}-${position}`} className="od-field" style={{ ["--od-gap" as string]: "4px" }}>
                        <span className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
                          <span className="badge badge-neutral">passo {position + 1}</span>
                          <Icon name={info?.icon ?? "i-repeat"} size="sm" />
                          <span className="od-truncate" style={{ fontWeight: 600, fontSize: "var(--fs-13)" }}>
                            {info?.label ?? step.type}
                          </span>
                          {step.warnings.length > 0 && (
                            <span className="badge badge-warning">
                              <span className="dot" aria-hidden="true" />
                              {step.warnings.length} aviso(s)
                            </span>
                          )}
                        </span>
                        <p className="card-sub">{step.summary}</p>
                        {step.warnings.map((warning, index) => (
                          <p key={index} className="hint" style={{ color: "var(--warning)" }}>
                            {warning}
                          </p>
                        ))}
                      </div>
                    )
                  })}
                </div>
              )}

              {preview.steps.length > 0 && preview.warnings.length === 0 && (
                <p className="hint" role="status" style={{ color: "var(--success)" }}>
                  Nenhum problema encontrado: a sequência está pronta para salvar e executar.
                </p>
              )}

              {previewOutdated && (
                <p className="hint">
                  A sequência mudou depois desta pré-visualização. Clique em Pré-visualizar de
                  novo para atualizar os avisos.
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>
      {(runResult || runError || runningId) && (
        <Card>
          <CardHeader>
            <CardTitle>Resultado da execução</CardTitle>
            <CardDescription>
              {runningId
                ? "Rodando os passos… isso pode levar alguns minutos, dependendo do tamanho do site."
                : runResult
                  ? `Status geral: ${runResult.status === "ok" ? "concluído" : "com falha"}.`
                  : "Veja abaixo o que aconteceu."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {runError && (
              <div role="alert">
                <p className="card-title" style={{ color: "var(--danger)" }}>
                  Não foi possível executar o fluxo.
                </p>
                <p className="card-sub">{runError}</p>
              </div>
            )}

            {runResult?.error && (
              <div role="alert">
                <p className="card-title" style={{ color: "var(--danger)" }}>
                  O fluxo parou.
                </p>
                <p className="card-sub">{runResult.error}</p>
              </div>
            )}

            {runResult && runResult.steps.length === 0 && (
              <p className="hint">
                Nenhum passo chegou a rodar. Corrija a sequência e tente de novo.
              </p>
            )}

            {runResult && runResult.steps.length > 0 && (
              <div
                className="console"
                role="log"
                aria-label={`Resultado da execução do fluxo ${workflows.find((w) => w.id === runWorkflowId)?.name ?? ""}`}
              >
                {runResult.steps.map((step, index) => {
                  const info = isStepType(step.type) ? STEP_INFO[step.type] : null
                  const status = RUN_STATUS[step.status] ?? { label: step.status, className: "lvl-info" }
                  return (
                    <div key={`${step.type}-${index}`} className="line">
                      <span className="ts">{String(index + 1).padStart(2, "0")}</span>
                      <span className={`lvl ${status.className}`}>{status.label}</span>
                      <span>
                        {info?.label ?? step.type} — {step.detail}
                        {step.output && (
                          <>
                            <br />
                            <span className="mono">{step.output}</span>
                          </>
                        )}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Agendamentos</CardTitle>
          <CardDescription>
            Rode uma captura sozinha em horário fixo — sem montar um fluxo. Informe a frequência
            em cron de 5 campos (minuto hora dia mês dia-da-semana), o endereço e o modo.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="od-grid" style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "12px" }}>
            <Input
              label="Frequência (cron)"
              placeholder="0 8 * * *"
              value={schedCron}
              onChange={(e) => setSchedCron(e.target.value)}
              hint="“0 8 * * *” roda todo dia às 08:00."
              className="input-mono"
            />
            <Input
              label="Endereço do site"
              placeholder="https://exemplo.com.br"
              value={schedUrl}
              onChange={(e) => setSchedUrl(e.target.value)}
            />
            <Select
              label="Modo"
              value={schedMode}
              onChange={(value) => setSchedMode(value as JobMode)}
              options={MODE_ORDER.map((m) => ({
                value: m,
                label: MODES[m].label,
                icon: MODES[m].icon,
              }))}
            />
            <Input
              label="Quantas páginas percorrer"
              type="number"
              min={0}
              placeholder="3"
              value={schedDepth}
              onChange={(e) => setSchedDepth(e.target.value)}
              hint="0 baixa só a página indicada."
            />
          </div>
          <div className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
            <Button onClick={() => void handleAddSchedule()} loading={schedSaving} className="od-touch">
              <Icon name="i-plus" size="sm" /> Agendar captura
            </Button>
          </div>
          {schedFormError && (
            <p className="error-text" role="alert">{schedFormError}</p>
          )}

          {schedulesError && (
            <div role="alert">
              <p className="card-title" style={{ color: "var(--danger)" }}>
                Não foi possível carregar os agendamentos.
              </p>
              <p className="card-sub">{schedulesError}</p>
              <Button size="sm" variant="secondary" onClick={() => void fetchSchedules()}>
                <Icon name="i-refresh" size="sm" /> Tentar de novo
              </Button>
            </div>
          )}

          {schedulesLoading && !schedulesError && (
            <div className="stack-sm" aria-hidden="true">
              <Skeleton style={{ height: 56 }} />
              <Skeleton style={{ height: 56 }} />
            </div>
          )}

          {!schedulesLoading && !schedulesError && schedules.length === 0 && (
            <EmptyState
              icon={<Icon name="i-calendar" size="lg" />}
              title="Nenhum agendamento ainda"
              description="Crie o primeiro acima: escolha a frequência, o endereço e o modo."
            />
          )}

          {!schedulesLoading && !schedulesError && schedules.length > 0 && (
            <div className="job-list">
              {schedules.map((schedule) => (
                <div key={schedule.id} className="job-row">
                  <span className="job-favicon" aria-hidden="true">
                    {faviconLetter(hostOf(schedule.url))}
                  </span>
                  <div className="job-meta">
                    <span className="job-url od-truncate">{schedule.url}</span>
                    <span className="job-sub">
                      <Badge variant={schedule.enabled ? "success" : "neutral"}>
                        {schedule.enabled && <span className="dot" aria-hidden="true" />}
                        {schedule.enabled ? "Ativo" : "Pausado"}
                      </Badge>
                      <span className="mono">{schedule.cron}</span>
                      <span>{MODES[schedule.mode as JobMode]?.label ?? schedule.mode}</span>
                      {schedule.next_run && <span>próxima: {formatStamp(schedule.next_run)}</span>}
                    </span>
                  </div>
                  <div className="job-actions">
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={schedRunningId === schedule.id}
                      disabled={schedRunningId !== null && schedRunningId !== schedule.id}
                      onClick={() => void handleRunSchedule(schedule)}
                    >
                      <Icon name="i-play" size="sm" /> Executar agora
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={schedRemovingId === schedule.id}
                      onClick={() => setSchedRemoving(schedule)}
                      aria-label={`Remover o agendamento de ${schedule.url}`}
                    >
                      <Trash2 className="ic ic-sm" aria-hidden="true" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Modal
        open={deleting !== null}
        title={`Excluir o fluxo “${deleting?.name ?? ""}”?`}
        body="O fluxo some da lista e não pode ser recuperado. As execuções já feitas continuam guardadas."
        confirmLabel="Excluir"
        danger
        onConfirm={() => {
          const target = deleting
          setDeleting(null)
          if (target) void handleDelete(target)
        }}
        onClose={() => setDeleting(null)}
      />

      <Modal
        open={schedRemoving !== null}
        title="Remover este agendamento?"
        body={`A captura de ${schedRemoving?.url ?? ""} (${schedRemoving?.cron ?? ""}) deixa de rodar sozinha.`}
        confirmLabel="Remover"
        danger
        onConfirm={() => {
          const target = schedRemoving
          setSchedRemoving(null)
          if (target) void handleRemoveSchedule(target)
        }}
        onClose={() => setSchedRemoving(null)}
      />
    </div>
  )
}

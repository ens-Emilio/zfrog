"use client"
import { useEffect, useState } from "react"
import {
  api,
  Workflow,
  WorkflowStep,
  WorkflowRunResult,
  WorkflowPreview,
} from "@/lib/api"
import { MODES, MODE_ORDER } from "@/lib/labels"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Workflow as WorkflowIcon,
  Search,
  Download,
  FileText,
  BarChart3,
  Table,
  GitCompare,
  FileType,
  Database,
  Save,
  Play,
  Trash2,
  Plus,
  ArrowUp,
  ArrowDown,
  X,
  RefreshCw,
  Check,
  AlertTriangle,
  CircleSlash,
  Eye,
} from "lucide-react"

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

const STEP_INFO: Record<StepType, { label: string; icon: typeof Search; what: string }> = {
  probe: { label: "Analisar site", icon: Search, what: "Descobre como o site é feito antes de baixar." },
  clone: { label: "Baixar site", icon: Download, what: "Baixa o site no modo escolhido." },
  summarize: { label: "Resumir com IA", icon: FileText, what: "Escreve um resumo curto da página." },
  analyze: { label: "Auditar", icon: BarChart3, what: "Checa SEO, acessibilidade e desempenho." },
  extract: { label: "Extrair dados", icon: Table, what: "Separa título, texto, links e imagens." },
  compare: { label: "Comparar fidelidade", icon: GitCompare, what: "Mede o quanto a cópia ficou fiel ao original." },
  pdf: { label: "Gerar PDF", icon: FileType, what: "Salva a página como um arquivo PDF." },
  search: { label: "Indexar para busca", icon: Database, what: "Deixa o que foi baixado pesquisável." },
  commit: { label: "Guardar versão", icon: Save, what: "Salva o resultado como uma versão no histórico." },
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

const RUN_STATUS: Record<string, { label: string; className: string }> = {
  ok: { label: "Concluído", className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20" },
  failed: { label: "Falhou", className: "bg-red-500/10 text-red-600 dark:text-red-400 ring-red-500/20" },
  skipped: { label: "Pulado", className: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20" },
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

export default function FluxosPage() {
  const [steps, setSteps] = useState<BuilderStep[]>([])
  const [name, setName] = useState("")

  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedName, setSavedName] = useState<string | null>(null)
  const [loadedId, setLoadedId] = useState<string | null>(null)

  const [runningId, setRunningId] = useState<string | null>(null)
  const [runResult, setRunResult] = useState<WorkflowRunResult | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  const [removingId, setRemovingId] = useState<string | null>(null)

  const [preview, setPreview] = useState<WorkflowPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  /** A sequência exata que foi pré-visualizada, para avisar quando ela mudar depois. */
  const [previewSignature, setPreviewSignature] = useState<string | null>(null)

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

  useEffect(() => {
    fetchWorkflows()
  }, [])

  const addStep = (type: StepType) => {
    setSteps((current) => [...current, newStep(type)])
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
  }

  const handleRun = async (workflow: Workflow) => {
    setRunningId(workflow.id)
    setRunResult(null)
    setRunError(null)
    try {
      setRunResult(await api.runWorkflow(workflow.id))
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e))
    } finally {
      setRunningId(null)
    }
  }

  const handleDelete = async (workflow: Workflow) => {
    if (!confirm(`Excluir o fluxo “${workflow.name}”?`)) return
    setRemovingId(workflow.id)
    setListError(null)
    try {
      await api.deleteWorkflow(workflow.id)
      if (loadedId === workflow.id) setLoadedId(null)
      await fetchWorkflows()
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e))
    } finally {
      setRemovingId(null)
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

  const previewOutdated = preview !== null && previewSignature !== JSON.stringify(buildSteps(steps).steps)

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Fluxos"
        description="Um fluxo é uma sequência de passos salvos — por exemplo: analisar, baixar e guardar a versão. Um passo que depende de outro espera ele terminar; passos sem dependência entre si rodam ao mesmo tempo."
        action={
          <Button onClick={fetchWorkflows} loading={listLoading} size="sm" variant="outline">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plus className="h-4 w-4" /> Passos disponíveis
          </CardTitle>
          <CardDescription>
            Clique em um passo para acrescentá-lo ao fim da sequência. A ordem em que eles aparecem é a ordem em que
            começam quando não há dependência entre eles.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {STEP_TYPES.map((type) => {
              const info = STEP_INFO[type]
              const Icon = info.icon
              return (
                <button
                  key={type}
                  onClick={() => addStep(type)}
                  className="text-left rounded-[10px] border p-3 transition-all hover:bg-accent hover:border-primary/40"
                >
                  <div className="flex items-center gap-2 text-[13px] font-medium">
                    <Icon className="h-3.5 w-3.5 text-primary" /> {info.label}
                  </div>
                  <p className="text-[11.5px] text-muted-foreground mt-1 leading-snug">{info.what}</p>
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <WorkflowIcon className="h-4 w-4" /> Sua sequência
          </CardTitle>
          <CardDescription>
            {steps.length === 0
              ? "Nenhum passo ainda. Escolha um passo acima para começar."
              : `${steps.length} passo(s). Um passo que depende de outro só começa depois que ele termina; passos sem dependência entre si rodam ao mesmo tempo.`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {steps.length === 0 ? (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <WorkflowIcon className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
              <p className="text-[13px] text-muted-foreground">
                Clique em um passo em <strong className="text-foreground">Passos disponíveis</strong> para montar o
                fluxo.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {steps.map((step, index) => {
                const info = isStepType(step.type) ? STEP_INFO[step.type] : null
                const Icon = info?.icon ?? WorkflowIcon
                const fields = isStepType(step.type) ? STEP_FIELDS[step.type] : []
                return (
                  <div key={step.uid} className="rounded-[12px] border p-4 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="rounded-full bg-primary/10 text-primary text-[11.5px] font-semibold px-2.5 py-1 shrink-0 whitespace-nowrap">
                          passo {index + 1}
                        </span>
                        <Icon className="h-4 w-4 text-primary shrink-0" />
                        <span className="text-[13.5px] font-medium truncate">
                          {info?.label ?? step.type}
                        </span>
                        <span className="text-[11px] font-mono text-muted-foreground hidden sm:inline">
                          {step.type}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => moveStep(index, -1)}
                          disabled={index === 0}
                          title="Mover para cima"
                        >
                          <ArrowUp className="h-3.5 w-3.5" /> mover para cima
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => moveStep(index, 1)}
                          disabled={index === steps.length - 1}
                          title="Mover para baixo"
                        >
                          <ArrowDown className="h-3.5 w-3.5" /> mover para baixo
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => removeStep(index)} title="Remover">
                          <X className="h-3.5 w-3.5" /> remover
                        </Button>
                      </div>
                    </div>

                    {fields.length === 0 ? (
                      <p className="text-[12px] text-muted-foreground">
                        Este passo não precisa de nenhuma informação sua — ele usa o que os passos anteriores
                        encontraram.
                      </p>
                    ) : (
                      <div className="grid sm:grid-cols-2 gap-3">
                        {fields.includes("url") && (
                          <Input
                            label="Endereço do site"
                            placeholder="https://exemplo.com.br"
                            value={String(step.params.url ?? "")}
                            onChange={(e) => updateParam(index, "url", e.target.value)}
                            hint="Em branco, usa o endereço do passo anterior."
                          />
                        )}
                        {fields.includes("mode") && (
                          <div className="flex flex-col gap-1.5">
                            <label className="text-[12.5px] font-medium text-foreground/80">
                              O que baixar
                            </label>
                            <select
                              value={String(step.params.mode ?? "auto")}
                              onChange={(e) => updateParam(index, "mode", e.target.value)}
                              className="h-10 rounded-[12px] border border-input bg-background px-3 text-[14px]"
                            >
                              {MODE_ORDER.map((m) => (
                                <option key={m} value={m}>
                                  {MODES[m].icon} {MODES[m].label}
                                </option>
                              ))}
                            </select>
                          </div>
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

                    <div className="flex flex-col gap-1.5">
                      <span className="text-[12.5px] font-medium text-foreground/80">Depende de</span>
                      {steps.length < 2 ? (
                        <p className="text-[12px] text-muted-foreground">
                          Este é o único passo do fluxo, então não há de onde depender.
                        </p>
                      ) : (
                        <>
                          <div className="flex flex-wrap gap-1.5">
                            {steps.map((other, otherIndex) =>
                              otherIndex === index ? null : (
                                <button
                                  key={other.uid}
                                  type="button"
                                  onClick={() => toggleNeed(index, other.uid)}
                                  aria-pressed={step.needs.includes(other.uid)}
                                  className={`inline-flex items-center gap-1.5 rounded-[10px] border px-2.5 py-1 text-[12px] font-medium transition-all ${
                                    step.needs.includes(other.uid)
                                      ? "border-primary bg-primary/5 text-primary ring-1 ring-primary/20"
                                      : "text-muted-foreground hover:bg-accent"
                                  }`}
                                >
                                  {step.needs.includes(other.uid) && <Check className="h-3 w-3" />}
                                  passo {otherIndex + 1}
                                </button>
                              )
                            )}
                          </div>
                          <span className="text-[11.5px] text-muted-foreground">
                            {step.needs.length === 0
                              ? "Sem dependência: este passo pode rodar ao mesmo tempo que os outros."
                              : "Este passo só começa depois que os passos marcados terminarem."}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div className="flex flex-col sm:flex-row gap-2 sm:items-end pt-1">
            <div className="flex-1">
              <Input
                label="Nome do fluxo"
                placeholder="ex.: backup diário do blog"
                value={name}
                onChange={(e) => setName(e.target.value)}
                hint="Salvar com um nome que já existe substitui o fluxo antigo."
              />
            </div>
            <Button onClick={handleSave} loading={saving} disabled={steps.length === 0 || !name.trim()}>
              <Save className="h-4 w-4" /> Salvar
            </Button>
          </div>

          {saveError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível salvar.</p>
              <p className="mt-1">{saveError}</p>
            </div>
          )}

          {savedName && !saveError && (
            <div className="rounded-[12px] bg-emerald-500/10 border border-emerald-500/20 p-3 text-[13px] text-emerald-700 dark:text-emerald-400 flex items-center gap-2">
              <Check className="h-4 w-4 shrink-0" /> Fluxo “{savedName}” salvo. Você já pode executá-lo na lista
              abaixo.
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Eye className="h-4 w-4" /> Pré-visualizar
          </CardTitle>
          <CardDescription>
            Mostra o que cada passo vai fazer antes de salvar ou executar, e aponta o que ainda falta — como um
            endereço de site em branco, ou um passo que precisa de outro que não está na sequência. Nada é baixado
            nem salvo aqui: é só uma conferida.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={handlePreview} loading={previewLoading} disabled={steps.length === 0}>
              <Eye className="h-4 w-4" /> Pré-visualizar
            </Button>
            {preview && (
              <span className="text-[12.5px] text-muted-foreground">
                {preview.total} passo(s) nesta sequência.
              </span>
            )}
          </div>

          {steps.length === 0 && (
            <p className="text-[12.5px] text-muted-foreground">
              Monte a sequência acima e clique em Pré-visualizar para ver o que vai acontecer.
            </p>
          )}

          {previewError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível pré-visualizar.</p>
              <p className="mt-1">{previewError}</p>
            </div>
          )}

          {preview && (
            <>
              {preview.warnings.length > 0 && (
                <div className="rounded-[12px] bg-amber-500/10 border border-amber-500/20 p-3 text-[13px] text-amber-700 dark:text-amber-400">
                  <p className="flex items-center gap-1.5 font-medium">
                    <AlertTriangle className="h-3.5 w-3.5" /> {preview.warnings.length} aviso(s) para conferir antes de
                    rodar
                  </p>
                  <ul className="mt-1.5 list-disc pl-5 space-y-1">
                    {preview.warnings.map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}

              {preview.steps.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">Nenhum passo na sequência.</p>
              ) : (
                <div className="rounded-[12px] border divide-y">
                  {preview.steps.map((step, position) => {
                    const info = isStepType(step.type) ? STEP_INFO[step.type] : null
                    const Icon = info?.icon ?? WorkflowIcon
                    return (
                      <div key={`${step.type}-${position}`} className="px-4 py-3 space-y-1">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="rounded-full bg-primary/10 text-primary text-[11.5px] font-semibold px-2.5 py-1 shrink-0 whitespace-nowrap">
                            passo {position + 1}
                          </span>
                          <Icon className="h-3.5 w-3.5 text-primary shrink-0" />
                          <span className="text-[13px] font-medium truncate">{info?.label ?? step.type}</span>
                          {step.warnings.length > 0 && (
                            <span className="shrink-0 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-medium bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-1 ring-inset ring-amber-500/20">
                              <AlertTriangle className="h-3 w-3" /> {step.warnings.length}
                            </span>
                          )}
                        </div>
                        <p className="text-[12.5px] text-muted-foreground pl-6 break-words">{step.summary}</p>
                        {step.warnings.map((warning, index) => (
                          <p
                            key={index}
                            className="text-[12px] text-amber-700 dark:text-amber-400 pl-6 flex items-start gap-1.5"
                          >
                            <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                            <span>{warning}</span>
                          </p>
                        ))}
                      </div>
                    )
                  })}
                </div>
              )}

              {preview.steps.length > 0 && preview.warnings.length === 0 && (
                <p className="text-[12.5px] text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                  <Check className="h-3.5 w-3.5" /> Nenhum problema encontrado: a sequência está pronta para salvar e
                  executar.
                </p>
              )}

              {previewOutdated && (
                <p className="text-[12px] text-muted-foreground">
                  A sequência mudou depois desta pré-visualização. Clique em Pré-visualizar de novo para atualizar os
                  avisos.
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-4 w-4" /> Fluxos salvos
          </CardTitle>
          <CardDescription>
            Carregar traz o fluxo de volta para a sequência acima. Executar roda os passos agora, respeitando as
            dependências: quem depende espera, quem não depende roda ao mesmo tempo.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {listError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível carregar os fluxos.</p>
              <p className="mt-1">{listError}</p>
            </div>
          )}

          {!listLoading && !listError && workflows.length === 0 && (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <WorkflowIcon className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
              <p className="text-[13px] font-medium">Nenhum fluxo salvo ainda</p>
              <p className="text-[12.5px] text-muted-foreground mt-1">
                Monte uma sequência acima, dê um nome e clique em Salvar.
              </p>
            </div>
          )}

          {workflows.length > 0 && (
            <div className="rounded-[12px] border divide-y">
              {workflows.map((workflow) => (
                <div key={workflow.id} className="px-4 py-3 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[13.5px] font-medium truncate">
                        {workflow.name}
                        {loadedId === workflow.id && (
                          <span className="ml-2 rounded-full bg-primary/10 text-primary px-2 py-0.5 text-[10.5px] font-medium">
                            carregado
                          </span>
                        )}
                      </p>
                      <p className="text-[11.5px] text-muted-foreground font-mono truncate">
                        {workflow.steps.map((step) => step.type).join(" → ") || "sem passos"}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Button size="sm" variant="outline" onClick={() => handleLoad(workflow)}>
                        Carregar
                      </Button>
                      <Button
                        size="sm"
                        variant="primary"
                        loading={runningId === workflow.id}
                        disabled={runningId !== null && runningId !== workflow.id}
                        onClick={() => handleRun(workflow)}
                      >
                        <Play className="h-3.5 w-3.5" /> Executar
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={removingId === workflow.id}
                        onClick={() => handleDelete(workflow)}
                        title="Excluir"
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Excluir
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {(runResult || runError || runningId) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Play className="h-4 w-4" /> Resultado da execução
            </CardTitle>
            <CardDescription>
              {runningId
                ? "Rodando os passos… isso pode levar alguns minutos, dependendo do tamanho do site."
                : runResult
                  ? `Status geral: ${runResult.status === "ok" ? "concluído" : "com falha"}.`
                  : "Veja abaixo o que aconteceu."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {runError && (
              <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                <p className="font-medium">Não foi possível executar o fluxo.</p>
                <p className="mt-1">{runError}</p>
              </div>
            )}

            {runResult?.error && (
              <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                <p className="font-medium">O fluxo parou.</p>
                <p className="mt-1">{runResult.error}</p>
              </div>
            )}

            {runResult && runResult.steps.length === 0 && (
              <p className="text-[13px] text-muted-foreground">
                Nenhum passo chegou a rodar. Corrija a sequência e tente de novo.
              </p>
            )}

            {runResult && runResult.steps.length > 0 && (
              <div className="rounded-[12px] border divide-y">
                {runResult.steps.map((step, index) => {
                  const info = isStepType(step.type) ? STEP_INFO[step.type] : null
                  const status = RUN_STATUS[step.status] ?? {
                    label: step.status,
                    className: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20",
                  }
                  const Icon = info?.icon ?? (step.status === "skipped" ? CircleSlash : AlertTriangle)
                  return (
                    <div key={`${step.type}-${index}`} className="px-4 py-3 space-y-1">
                      <div className="flex items-center justify-between gap-3">
                        <span className="flex items-center gap-2 text-[13px] font-medium min-w-0">
                          <span className="text-[11.5px] text-muted-foreground font-mono shrink-0">
                            {index + 1}
                          </span>
                          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate">{info?.label ?? step.type}</span>
                        </span>
                        <span
                          className={`shrink-0 inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${status.className}`}
                        >
                          {status.label}
                        </span>
                      </div>
                      <p className="text-[12.5px] text-muted-foreground pl-6 break-words">{step.detail}</p>
                      {step.output && (
                        <p className="text-[11.5px] font-mono text-muted-foreground/80 pl-6 break-all">
                          {step.output}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

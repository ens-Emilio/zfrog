"use client"

import { useState } from "react"
import Link from "next/link"
import { api, JobMode, ProbeResult } from "@/lib/api"
import { ADVANCED_MODES, MODES, RECOMMENDED_MODES } from "@/lib/labels"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { ModeCard } from "@/components/ui/ds"
import { Icon } from "@/lib/icons"
import { useToast } from "@/components/ToastRegion"

const engineToMode: Record<ProbeResult["suggested_engine"], JobMode> = {
  wget: "mirror",
  playwright: "scrape",
  static_file: "singlepage",
}

/**
 * Modes that actually crawl beyond the given URL. `singlepage`/`extract` never
 * follow links, and `pdf`/`summarize` only ever read the root URL — offering a
 * depth field for those would be a control that does nothing.
 */
const MODES_WITH_DEPTH: JobMode[] = ["mirror", "scrape", "analyze", "compare", "ask", "delta"]

/** Same rule as the prototype: a full address with `https://` and a real host. */
function validateUrl(value: string): string {
  if (!value.trim()) return "Informe o endereço do site."
  const trimmed = value.trim()
  if (!/^https:\/\//i.test(trimmed)) return "Inclua o começo do endereço, por exemplo https://."
  try {
    const parsed = new URL(trimmed)
    if (!parsed.hostname || !parsed.hostname.includes(".")) return "Esse endereço não parece um site válido."
  } catch {
    return "Esse endereço não parece um site válido."
  }
  return ""
}

export default function ProbePage() {
  const toast = useToast()

  const [url, setUrl] = useState("")
  const [urlError, setUrlError] = useState("")

  const [probing, setProbing] = useState(false)
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null)
  const [probeError, setProbeError] = useState<string | null>(null)

  const [mode, setMode] = useState<JobMode>("auto")
  const [depth, setDepth] = useState(1)
  const [pdfName, setPdfName] = useState("")
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const [creating, setCreating] = useState(false)
  const [createdJob, setCreatedJob] = useState<string | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)

  const selected = MODES[mode]
  const depthApplies = MODES_WITH_DEPTH.includes(mode)

  const handleAnalyze = async () => {
    const problem = validateUrl(url)
    if (problem) {
      setUrlError(problem)
      toast("Corrija o endereço para continuar.", "err")
      return
    }
    setProbing(true)
    setProbeError(null)
    setProbeResult(null)
    try {
      const result = await api.probe(url.trim())
      setProbeResult(result)
      const recommended = engineToMode[result.suggested_engine] ?? "singlepage"
      setMode(recommended)
      toast(`Análise concluída: modo ${MODES[recommended].label} sugerido.`)
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : String(e))
    } finally {
      setProbing(false)
    }
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    const problem = validateUrl(url)
    if (problem) {
      setUrlError(problem)
      toast("Corrija o endereço para continuar.", "err")
      return
    }
    setCreating(true)
    setCreatedJob(null)
    setCreateError(null)
    try {
      const job = await api.createJob({
        url: url.trim(),
        mode,
        max_depth: depthApplies ? depth : 0,
        ...(mode === "pdf" && pdfName.trim() ? { pdf_filename: pdfName.trim() } : {}),
      })
      setCreatedJob(job.id)
      toast("Extração iniciada.")
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  const handleClear = () => {
    setUrl("")
    setUrlError("")
    setProbeResult(null)
    setProbeError(null)
    setMode("auto")
    setDepth(1)
    setPdfName("")
    setCreatedJob(null)
    setCreateError(null)
  }

  return (
    <div className="view-grid">
      <Topbar
        title="Nova extração"
        description="Baixar um site ou extrair dados"
        action={
          <Link href="/captura">
            <Button variant="secondary" size="sm" className="od-touch">
              <Icon name="i-target" size="sm" /> Escolher o que pegar na página
            </Button>
          </Link>
        }
      />

      <div className="two-col">
        <form className="card" onSubmit={handleSubmit} noValidate>
          <div className="od-field" style={{ "--od-gap": "6px" } as React.CSSProperties}>
            <label className="label" htmlFor="probe-url">
              Endereço do site
              <span className="req" aria-hidden="true">
                *
              </span>
            </label>
            <input
              id="probe-url"
              name="url"
              className="input input-mono"
              type="url"
              inputMode="url"
              autoComplete="url"
              required
              placeholder="https://exemplo.com/pagina"
              aria-describedby="probe-url-hint"
              aria-invalid={urlError ? true : undefined}
              value={url}
              onChange={(event) => {
                setUrl(event.target.value)
                if (urlError) setUrlError("")
              }}
              onBlur={() => setUrlError(validateUrl(url))}
            />
            <p className="hint" id="probe-url-hint">
              Endereço completo, incluindo o começo <span className="mono">https://</span>.
            </p>
            {urlError && (
              <p className="error-text" role="alert">
                <Icon name="i-alert" size="sm" />
                <span>{urlError}</span>
              </p>
            )}
          </div>

          <div className="od-row" style={{ "--od-gap": "12px", marginTop: "var(--sp-3)", flexWrap: "wrap" } as React.CSSProperties}>
            <Button type="button" variant="secondary" size="sm" onClick={handleAnalyze} loading={probing} disabled={!url.trim()}>
              <Icon name="i-search" size="sm" /> Analisar endereço
            </Button>
            <span className="hint">
              Opcional: descobre a tecnologia do site e já marca o modo que funciona melhor nele.
            </span>
          </div>

          {probing && (
            <div className="od-stack" style={{ "--od-gap": "8px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
              <Skeleton className="h-[18px] w-[180px]" />
              <Skeleton className="h-[64px]" />
            </div>
          )}

          {probeError && (
            <div className="od-stack" style={{ "--od-gap": "8px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
              <Badge variant="danger">
                <span className="dot" aria-hidden="true" />
                Não conseguimos analisar
              </Badge>
              <p className="card-sub">{probeError}</p>
              <p className="hint">
                Confira se o endereço está completo (com <span className="mono">https://</span>) e se o site responde
                publicamente.
              </p>
              <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
                <Button type="button" size="sm" onClick={handleAnalyze} loading={probing}>
                  Tentar de novo
                </Button>
              </div>
            </div>
          )}

          {probeResult && (
            <div className="od-stack" style={{ "--od-gap": "12px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
              <div className="row-between">
                <span className="label">Resultado da análise</span>
                <Badge variant="success">
                  <span className="dot" aria-hidden="true" />
                  Site acessível
                </Badge>
              </div>

              <div className="mode-summary">
                <span>
                  <strong>Modo recomendado: {MODES[engineToMode[probeResult.suggested_engine] ?? "singlepage"].label}</strong>{" "}
                  — {MODES[engineToMode[probeResult.suggested_engine] ?? "singlepage"].what}
                </span>
                <span className="mode-out">
                  Já marcamos este modo abaixo. É só clicar em Iniciar extração.
                </span>
              </div>

              <StatStrip columns={4}>
                <StatCard
                  label="Tecnologia"
                  value={probeResult.framework || "Site comum"}
                  trend={probeResult.is_spa ? "montado por JavaScript" : "HTML pronto no servidor"}
                />
                <StatCard
                  label="Navegador necessário"
                  value={probeResult.suggested_engine === "playwright" ? "Sim" : "Não"}
                  trend={probeResult.has_js_rendering ? "o site precisa executar scripts" : "não precisa executar scripts"}
                />
                <StatCard label="Tipo de conteúdo" value={probeResult.content_type || "—"} />
                <StatCard
                  label="Resposta"
                  value={probeResult.status_code ?? "—"}
                  trend={probeResult.status_code === 200 ? "ok" : "resposta do servidor"}
                />
              </StatStrip>

              <p className="hint">
                robots.txt: {probeResult.robots_restricted ? "o site restringe parte do conteúdo" : "sem restrição declarada"}.
              </p>

              {probeResult.final_url && probeResult.final_url !== probeResult.url && (
                <p className="hint">
                  O endereço redireciona para <span className="mono break-all">{probeResult.final_url}</span>.
                </p>
              )}
            </div>
          )}

          <fieldset
            style={{ border: 0, padding: 0, margin: "var(--sp-5) 0 0" }}
            aria-labelledby="mode-legend"
          >
            <div className="row-between" style={{ marginBottom: "var(--sp-3)" }}>
              <span className="label" id="mode-legend">
                O que você quer fazer?
              </span>
              <span className="select-wrap" style={{ flex: "0 1 220px" }}>
                <select
                  className="select"
                  aria-label="Mais modos de extração"
                  value={ADVANCED_MODES.includes(mode) ? mode : ""}
                  onChange={(event) => {
                    const next = event.target.value as JobMode
                    if (next) setMode(next)
                  }}
                >
                  <option value="">Mais modos…</option>
                  {ADVANCED_MODES.map((id) => (
                    <option key={id} value={id}>
                      {MODES[id].label}
                    </option>
                  ))}
                </select>
                <Icon name="i-chevron" />
              </span>
            </div>

            <div className="mode-grid">
              {RECOMMENDED_MODES.map((id) => (
                <ModeCard
                  key={id}
                  active={mode === id}
                  label={MODES[id].label}
                  icon={<Icon name={MODES[id].icon} size="lg" />}
                  onClick={() => setMode(id)}
                />
              ))}
            </div>

            <div className="mode-summary" aria-live="polite" style={{ marginTop: "var(--sp-3)" }}>
              <span>
                <strong>{selected.label}</strong> — {selected.what}
              </span>
              <span className="mode-out">Você recebe: {selected.output}</span>
            </div>
          </fieldset>

          <div className="accordion" style={{ marginTop: "var(--sp-6)" }}>
            <button
              className="acc-trigger"
              type="button"
              aria-expanded={advancedOpen}
              aria-controls="adv-panel"
              onClick={() => setAdvancedOpen((open) => !open)}
            >
              <Icon name="i-sliders" />
              Opções avançadas
              <Icon name="i-chevron" />
            </button>
            <div className="acc-panel" id="adv-panel" hidden={!advancedOpen}>
              <div className="od-grid" style={{ "--od-cols": 2, "--od-gap": "16px" } as React.CSSProperties}>
                <div className="od-field" style={{ "--od-gap": "6px" } as React.CSSProperties}>
                  <label className="label" htmlFor="adv-depth">
                    Profundidade
                  </label>
                  <input
                    id="adv-depth"
                    className="input"
                    type="number"
                    min={0}
                    max={5}
                    value={depthApplies ? depth : 0}
                    disabled={!depthApplies}
                    onChange={(event) => setDepth(Math.max(0, Math.min(5, Number(event.target.value))))}
                  />
                  <span className="hint">
                    {depthApplies
                      ? "Quantos níveis de links seguir."
                      : `O modo ${selected.label} não segue links, então a profundidade não se aplica.`}
                  </span>
                </div>

                <div className="od-field" style={{ "--od-gap": "6px" } as React.CSSProperties}>
                  <label className="label" htmlFor="adv-limit">
                    Limite de páginas
                  </label>
                  <input
                    id="adv-limit"
                    className="input"
                    type="number"
                    min={1}
                    max={10000}
                    placeholder="Padrão do servidor"
                    disabled
                  />
                  <span className="hint">
                    Trava de segurança do download, definida no servidor. Esta tela ainda não envia esse valor.
                  </span>
                </div>

                <div className="od-field" style={{ "--od-gap": "6px" } as React.CSSProperties}>
                  <label className="label" htmlFor="adv-delay">
                    Pausa entre requisições (ms)
                  </label>
                  <input
                    id="adv-delay"
                    className="input"
                    type="number"
                    min={0}
                    step={100}
                    placeholder="Padrão do servidor"
                    disabled
                  />
                  <span className="hint">
                    Mais pausa é mais gentil com o site. Definida no servidor; esta tela ainda não envia esse valor.
                  </span>
                </div>

                <div className="od-field" style={{ "--od-gap": "6px" } as React.CSSProperties}>
                  <label className="label" htmlFor="adv-selector">
                    Seletor de conteúdo (opcional)
                  </label>
                  <input
                    id="adv-selector"
                    className="input input-mono"
                    placeholder="article.main-content"
                    disabled
                  />
                  <span className="hint">
                    Ainda não enviado pelo painel. Para escolher o que pegar clicando na página, use a tela{" "}
                    <Link href="/captura">Captura</Link>.
                  </span>
                </div>

                {mode === "pdf" && (
                  <div className="od-field" style={{ "--od-gap": "6px" } as React.CSSProperties}>
                    <label className="label" htmlFor="adv-pdf">
                      Nome do arquivo PDF (opcional)
                    </label>
                    <input
                      id="adv-pdf"
                      className="input input-mono"
                      placeholder="index"
                      value={pdfName}
                      onChange={(event) => setPdfName(event.target.value)}
                    />
                    <span className="hint">Vira o nome do PDF. Caracteres especiais são trocados por _.</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div
            className="od-row"
            style={{ "--od-gap": "12px", marginTop: "var(--sp-6)", flexWrap: "wrap" } as React.CSSProperties}
          >
            <Button type="submit" size="lg" loading={creating} className="od-touch">
              <Icon name="i-play" size="sm" /> Iniciar extração
            </Button>
            <Button type="button" variant="ghost" size="lg" className="od-touch" onClick={handleClear}>
              Limpar
            </Button>
          </div>

          {createError && (
            <div className="od-stack" style={{ "--od-gap": "8px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
              <Badge variant="danger">
                <span className="dot" aria-hidden="true" />
                Não foi possível iniciar
              </Badge>
              <p className="card-sub">{createError}</p>
              <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
                <Button type="submit" size="sm" loading={creating}>
                  Tentar de novo
                </Button>
              </div>
            </div>
          )}

          {createdJob && (
            <div className="od-stack" style={{ "--od-gap": "8px", marginTop: "var(--sp-4)" } as React.CSSProperties}>
              <Badge variant="success">
                <span className="dot" aria-hidden="true" />
                Extração iniciada
              </Badge>
              <p className="card-sub">
                Você pode acompanhar o andamento e baixar o resultado. Identificador:{" "}
                <span className="mono break-all">{createdJob}</span>
              </p>
              <div className="od-row" style={{ "--od-gap": "8px", flexWrap: "wrap" } as React.CSSProperties}>
                <Link href={`/jobs/${createdJob}`}>
                  <Button size="sm" className="od-touch">
                    Acompanhar
                  </Button>
                </Link>
                <Link href="/">
                  <Button size="sm" variant="secondary" className="od-touch">
                    Ver todas
                  </Button>
                </Link>
              </div>
            </div>
          )}
        </form>

        <aside className="stack-md">
          <div className="card">
            <h2 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
              Antes de começar
            </h2>
            <ul
              className="stack-sm"
              style={{ listStyle: "none", padding: 0, margin: 0, fontSize: "var(--fs-13)", color: "var(--text-2)" }}
            >
              <li className="od-row" style={{ "--od-gap": "8px", alignItems: "flex-start" } as React.CSSProperties}>
                <Icon name="i-check" size="sm" className="text-[var(--success)] mt-0.5" />
                <span>
                  Respeitamos o <span className="mono">robots.txt</span> por padrão.
                </span>
              </li>
              <li className="od-row" style={{ "--od-gap": "8px", alignItems: "flex-start" } as React.CSSProperties}>
                <Icon name="i-check" size="sm" className="text-[var(--success)] mt-0.5" />
                <span>A pausa entre requisições evita sobrecarregar o site.</span>
              </li>
              <li className="od-row" style={{ "--od-gap": "8px", alignItems: "flex-start" } as React.CSSProperties}>
                <Icon name="i-check" size="sm" className="text-[var(--success)] mt-0.5" />
                <span>Você pode cancelar a qualquer momento na tela da execução.</span>
              </li>
            </ul>
          </div>

          <div className="card">
            <h2 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Qual modo escolher?
            </h2>
            <p className="card-sub" style={{ marginBottom: "var(--sp-3)" }}>
              Não sabe a diferença entre os modos? O guia explica cada um em uma frase, incluindo o que você recebe no
              fim.
            </p>
            <Link href="/ajuda">
              <Button variant="secondary" size="sm" className="od-touch">
                <Icon name="i-book" size="sm" /> Ver o guia de modos
              </Button>
            </Link>
          </div>
        </aside>
      </div>
    </div>
  )
}

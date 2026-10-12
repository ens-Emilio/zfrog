import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, JobMode, ProbeResult } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT, type I18nKey } from "@/lib/i18n"
import { Spinner } from "@/components/ui/tui"

const engineToMode: Record<ProbeResult["suggested_engine"], JobMode> = {
  wget: "mirror",
  playwright: "scrape",
  static_file: "singlepage",
}

interface ModeDef {
  mode: JobMode
  short: string
  category: "visual" | "ai"
}

const MODES: ModeDef[] = [
  { mode: "jump", short: "jump", category: "visual" },
  { mode: "tongue", short: "tongue", category: "visual" },
  { mode: "auto", short: "auto", category: "visual" },
  { mode: "scrape", short: "scrape", category: "visual" },
  { mode: "mirror", short: "mirror", category: "visual" },
  { mode: "singlepage", short: "singlepage", category: "visual" },
  { mode: "pdf", short: "pdf", category: "visual" },
  { mode: "video", short: "video", category: "visual" },
  { mode: "summarize", short: "summarize", category: "ai" },
  { mode: "sentiment", short: "sentiment", category: "ai" },
  { mode: "translate", short: "translate", category: "ai" },
  { mode: "entities", short: "entities", category: "ai" },
  { mode: "tags", short: "tags", category: "ai" },
  { mode: "api_discovery", short: "api discovery", category: "ai" },
  { mode: "delta", short: "delta", category: "ai" },
]

function validateUrl(value: string, t: (k: I18nKey) => string): string {
  if (!value.trim()) return t("probe.urlRequired")
  const trimmed = value.trim()
  if (!/^https?:\/\//i.test(trimmed)) return t("probe.urlNeedScheme")
  try {
    const parsed = new URL(trimmed)
    if (!parsed.hostname || !parsed.hostname.includes(".")) return t("probe.urlIncomplete")
  } catch {
    return t("probe.urlInvalid")
  }
  return ""
}

function ProbePage() {
  const t = useT()
  const toast = useToast()
  const search = Route.useSearch()

  const [url, setUrl] = useState(search.url ?? "")
  const [urlError, setUrlError] = useState("")
  const [probing, setProbing] = useState(false)
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null)
  const [probeError, setProbeError] = useState<string | null>(null)
  const [mode, setMode] = useState<JobMode>("jump")
  const [depth, setDepth] = useState(1)
  const [pdfName, setPdfName] = useState("")
  const [selector, setSelector] = useState("")
  const [breakpointName, setBreakpointName] = useState("desktop")
  const [fullPage, setFullPage] = useState(true)
  const [imageFormat, setImageFormat] = useState("png")
  const [tags, setTags] = useState("")
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createdJob, setCreatedJob] = useState<string | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)

  useEffect(() => {
    if (search.url) setUrl(search.url)
  }, [search.url])

  const handleAnalyze = async () => {
    const problem = validateUrl(url, t)
    if (problem) {
      setUrlError(problem)
      toast(problem, "err")
      return
    }
    setProbing(true)
    setProbeError(null)
    setProbeResult(null)
    try {
      const result = await api.probe(url.trim())
      setProbeResult(result)
      setMode(engineToMode[result.suggested_engine] ?? "jump")
      toast(`${t("probe.probeDone")} ${engineToMode[result.suggested_engine] ?? "jump"}`, "ok")
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : String(e))
    } finally {
      setProbing(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const problem = validateUrl(url, t)
    if (problem) {
      setUrlError(problem)
      toast(problem, "err")
      return
    }
    if (mode === "tongue" && !selector.trim()) {
      toast(t("probe.selectorRequired"), "err")
      return
    }
    setCreating(true)
    setCreatedJob(null)
    setCreateError(null)
    try {
      const job = await api.createJob({
        url: url.trim(),
        mode,
        max_depth: depth,
        selector: selector.trim() || undefined,
        pdf_filename: pdfName.trim() || undefined,
        token_breakpoint: breakpointName,
        screenshot_full_page: fullPage,
        screenshot_format: imageFormat,
        card_tags: tags.split(",").map((v) => v.trim()).filter(Boolean),
      })
      setCreatedJob(job.id)
      toast(mode === "jump" ? t("probe.jumpStarted") : t("probe.genericStarted"), "ok")
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  const activeMode = MODES.find((m) => m.mode === mode) ?? MODES[0]

  return (
    <div className="zf-view">
      <div className="zf-head">
        <h1 className="zf-title">{t("probe.title")}</h1>
        <span className="zf-meta">{t("probe.modesAvailable")}</span>
      </div>
      <p className="zf-meta" style={{ marginBottom: "var(--s5)" }}>{t("probe.intro")}</p>

      {createdJob && (
        <div className="zf-panel" style={{ borderColor: "var(--ok)", marginBottom: "var(--s5)" }}>
          <div className="zf-panel-bd">
            <p style={{ color: "var(--ok)", fontSize: "var(--fs-meta)" }}>✓ {t("probe.jobCreated")} <code className="zf-code" style={{ padding: "0 4px" }}>{createdJob}</code></p>
            <div className="zf-row" style={{ marginTop: "var(--s3)" }}>
              <Link to="/" className="zf-btn" style={{ textDecoration: "none" }}>{t("probe.viewRuns")}</Link>
              {mode === "jump" && <Link to="/colecao" className="zf-btn" style={{ textDecoration: "none" }}>{t("probe.openLibrary")}</Link>}
              <button type="button" className="zf-btn zf-btn--ghost" onClick={() => setCreatedJob(null)}>{t("probe.captureAnother")}</button>
            </div>
          </div>
        </div>
      )}

      {createError && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", marginBottom: "var(--s5)" }}>
          <div className="zf-panel-bd">
            <p style={{ color: "var(--error)", fontSize: "var(--fs-meta)" }}>✗ {t("probe.createFailed")} {createError}</p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div id="probe-url" className="zf-panel" style={{ marginBottom: "var(--s5)" }}>
          <div className="zf-panel-hd">
            <label className="zf-label" htmlFor="probe-url-input">{t("probe.urlLabel")}</label>
          </div>
          <div className="zf-panel-bd">
            <div className="zf-row">
              <input
                id="probe-url-input"
                className="zf-input"
                type="text"
                value={url}
                placeholder="https://exemplo.com.br"
                onChange={(e) => { setUrl(e.target.value); if (urlError) setUrlError("") }}
                style={{ flex: 1 }}
                autoFocus
                aria-invalid={Boolean(urlError)}
              />
              <button type="button" className="zf-btn" onClick={() => void handleAnalyze()} disabled={probing || !url.trim()} title={t("probe.analyzeTitle")}>
                {probing ? <Spinner /> : t("probe.analyze")}
              </button>
            </div>
            {urlError && <span className="zf-hint zf-hint--error">{urlError}</span>}
          </div>
        </div>

        {probeResult && (
          <div className="zf-panel" style={{ marginBottom: "var(--s5)" }}>
            <div className="zf-panel-hd">
              <span className="zf-label">{t("probe.diagnosisTitle")}</span>
              <span className="zf-meta" style={{ marginLeft: "auto" }}>{t("probe.statusCode")} {probeResult.status_code ?? "200"} · {probeResult.content_type}</span>
            </div>
            <div className="zf-panel-bd">
              <dl className="zf-kv">
                <dt>{t("probe.suggestedMode")}</dt><dd style={{ color: "var(--accent)", fontWeight: 550 }}>{probeResult.suggested_engine} {t("probe.adjustedBelow")}</dd>
                <dt>{t("probe.finalUrl")}</dt><dd>{probeResult.final_url || probeResult.url}</dd>
                <dt>{t("probe.needsJs")}</dt><dd>{probeResult.is_spa ? t("probe.jsSpa") : probeResult.has_js_rendering ? t("probe.jsRendering") : t("probe.jsNo")}</dd>
                <dt>{t("probe.techDetected")}</dt><dd>{probeResult.framework || t("probe.techHtml")}</dd>
                <dt>{t("probe.accessPermission")}</dt><dd>{probeResult.robots_restricted ? t("probe.robotsRestricted") : t("probe.accessFree")}</dd>
              </dl>
            </div>
          </div>
        )}

        {probeError && <p className="zf-hint zf-hint--error" style={{ marginBottom: "var(--s4)" }}>✗ {t("probe.probeFailed")} {probeError}</p>}

        <div id="probe-modes" className="zf-panel" style={{ marginBottom: "var(--s5)" }}>
          <div className="zf-panel-hd"><span className="zf-label">{t("probe.visualSection")}</span></div>
          <div className="zf-panel-bd" style={{ gap: "var(--s3)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: "var(--s2)" }}>
              {MODES.filter((m) => m.category === "visual").map((m) => (
                <button key={m.mode} type="button" className="zf-btn" aria-pressed={mode === m.mode} onClick={() => setMode(m.mode)} style={mode === m.mode ? { background: "var(--accent-soft)", borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
                  {t(`probe.mode.${m.mode}.name` as I18nKey)}
                </button>
              ))}
            </div>
            <div className="zf-panel-hd" style={{ padding: "0", borderBottom: 0, marginTop: "var(--s2)" }}><span className="zf-label">{t("probe.aiSection")}</span></div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: "var(--s2)" }}>
              {MODES.filter((m) => m.category === "ai").map((m) => (
                <button key={m.mode} type="button" className="zf-btn" aria-pressed={mode === m.mode} onClick={() => setMode(m.mode)} style={mode === m.mode ? { background: "var(--accent-soft)", borderColor: "var(--accent)", color: "var(--accent)" } : undefined}>
                  {t(`probe.mode.${m.mode}.name` as I18nKey)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="zf-panel" style={{ marginBottom: "var(--s5)", background: "var(--bg)" }}>
          <div className="zf-panel-bd">
            <span style={{ fontWeight: 550 }}>{t("probe.activeMode")} <code className="zf-code" style={{ padding: "0 4px" }}>{activeMode.short}</code> — {t(`probe.mode.${activeMode.mode}.name` as I18nKey)}</span>
            <p className="zf-meta" style={{ marginTop: "var(--s2)" }}>{t(`probe.mode.${activeMode.mode}.desc` as I18nKey)}</p>
          </div>
        </div>

        <div id="probe-fields" style={{ display: "flex", flexDirection: "column", gap: "var(--s5)", marginBottom: "var(--s5)" }}>
          {mode === "jump" && (
            <div className="zf-panel">
              <div className="zf-panel-hd"><span className="zf-label">{t("probe.jump.settings")}</span></div>
              <div className="zf-panel-bd">
                <div className="zf-row">
                  <label className="zf-field" style={{ minWidth: 140 }}>
                    <span className="zf-label">{t("probe.jump.device")}</span>
                    <select className="zf-select" value={breakpointName} onChange={(e) => setBreakpointName(e.target.value)}>
                      <option value="desktop">{t("probe.jump.desktop")}</option>
                      <option value="tablet">{t("probe.jump.tablet")}</option>
                      <option value="mobile">{t("probe.jump.mobile")}</option>
                    </select>
                  </label>
                  <label className="zf-field" style={{ minWidth: 120 }}>
                    <span className="zf-label">{t("probe.jump.imageFormat")}</span>
                    <select className="zf-select" value={imageFormat} onChange={(e) => setImageFormat(e.target.value)}>
                      <option value="png">{t("probe.jump.png")}</option>
                      <option value="webp">{t("probe.jump.webp")}</option>
                    </select>
                  </label>
                  <label className="zf-field" style={{ minWidth: 140 }}>
                    <span className="zf-label">{t("probe.jump.shotSize")}</span>
                    <select className="zf-select" value={fullPage ? "true" : "false"} onChange={(e) => setFullPage(e.target.value === "true")}>
                      <option value="true">{t("probe.jump.fullPage")}</option>
                      <option value="false">{t("probe.jump.firstFold")}</option>
                    </select>
                  </label>
                </div>
                <label className="zf-field">
                  <span className="zf-label">{t("probe.jump.tagsLabel")}</span>
                  <input id="jump-tags" className="zf-input" value={tags} placeholder={t("probe.jump.tagsPlaceholder")} onChange={(e) => setTags(e.target.value)} />
                </label>
              </div>
            </div>
          )}

          {mode === "tongue" && (
            <div className="zf-panel">
              <div className="zf-panel-hd"><span className="zf-label">{t("probe.tongue.question")}</span></div>
              <div className="zf-panel-bd">
                <label className="zf-field">
                  <input className="zf-input" value={selector} placeholder={t("probe.tongue.selectorPlaceholder")} onChange={(e) => setSelector(e.target.value)} autoFocus />
                  <span className="zf-hint">{t("probe.tongue.hint")}</span>
                </label>
              </div>
            </div>
          )}

          {(mode === "mirror" || mode === "scrape" || mode === "auto") && (
            <label className="zf-field" style={{ maxWidth: 220 }}>
              <span className="zf-label">{t("probe.depthLabel")}</span>
              <input id="depth-input" type="number" min={1} max={5} className="zf-input" value={depth} onChange={(e) => setDepth(Number(e.target.value))} />
              <span className="zf-hint">{t("probe.depthHint")}</span>
            </label>
          )}

          {mode === "pdf" && (
            <label className="zf-field" style={{ maxWidth: 320 }}>
              <span className="zf-label">{t("probe.pdfNameLabel")}</span>
              <input id="pdf-name" className="zf-input" value={pdfName} placeholder="documento-pagina" onChange={(e) => setPdfName(e.target.value)} />
            </label>
          )}
        </div>

        <div style={{ marginBottom: "var(--s4)" }}>
          <button type="button" className="zf-btn zf-btn--ghost" onClick={() => setAdvancedOpen((v) => !v)}>{advancedOpen ? t("probe.tipsLess") : t("probe.tipsMore")}</button>
        </div>
        {advancedOpen && (
          <div className="zf-panel" style={{ marginBottom: "var(--s5)" }}>
            <div className="zf-panel-bd">
              <p className="zf-meta">{t("probe.tipsIntro")}</p>
              <p className="zf-meta" style={{ marginTop: "var(--s2)" }}><code className="zf-code" style={{ padding: "0 3px" }}>jump https://exemplo.com</code> {t("probe.tipsJump")} <code className="zf-code" style={{ padding: "0 3px" }}>tongue https://exemplo.com .hero</code> {t("probe.tipsTongue")}</p>
            </div>
          </div>
        )}

        <div className="zf-row">
          <button type="submit" className="zf-btn zf-btn--primary" disabled={creating || !url.trim()}>{creating ? <Spinner /> : t("probe.submit")}</button>
          <button type="button" className="zf-btn zf-btn--ghost" onClick={() => { setUrl(""); setProbeResult(null); setCreatedJob(null) }}>{t("probe.clear")}</button>
        </div>
      </form>
    </div>
  )
}

export const Route = createFileRoute("/probe")({
  validateSearch: (search: Record<string, unknown>): { url?: string } =>
    "url" in search && typeof search.url === "string" ? { url: search.url } : {},
  component: ProbePage,
})

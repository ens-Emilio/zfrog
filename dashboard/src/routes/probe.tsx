import { createFileRoute, Link } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, JobMode, ProbeResult } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT, type I18nKey } from "@/lib/i18n"
import { Spinner, SYM, TuiPanel } from "@/components/ui/tui"

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
  {
    mode: "jump",
    short: "jump",
    category: "visual",
  },
  {
    mode: "tongue",
    short: "tongue",
    category: "visual",
  },
  {
    mode: "auto",
    short: "auto",
    category: "visual",
  },
  {
    mode: "scrape",
    short: "scrape",
    category: "visual",
  },
  {
    mode: "mirror",
    short: "mirror",
    category: "visual",
  },
  {
    mode: "singlepage",
    short: "singlepage",
    category: "visual",
  },
  {
    mode: "pdf",
    short: "pdf",
    category: "visual",
  },
  {
    mode: "video",
    short: "video",
    category: "visual",
  },
  {
    mode: "summarize",
    short: "summarize",
    category: "ai",
  },
  {
    mode: "sentiment",
    short: "sentiment",
    category: "ai",
  },
  {
    mode: "translate",
    short: "translate",
    category: "ai",
  },
  {
    mode: "entities",
    short: "entities",
    category: "ai",
  },
  {
    mode: "tags",
    short: "tags",
    category: "ai",
  },
  {
    mode: "api_discovery",
    short: "api discovery",
    category: "ai",
  },
  {
    mode: "delta",
    short: "delta",
    category: "ai",
  },
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
    if (search.url) {
      setUrl(search.url)
    }
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
      const recommended = engineToMode[result.suggested_engine] ?? "jump"
      setMode(recommended)
      toast(`${t("probe.probeDone")} ${recommended}`, "ok")
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
        card_tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
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
    <div className="flex flex-col gap-3">
      <TuiPanel
        title={t("probe.title")}
        action={
          <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>
            {t("probe.modesAvailable")}
          </span>
        }
      >
        <p style={{ color: "var(--fg-muted)", fontSize: 13, marginBottom: "0.25lh" }}>
          {t("probe.intro")}
        </p>

        {createdJob && (
          <div className="tui-panel" style={{ borderColor: "var(--ok)", background: "var(--bg)", margin: "0.5lh 0" }}>
            <p style={{ color: "var(--ok)" }}>
              {SYM.ok} {t("probe.jobCreated")} <code>{createdJob}</code>
            </p>
            <div className="flex gap-2" style={{ marginTop: "0.5lh" }}>
              <Link to="/" className="tui-btn" style={{ textDecoration: "none" }}>
                {t("probe.viewRuns")}
              </Link>
              {mode === "jump" && (
                <Link to="/colecao" className="tui-btn" style={{ textDecoration: "none" }}>
                  {t("probe.openLibrary")}
                </Link>
              )}
              <button type="button" className="tui-btn" onClick={() => setCreatedJob(null)}>
                {t("probe.captureAnother")}
              </button>
            </div>
          </div>
        )}

        {createError && (
          <div className="tui-panel" style={{ borderColor: "var(--error)", margin: "0.5lh 0" }}>
            <p style={{ color: "var(--error)" }}>{SYM.fail} {t("probe.createFailed")} {createError}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ marginTop: "0.5lh" }}>
          {/* Main URL field */}
          <div className="tui-field">
            <label className="tui-label" htmlFor="probe-url">
              {t("probe.urlLabel")}
            </label>
            <div className="flex gap-1">
              <input
                id="probe-url"
                className="tui-input"
                type="text"
                value={url}
                placeholder="https://exemplo.com.br"
                onChange={(e) => {
                  setUrl(e.target.value)
                  if (urlError) setUrlError("")
                }}
                style={{ flex: 1 }}
                autoFocus
              />
              <button
                type="button"
                className="tui-btn"
                onClick={() => void handleAnalyze()}
                disabled={probing || !url.trim()}
                title={t("probe.analyzeTitle")}
              >
                {probing ? <Spinner /> : t("probe.analyze")}
              </button>
            </div>
            {urlError && <span style={{ color: "var(--error)", fontSize: 12 }}>{urlError}</span>}
          </div>

          {/* Diagnosis result */}
          {probeResult && (
            <div className="tui-panel" style={{ margin: "0.5lh 0" }}>
              <div className="tui-panel-head">
                <span className="tui-panel-title">{t("probe.diagnosisTitle")}</span>
                <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>
                  {t("probe.statusCode")} {probeResult.status_code ?? "200"} · {probeResult.content_type}
                </span>
              </div>
              <dl className="tui-kv" style={{ marginTop: "0.25lh" }}>
                <dt>{t("probe.suggestedMode")}</dt>
                <dd style={{ color: "var(--accent)", fontWeight: 500 }}>{probeResult.suggested_engine} {t("probe.adjustedBelow")}</dd>
                <dt>{t("probe.finalUrl")}</dt>
                <dd>{probeResult.final_url || probeResult.url}</dd>
                <dt>{t("probe.needsJs")}</dt>
                <dd>{probeResult.is_spa ? t("probe.jsSpa") : probeResult.has_js_rendering ? t("probe.jsRendering") : t("probe.jsNo")}</dd>
                <dt>{t("probe.techDetected")}</dt>
                <dd>{probeResult.framework || t("probe.techHtml")}</dd>
                <dt>{t("probe.accessPermission")}</dt>
                <dd>{probeResult.robots_restricted ? t("probe.robotsRestricted") : t("probe.accessFree")}</dd>
              </dl>
            </div>
          )}

          {probeError && (
            <p style={{ color: "var(--error)", fontSize: 12, margin: "0.25lh 0" }}>
              {SYM.fail} {t("probe.probeFailed")} {probeError}
            </p>
          )}

          {/* Categorized mode selection */}
          <div style={{ marginTop: "0.75lh" }}>
            <span className="tui-panel-title" style={{ fontSize: 12, display: "block", marginBottom: "0.25lh" }}>
              {t("probe.visualSection")}
            </span>
            <div className="tui-tags" style={{ marginBottom: "0.75lh" }}>
              {MODES.filter((m) => m.category === "visual").map((m) => (
                <button
                  key={m.mode}
                  type="button"
                  className={`tui-tag${mode === m.mode ? " active" : ""}`}
                  onClick={() => setMode(m.mode)}
                >
                  {t(`probe.mode.${m.mode}.name` as I18nKey)}
                </button>
              ))}
            </div>

            <span className="tui-panel-title" style={{ fontSize: 12, display: "block", marginBottom: "0.25lh" }}>
              {t("probe.aiSection")}
            </span>
            <div className="tui-tags">
              {MODES.filter((m) => m.category === "ai").map((m) => (
                <button
                  key={m.mode}
                  type="button"
                  className={`tui-tag${mode === m.mode ? " active" : ""}`}
                  onClick={() => setMode(m.mode)}
                >
                  {t(`probe.mode.${m.mode}.name` as I18nKey)}
                </button>
              ))}
            </div>
          </div>

          {/* Selected mode explainer box */}
          <div className="tui-panel" style={{ marginTop: "0.5lh", background: "var(--bg)" }}>
            <div className="flex items-baseline justify-between">
              <span className="font-semibold" style={{ color: "var(--fg)" }}>
                {t("probe.activeMode")} <code>{activeMode.short}</code> — {t(`probe.mode.${activeMode.mode}.name` as I18nKey)}
              </span>
            </div>
            <p style={{ color: "var(--fg-muted)", fontSize: 12, marginTop: "0.25lh" }}>
              {t(`probe.mode.${activeMode.mode}.desc` as I18nKey)}
            </p>
          </div>

          {/* Per-mode fields */}
          {mode === "jump" && (
            <div className="tui-panel" style={{ marginTop: "0.5lh" }}>
              <span className="tui-label">{t("probe.jump.settings")}</span>
              <div className="flex gap-3 flex-wrap" style={{ marginTop: "0.25lh" }}>
                <label className="flex items-center gap-1 text-[12px]">
                  {t("probe.jump.device")}
                  <select
                    className="tui-select"
                    value={breakpointName}
                    onChange={(e) => setBreakpointName(e.target.value)}
                    style={{ width: "auto" }}
                  >
                    <option value="desktop">{t("probe.jump.desktop")}</option>
                    <option value="tablet">{t("probe.jump.tablet")}</option>
                    <option value="mobile">{t("probe.jump.mobile")}</option>
                  </select>
                </label>

                <label className="flex items-center gap-1 text-[12px]">
                  {t("probe.jump.imageFormat")}
                  <select
                    className="tui-select"
                    value={imageFormat}
                    onChange={(e) => setImageFormat(e.target.value)}
                    style={{ width: "auto" }}
                  >
                    <option value="png">{t("probe.jump.png")}</option>
                    <option value="webp">{t("probe.jump.webp")}</option>
                  </select>
                </label>

                <label className="flex items-center gap-1 text-[12px]">
                  {t("probe.jump.shotSize")}
                  <select
                    className="tui-select"
                    value={fullPage ? "true" : "false"}
                    onChange={(e) => setFullPage(e.target.value === "true")}
                    style={{ width: "auto" }}
                  >
                    <option value="true">{t("probe.jump.fullPage")}</option>
                    <option value="false">{t("probe.jump.firstFold")}</option>
                  </select>
                </label>
              </div>

              <div className="tui-field" style={{ marginTop: "0.5lh" }}>
                <label className="tui-label" htmlFor="jump-tags">
                  {t("probe.jump.tagsLabel")}
                </label>
                <input
                  id="jump-tags"
                  className="tui-input"
                  value={tags}
                  placeholder={t("probe.jump.tagsPlaceholder")}
                  onChange={(e) => setTags(e.target.value)}
                />
              </div>
            </div>
          )}

          {mode === "tongue" && (
            <div className="tui-panel" style={{ marginTop: "0.5lh" }}>
              <span className="tui-label">{t("probe.tongue.question")}</span>
              <div className="tui-field" style={{ marginTop: "0.25lh" }}>
                <input
                  className="tui-input"
                  value={selector}
                  placeholder={t("probe.tongue.selectorPlaceholder")}
                  onChange={(e) => setSelector(e.target.value)}
                  autoFocus
                />
                <span className="tui-hint">
                  {t("probe.tongue.hint")}
                </span>
              </div>
            </div>
          )}

          {/* Depth for crawlers */}
          {(mode === "mirror" || mode === "scrape" || mode === "auto") && (
            <div className="tui-field" style={{ marginTop: "0.5lh" }}>
              <label className="tui-label" htmlFor="depth-input">
                {t("probe.depthLabel")}
              </label>
              <input
                id="depth-input"
                type="number"
                min={1}
                max={5}
                className="tui-input"
                value={depth}
                onChange={(e) => setDepth(Number(e.target.value))}
                style={{ width: "14ch" }}
              />
              <span className="tui-hint">{t("probe.depthHint")}</span>
            </div>
          )}

          {/* PDF name */}
          {mode === "pdf" && (
            <div className="tui-field" style={{ marginTop: "0.5lh" }}>
              <label className="tui-label" htmlFor="pdf-name">
                {t("probe.pdfNameLabel")}
              </label>
              <input
                id="pdf-name"
                className="tui-input"
                value={pdfName}
                placeholder="documento-pagina"
                onChange={(e) => setPdfName(e.target.value)}
                style={{ maxWidth: "32ch" }}
              />
            </div>
          )}

          {/* Advanced options toggle */}
          <div style={{ margin: "0.5lh 0" }}>
            <button
              type="button"
              className="tui-btn"
              onClick={() => setAdvancedOpen((v) => !v)}
              style={{ fontSize: 12 }}
            >
              {advancedOpen ? t("probe.tipsLess") : t("probe.tipsMore")}
            </button>
          </div>

          {advancedOpen && (
            <div className="tui-panel text-[12px]">
              <p style={{ color: "var(--fg-dim)" }}>
                {t("probe.tipsIntro")}
              </p>
              <p style={{ marginTop: "0.25lh" }}>
                <code>jump https://exemplo.com</code> {t("probe.tipsJump")} <code>tongue https://exemplo.com .hero</code> {t("probe.tipsTongue")}
              </p>
            </div>
          )}

          {/* Submit button */}
          <div className="flex gap-2" style={{ marginTop: "1lh" }}>
            <button
              type="submit"
              className="tui-btn"
              disabled={creating || !url.trim()}
              style={{ fontWeight: 500 }}
            >
              {creating ? <Spinner /> : t("probe.submit")}
            </button>
            <button
              type="button"
              className="tui-btn"
              onClick={() => {
                setUrl("")
                setProbeResult(null)
                setCreatedJob(null)
              }}
            >
              {t("probe.clear")}
            </button>
          </div>
        </form>
      </TuiPanel>
    </div>
  )
}

export const Route = createFileRoute("/probe")({
  validateSearch: (search: Record<string, unknown>): { url?: string } =>
    "url" in search && typeof search.url === "string" ? { url: search.url } : {},
  component: ProbePage,
})

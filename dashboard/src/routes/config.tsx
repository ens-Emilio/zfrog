import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"
import { api, type AppConfig } from "@/lib/api"
import { useMotion, useTheme } from "@/lib/prefs"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { Spinner, SYM } from "@/components/ui/tui"

const LOCAL_KEY = "zfrog-config-local"

interface LocalPrefs {
  threads: number
  timeout: number
  userAgent: string
  proxies: string
  headers: string
  robots: boolean
}

const DEFAULTS: LocalPrefs = {
  threads: 8,
  timeout: 30,
  userAgent: "Mozilla/5.0 (compatible; zfrog/1.0)",
  proxies: "",
  headers: "",
  robots: true,
}

function readLocal(): LocalPrefs | null {
  try {
    const raw = localStorage.getItem(LOCAL_KEY)
    if (!raw) return null
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<LocalPrefs>) }
  } catch {
    return null
  }
}

function writeLocal(prefs: LocalPrefs) {
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify(prefs))
  } catch {
    /* storage disabled */
  }
}

function ConfigPage() {
  const t = useT()
  const toast = useToast()
  const [theme, toggleTheme] = useTheme()
  const [motion, setMotion] = useMotion()

  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [rps, setRps] = useState(4)
  const [threads, setThreads] = useState(String(DEFAULTS.threads))
  const [timeoutSec, setTimeoutSec] = useState(String(DEFAULTS.timeout))
  const [userAgent, setUserAgent] = useState(DEFAULTS.userAgent)
  const [headers, setHeaders] = useState(DEFAULTS.headers)
  const [robots, setRobots] = useState(DEFAULTS.robots)

  const [saving, setSaving] = useState(false)

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getConfig()
      setConfig(data)
      setRps(Math.min(16, Math.max(1, data.rate_limit_rps)))
      const stored = readLocal()
      setThreads(String(stored?.threads ?? data.worker_concurrency))
      setTimeoutSec(String(stored?.timeout ?? data.http_timeout_read))
      setUserAgent(stored?.userAgent ?? DEFAULTS.userAgent)
      setHeaders(stored?.headers ?? "")
      setRobots(stored?.robots ?? true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void fetchConfig()
  }, [fetchConfig])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await api.updateRateLimit(rps)
      writeLocal({
        threads: Number(threads) || DEFAULTS.threads,
        timeout: Number(timeoutSec) || DEFAULTS.timeout,
        userAgent,
        proxies: "",
        headers,
        robots,
      })
      toast(t("config.savedToast"))
    } catch (err) {
      toast(err instanceof Error ? err.message : t("config.saveError"), "err")
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("config.title")}</h1>
        <span className="zf-meta">{t("config.subtitle")}</span>
        <span className="spacer" style={{ flex: 1 }} />
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s5)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>{SYM.fail} {t("config.readError")} {error}</p>
        </div>
      )}

      {loading ? (
        <div className="zf-empty"><Spinner /> {t("config.loading")}</div>
      ) : (
        <form onSubmit={handleSave} style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("config.appearanceSection")}</span></div>
            <div className="zf-panel-bd">
              <dl className="zf-kv">
                <dt>{t("config.theme")}</dt>
                <dd>
                  <div style={{ display: "flex", gap: "var(--s2)", alignItems: "center", flexWrap: "wrap" }}>
                    <button type="button" className="zf-btn" onClick={toggleTheme}>
                      {t("config.toggleTheme.before")}<b>{theme}</b>)
                    </button>
                    <span className="zf-hint">{t("config.themeHint")}</span>
                  </div>
                </dd>
                <dt>{t("config.motion")}</dt>
                <dd>
                  <div style={{ display: "flex", gap: "var(--s2)", alignItems: "center", flexWrap: "wrap" }}>
                    <button type="button" className="zf-btn" onClick={() => setMotion(motion === "full" ? "reduced" : "full")}>
                      {motion === "reduced" ? t("config.motionReduced") : t("config.motionFull")}
                    </button>
                    <span className="zf-hint">{t("config.motionHint")}</span>
                  </div>
                </dd>
              </dl>
            </div>
          </div>

          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("config.limitsSection")}</span></div>
            <div className="zf-panel-bd">
              <div className="zf-field" style={{ maxWidth: "22ch" }}>
                <label className="zf-label" htmlFor="rps-input">{t("config.rpsLabel")}</label>
                <input id="rps-input" type="number" min={1} max={32} className="zf-input" value={rps} onChange={(e) => setRps(Number(e.target.value))} />
                <span className="zf-hint">{t("config.rpsHint")}</span>
              </div>
              {config && (
                <dl className="zf-kv" style={{ marginTop: "var(--s2)" }}>
                  <dt>redis</dt>
                  <dd><code>{config.redis_url}</code></dd>
                  <dt>{t("config.workers")}</dt>
                  <dd>{config.worker_concurrency} {t("config.workersUnit")}</dd>
                  <dt>{t("config.timeout")}</dt>
                  <dd>{config.http_timeout_read}s</dd>
                </dl>
              )}
            </div>
          </div>

          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("config.clientSection")}</span></div>
            <div className="zf-panel-bd">
              <div className="zf-field">
                <label className="zf-label" htmlFor="ua-input">{t("config.uaLabel")}</label>
                <input id="ua-input" className="zf-input" value={userAgent} onChange={(e) => setUserAgent(e.target.value)} />
              </div>
              <div className="zf-field">
                <label className="zf-label" htmlFor="headers-input">{t("config.headersLabel")}</label>
                <textarea id="headers-input" className="zf-textarea" value={headers} placeholder='{"Authorization": "Bearer ...", "Accept-Language": "pt-BR"}' onChange={(e) => setHeaders(e.target.value)} rows={2} />
              </div>
              <label className="zf-check">
                <input type="checkbox" checked={robots} onChange={(e) => setRobots(e.target.checked)} />
                {t("config.robotsLabel")}
              </label>
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button type="submit" className="zf-btn zf-btn--primary" disabled={saving}>
              {saving ? <Spinner /> : SYM.ok} {t("config.save")}
            </button>
          </div>
        </form>
      )}
    </>
  )
}

export const Route = createFileRoute("/config")({
  component: ConfigPage,
})

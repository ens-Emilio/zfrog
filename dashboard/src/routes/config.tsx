import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"
import { api, type AppConfig } from "@/lib/api"
import { useMotion, useTheme } from "@/lib/prefs"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { Spinner, SYM, TuiPanel } from "@/components/ui/tui"

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
    <TuiPanel
      title={t("config.title")}
      action={
        <span style={{ color: "var(--fg-dim)", fontSize: 11 }}>
          {t("config.subtitle")}
        </span>
      }
    >
      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)", marginTop: "0.5lh" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("config.readError")} {error}</p>
        </div>
      )}

      {loading ? (
        <p className="empty"><Spinner /> {t("config.loading")}</p>
      ) : (
        <form onSubmit={handleSave} style={{ display: "flex", flexDirection: "column", gap: "1lh", marginTop: "0.5lh" }}>
          {/* Appearance & accessibility */}
          <div className="tui-panel">
            <span className="tui-label">{t("config.appearanceSection")}</span>
            <dl className="tui-kv">
              <dt>{t("config.theme")}</dt>
              <dd>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="tui-btn"
                    onClick={toggleTheme}
                  >
                    {t("config.toggleTheme.before")}<b>{theme}</b>)
                  </button>
                  <span className="tui-hint" style={{ alignSelf: "center" }}>
                    {t("config.themeHint")}
                  </span>
                </div>
              </dd>
              <dt>{t("config.motion")}</dt>
              <dd>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="tui-btn"
                    onClick={() => setMotion(motion === "full" ? "reduced" : "full")}
                  >
                    {motion === "reduced" ? t("config.motionReduced") : t("config.motionFull")}
                  </button>
                  <span className="tui-hint" style={{ alignSelf: "center" }}>
                    {t("config.motionHint")}
                  </span>
                </div>
              </dd>
            </dl>
          </div>

          {/* API limits */}
          <div className="tui-panel">
            <span className="tui-label">{t("config.limitsSection")}</span>
            <div className="tui-field" style={{ marginTop: "0.25lh" }}>
              <label className="tui-label" htmlFor="rps-input">
                {t("config.rpsLabel")}
              </label>
              <input
                id="rps-input"
                type="number"
                min={1}
                max={32}
                className="tui-input"
                value={rps}
                onChange={(e) => setRps(Number(e.target.value))}
                style={{ width: "12ch" }}
              />
              <span className="tui-hint">
                {t("config.rpsHint")}
              </span>
            </div>

            {config && (
              <dl className="tui-kv" style={{ marginTop: "0.5lh" }}>
                <dt>redis</dt>
                <dd><code>{config.redis_url}</code></dd>
                <dt>{t("config.workers")}</dt>
                <dd>{config.worker_concurrency} {t("config.workersUnit")}</dd>
                <dt>{t("config.timeout")}</dt>
                <dd>{config.http_timeout_read}s</dd>
              </dl>
            )}
          </div>

          {/* Local client preferences */}
          <div className="tui-panel">
            <span className="tui-label">{t("config.clientSection")}</span>
            <div className="tui-field" style={{ marginTop: "0.25lh" }}>
              <label className="tui-label" htmlFor="ua-input">{t("config.uaLabel")}</label>
              <input
                id="ua-input"
                className="tui-input"
                value={userAgent}
                onChange={(e) => setUserAgent(e.target.value)}
              />
            </div>

            <div className="tui-field">
              <label className="tui-label" htmlFor="headers-input">
                {t("config.headersLabel")}
              </label>
              <textarea
                id="headers-input"
                className="tui-textarea"
                value={headers}
                placeholder='{"Authorization": "Bearer ...", "Accept-Language": "pt-BR"}'
                onChange={(e) => setHeaders(e.target.value)}
                rows={2}
              />
            </div>

            <div className="flex gap-2 items-center" style={{ marginTop: "0.25lh" }}>
              <label className="flex items-center gap-1 text-[12px]">
                <input
                  type="checkbox"
                  checked={robots}
                  onChange={(e) => setRobots(e.target.checked)}
                />
                {t("config.robotsLabel")}
              </label>
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <button type="submit" className="tui-btn accent" disabled={saving}>
              {saving ? <Spinner /> : SYM.ok} {t("config.save")}
            </button>
          </div>
        </form>
      )}
    </TuiPanel>
  )
}

export const Route = createFileRoute("/config")({
  component: ConfigPage,
})

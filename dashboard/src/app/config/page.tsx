"use client"
import { useCallback, useEffect, useState } from "react"
import { api, type AppConfig } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Modal } from "@/components/ui/modal"
import { Icon } from "@/lib/icons"
import { useMotion, useTheme } from "@/lib/prefs"
import { useToast } from "@/components/ToastRegion"

/**
 * Everything the server does not expose a write endpoint for lives here, in the
 * browser. The labels say so, so nobody expects these to change the worker.
 */
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
    // Storage disabled or a hand-edited value: fall back to the defaults.
    return null
  }
}

function writeLocal(prefs: LocalPrefs) {
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify(prefs))
  } catch {
    /* storage disabled: the fields still apply for this session */
  }
}

function clearLocal() {
  try {
    localStorage.removeItem(LOCAL_KEY)
  } catch {
    /* storage disabled */
  }
}

export default function ConfigPage() {
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
  const [proxies, setProxies] = useState(DEFAULTS.proxies)
  const [headers, setHeaders] = useState(DEFAULTS.headers)
  const [robots, setRobots] = useState(DEFAULTS.robots)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [headersError, setHeadersError] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getConfig()
      setConfig(data)
      setRps(Math.min(16, Math.max(1, data.rate_limit_rps)))
      // Stored browser preferences win; otherwise the server's own values seed them.
      const stored = readLocal()
      setThreads(String(stored?.threads ?? data.worker_concurrency))
      setTimeoutSec(String(stored?.timeout ?? data.http_timeout_read))
      setUserAgent(stored?.userAgent ?? DEFAULTS.userAgent)
      setProxies(stored?.proxies ?? "")
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

  const handleSave = async () => {
    setSaveError(null)
    setHeadersError(null)

    const trimmedHeaders = headers.trim()
    if (trimmedHeaders) {
      try {
        JSON.parse(trimmedHeaders)
      } catch {
        setHeadersError("Não é um JSON válido. Confira as aspas e as vírgulas.")
        return
      }
    }

    setSaving(true)
    try {
      const result = await api.updateRateLimit(rps)
      writeLocal({
        threads: Number(threads) || DEFAULTS.threads,
        timeout: Number(timeoutSec) || DEFAULTS.timeout,
        userAgent,
        proxies,
        headers,
        robots,
      })
      setConfig((current) => (current ? { ...current, rate_limit_rps: result.rate_limit_rps } : current))
      setRps(Math.min(16, Math.max(1, result.rate_limit_rps)))
      toast("Configurações salvas.")
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      setSaveError(message)
      toast("Não foi possível salvar.", "err")
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    const next: LocalPrefs = {
      ...DEFAULTS,
      threads: config?.worker_concurrency ?? DEFAULTS.threads,
      timeout: config?.http_timeout_read ?? DEFAULTS.timeout,
    }
    setRps(Math.min(16, Math.max(1, config?.rate_limit_rps ?? 4)))
    setThreads(String(next.threads))
    setTimeoutSec(String(next.timeout))
    setUserAgent(next.userAgent)
    setProxies(next.proxies)
    setHeaders(next.headers)
    setRobots(next.robots)
    setHeadersError(null)
    clearLocal()
    setConfirmReset(false)
    toast("Padrões restaurados. Salve para aplicar no servidor.")
  }

  return (
    <div className="view-grid">
      <Topbar
        title="Configurações"
        description="Como o zfrog se comporta no servidor e neste navegador."
        action={
          <Button variant="secondary" onClick={() => void fetchConfig()} disabled={loading}>
            <Icon name="i-refresh" size="sm" />
            Recarregar
          </Button>
        }
      />

      {loading && (
        <>
          {[0, 1, 2].map((i) => (
            <div className="card" key={i}>
              <Skeleton style={{ height: 20, width: 220, marginBottom: 12 }} />
              <Skeleton style={{ height: 14, width: "60%", marginBottom: 20 }} />
              <Skeleton style={{ height: 44, width: "100%", marginBottom: 12 }} />
              <Skeleton style={{ height: 44, width: "100%" }} />
            </div>
          ))}
        </>
      )}

      {!loading && error && (
        <div className="card">
          <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
            Não foi possível carregar as configurações
          </h3>
          <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
            {error}
          </p>
          <Button onClick={() => void fetchConfig()}>
            <Icon name="i-refresh" size="sm" />
            Tentar de novo
          </Button>
        </div>
      )}

      {!loading && !error && config && (
        <>
          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Limites operacionais
            </h3>
            <p className="card-sub" style={{ marginBottom: "var(--sp-5)" }}>
              Equilíbrio entre velocidade e gentileza com os sites visitados.
            </p>

            <div className="od-row" style={{ ["--od-gap" as string]: "12px", justifyContent: "space-between" }}>
              <span className="label">Concorrência máxima do servidor</span>
              <span className="mono" style={{ color: "var(--text-2)" }}>
                {config.max_concurrent_jobs}
              </span>
            </div>
            <span className="hint">Definida no servidor. O ritmo você ajusta abaixo.</span>

            <div className="od-field" style={{ ["--od-gap" as string]: "8px", marginTop: "var(--sp-5)" }}>
              <span className="od-row" style={{ ["--od-gap" as string]: "12px", justifyContent: "space-between" }}>
                <label className="label" htmlFor="cfg-rps">
                  Requisições por segundo
                </label>
                <span className="mono" style={{ color: "var(--accent-strong)" }}>
                  {rps}
                </span>
              </span>
              <input
                className="range"
                id="cfg-rps"
                type="range"
                min={1}
                max={16}
                value={rps}
                aria-valuetext={`${rps} requisições por segundo`}
                onChange={(event) => setRps(Number(event.target.value))}
              />
              <span className="hint">
                Quantas requisições o zfrog envia por segundo. Vale no servidor assim que você salva.
              </span>
            </div>

            <div
              className="od-grid"
              style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "16px", marginTop: "var(--sp-5)" }}
            >
              <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
                <label className="label" htmlFor="cfg-threads">
                  Threads do worker
                </label>
                <input
                  className="input"
                  id="cfg-threads"
                  type="number"
                  min={1}
                  max={32}
                  value={threads}
                  onChange={(event) => setThreads(event.target.value)}
                />
                <span className="hint">Preferência local: o servidor ainda usa {config.worker_concurrency}.</span>
              </div>
              <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
                <label className="label" htmlFor="cfg-timeout">
                  Timeout por requisição (s)
                </label>
                <input
                  className="input"
                  id="cfg-timeout"
                  type="number"
                  min={5}
                  max={120}
                  value={timeoutSec}
                  onChange={(event) => setTimeoutSec(event.target.value)}
                />
                <span className="hint">Preferência local: o servidor ainda usa {config.http_timeout_read}s.</span>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Rede &amp; identidade
            </h3>
            <p className="card-sub" style={{ marginBottom: "var(--sp-5)" }}>
              Como o zfrog se apresenta aos sites. Estas preferências ficam neste navegador.
            </p>

            <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
              <label className="label" htmlFor="cfg-ua">
                User-Agent padrão
              </label>
              <input
                className="input input-mono"
                id="cfg-ua"
                value={userAgent}
                onChange={(event) => setUserAgent(event.target.value)}
              />
              <span className="hint">Preferência local (localStorage): ainda não é enviada ao servidor.</span>
            </div>

            <div
              className="od-grid"
              style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "16px", marginTop: "var(--sp-5)" }}
            >
              <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
                <label className="label" htmlFor="cfg-proxy">
                  Proxies (um por linha)
                </label>
                <textarea
                  className="textarea"
                  id="cfg-proxy"
                  placeholder={"http://proxy1:8080\nhttp://proxy2:8080"}
                  value={proxies}
                  onChange={(event) => setProxies(event.target.value)}
                />
                <span className="hint">
                  Preferência local (localStorage). O servidor já usa {config.proxy_url ? "um proxy" : "conexão direta"}.
                </span>
              </div>
              <div className="od-field" style={{ ["--od-gap" as string]: "6px" }}>
                <label className="label" htmlFor="cfg-headers">
                  Cabeçalhos extras (JSON)
                </label>
                <textarea
                  className="textarea"
                  id="cfg-headers"
                  placeholder={'{"Accept-Language": "pt-BR"}'}
                  aria-invalid={headersError ? true : undefined}
                  aria-describedby={headersError ? "cfg-headers-error" : undefined}
                  value={headers}
                  onChange={(event) => {
                    setHeaders(event.target.value)
                    if (headersError) setHeadersError(null)
                  }}
                />
                {headersError ? (
                  <span className="error-text" id="cfg-headers-error">
                    {headersError}
                  </span>
                ) : (
                  <span className="hint">Preferência local (localStorage): ainda não é enviada ao servidor.</span>
                )}
              </div>
            </div>

            <div style={{ marginTop: "var(--sp-5)" }}>
              <Switch
                label="Respeitar robots.txt"
                hint="Recomendado: mantém a extração dentro das regras do site. Preferência local (localStorage)."
                checked={robots}
                onChange={setRobots}
              />
            </div>
          </div>

          <div className="card">
            <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
              Aparência
            </h3>
            <p className="card-sub" style={{ marginBottom: "var(--sp-5)" }}>
              Preferências visuais deste navegador. Aplicam na hora e continuam depois de recarregar.
            </p>
            <div style={{ marginBottom: "var(--sp-4)" }}>
              <Switch
                label="Tema escuro"
                hint="Desligue para o tema claro."
                checked={theme === "dark"}
                onChange={() => toggleTheme()}
              />
            </div>
            <Switch
              label="Reduzir animações"
              hint="Segue também a preferência do sistema."
              checked={motion === "reduced"}
              onChange={(value) => setMotion(value ? "reduced" : "full")}
            />
          </div>

          {saveError && (
            <p className="error-text" role="alert">
              {saveError}
            </p>
          )}

          <div className="od-row" style={{ ["--od-gap" as string]: "12px", flexWrap: "wrap" }}>
            <Button className="od-touch" onClick={() => void handleSave()} loading={saving}>
              {!saving && <Icon name="i-check" size="sm" />}
              Salvar configurações
            </Button>
            <Button variant="secondary" className="od-touch" onClick={() => setConfirmReset(true)} disabled={saving}>
              Restaurar padrões
            </Button>
          </div>
        </>
      )}

      <Modal
        open={confirmReset}
        title="Restaurar os padrões?"
        body="Os campos de rede, threads e timeout voltam ao padrão e as preferências locais são apagadas. O tema e o movimento escolhidos são mantidos."
        confirmLabel="Restaurar"
        onConfirm={handleReset}
        onClose={() => setConfirmReset(false)}
      />
    </div>
  )
}


import { useCallback, useEffect, useState } from "react"
import { API_URL, api } from "@/lib/api"
import { clearApiKey, getApiKey, setApiKey } from "@/lib/auth"
import { useT } from "@/lib/i18n"

type Gate = "checking" | "open" | "locked" | "ready"

/**
 * Asks for a login when the server requires one, and gets out of the way when it
 * does not.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [gate, setGate] = useState<Gate>("checking")
  const [draft, setDraft] = useState("")
  const t = useT()
  const [error, setError] = useState("")
  const [sso, setSso] = useState(false)
  const [hasStoredKey, setHasStoredKey] = useState(false)

  const check = useCallback(async () => {
    let config
    try {
      config = await api.getAuthConfig()
    } catch {
      setGate("open")
      return
    }

    if (!config.auth_enabled) {
      setGate("open")
      return
    }

    setSso(Boolean(config.sso))
    setHasStoredKey(Boolean(getApiKey()))

    try {
      await api.verifyCredential()
      setGate("ready")
    } catch {
      setGate("locked")
    }
  }, [])

  useEffect(() => {
    void check()
  }, [check])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError("")
    setApiKey(draft)

    try {
      await api.verifyCredential()
      setHasStoredKey(true)
      setDraft("")
      setGate("ready")
    } catch (e) {
      clearApiKey()
      setHasStoredKey(false)
      setError(e instanceof Error ? e.message : t("auth.rejected"))
    }
  }

  if (gate === "checking") {
    return (
      <div className="tui-col" style={{ padding: "2lh 0", color: "var(--fg-dim)" }}>
        {t("auth.checking")}
      </div>
    )
  }

  if (gate === "ready" || gate === "open") {
    return <>{children}</>
  }

  return (
    <div className="tui-col" style={{ maxWidth: "60ch", margin: "2lh auto" }}>
      <div className="tui-panel">
        <h2 style={{ fontSize: "14px", fontWeight: 500, marginBottom: "0.5lh" }}>{t("auth.title")}</h2>
        <p style={{ color: "var(--fg-muted)", fontSize: "12px", marginBottom: "1lh", lineHeight: 1.5 }}>
          {sso
            ? t("auth.ssoBody")
            : <>{t("auth.keyBody")} <code>zfrog key create painel -r operator</code> {t("auth.keyBodyAfter")}</>}
        </p>

        {sso && (
          <div style={{ marginBottom: "1lh" }}>
            <button
              type="button"
              className="tui-btn"
              style={{ width: "100%", textAlign: "center" }}
              onClick={() => {
                window.location.href = `${API_URL}/auth/login`
              }}
            >
              {t("auth.ssoButton")}
            </button>
          </div>
        )}

        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "0.75lh" }}>
          <div>
            <label style={{ display: "block", color: "var(--fg-muted)", fontSize: "12px", marginBottom: "0.25lh" }}>
              {sso ? t("auth.orKey") : t("auth.keyLabel")}
            </label>
            <input
              type="password"
              autoFocus={!sso}
              placeholder="zk_…"
              value={draft}
              className="tui-input"
              style={{ width: "100%" }}
              onChange={(event) => setDraft(event.target.value)}
            />
            {error && (
              <p style={{ color: "var(--error)", fontSize: "12px", marginTop: "0.25lh" }}>
                {error}
              </p>
            )}
          </div>

          <div style={{ display: "flex", gap: "1ch", alignItems: "baseline" }}>
            <button
              type="submit"
              className="tui-btn"
              disabled={!draft.trim()}
              style={{ opacity: draft.trim() ? 1 : 0.5 }}
            >
              {t("auth.keyButton")}
            </button>
            {hasStoredKey && (
              <button
                type="button"
                className="tui-btn"
                style={{ color: "var(--fg-dim)" }}
                onClick={() => {
                  clearApiKey()
                  setHasStoredKey(false)
                  setDraft("")
                  setError("")
                }}
              >
                {t("auth.clearKey")}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}

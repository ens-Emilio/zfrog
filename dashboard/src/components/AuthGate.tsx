
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
      <div className="zf-view" style={{ padding: "var(--s8) 0", color: "var(--muted)", textAlign: "center" }}>
        {t("auth.checking")}
      </div>
    )
  }

  if (gate === "ready" || gate === "open") {
    return <>{children}</>
  }

  return (
    <div className="zf-view" style={{ maxWidth: "56ch", margin: "var(--s8) auto" }}>
      <div className="zf-panel" style={{ padding: "var(--s6)" }}>
        <h2 style={{ fontSize: "14px", fontWeight: 600, marginBottom: "var(--s3)", letterSpacing: "-.02em" }}>{t("auth.title")}</h2>
        <p style={{ color: "var(--muted)", fontSize: "var(--fs-meta)", marginBottom: "var(--s5)", lineHeight: 1.6 }}>
          {sso
            ? t("auth.ssoBody")
            : <>{t("auth.keyBody")} <code>zfrog key create painel -r operator</code> {t("auth.keyBodyAfter")}</>}
        </p>

        {sso && (
          <div style={{ marginBottom: "var(--s5)" }}>
            <button
              type="button"
              className="zf-btn zf-btn--primary"
              style={{ width: "100%", justifyContent: "center" }}
              onClick={() => {
                window.location.href = `${API_URL}/auth/login`
              }}
            >
              {t("auth.ssoButton")}
            </button>
          </div>
        )}

        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
          <div className="zf-field">
            <label className="zf-label">
              {sso ? t("auth.orKey") : t("auth.keyLabel")}
            </label>
            <input
              type="password"
              autoFocus={!sso}
              placeholder="zk_…"
              value={draft}
              className="zf-input"
              onChange={(event) => setDraft(event.target.value)}
            />
            {error && (
              <p className="zf-hint zf-hint--error">
                {error}
              </p>
            )}
          </div>

          <div style={{ display: "flex", gap: "var(--s2)", alignItems: "center" }}>
            <button
              type="submit"
              className="zf-btn zf-btn--primary"
              disabled={!draft.trim()}
            >
              {t("auth.keyButton")}
            </button>
            {hasStoredKey && (
              <button
                type="button"
                className="zf-btn zf-btn--ghost"
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

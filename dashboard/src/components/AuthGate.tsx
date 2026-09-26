"use client"

import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { API_URL, api } from "@/lib/api"
import { clearApiKey, getApiKey, setApiKey } from "@/lib/auth"

type Gate = "checking" | "open" | "locked" | "ready"

/**
 * Asks for a login when the server requires one, and gets out of the way when it
 * does not.
 *
 * Two ways in, because two kinds of deployment exist:
 *
 * - **SSO**, when configured. The button goes to `/auth/login`; the identity
 *   provider sends the browser back to `/auth/callback`, which sets the signed
 *   `zfrog_session` cookie. The credential never touches JavaScript.
 * - **An API key**, pasted here and kept in localStorage, for an installation
 *   with no identity provider.
 *
 * Either way the check is the same: ask the API for something that needs
 * `read:jobs`. A 200 means whatever credential is in play is accepted — so the
 * gate cannot claim success on a cookie the server would reject.
 *
 * Local use (auth off) is unchanged: the gate opens without asking for anything.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [gate, setGate] = useState<Gate>("checking")
  const [draft, setDraft] = useState("")
  const [error, setError] = useState("")
  const [sso, setSso] = useState(false)
  // Read through state rather than during render: localStorage does not exist on
  // the server, and a value read inline would not update when the key changes.
  const [hasStoredKey, setHasStoredKey] = useState(false)

  const check = useCallback(async () => {
    let config
    try {
      config = await api.getAuthConfig()
    } catch {
      // The API is unreachable; let the pages report that themselves.
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
      // No usable session cookie and no usable key. Not an error to display: the
      // form below is the answer.
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
      setError(e instanceof Error ? e.message : "Chave recusada")
    }
  }

  if (gate === "checking") {
    return <p className="text-[13px] text-muted-foreground">Verificando acesso…</p>
  }

  if (gate === "ready" || gate === "open") {
    return <>{children}</>
  }

  return (
    <div className="max-w-[520px] mx-auto mt-8">
      <Card>
        <CardHeader>
          <CardTitle>Entrar</CardTitle>
          <CardDescription>
            {sso
              ? "Entre com a sua conta da empresa. Se preferir, use uma chave de API."
              : "Esta instalação exige uma chave de API. Crie uma com zfrog key create painel -r operator e cole aqui — ela fica guardada só neste navegador."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {sso ? (
            <Button
              className="w-full"
              onClick={() => {
                // Full navigation: the provider redirects back to the API, which
                // sets the cookie and forwards to the dashboard.
                window.location.href = `${API_URL}/auth/login`
              }}
            >
              Entrar com a conta da empresa
            </Button>
          ) : null}

          <form onSubmit={submit} className="flex flex-col gap-4">
            <Input
              label={sso ? "Ou use uma chave de API" : "Chave"}
              type="password"
              autoFocus={!sso}
              placeholder="zk_…"
              value={draft}
              error={error}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="flex items-center gap-2">
              <Button type="submit" variant={sso ? "outline" : "primary"} disabled={!draft.trim()}>
                Entrar com a chave
              </Button>
              {hasStoredKey ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    clearApiKey()
                    setHasStoredKey(false)
                    setDraft("")
                    setError("")
                  }}
                >
                  Limpar chave guardada
                </Button>
              ) : null}
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

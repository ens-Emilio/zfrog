import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, WebhookEntry } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner, SYM } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

const EVENTS = [
  { name: "job.completed", key: "webhooks.eventExtractDone" },
  { name: "job.failed", key: "webhooks.eventExtractFailed" },
  { name: "site.changed", key: "webhooks.eventSiteChanged" },
] as const

function WebhooksPage() {
  const t = useT()
  const toast = useToast()

  const [hooks, setHooks] = useState<WebhookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [url, setUrl] = useState("")
  const [selectedEvents, setSelectedEvents] = useState<string[]>(["job.completed"])
  const [secret, setSecret] = useState("")
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<WebhookEntry | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getWebhooks()
      setHooks(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return
    setSaving(true)
    try {
      await api.registerWebhook({
        url: url.trim(),
        events: selectedEvents,
        secret: secret.trim() || undefined,
      })
      toast(t("webhooks.registeredOk"))
      setUrl("")
      setSecret("")
      void load()
    } catch (err) {
      toast(err instanceof Error ? err.message : t("webhooks.registerFailed"), "err")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (hook: WebhookEntry) => {
    setConfirmDelete(null)
    try {
      await api.deleteWebhook(hook.id)
      toast(t("webhooks.removedOk"))
      void load()
    } catch (err) {
      toast(err instanceof Error ? err.message : t("webhooks.removeFailed"), "err")
    }
  }

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("webhooks.title")}</h1>
        <span className="zf-meta">{hooks.length} {t("webhooks.count")}</span>
        <span className="spacer" style={{ flex: 1 }} />
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>{SYM.fail} {t("webhooks.error")}{error}</p>
        </div>
      )}

      <form onSubmit={handleRegister} className="zf-panel">
        <div className="zf-panel-hd"><span className="zf-micro">{t("webhooks.newEndpoint")}</span></div>
        <div className="zf-panel-bd">
          <div className="zf-field">
            <label className="zf-label" htmlFor="webhook-url">{t("webhooks.urlLabel")}</label>
            <input
              id="webhook-url"
              className="zf-input"
              type="url"
              value={url}
              placeholder="https://your-server.com/api/webhook"
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </div>

          <div className="zf-field">
            <span className="zf-label">{t("webhooks.eventsLabel")}</span>
            <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
              {EVENTS.map((ev) => {
                const active = selectedEvents.includes(ev.name)
                return (
                  <button
                    key={ev.name}
                    type="button"
                    className="zf-chip"
                    aria-pressed={active}
                    onClick={() => setSelectedEvents((cur) => cur.includes(ev.name) ? cur.filter((e) => e !== ev.name) : [...cur, ev.name])}
                  >
                    {t(ev.key)}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="zf-field">
            <label className="zf-label" htmlFor="webhook-secret">{t("webhooks.secretLabel")}</label>
            <input
              id="webhook-secret"
              className="zf-input"
              type="password"
              value={secret}
              placeholder={t("webhooks.secretPlaceholder")}
              onChange={(e) => setSecret(e.target.value)}
              style={{ maxWidth: "32ch" }}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button type="submit" className="zf-btn zf-btn--primary" disabled={saving || !url.trim()}>
              {saving ? <Spinner /> : t("webhooks.registerBtn")}
            </button>
          </div>
        </div>
      </form>

      <div className="zf-panel" style={{ marginTop: "var(--s5)" }}>
        <div className="zf-panel-hd"><span className="zf-micro">{t("webhooks.activeLabel")}</span><span className="zf-meta" style={{ marginLeft: "auto" }}>{hooks.length}</span></div>
        {loading ? (
          <div className="zf-panel-bd"><div className="zf-empty"><Spinner /> {t("webhooks.loading")}</div></div>
        ) : hooks.length === 0 ? (
          <div className="zf-panel-bd"><p className="zf-empty" style={{ margin: 0 }}>{t("webhooks.empty")}</p></div>
        ) : (
          <div className="zf-list">
            {hooks.map((h) => (
              <div key={h.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--s3)", padding: "var(--s3) var(--s4)" }}>
                <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontWeight: 500, color: "var(--fg)", overflowWrap: "anywhere" }}>{h.url}</span>
                  <div style={{ display: "flex", gap: "var(--s1)", flexWrap: "wrap" }}>
                    {h.events.map((ev) => (
                      <span key={ev} className="zf-chip" style={{ cursor: "default" }}>{ev}</span>
                    ))}
                  </div>
                </div>
                <button type="button" className="zf-btn zf-btn--danger" onClick={() => setConfirmDelete(h)}>
                  {t("webhooks.remove")}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {confirmDelete && (
        <dialog
          open
          className="zf-modal"
          onClose={() => setConfirmDelete(null)}
          aria-label={t("webhooks.removeTitle")}
          style={{
            position: "fixed",
            inset: 0,
            margin: "auto",
          }}
        >
          <div className="zf-modal-hd">
            <span style={{ fontWeight: 600 }}>{t("webhooks.removeTitle")}</span>
            <span className="zf-spacer" />
            <button type="button" className="zf-btn zf-btn--ghost" onClick={() => setConfirmDelete(null)} aria-label="fechar">✗</button>
          </div>
          <div className="zf-modal-bd"><p style={{ margin: 0 }}>{t("webhooks.removeBodyPrefix")}<b>{confirmDelete.url}</b>?</p></div>
          <div className="zf-modal-ft">
            <button type="button" className="zf-btn zf-btn--danger" onClick={() => void handleDelete(confirmDelete)}>
              {t("webhooks.confirmRemove")}
            </button>
            <button type="button" className="zf-btn" onClick={() => setConfirmDelete(null)}>
              {t("webhooks.cancel")}
            </button>
          </div>
        </dialog>
      )}
    </>
  )
}

export const Route = createFileRoute("/webhooks")({
  component: WebhooksPage,
})

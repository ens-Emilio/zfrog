import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, WebhookEntry } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner, SYM, TuiModal } from "@/components/ui/tui"
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

  const toggleEvent = (eventName: string) => {
    setSelectedEvents((cur) =>
      cur.includes(eventName) ? cur.filter((e) => e !== eventName) : [...cur, eventName],
    )
  }

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("webhooks.title")}</h1>
        <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
          {hooks.length} {t("webhooks.count")}
        </span>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("webhooks.error")}{error}</p>
        </div>
      )}

      {/* Registration form */}
      <form onSubmit={handleRegister} className="tui-panel" style={{ marginTop: "0.5lh" }}>
        <span className="tui-label">{t("webhooks.newEndpoint")}</span>
        <div className="tui-field" style={{ marginTop: "0.25lh" }}>
          <label className="tui-label" htmlFor="webhook-url">{t("webhooks.urlLabel")}</label>
          <input
            id="webhook-url"
            className="tui-input"
            type="url"
            value={url}
            placeholder="https://your-server.com/api/webhook"
            onChange={(e) => setUrl(e.target.value)}
            required
          />
        </div>

        <div className="tui-field">
          <label className="tui-label">{t("webhooks.eventsLabel")}</label>
          <div className="tui-tags" style={{ marginTop: "0.25lh" }}>
            {EVENTS.map((ev) => {
              const active = selectedEvents.includes(ev.name)
              return (
                <button
                  key={ev.name}
                  type="button"
                  className={`tui-tag${active ? " active" : ""}`}
                  onClick={() => toggleEvent(ev.name)}
                >
                  {t(ev.key)}
                </button>
              )
            })}
          </div>
        </div>

        <div className="tui-field">
          <label className="tui-label" htmlFor="webhook-secret">{t("webhooks.secretLabel")}</label>
          <input
            id="webhook-secret"
            className="tui-input"
            type="password"
            value={secret}
            placeholder={t("webhooks.secretPlaceholder")}
            onChange={(e) => setSecret(e.target.value)}
            style={{ maxWidth: "32ch" }}
          />
        </div>

        <div className="flex justify-end">
          <button type="submit" className="tui-btn accent" disabled={saving || !url.trim()}>
            {saving ? <Spinner /> : t("webhooks.registerBtn")}
          </button>
        </div>
      </form>

      {/* Webhook list */}
      <div style={{ marginTop: "1lh" }}>
        <span className="tui-label">{t("webhooks.activeLabel")}</span>
        {loading ? (
          <p className="empty"><Spinner /> {t("webhooks.loading")}</p>
        ) : hooks.length === 0 ? (
          <p className="empty">{t("webhooks.empty")}</p>
        ) : (
          <div className="rows" style={{ marginTop: "0.25lh" }}>
            {hooks.map((h) => (
              <div
                key={h.id}
                style={{
                  borderBottom: "1px solid var(--line)",
                  padding: "0.5lh 0",
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  gap: "1ch",
                }}
              >
                <div>
                  <span style={{ fontWeight: 500, color: "var(--fg)" }}>{h.url}</span>
                  <div className="tui-tags" style={{ marginTop: "0.25lh" }}>
                    {h.events.map((ev) => (
                      <span key={ev} className="tui-tag" style={{ cursor: "default" }}>
                        {ev}
                      </span>
                    ))}
                  </div>
                </div>
                <button
                  type="button"
                  className="tui-btn danger"
                  onClick={() => setConfirmDelete(h)}
                  style={{ fontSize: 11 }}
                >
                  {t("webhooks.remove")}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {confirmDelete && (
        <TuiModal open={true} title={t("webhooks.removeTitle")} onClose={() => setConfirmDelete(null)}>
          <p>{t("webhooks.removeBodyPrefix")}<b>{confirmDelete.url}</b>?</p>
          <div className="flex justify-end gap-2" style={{ marginTop: "0.5lh" }}>
            <button type="button" className="tui-btn danger" onClick={() => void handleDelete(confirmDelete)}>
              {t("webhooks.confirmRemove")}
            </button>
            <button type="button" className="tui-btn" onClick={() => setConfirmDelete(null)}>
              {t("webhooks.cancel")}
            </button>
          </div>
        </TuiModal>
      )}
    </>
  )
}

export const Route = createFileRoute("/webhooks")({
  component: WebhooksPage,
})

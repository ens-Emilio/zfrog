"use client"
import { useEffect, useState } from "react"
import type { CSSProperties } from "react"
import { api, AuditEntry, WebhookEntry } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Input, Switch } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Modal } from "@/components/ui/modal"
import { useToast } from "@/components/ToastRegion"
import {
  Trash2,
  RefreshCw,
  Check,
  AlertTriangle,
  BellRing,
  Activity,
} from "lucide-react"

/**
 * Aviso enviado para outro sistema quando algo acontece. Um webhook é um
 * recado: quando o sistema termina uma extração, ele manda uma mensagem para o
 * endereço cadastrado aqui.
 */

/** Os eventos que a API aceita em um aviso, com uma explicação em português. */
const EVENTS: { name: string; label: string; what: string }[] = [
  { name: "job.completed", label: "Extração concluída", what: "Quando uma cópia termina sem erro." },
  { name: "job.failed", label: "Extração falhou", what: "Quando uma cópia termina com erro." },
  { name: "site.changed", label: "Site mudou", what: "Quando uma página mudou desde a última cópia." },
]

/** Nome em português de cada evento, incluindo os que a tela ainda não conhece. */
const EVENT_LABELS: Record<string, string> = {
  "job.completed": "Extração concluída",
  "job.failed": "Extração falhou",
  "site.changed": "Site mudou",
}

/** Prefixo das ações de aviso no registro de auditoria. */
const AUDIT_PREFIX = "webhook."

/** A ação que registra uma entrega de verdade no endereço cadastrado. */
const DELIVERY_ACTION = "webhook.deliver"

/**
 * O que mostrar depois de cadastrar. A API confirma o cadastro sem repetir os
 * eventos escolhidos, então o aviso vem da lista recém-carregada — e, se ela não
 * trouxer o endereço, do que a própria pessoa acabou de preencher.
 */
type RegisteredNotice = { url: string; events: string[] }

/** Um registro de auditoria já com o resultado da entrega decidido uma vez só. */
type WebhookLogEntry = AuditEntry & { ok: boolean }

/** O rótulo curto do resultado, na coluna de nível do console. */
function outcomeLabel(entry: WebhookLogEntry) {
  if (entry.ok) return "OK"
  return entry.outcome ? entry.outcome.toUpperCase() : "—"
}

const gridStyle: CSSProperties = { ["--od-cols" as string]: 2, ["--od-gap" as string]: "16px" }
const clusterStyle: CSSProperties = { ["--od-gap" as string]: "8px" }
const rowStyle: CSSProperties = { gridTemplateColumns: "minmax(0,1fr) auto" }

export default function WebhooksPage() {
  const toast = useToast()

  const [hooks, setHooks] = useState<WebhookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [url, setUrl] = useState("")
  const [primaryEvent, setPrimaryEvent] = useState(EVENTS[0].name)
  const [extraEvents, setExtraEvents] = useState<string[]>([])
  const [secret, setSecret] = useState("")
  const [active, setActive] = useState(true)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [created, setCreated] = useState<RegisteredNotice | null>(null)

  const [pendingRemove, setPendingRemove] = useState<WebhookEntry | null>(null)
  const [removing, setRemoving] = useState(false)

  const [audit, setAudit] = useState<WebhookLogEntry[]>([])
  const [auditLoading, setAuditLoading] = useState(true)
  const [auditError, setAuditError] = useState<string | null>(null)

  const fetchHooks = async () => {
    setLoading(true)
    setError(null)
    try {
      setHooks(await api.getWebhooks())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  /** Os registros de aviso do sistema: só o que já saiu de verdade para algum endereço. */
  const fetchAudit = async () => {
    setAuditLoading(true)
    setAuditError(null)
    try {
      const entries = await api.getAuditLog(50)
      setAudit(
        entries
          .filter((entry) => entry.action.startsWith(AUDIT_PREFIX))
          .map((entry) => ({
            ...entry,
            ok: entry.outcome === "success" || entry.outcome === "ok",
          }))
      )
    } catch (e) {
      setAuditError(e instanceof Error ? e.message : String(e))
    } finally {
      setAuditLoading(false)
    }
  }

  useEffect(() => {
    void fetchHooks()
    void fetchAudit()
  }, [])

  const selectedEvents = [primaryEvent, ...extraEvents.filter((name) => name !== primaryEvent)]

  const toggleExtraEvent = (name: string) => {
    setExtraEvents((current) =>
      current.includes(name) ? current.filter((value) => value !== name) : [...current, name]
    )
  }

  const handleRegister = async () => {
    const trimmedUrl = url.trim()
    if (!trimmedUrl) {
      setFormError("Informe o endereço que deve receber os avisos.")
      return
    }
    if (!/^https?:\/\/\S+$/i.test(trimmedUrl)) {
      setFormError("O endereço precisa começar com http:// ou https://.")
      return
    }
    if (!active) {
      setFormError("O aviso está desligado. Ligue o interruptor Ativo para cadastrar.")
      return
    }

    setSaving(true)
    setFormError(null)
    setCreated(null)
    const chosen = [...selectedEvents]
    const target = trimmedUrl.replace(/\/+$/, "")
    try {
      await api.registerWebhook({
        url: trimmedUrl,
        events: chosen,
        secret: secret.trim() || undefined,
      })
      // A confirmação do cadastro não repete os eventos: quem manda é a lista.
      const listed = await api.getWebhooks().catch(() => null)
      if (listed) setHooks(listed)
      const saved = listed?.find((hook) => hook.url.replace(/\/+$/, "") === target)
      setCreated(saved ? { url: saved.url, events: saved.events } : { url: trimmedUrl, events: chosen })
      setUrl("")
      setExtraEvents([])
      setSecret("")
      toast("Webhook salvo.")
      void fetchAudit()
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e))
      toast("Não foi possível salvar o webhook.", "err")
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async () => {
    if (!pendingRemove) return
    const hook = pendingRemove
    setRemoving(true)
    setError(null)
    try {
      await api.deleteWebhook(hook.id)
      setPendingRemove(null)
      if (created && created.url.replace(/\/+$/, "") === hook.url.replace(/\/+$/, "")) setCreated(null)
      await fetchHooks()
      await fetchAudit()
      toast("Webhook removido.")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      toast("Não foi possível remover o webhook.", "err")
    } finally {
      setRemoving(false)
    }
  }

  return (
    <div className="view-grid">
      <Topbar
        title="Webhooks"
        description="Um aviso é uma mensagem que o sistema manda para o seu endereço quando uma extração termina, falha ou o site muda. Assim outro sistema seu fica sabendo na hora, sem precisar ficar perguntando."
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void fetchHooks()
              void fetchAudit()
            }}
            loading={loading}
          >
            <RefreshCw className="ic ic-sm" aria-hidden="true" /> Atualizar
          </Button>
        }
      />

      <section className="card stack-md" aria-labelledby="novo-webhook">
        <h2 id="novo-webhook" className="card-title">
          Novo webhook
        </h2>

        <div className="od-grid" style={gridStyle}>
          <Input
            label="URL de destino"
            className="input-mono"
            placeholder="https://sistema.exemplo.com/hooks/zfrog"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void handleRegister()}
          />
          <Select
            label="Evento"
            value={primaryEvent}
            onChange={(value) => {
              setPrimaryEvent(value)
              setExtraEvents((current) => current.filter((name) => name !== value))
            }}
            options={EVENTS.map((event) => ({
              value: event.name,
              label: event.label,
              hint: event.what,
            }))}
          />
        </div>

        <div className="od-field">
          <span className="label">Também avisar em</span>
          <div className="od-cluster" style={clusterStyle}>
            {EVENTS.filter((event) => event.name !== primaryEvent).map((event) => {
              const checked = extraEvents.includes(event.name)
              return (
                <button
                  key={event.name}
                  type="button"
                  className="chip"
                  aria-pressed={checked}
                  onClick={() => toggleExtraEvent(event.name)}
                  title={event.what}
                >
                  {event.label}
                </button>
              )
            })}
          </div>
          <span className="hint">Um mesmo endereço pode escutar mais de um evento.</span>
        </div>

        <Input
          label="Segredo (opcional)"
          type="password"
          placeholder="uma senha combinada com o seu sistema"
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
          hint="Serve para o seu sistema confirmar que a mensagem veio daqui. Ele nunca é mostrado de volta."
        />

        <Switch
          checked={active}
          onChange={setActive}
          label="Ativo"
          hint="Sem repetição automática: cada evento gera uma única entrega no endereço."
        />

        {!active && <span className="hint">Desligado, o aviso não é cadastrado.</span>}

        <div>
          <Button variant="primary" onClick={handleRegister} loading={saving} disabled={!url.trim() || !active}>
            Salvar webhook
          </Button>
        </div>

        {formError && (
          <p className="error-text" role="alert">
            <AlertTriangle className="ic ic-sm" aria-hidden="true" />
            {formError}
          </p>
        )}

        {created && !formError && (
          <p className="hint od-row" style={clusterStyle}>
            <Check className="ic ic-sm" style={{ color: "var(--success)" }} aria-hidden="true" />
            <span>
              Webhook salvo para <span className="mono">{created.url}</span>. Ele vai receber:{" "}
              {created.events.map((name) => EVENT_LABELS[name] ?? name).join(", ") || "nenhum evento"}.
            </span>
          </p>
        )}
      </section>

      <section className="card" aria-labelledby="webhooks-configurados">
        <h2 id="webhooks-configurados" className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
          Webhooks configurados
        </h2>

        {error && (
          <div className="stack-sm">
            <p className="error-text" role="alert">
              <AlertTriangle className="ic ic-sm" aria-hidden="true" />
              Não foi possível carregar os webhooks: {error}
            </p>
            <div>
              <Button variant="outline" size="sm" onClick={() => void fetchHooks()}>
                <RefreshCw className="ic ic-sm" aria-hidden="true" /> Tentar de novo
              </Button>
            </div>
          </div>
        )}

        {!error && loading && (
          <div className="stack-sm">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-[76px] w-full" />
            ))}
          </div>
        )}

        {!error && !loading && hooks.length === 0 && (
          <EmptyState
            icon={<BellRing className="ic ic-lg" aria-hidden="true" />}
            title="Nenhum webhook cadastrado"
            description="Preencha o endereço do seu sistema acima e escolha em quais situações ele deve ser avisado."
          />
        )}

        {!error && !loading && hooks.length > 0 && (
          <div className="stack-sm">
            {hooks.map((hook) => {
              const delivered = audit.filter(
                (entry) => entry.action === DELIVERY_ACTION && entry.target === hook.url
              )
              const failures = delivered.filter((entry) => !entry.ok).length
              const events = hook.events.map((name) => EVENT_LABELS[name] ?? name)
              return (
                <article className="job-row" style={rowStyle} key={hook.id}>
                  <div className="job-meta">
                    <span className="detail-url od-truncate" title={hook.url}>
                      {hook.url}
                    </span>
                    <span className="job-sub">
                      <span>{events.length > 0 ? events.join(" · ") : "Nenhum evento"}</span>
                      <span aria-hidden="true">·</span>
                      <span>
                        {auditLoading
                          ? "entregas: carregando…"
                          : delivered.length === 0
                            ? "nenhuma entrega nos últimos 50 registros"
                            : `${delivered.length} entrega(s) nos últimos 50 registros · ${failures} falha(s)`}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>{hook.has_secret ? "com segredo" : "sem segredo"}</span>
                    </span>
                  </div>
                  <div className="od-cluster" style={clusterStyle}>
                    <Badge variant="success">
                      <span className="dot" aria-hidden="true" />
                      Ativo
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remover o webhook para ${hook.url}`}
                      title="Remover"
                      onClick={() => setPendingRemove(hook)}
                    >
                      <Trash2 className="ic ic-sm" aria-hidden="true" />
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="registros-webhook">
        <h2 id="registros-webhook" className="card-title">
          Registros de entrega
        </h2>
        <p className="card-sub" style={{ marginBottom: "var(--sp-3)" }}>
          As últimas 50 ações do sistema, mostrando só as ligadas a webhooks. Cada linha é uma ação registrada, com o
          endereço de destino e o resultado dela.
        </p>

        {auditError && (
          <div className="stack-sm">
            <p className="error-text" role="alert">
              <AlertTriangle className="ic ic-sm" aria-hidden="true" />
              Não foi possível carregar os registros: {auditError}
            </p>
            <div>
              <Button variant="outline" size="sm" onClick={() => void fetchAudit()}>
                <RefreshCw className="ic ic-sm" aria-hidden="true" /> Tentar de novo
              </Button>
            </div>
          </div>
        )}

        {!auditError && auditLoading && (
          <div className="stack-sm">
            {[0, 1, 2, 3].map((index) => (
              <Skeleton key={index} className="h-[20px] w-full" />
            ))}
          </div>
        )}

        {!auditError && !auditLoading && audit.length === 0 && (
          <EmptyState
            icon={<Activity className="ic ic-lg" aria-hidden="true" />}
            title="Nenhum registro de webhook ainda"
            description="Cadastrar e remover webhooks aparece aqui. A entrega acontece quando uma extração termina, falha ou o site muda."
          />
        )}

        {!auditError && !auditLoading && audit.length > 0 && (
          <div className="console" role="log" aria-label="Registros de webhook">
            {audit.map((entry, index) => {
              return (
                <div className="line" key={`${entry.timestamp}-${entry.action}-${index}`}>
                  <span className="ts" title={entry.timestamp}>
                    {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString("pt-BR") : "--:--"}
                  </span>
                  <span className={`lvl ${entry.ok ? "lvl-ok" : "lvl-err"}`}>{outcomeLabel(entry)}</span>
                  <span className="od-fill od-truncate">
                    {entry.action}
                    {entry.target ? ` · ${entry.target}` : ""}
                    {entry.detail ? ` · ${entry.detail}` : ""}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </section>

      <Modal
        open={pendingRemove !== null}
        title="Remover este webhook?"
        body={
          pendingRemove
            ? `O endereço ${pendingRemove.url} deixa de receber avisos. As entregas já registradas continuam no histórico.`
            : ""
        }
        confirmLabel="Remover"
        danger
        onConfirm={() => void handleRemove()}
        onClose={() => {
          if (!removing) setPendingRemove(null)
        }}
      />
    </div>
  )
}

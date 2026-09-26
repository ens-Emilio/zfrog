"use client"
import { useEffect, useState } from "react"
import { api, AuditEntry, WebhookEntry } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  Webhook,
  Link2,
  KeyRound,
  Plus,
  Trash2,
  RefreshCw,
  Check,
  AlertTriangle,
  Inbox,
  Send,
  BellRing,
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

/**
 * O que mostrar depois de cadastrar. A API confirma o cadastro sem repetir os
 * eventos escolhidos, então o aviso vem da lista recém-carregada — e, se ela não
 * trouxer o endereço, do que a própria pessoa acabou de preencher.
 */
type RegisteredNotice = { url: string; events: string[] }

/** Como o resultado de uma ação de aviso aparece na tela. */
const OUTCOME: Record<string, string> = {
  success: "Deu certo",
  ok: "Deu certo",
  failed: "Falhou",
  error: "Falhou",
}

export default function WebhooksPage() {
  const [hooks, setHooks] = useState<WebhookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [url, setUrl] = useState("")
  const [events, setEvents] = useState<string[]>([])
  const [secret, setSecret] = useState("")
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [created, setCreated] = useState<RegisteredNotice | null>(null)

  const [removingId, setRemovingId] = useState<string | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testedId, setTestedId] = useState<string | null>(null)

  const [audit, setAudit] = useState<AuditEntry[]>([])
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
      setAudit(entries.filter((entry) => entry.action.startsWith(AUDIT_PREFIX)))
    } catch (e) {
      setAuditError(e instanceof Error ? e.message : String(e))
    } finally {
      setAuditLoading(false)
    }
  }

  useEffect(() => {
    fetchHooks()
    fetchAudit()
  }, [])

  const toggleEvent = (name: string) => {
    setEvents((current) =>
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
    if (events.length === 0) {
      setFormError("Escolha pelo menos um evento para avisar.")
      return
    }

    setSaving(true)
    setFormError(null)
    setCreated(null)
    const chosen = [...events]
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
      setEvents([])
      setSecret("")
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async (hook: WebhookEntry) => {
    if (!confirm(`Remover o aviso para ${hook.url}?`)) return
    setRemovingId(hook.id)
    setError(null)
    try {
      await api.deleteWebhook(hook.id)
      if (created && created.url.replace(/\/+$/, "") === hook.url.replace(/\/+$/, "")) setCreated(null)
      if (testedId === hook.id) setTestedId(null)
      await fetchHooks()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRemovingId(null)
    }
  }

  /**
   * Não existe envio de teste avulso: o aviso sai quando uma extração termina.
   * O botão apenas recarrega os registros abaixo, para conferir o que já saiu.
   */
  const handleTest = async (hook: WebhookEntry) => {
    setTestingId(hook.id)
    setTestedId(hook.id)
    await fetchAudit()
    setTestingId(null)
  }

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Avisos"
        description="Um aviso (webhook) é uma mensagem que o sistema manda para o seu endereço quando algo acontece: uma extração terminou, falhou ou o site mudou. Assim outro sistema seu fica sabendo na hora, sem precisar ficar perguntando."
        action={
          <Button
            onClick={() => {
              fetchHooks()
              fetchAudit()
            }}
            loading={loading}
            size="sm"
            variant="outline"
          >
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plus className="h-4 w-4" /> Novo aviso
          </CardTitle>
          <CardDescription>
            Informe para onde mandar a mensagem e em quais situações. O endereço precisa aceitar chamadas
            automáticas (um endereço https:// do seu sistema).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input
            label="Endereço de destino"
            placeholder="https://meusistema.com.br/avisos"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleRegister()}
            leftIcon={<Link2 className="h-4 w-4" />}
            hint="Onde a mensagem deve chegar. Precisa começar com http:// ou https://."
          />

          <div className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-medium text-foreground/80">Quando avisar</span>
            <div className="grid sm:grid-cols-3 gap-2">
              {EVENTS.map((event) => {
                const checked = events.includes(event.name)
                return (
                  <button
                    key={event.name}
                    type="button"
                    onClick={() => toggleEvent(event.name)}
                    aria-pressed={checked}
                    className={cn(
                      "text-left rounded-[10px] border p-3 transition-all",
                      checked ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "hover:bg-accent"
                    )}
                  >
                    <div className="flex items-center gap-2 text-[13px] font-medium">
                      <span
                        className={cn(
                          "h-4 w-4 shrink-0 rounded-[5px] border flex items-center justify-center",
                          checked ? "bg-primary border-primary text-primary-foreground" : "border-input"
                        )}
                      >
                        {checked && <Check className="h-3 w-3" />}
                      </span>
                      {event.label}
                    </div>
                    <p className="text-[11.5px] text-muted-foreground mt-1 leading-snug">{event.what}</p>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Segredo (opcional)"
                placeholder="uma senha combinada com o seu sistema"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                leftIcon={<KeyRound className="h-4 w-4" />}
                hint="Serve para o seu sistema confirmar que a mensagem veio daqui. Ele nunca é mostrado de volta."
              />
            </div>
            <Button onClick={handleRegister} loading={saving} disabled={!url.trim() || events.length === 0}>
              <Plus className="h-4 w-4" /> Cadastrar aviso
            </Button>
          </div>

          {formError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível cadastrar o aviso.</p>
              <p className="mt-1">{formError}</p>
            </div>
          )}

          {created && !formError && (
            <div className="rounded-[12px] bg-emerald-500/10 border border-emerald-500/20 p-3 text-[13px] text-emerald-700 dark:text-emerald-400 flex items-start gap-2">
              <Check className="h-4 w-4 shrink-0 mt-0.5" />
              <span>
                Aviso cadastrado para <strong className="break-all">{created.url}</strong>. Ele vai receber:{" "}
                {created.events.map((name) => EVENT_LABELS[name] ?? name).join(", ") || "nenhum evento"}.
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Webhook className="h-4 w-4" /> Avisos cadastrados
          </CardTitle>
          <CardDescription>
            {hooks.length === 0
              ? "Nenhum aviso cadastrado ainda."
              : `${hooks.length} aviso(s). O segredo aparece só como sim ou não — ele nunca é mostrado de volta.`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível carregar os avisos.</p>
              <p className="mt-1">{error}</p>
              <p className="mt-1 text-muted-foreground">
                Confira se o sistema está no ar e tente <strong className="text-foreground/80">Atualizar</strong> de
                novo.
              </p>
            </div>
          )}

          {!loading && !error && hooks.length === 0 && (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <BellRing className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
              <p className="text-[13px] font-medium">Nenhum aviso cadastrado ainda</p>
              <p className="text-[12.5px] text-muted-foreground mt-1 max-w-md mx-auto">
                Preencha o formulário acima com o endereço do seu sistema e escolha em quais situações ele deve ser
                avisado.
              </p>
            </div>
          )}

          {hooks.length > 0 && (
            <div className="overflow-x-auto rounded-[12px] border">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Endereço</th>
                    <th className="px-4 py-3 font-medium">Quando avisar</th>
                    <th className="px-4 py-3 font-medium">Segredo</th>
                    <th className="px-4 py-3 font-medium text-right">Ações</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {hooks.map((hook) => (
                    <tr key={hook.id} className="hover:bg-accent/50 align-top">
                      <td className="px-4 py-3">
                        <span className="text-[12.5px] font-mono break-all">{hook.url}</span>
                      </td>
                      <td className="px-4 py-3">
                        {hook.events.length === 0 ? (
                          <span className="text-[12px] text-muted-foreground">Nenhum evento</span>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {hook.events.map((name) => (
                              <Badge
                                key={name}
                                className="bg-secondary text-secondary-foreground whitespace-nowrap"
                              >
                                {EVENT_LABELS[name] ?? name}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap",
                            hook.has_secret
                              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
                              : "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20"
                          )}
                        >
                          <KeyRound className="h-3 w-3" />
                          {hook.has_secret ? "sim" : "não"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            loading={testingId === hook.id}
                            disabled={testingId !== null && testingId !== hook.id}
                            onClick={() => handleTest(hook)}
                            title="Ver os avisos que já saíram"
                          >
                            <Send className="h-3.5 w-3.5" /> Testar
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={removingId === hook.id}
                            disabled={removingId !== null && removingId !== hook.id}
                            onClick={() => handleRemove(hook)}
                            title="Remover"
                          >
                            <Trash2 className="h-3.5 w-3.5" /> Remover
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {testedId && (
            <p className="text-[12px] text-muted-foreground">
              Não existe um envio de teste separado: o aviso sai de verdade quando uma extração termina. O botão
              Testar apenas recarrega os registros abaixo, para você ver o que já foi registrado.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Send className="h-4 w-4" /> Registros de avisos
          </CardTitle>
          <CardDescription>
            As últimas 50 ações do sistema, mostrando só as ligadas a avisos. Cada linha é uma ação registrada para
            um endereço cadastrado, com o resultado dela.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {auditError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível carregar os registros.</p>
              <p className="mt-1">{auditError}</p>
            </div>
          )}

          {!auditLoading && !auditError && audit.length === 0 && (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <Inbox className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
              <p className="text-[13px] font-medium">Nenhum registro de aviso ainda</p>
              <p className="text-[12.5px] text-muted-foreground mt-1 max-w-md mx-auto">
                Cadastrar e remover avisos aparece aqui. O envio de um aviso acontece quando uma extração termina,
                falha ou o site muda.
              </p>
            </div>
          )}

          {audit.length > 0 && (
            <div className="overflow-x-auto rounded-[12px] border">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Quando</th>
                    <th className="px-4 py-3 font-medium">Ação</th>
                    <th className="px-4 py-3 font-medium">Destino</th>
                    <th className="px-4 py-3 font-medium">Resultado</th>
                    <th className="px-4 py-3 font-medium">Detalhe</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {audit.map((entry, index) => {
                    const outcome = OUTCOME[entry.outcome] ?? entry.outcome
                    const succeeded = entry.outcome === "success" || entry.outcome === "ok"
                    return (
                      <tr key={`${entry.timestamp}-${entry.action}-${index}`} className="hover:bg-accent/50">
                        <td className="px-4 py-3 text-[12px] text-muted-foreground whitespace-nowrap">
                          {entry.timestamp ? new Date(entry.timestamp).toLocaleString("pt-BR") : "—"}
                        </td>
                        <td className="px-4 py-3 text-[12.5px] font-mono whitespace-nowrap">{entry.action}</td>
                        <td className="px-4 py-3 text-[12px] font-mono text-muted-foreground break-all">
                          {entry.target || "—"}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={cn(
                              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap",
                              succeeded
                                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
                                : "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20"
                            )}
                          >
                            {succeeded ? <Check className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                            {outcome || "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-[12px] text-muted-foreground break-words">{entry.detail || "—"}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

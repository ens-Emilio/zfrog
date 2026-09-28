"use client"
import { useEffect, useState } from "react"
import { api, Annotation, AnnotationCounts } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Chip } from "@/components/ui/ds"
import { EmptyState } from "@/components/ui/empty"
import { Modal } from "@/components/ui/modal"
import { Skeleton } from "@/components/ui/skeleton"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { useToast } from "@/components/ToastRegion"
import { Icon } from "@/lib/icons"
import { formatStamp, timeAgo } from "@/lib/utils"

/**
 * Comentários deixados nas páginas de uma cópia, para revisar o material antes
 * de publicar. Cada comentário aponta para uma página, pode ter respostas e
 * pode ser resolvido quando alguém já tratou do assunto.
 */

/** Filtro da lista. A contagem do topo sempre olha todos os comentários da cópia. */
type ResolvedFilter = "all" | "open" | "resolved"

const FILTERS: { value: ResolvedFilter; label: string }[] = [
  { value: "all", label: "Todos" },
  { value: "open", label: "Abertos" },
  { value: "resolved", label: "Resolvidos" },
]

/** Uma etiqueta por vírgula, sem espaços sobrando e sem repetição. */
function parseTags(value: string): string[] {
  const tags = value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean)
  return Array.from(new Set(tags))
}

/** Os números que aparecem no topo, calculados sobre a lista inteira da cópia. */
function countAnnotations(notes: Annotation[]): AnnotationCounts {
  const by_author: Record<string, number> = {}
  const by_tag: Record<string, number> = {}
  let open = 0
  let resolved = 0

  for (const note of notes) {
    if (note.resolved) resolved += 1
    else open += 1
    const author = note.author || "sem autor"
    by_author[author] = (by_author[author] ?? 0) + 1
    for (const tag of note.tags) by_tag[tag] = (by_tag[tag] ?? 0) + 1
  }

  return { total: notes.length, open, resolved, by_author, by_tag }
}

/** Falha de leitura ou de ação: o rótulo diz o que aconteceu e há como tentar de novo. */
function ErrorBlock({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className="card stack-sm" style={{ borderColor: "var(--danger)" }}>
      <span className="badge badge-danger">
        <span className="dot" aria-hidden="true" />
        Erro
      </span>
      <h3 className="card-title">{title}</h3>
      <p className="card-sub">{message}</p>
      {onRetry && (
        <div>
          <Button variant="secondary" size="sm" className="od-touch" onClick={onRetry}>
            <Icon name="i-refresh" size="sm" />
            Tentar de novo
          </Button>
        </div>
      )}
    </div>
  )
}

/** Enquanto a lista chega, cartões com a mesma silhueta dos cartões de comentário. */
function CardsSkeleton() {
  return (
    <div className="grid-cards" aria-hidden="true">
      {[0, 1, 2].map((row) => (
        <div key={row} className="card stack-sm">
          <div className="od-row-top" style={{ ["--od-gap" as string]: "12px" }}>
            <Skeleton className="h-10 w-10" />
            <div className="od-fill od-stack" style={{ ["--od-gap" as string]: "6px" }}>
              <Skeleton className="h-3.5 w-28" />
              <Skeleton className="h-3 w-40" />
            </div>
          </div>
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-4/5" />
        </div>
      ))}
    </div>
  )
}

export default function RevisaoPage() {
  const toast = useToast()

  const [jobId, setJobId] = useState("")
  const [appliedJob, setAppliedJob] = useState("")
  const [filter, setFilter] = useState<ResolvedFilter>("all")

  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [replyTo, setReplyTo] = useState<string | null>(null)
  const [replyText, setReplyText] = useState("")
  const [replyAuthor, setReplyAuthor] = useState("")

  const [newJob, setNewJob] = useState("")
  const [newPath, setNewPath] = useState("")
  const [newSelector, setNewSelector] = useState("")
  const [newText, setNewText] = useState("")
  const [newAuthor, setNewAuthor] = useState("")
  const [newTags, setNewTags] = useState("")
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [created, setCreated] = useState<Annotation | null>(null)

  const [markdown, setMarkdown] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const [confirming, setConfirming] = useState<Annotation | null>(null)

  const fetchAnnotations = async (targetJob: string) => {
    setLoading(true)
    try {
      const notes = await api.getAnnotations(targetJob.trim() || undefined)
      setAnnotations(notes)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void (async () => {
      await fetchAnnotations("")
    })()
  }, [])

  const handleLoad = () => {
    setAppliedJob(jobId.trim())
    setReplyTo(null)
    void fetchAnnotations(jobId)
  }

  const replaceAnnotation = (updated: Annotation) => {
    setAnnotations((current) => current.map((note) => (note.id === updated.id ? updated : note)))
  }

  const handleResolve = async (note: Annotation) => {
    setBusyId(note.id)
    setActionError(null)
    try {
      const updated = await api.resolveAnnotation(note.id, !note.resolved)
      replaceAnnotation(updated)
      toast(updated.resolved ? "Comentário marcado como resolvido." : "Comentário reaberto.")
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (note: Annotation) => {
    setBusyId(note.id)
    setActionError(null)
    try {
      await api.deleteAnnotation(note.id)
      setAnnotations((current) => current.filter((item) => item.id !== note.id))
      if (replyTo === note.id) setReplyTo(null)
      toast("Comentário excluído.")
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
    }
  }

  const handleReply = async (note: Annotation) => {
    const text = replyText.trim()
    if (!text) return
    setBusyId(note.id)
    setActionError(null)
    try {
      replaceAnnotation(
        await api.replyAnnotation(note.id, { text, author: replyAuthor.trim() || undefined })
      )
      setReplyText("")
      setReplyTo(null)
      toast("Resposta publicada.")
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
    }
  }

  const canCreate = newJob.trim() !== "" && newPath.trim() !== "" && newText.trim() !== ""

  const handleCreate = async () => {
    if (!canCreate) return
    setCreating(true)
    setCreateError(null)
    setCreated(null)
    try {
      const note = await api.createAnnotation({
        job_id: newJob.trim(),
        path: newPath.trim(),
        text: newText.trim(),
        author: newAuthor.trim() || undefined,
        selector: newSelector.trim() || undefined,
        tags: parseTags(newTags),
      })
      setCreated(note)
      setNewText("")
      setNewSelector("")
      setNewTags("")
      toast("Comentário salvo.")
      if (!appliedJob || appliedJob === note.job_id) await fetchAnnotations(appliedJob)
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  const exportTarget = appliedJob || jobId.trim()

  const handleExport = async () => {
    if (!exportTarget) return
    setExporting(true)
    setExportError(null)
    setCopied(false)
    try {
      const result = await api.exportAnnotations(exportTarget)
      setMarkdown(result.markdown)
    } catch (e) {
      setMarkdown(null)
      setExportError(e instanceof Error ? e.message : String(e))
    } finally {
      setExporting(false)
    }
  }

  const handleCopy = async () => {
    if (markdown === null) return
    try {
      await navigator.clipboard.writeText(markdown)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const counts = countAnnotations(annotations)
  const visible =
    filter === "all" ? annotations : annotations.filter((note) => note.resolved === (filter === "resolved"))
  // Da maior contagem para a menor; empate sai em ordem alfabética.
  const authors = Object.entries(counts.by_author).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  const tags = Object.entries(counts.by_tag).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))

  return (
    <div className="view-grid">
      <Topbar
        title="Revisão"
        description="Comentários deixados nas páginas de uma cópia: quem escreveu, em qual página, o que precisa mudar e o que já foi resolvido."
        action={
          <Button
            variant="secondary"
            size="sm"
            className="od-touch"
            loading={loading}
            onClick={() => void fetchAnnotations(appliedJob)}
          >
            <Icon name="i-refresh" size="sm" />
            Atualizar
          </Button>
        }
      />

      <section className="card stack-md">
        <div className="od-field" style={{ ["--od-gap" as string]: "2px" }}>
          <h2 className="card-title">Procurar comentários</h2>
          <p className="card-sub">
            Informe o id de uma cópia para ver só os comentários dela. Em branco, aparecem os comentários de todas as
            cópias.
          </p>
        </div>

        <div className="od-row" style={{ ["--od-gap" as string]: "12px", alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="od-fill">
            <Input
              label="Id da cópia"
              placeholder="ex.: a1b2c3d4"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleLoad()}
              hint="O id aparece em Execuções, no endereço de cada cópia."
            />
          </div>
          <Button className="od-touch" loading={loading} onClick={handleLoad}>
            <Icon name="i-search" />
            Carregar
          </Button>
        </div>

        <div className="filter-rail">
          {FILTERS.map((option) => (
            <Chip key={option.value} active={filter === option.value} onClick={() => setFilter(option.value)}>
              {option.label}
            </Chip>
          ))}
        </div>
      </section>

      {error && (
        <ErrorBlock
          title="Não foi possível carregar os comentários."
          message={error}
          onRetry={() => void fetchAnnotations(appliedJob)}
        />
      )}

      {actionError && (
        <ErrorBlock title="A ação não deu certo." message={actionError} />
      )}

      {!error && counts.total > 0 && (
        <>
          <StatStrip>
            <StatCard
              label="Comentários"
              value={counts.total}
              trend={appliedJob ? "nesta cópia" : "no total"}
            />
            <StatCard label="Abertos" value={counts.open} trend="a tratar" />
            <StatCard label="Resolvidos" value={counts.resolved} trend="já tratados" />
            <StatCard label="Pessoas" value={authors.length} trend="quem comentou" />
          </StatStrip>

          <section className="card stack-md">
            <div className="od-field" style={{ ["--od-gap" as string]: "2px" }}>
              <h2 className="card-title">Quem comentou</h2>
              <p className="card-sub">Quantos comentários cada pessoa deixou nesta cópia.</p>
            </div>

            <div className="od-cluster">
              {authors.map(([author, count]) => (
                <Badge key={author} variant="neutral">
                  {author} · {count}
                </Badge>
              ))}
            </div>

            {tags.length > 0 && (
              <div className="od-cluster">
                {tags.map(([tag, count]) => (
                  <Badge key={tag} variant="accent">
                    {tag} · {count}
                  </Badge>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {loading && annotations.length === 0 && !error && <CardsSkeleton />}

      {!loading && !error && visible.length === 0 && (
        <EmptyState
          icon={<Icon name="i-message" size="lg" />}
          title={
            counts.total > 0
              ? "Nada com esse filtro"
              : appliedJob
                ? "Nenhum comentário nesta cópia"
                : "Nenhum comentário ainda"
          }
          description={
            counts.total > 0
              ? "Troque o filtro para ver os outros comentários desta cópia."
              : "Use o formulário Novo comentário abaixo para apontar o que precisa mudar em uma página da cópia."
          }
        />
      )}

      {visible.length > 0 && (
        <section className="stack-md">
          <p className="list-meta">
            <span>
              {visible.length} comentário(s) {filter === "all" ? "nesta cópia" : "com esse filtro"}
            </span>
            {appliedJob && <span className="mono">cópia {appliedJob}</span>}
          </p>

          <div className="grid-cards">
            {visible.map((note) => (
              <article key={note.id} className="card stack-sm">
                <div className="od-row-top" style={{ ["--od-gap" as string]: "12px" }}>
                  <span className="job-favicon" aria-hidden="true">
                    {note.author.trim() ? note.author.trim().charAt(0).toUpperCase() : "?"}
                  </span>
                  <div className="od-fill od-stack" style={{ ["--od-gap" as string]: "2px" }}>
                    <span className="job-url">{note.author || "sem autor"}</span>
                    <span className="hint">
                      {timeAgo(note.created_at)} · {note.path}
                    </span>
                  </div>
                  <Badge variant={note.resolved ? "success" : "warning"}>
                    <span className="dot" aria-hidden="true" />
                    {note.resolved ? "Resolvido" : "Aberto"}
                  </Badge>
                </div>

                <p className="card-sub whitespace-pre-wrap break-words">{note.text}</p>

                {note.selector && (
                  <p className="hint">
                    Onde: <span className="mono">{note.selector}</span>
                  </p>
                )}

                <p className="hint">
                  <span title={formatStamp(note.created_at)}>criado em {formatStamp(note.created_at)}</span>
                  {note.updated_at && note.updated_at !== note.created_at && (
                    <>
                      {" · "}
                      <span title={formatStamp(note.updated_at)}>editado em {formatStamp(note.updated_at)}</span>
                    </>
                  )}
                  {" · "}
                  <span className="mono">cópia {note.job_id}</span>
                </p>

                {note.tags.length > 0 && (
                  <div className="od-cluster">
                    {note.tags.map((tag) => (
                      <Badge key={tag} variant="neutral">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}

                {note.replies.length > 0 && (
                  <div
                    className="stack-sm"
                    style={{
                      borderLeft: "2px solid var(--glass-border-strong)",
                      paddingLeft: "var(--sp-3)",
                    }}
                  >
                    {note.replies.map((reply) => (
                      <div key={reply.id} className="od-field" style={{ ["--od-gap" as string]: "2px" }}>
                        <span className="job-sub">
                          <span>{reply.author || "sem autor"}</span>
                          <span aria-hidden="true">·</span>
                          <span title={formatStamp(reply.created_at)}>{timeAgo(reply.created_at)}</span>
                        </span>
                        <p className="card-sub whitespace-pre-wrap break-words">{reply.text}</p>
                      </div>
                    ))}
                  </div>
                )}

                <div className="od-row" style={{ ["--od-gap" as string]: "8px", flexWrap: "wrap" }}>
                  <Button
                    size="sm"
                    className="od-touch"
                    aria-expanded={replyTo === note.id}
                    disabled={busyId !== null && busyId !== note.id}
                    onClick={() => {
                      const opening = replyTo !== note.id
                      setReplyTo(opening ? note.id : null)
                      setReplyText("")
                    }}
                  >
                    <Icon name="i-message" size="sm" />
                    Responder
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="od-touch"
                    loading={busyId === note.id}
                    disabled={busyId !== null && busyId !== note.id}
                    onClick={() => void handleResolve(note)}
                  >
                    <Icon name={note.resolved ? "i-rotate" : "i-check-circle"} size="sm" />
                    {note.resolved ? "Reabrir" : "Resolver"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="od-touch"
                    disabled={busyId !== null && busyId !== note.id}
                    onClick={() => setConfirming(note)}
                  >
                    <Icon name="i-trash" size="sm" />
                    Excluir
                  </Button>
                  {note.replies.length > 0 && <span className="hint">{note.replies.length} resposta(s)</span>}
                </div>

                {replyTo === note.id && (
                  <div className="stack-sm">
                    <label className="field">
                      <span className="label">Resposta</span>
                      <textarea
                        className="textarea"
                        placeholder="Escreva a resposta"
                        value={replyText}
                        onChange={(e) => setReplyText(e.target.value)}
                      />
                    </label>
                    <div
                      className="od-row"
                      style={{ ["--od-gap" as string]: "8px", alignItems: "flex-end", flexWrap: "wrap" }}
                    >
                      <div className="od-fill">
                        <Input
                          label="Seu nome"
                          placeholder="ex.: Ana"
                          value={replyAuthor}
                          onChange={(e) => setReplyAuthor(e.target.value)}
                        />
                      </div>
                      <Button
                        size="sm"
                        className="od-touch"
                        loading={busyId === note.id}
                        disabled={!replyText.trim()}
                        onClick={() => void handleReply(note)}
                      >
                        <Icon name="i-check" size="sm" />
                        Enviar resposta
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="od-touch"
                        onClick={() => {
                          setReplyTo(null)
                          setReplyText("")
                        }}
                      >
                        Cancelar
                      </Button>
                    </div>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="card stack-md">
        <div className="od-field" style={{ ["--od-gap" as string]: "2px" }}>
          <h2 className="card-title">Novo comentário</h2>
          <p className="card-sub">
            Aponte o que precisa mudar em uma página da cópia. O caminho é o mesmo que aparece na lista de arquivos
            baixados; o seletor é opcional e serve para marcar um trecho específico da página.
          </p>
        </div>

        <div className="od-grid" style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "16px" }}>
          <Input
            label="Id da cópia"
            placeholder="ex.: a1b2c3d4"
            value={newJob}
            onChange={(e) => setNewJob(e.target.value)}
          />
          <Input
            label="Caminho da página"
            placeholder="ex.: index.html"
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
          />
          <Input
            label="Seletor (opcional)"
            placeholder="ex.: #preco"
            value={newSelector}
            onChange={(e) => setNewSelector(e.target.value)}
            hint="Marca um trecho específico da página. Em branco, o comentário vale para a página toda."
          />
          <Input
            label="Seu nome"
            placeholder="ex.: Ana"
            value={newAuthor}
            onChange={(e) => setNewAuthor(e.target.value)}
          />
        </div>

        <label className="field">
          <span className="label">Comentário</span>
          <textarea
            className="textarea"
            placeholder="ex.: o telefone do rodapé está errado"
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
          />
        </label>

        <Input
          label="Etiquetas (opcional)"
          placeholder="ex.: preço, texto, urgente"
          value={newTags}
          onChange={(e) => setNewTags(e.target.value)}
          hint="Separe por vírgula. Ajuda a agrupar os comentários depois."
        />

        {createError && (
          <div className="od-stack" style={{ ["--od-gap" as string]: "4px" }}>
            <span className="error-text">
              <Icon name="i-alert" size="sm" />
              Não foi possível salvar o comentário.
            </span>
            <span className="hint">{createError}</span>
          </div>
        )}

        {created && (
          <div className="od-stack" style={{ ["--od-gap" as string]: "4px" }}>
            <span className="badge badge-success">
              <span className="dot" aria-hidden="true" />
              Comentário salvo em {created.path}
            </span>
            <span className="hint mono">id {created.id}</span>
          </div>
        )}

        <div>
          <Button className="od-touch" loading={creating} disabled={!canCreate} onClick={() => void handleCreate()}>
            <Icon name="i-plus" />
            Salvar comentário
          </Button>
        </div>
      </section>

      <section className="card stack-md">
        <div className="od-field" style={{ ["--od-gap" as string]: "2px" }}>
          <h2 className="card-title">Exportar Markdown</h2>
          <p className="card-sub">
            Gera um documento com todos os comentários de uma cópia, para colar em uma tarefa ou enviar para alguém.
            {exportTarget ? (
              <>
                {" "}
                Vai exportar a cópia <span className="mono">{exportTarget}</span>.
              </>
            ) : (
              " Informe o id de uma cópia acima para poder exportar."
            )}
          </p>
        </div>

        <div className="od-row" style={{ ["--od-gap" as string]: "8px", flexWrap: "wrap" }}>
          <Button className="od-touch" loading={exporting} disabled={!exportTarget} onClick={() => void handleExport()}>
            <Icon name="i-file-down" />
            Exportar Markdown
          </Button>
          {markdown !== null && (
            <Button variant="secondary" size="sm" className="od-touch" onClick={() => void handleCopy()}>
              <Icon name={copied ? "i-check" : "i-copy"} size="sm" />
              {copied ? "copiado" : "copiar"}
            </Button>
          )}
        </div>

        {exportError && (
          <div className="od-stack" style={{ ["--od-gap" as string]: "4px" }}>
            <span className="error-text">
              <Icon name="i-alert" size="sm" />
              Não foi possível exportar os comentários.
            </span>
            <span className="hint">{exportError}</span>
          </div>
        )}

        {markdown !== null && (
          <pre className="console whitespace-pre-wrap break-words" tabIndex={0} aria-label="Markdown exportado">
            {markdown}
          </pre>
        )}
      </section>

      <Modal
        open={confirming !== null}
        title="Excluir este comentário?"
        body="As respostas dele também são apagadas. Não dá para desfazer."
        confirmLabel="Excluir"
        danger
        onConfirm={() => {
          const note = confirming
          setConfirming(null)
          if (note) void handleDelete(note)
        }}
        onClose={() => setConfirming(null)}
      />
    </div>
  )
}

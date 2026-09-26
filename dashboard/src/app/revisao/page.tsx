"use client"
import { useEffect, useState } from "react"
import { api, Annotation, AnnotationCounts } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { StatCard } from "@/components/ui/stat-card"
import { timeAgo } from "@/lib/utils"
import {
  MessageSquare,
  MessageSquarePlus,
  CornerDownRight,
  Send,
  CheckCircle2,
  RotateCcw,
  Trash2,
  RefreshCw,
  FileText,
  Copy,
  Check,
  AlertTriangle,
  Inbox,
  User,
  Tag,
} from "lucide-react"

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

export default function RevisaoPage() {
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
    fetchAnnotations(jobId)
  }

  const replaceAnnotation = (updated: Annotation) => {
    setAnnotations((current) => current.map((note) => (note.id === updated.id ? updated : note)))
  }

  const handleResolve = async (note: Annotation) => {
    setBusyId(note.id)
    setActionError(null)
    try {
      replaceAnnotation(await api.resolveAnnotation(note.id, !note.resolved))
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (note: Annotation) => {
    if (!confirm("Excluir este comentário e as respostas dele? Não dá para desfazer.")) return
    setBusyId(note.id)
    setActionError(null)
    try {
      await api.deleteAnnotation(note.id)
      setAnnotations((current) => current.filter((item) => item.id !== note.id))
      if (replyTo === note.id) setReplyTo(null)
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
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Revisão"
        description="Comentários deixados nas páginas de uma cópia: quem escreveu, em qual página, o que precisa mudar e o que já foi resolvido. Serve para revisar o material antes de publicar."
        action={
          <Button onClick={() => fetchAnnotations(appliedJob)} loading={loading} size="sm" variant="outline">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4" /> Procurar comentários
          </CardTitle>
          <CardDescription>
            Informe o id de uma cópia para ver só os comentários dela. Em branco, aparecem os comentários de todas as
            cópias.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Id da cópia"
                placeholder="ex.: a1b2c3d4"
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleLoad()}
                leftIcon={<FileText className="h-4 w-4" />}
                hint="O id aparece em Execuções, no endereço de cada cópia."
              />
            </div>
            <Button onClick={handleLoad} loading={loading}>
              <MessageSquare className="h-4 w-4" /> Carregar
            </Button>
          </div>

          <div className="flex flex-wrap gap-2">
            {FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFilter(option.value)}
                aria-pressed={filter === option.value}
                className={`rounded-[10px] border px-3 py-1.5 text-[12.5px] font-medium transition-all ${
                  filter === option.value
                    ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                    : "text-muted-foreground hover:bg-accent"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar os comentários.</p>
            <p className="mt-1">{error}</p>
            <p className="mt-1 text-muted-foreground">
              Confira se o sistema está no ar e clique em <strong className="text-foreground/80">Atualizar</strong>.
            </p>
          </CardContent>
        </Card>
      )}

      {actionError && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">A ação não deu certo.</p>
            <p className="mt-1">{actionError}</p>
          </CardContent>
        </Card>
      )}

      {!error && counts.total > 0 && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <StatCard
              label="Comentários"
              value={counts.total}
              icon={<MessageSquare className="h-4 w-4" />}
              trend={appliedJob ? "nesta cópia" : "no total"}
            />
            <StatCard
              label="Abertos"
              value={counts.open}
              icon={<AlertTriangle className="h-4 w-4" />}
              trend="a tratar"
              className={counts.open > 0 ? "ring-1 ring-amber-500/20" : undefined}
            />
            <StatCard
              label="Resolvidos"
              value={counts.resolved}
              icon={<CheckCircle2 className="h-4 w-4" />}
              trend="já tratados"
              className="ring-1 ring-emerald-500/20"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="h-4 w-4" /> Quem comentou
              </CardTitle>
              <CardDescription>Quantos comentários cada pessoa deixou nesta cópia.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {authors.map(([author, count]) => (
                  <span
                    key={author}
                    className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-[12.5px]"
                  >
                    {author}
                    <span className="font-semibold tabular-nums">{count}</span>
                  </span>
                ))}
              </div>

              {tags.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Tag className="h-3.5 w-3.5 text-muted-foreground" />
                  {tags.map(([tag, count]) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] text-muted-foreground"
                    >
                      {tag}
                      <span className="font-semibold tabular-nums">{count}</span>
                    </span>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {!loading && !error && visible.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <Inbox className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">
              {counts.total > 0
                ? "Nada com esse filtro"
                : appliedJob
                  ? "Nenhum comentário nesta cópia"
                  : "Nenhum comentário ainda"}
            </h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
              {counts.total > 0
                ? "Troque o filtro para ver os outros comentários desta cópia."
                : "Use o formulário Novo comentário abaixo para apontar o que precisa mudar em uma página da cópia."}
            </p>
          </CardContent>
        </Card>
      )}

      {loading && annotations.length === 0 && !error && (
        <Card>
          <CardContent className="p-10 text-center">
            <MessageSquare className="h-6 w-6 mx-auto text-muted-foreground/40 mb-2 animate-pulse" />
            <p className="text-[13px] text-muted-foreground">Carregando os comentários…</p>
          </CardContent>
        </Card>
      )}

      {visible.length > 0 && (
        <div className="space-y-3">
          <p className="text-[12.5px] text-muted-foreground">
            {visible.length} comentário(s) {filter === "all" ? "nesta cópia" : "com esse filtro"}.
          </p>

          {visible.map((note) => (
            <Card key={note.id}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="font-mono text-[13px] break-all">{note.path}</CardTitle>
                    <CardDescription className="flex flex-wrap items-center gap-3 mt-1">
                      <span className="inline-flex items-center gap-1">
                        <User className="h-3 w-3" /> {note.author || "sem autor"}
                      </span>
                      <span title={new Date(note.created_at).toLocaleString("pt-BR")}>
                        {timeAgo(note.created_at)}
                      </span>
                      {note.updated_at && note.updated_at !== note.created_at && (
                        <span
                          className="text-muted-foreground/80"
                          title={new Date(note.updated_at).toLocaleString("pt-BR")}
                        >
                          editado {timeAgo(note.updated_at)}
                        </span>
                      )}
                      <span className="font-mono text-[11.5px]">{note.job_id}</span>
                    </CardDescription>
                  </div>
                  <span
                    className={`shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap ${
                      note.resolved
                        ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
                        : "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20"
                    }`}
                  >
                    {note.resolved ? (
                      <CheckCircle2 className="h-3 w-3" />
                    ) : (
                      <AlertTriangle className="h-3 w-3" />
                    )}
                    {note.resolved ? "Resolvido" : "Aberto"}
                  </span>
                </div>
              </CardHeader>

              <CardContent className="space-y-3">
                {note.selector && (
                  <p className="text-[12px] text-muted-foreground">
                    Onde: <span className="font-mono text-foreground/80">{note.selector}</span>
                  </p>
                )}

                <p className="text-[13.5px] whitespace-pre-wrap break-words">{note.text}</p>

                {note.tags.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Tag className="h-3 w-3 text-muted-foreground" />
                    {note.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-[11.5px] text-secondary-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                {note.replies.length > 0 && (
                  <div className="rounded-[12px] border bg-muted/20 divide-y divide-border/60">
                    {note.replies.map((reply) => (
                      <div key={reply.id} className="flex gap-2 p-3">
                        <CornerDownRight className="h-3.5 w-3.5 shrink-0 mt-0.5 text-muted-foreground" />
                        <div className="min-w-0">
                          <p className="text-[12px] text-muted-foreground flex flex-wrap items-center gap-2">
                            <span className="font-medium text-foreground/80">{reply.author || "sem autor"}</span>
                            <span title={new Date(reply.created_at).toLocaleString("pt-BR")}>
                              {timeAgo(reply.created_at)}
                            </span>
                          </p>
                          <p className="text-[13px] mt-1 whitespace-pre-wrap break-words">{reply.text}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {replyTo === note.id ? (
                  <div className="rounded-[12px] border p-3 space-y-2 bg-muted/20">
                    <textarea
                      className="w-full min-h-[72px] rounded-[12px] border border-input bg-background px-3 py-2 text-[13.5px] focus:outline-none focus:ring-2 focus:ring-ring"
                      placeholder="Escreva a resposta"
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                    />
                    <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
                      <div className="flex-1">
                        <Input
                          label="Seu nome"
                          placeholder="ex.: Ana"
                          value={replyAuthor}
                          onChange={(e) => setReplyAuthor(e.target.value)}
                        />
                      </div>
                      <Button
                        size="sm"
                        loading={busyId === note.id}
                        disabled={!replyText.trim()}
                        onClick={() => handleReply(note)}
                      >
                        <Send className="h-3.5 w-3.5" /> Enviar resposta
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setReplyTo(null)
                          setReplyText("")
                        }}
                      >
                        Cancelar
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busyId !== null && busyId !== note.id}
                      onClick={() => {
                        setReplyTo(note.id)
                        setReplyText("")
                      }}
                    >
                      <CornerDownRight className="h-3.5 w-3.5" /> Responder
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      loading={busyId === note.id}
                      disabled={busyId !== null && busyId !== note.id}
                      onClick={() => handleResolve(note)}
                    >
                      {note.resolved ? (
                        <>
                          <RotateCcw className="h-3.5 w-3.5" /> Reabrir
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="h-3.5 w-3.5" /> Resolver
                        </>
                      )}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busyId !== null && busyId !== note.id}
                      onClick={() => handleDelete(note)}
                    >
                      <Trash2 className="h-3.5 w-3.5" /> Excluir
                    </Button>
                    {note.replies.length > 0 && (
                      <span className="text-[11.5px] text-muted-foreground ml-1">
                        {note.replies.length} resposta(s)
                      </span>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquarePlus className="h-4 w-4" /> Novo comentário
          </CardTitle>
          <CardDescription>
            Aponte o que precisa mudar em uma página da cópia. O caminho é o mesmo que aparece na lista de arquivos
            baixados; o seletor é opcional e serve para marcar um trecho específico da página.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid sm:grid-cols-2 gap-3">
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

          <label className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-medium text-foreground/80">Comentário</span>
            <textarea
              className="w-full min-h-[96px] rounded-[12px] border border-input bg-background px-3 py-2 text-[14px] focus:outline-none focus:ring-2 focus:ring-ring"
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
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível salvar o comentário.</p>
              <p className="mt-1">{createError}</p>
            </div>
          )}

          {created && (
            <div className="rounded-[12px] bg-emerald-500/10 border border-emerald-500/20 p-3 text-[13px] text-emerald-700 dark:text-emerald-400">
              <p className="flex items-center gap-1.5 font-medium">
                <Check className="h-3.5 w-3.5" /> Comentário salvo em {created.path}.
              </p>
              <p className="mt-1 break-all font-mono text-[12px]">id {created.id}</p>
            </div>
          )}

          <Button onClick={handleCreate} loading={creating} disabled={!canCreate}>
            <MessageSquarePlus className="h-4 w-4" /> Salvar comentário
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" /> Exportar Markdown
          </CardTitle>
          <CardDescription>
            Gera um documento com todos os comentários de uma cópia, para colar em uma tarefa ou enviar para alguém.
            {exportTarget ? (
              <>
                {" "}
                Vai exportar a cópia <span className="font-mono text-foreground/80">{exportTarget}</span>.
              </>
            ) : (
              " Informe o id de uma cópia acima para poder exportar."
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={handleExport} loading={exporting} disabled={!exportTarget}>
              <FileText className="h-4 w-4" /> Exportar Markdown
            </Button>
            {markdown !== null && (
              <Button variant="outline" size="sm" onClick={handleCopy}>
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "copiado" : "copiar"}
              </Button>
            )}
          </div>

          {exportError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível exportar os comentários.</p>
              <p className="mt-1">{exportError}</p>
            </div>
          )}

          {markdown !== null && (
            <pre className="max-h-[420px] overflow-auto rounded-[12px] border bg-muted/30 p-4 text-[12px] font-mono whitespace-pre-wrap break-words">
              {markdown}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

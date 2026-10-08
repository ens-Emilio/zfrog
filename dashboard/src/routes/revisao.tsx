import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, Annotation, AnnotationCounts } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { timeAgo } from "@/lib/utils"
import { Spinner, SYM, TuiModal } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

type ResolvedFilter = "all" | "open" | "resolved"

const FILTERS: { value: ResolvedFilter; key: "revisao.filterAll" | "revisao.filterOpen" | "revisao.filterResolved" }[] = [
  { value: "all", key: "revisao.filterAll" },
  { value: "open", key: "revisao.filterOpen" },
  { value: "resolved", key: "revisao.filterResolved" },
]

function parseTags(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  )
}

function countAnnotations(notes: Annotation[]): AnnotationCounts {
  const by_author: Record<string, number> = {}
  const by_tag: Record<string, number> = {}
  let open = 0
  let resolved = 0

  for (const note of notes) {
    if (note.resolved) resolved += 1
    else open += 1
    const author = note.author || "anonymous"
    by_author[author] = (by_author[author] ?? 0) + 1
    for (const tag of note.tags) by_tag[tag] = (by_tag[tag] ?? 0) + 1
  }

  return { total: notes.length, open, resolved, by_author, by_tag }
}

function RevisaoPage() {
  const t = useT()
  const toast = useToast()

  const [notes, setNotes] = useState<Annotation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [filter, setFilter] = useState<ResolvedFilter>("all")
  const [selectedTag, setSelectedTag] = useState<string | null>(null)

  const [newPath, setNewPath] = useState("/")
  const [newAuthor, setNewAuthor] = useState("")
  const [newContent, setNewContent] = useState("")
  const [newTags, setNewTags] = useState("")
  const [saving, setSaving] = useState(false)

  const [confirmDelete, setConfirmDelete] = useState<Annotation | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getAnnotations()
      setNotes(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const counts = countAnnotations(notes)

  const filtered = notes.filter((note) => {
    if (filter === "open" && note.resolved) return false
    if (filter === "resolved" && !note.resolved) return false
    if (selectedTag && !note.tags.includes(selectedTag)) return false
    return true
  })

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newContent.trim()) return
    setSaving(true)
    try {
      await api.createAnnotation({
        job_id: "global",
        path: newPath.trim() || "/",
        author: newAuthor.trim() || t("revisao.anonymous"),
        text: newContent.trim(),
        tags: parseTags(newTags),
      })
      toast(t("revisao.createdToast"))
      setNewContent("")
      setNewTags("")
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("revisao.createFailed"), "err")
    } finally {
      setSaving(false)
    }
  }

  const toggleResolved = async (note: Annotation) => {
    try {
      await api.resolveAnnotation(note.id, !note.resolved)
      toast(note.resolved ? t("revisao.reopenedToast") : t("revisao.resolvedToast"))
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("revisao.statusFailed"), "err")
    }
  }

  const handleDelete = async (note: Annotation) => {
    setConfirmDelete(null)
    try {
      await api.deleteAnnotation(note.id)
      toast(t("revisao.deletedToast"))
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("revisao.deleteFailed"), "err")
    }
  }

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("revisao.title")}</h1>
        <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
          {counts.total} {t("revisao.notesWord")} · {counts.open} {t("revisao.openWord")} · {counts.resolved} {t("revisao.resolvedWord")}
        </span>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("revisao.loadError")}{error}</p>
        </div>
      )}

      {/* Inline filters */}
      <div className="filters flex-wrap" style={{ gap: "1ch 1.5ch", marginTop: "0.5lh" }}>
        <div className="toggles" role="group" aria-label={t("revisao.filterAria")}>
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className="tgl"
              aria-pressed={filter === f.value}
              onClick={() => setFilter(f.value)}
            >
              {t(f.key)}
            </button>
          ))}
        </div>

        {Object.keys(counts.by_tag).length > 0 && (
          <div className="tui-tags">
            {Object.entries(counts.by_tag).map(([t, c]) => (
              <button
                key={t}
                type="button"
                className={`tui-tag${selectedTag === t ? " active" : ""}`}
                onClick={() => setSelectedTag(selectedTag === t ? null : t)}
              >
                {t} <span style={{ color: "var(--fg-dim)" }}>{c}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Quick add-note form */}
      <form onSubmit={handleCreate} className="tui-panel" style={{ marginTop: "0.5lh" }}>
        <span className="tui-label">{t("revisao.newNoteLabel")}</span>
        <div className="flex gap-2 flex-wrap" style={{ marginTop: "0.25lh" }}>
          <input
            className="tui-input"
            value={newPath}
            placeholder={t("revisao.pathPlaceholder")}
            onChange={(e) => setNewPath(e.target.value)}
            style={{ maxWidth: "24ch" }}
          />
          <input
            className="tui-input"
            value={newAuthor}
            placeholder={t("revisao.authorPlaceholder")}
            onChange={(e) => setNewAuthor(e.target.value)}
            style={{ maxWidth: "20ch" }}
          />
          <input
            className="tui-input"
            value={newTags}
            placeholder={t("revisao.tagsPlaceholder")}
            onChange={(e) => setNewTags(e.target.value)}
            style={{ flex: 1, minWidth: "16ch" }}
          />
        </div>
        <textarea
          className="tui-textarea"
          value={newContent}
          placeholder={t("revisao.contentPlaceholder")}
          onChange={(e) => setNewContent(e.target.value)}
          rows={2}
          style={{ minHeight: "3lh", marginTop: "0.25lh" }}
        />
        <div className="flex justify-end">
          <button
            type="submit"
            className="tui-btn accent"
            disabled={saving || !newContent.trim()}
          >
            {saving ? <Spinner /> : t("revisao.addNoteBtn")}
          </button>
        </div>
      </form>

      {/* Notes list */}
      {loading ? (
        <p className="empty"><Spinner /> {t("revisao.loadingNotes")}</p>
      ) : filtered.length === 0 ? (
        <p className="empty">{t("revisao.emptyFiltered")}</p>
      ) : (
        <div className="rows" style={{ marginTop: "0.5lh" }}>
          {filtered.map((note) => (
            <div
              key={note.id}
              style={{
                borderBottom: "1px solid var(--line)",
                padding: "0.5lh 0",
                display: "flex",
                flexDirection: "column",
                gap: "0.25lh",
              }}
            >
              <div className="flex items-baseline justify-between">
                <div className="flex items-baseline gap-2">
                  <span style={{ color: note.resolved ? "var(--ok)" : "var(--warn)" }}>
                    {note.resolved ? SYM.ok : SYM.on}
                  </span>
                  <span style={{ fontWeight: 500, color: "var(--fg)" }}>{note.author}</span>
                  <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>{t("revisao.atWord")} {note.path}</span>
                  <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>· {timeAgo(note.created_at)}</span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="tui-btn"
                    onClick={() => void toggleResolved(note)}
                    style={{ fontSize: 11 }}
                  >
                    {note.resolved ? t("revisao.reopenBtn") : t("revisao.markResolvedBtn")}
                  </button>
                  <button
                    type="button"
                    className="tui-btn danger"
                    onClick={() => setConfirmDelete(note)}
                    style={{ fontSize: 11 }}
                  >
                    {t("revisao.deleteBtn")}
                  </button>
                </div>
              </div>

              <p style={{ color: "var(--fg)", margin: "0.25lh 0", whiteSpace: "pre-wrap" }}>
                {note.text}
              </p>

              {note.tags.length > 0 && (
                <div className="tui-tags">
                  {note.tags.map((t) => (
                    <span key={t} className="tui-tag" style={{ cursor: "default" }}>
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {confirmDelete && (
        <TuiModal open={true} title={t("revisao.deleteTitle")} onClose={() => setConfirmDelete(null)}>
          <p>{t("revisao.deleteBodyPrefix")}<b>{confirmDelete.author}</b>?</p>
          <div className="flex justify-end gap-2" style={{ marginTop: "0.5lh" }}>
            <button type="button" className="tui-btn danger" onClick={() => void handleDelete(confirmDelete)}>
              {t("revisao.confirmDeleteBtn")}
            </button>
            <button type="button" className="tui-btn" onClick={() => setConfirmDelete(null)}>
              {t("revisao.cancel")}
            </button>
          </div>
        </TuiModal>
      )}
    </>
  )
}

export const Route = createFileRoute("/revisao")({
  component: RevisaoPage,
})

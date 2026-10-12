import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, Annotation, AnnotationCounts } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { timeAgo } from "@/lib/utils"
import { Spinner } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

type ResolvedFilter = "all" | "open" | "resolved"

const FILTERS: { value: ResolvedFilter; key: "revisao.filterAll" | "revisao.filterOpen" | "revisao.filterResolved" }[] = [
  { value: "all", key: "revisao.filterAll" },
  { value: "open", key: "revisao.filterOpen" },
  { value: "resolved", key: "revisao.filterResolved" },
]

function parseTags(value: string): string[] {
  return Array.from(new Set(value.split(",").map((t) => t.trim()).filter(Boolean)))
}

function countAnnotations(notes: Annotation[]): AnnotationCounts {
  const by_author: Record<string, number> = {}
  const by_tag: Record<string, number> = {}
  let open = 0, resolved = 0
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
    try { setNotes(await api.getAnnotations()) } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])
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
      await api.createAnnotation({ job_id: "global", path: newPath.trim() || "/", author: newAuthor.trim() || t("revisao.anonymous"), text: newContent.trim(), tags: parseTags(newTags) })
      toast(t("revisao.createdToast"))
      setNewContent(""); setNewTags("")
      void load()
    } catch (e) { toast(e instanceof Error ? e.message : t("revisao.createFailed"), "err") } finally { setSaving(false) }
  }

  const toggleResolved = async (note: Annotation) => {
    try { await api.resolveAnnotation(note.id, !note.resolved); toast(note.resolved ? t("revisao.reopenedToast") : t("revisao.resolvedToast")); void load() } catch (e) { toast(e instanceof Error ? e.message : t("revisao.statusFailed"), "err") }
  }

  const handleDelete = async (note: Annotation) => {
    setConfirmDelete(null)
    try { await api.deleteAnnotation(note.id); toast(t("revisao.deletedToast")); void load() } catch (e) { toast(e instanceof Error ? e.message : t("revisao.deleteFailed"), "err") }
  }

  return (
    <div className="zf-view">
      <div className="zf-head">
        <h1 className="zf-title">{t("revisao.title")}</h1>
        <span className="zf-meta">{counts.total} {t("revisao.notesWord")} · {counts.open} {t("revisao.openWord")} · {counts.resolved} {t("revisao.resolvedWord")}</span>
      </div>

      {error && <div className="zf-panel" style={{ borderColor: "var(--error)" }}><div className="zf-panel-bd"><p style={{ color: "var(--error)", fontSize: "var(--fs-meta)" }}>✗ {t("revisao.loadError")}{error}</p></div></div>}

      <div className="zf-filters">
        <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }} role="group" aria-label={t("revisao.filterAria")}>
          {FILTERS.map((f) => (<button key={f.value} type="button" className="zf-pill" aria-pressed={filter === f.value} onClick={() => setFilter(f.value)}>{t(f.key)}</button>))}
        </div>
        {Object.keys(counts.by_tag).length > 0 && (
          <div className="zf-chips">
            {Object.entries(counts.by_tag).map(([tag, c]) => (
              <button key={tag} type="button" className="zf-chip" aria-pressed={selectedTag === tag} onClick={() => setSelectedTag(selectedTag === tag ? null : tag)}>{tag} <span className="zf-meta">{c}</span></button>
            ))}
          </div>
        )}
      </div>

      <form onSubmit={handleCreate} className="zf-panel">
        <div className="zf-panel-hd"><span className="zf-label">{t("revisao.newNoteLabel")}</span></div>
        <div className="zf-panel-bd">
          <div className="zf-split zf-split--2">
            <label className="zf-field"><span className="zf-label">{t("revisao.pathPlaceholder")}</span><input className="zf-input" value={newPath} placeholder={t("revisao.pathPlaceholder")} onChange={(e) => setNewPath(e.target.value)} /></label>
            <label className="zf-field"><span className="zf-label">{t("revisao.authorPlaceholder")}</span><input className="zf-input" value={newAuthor} placeholder={t("revisao.authorPlaceholder")} onChange={(e) => setNewAuthor(e.target.value)} /></label>
          </div>
          <label className="zf-field"><span className="zf-label">{t("revisao.tagsPlaceholder")}</span><input className="zf-input" value={newTags} placeholder={t("revisao.tagsPlaceholder")} onChange={(e) => setNewTags(e.target.value)} /></label>
          <label className="zf-field"><span className="zf-label">{t("revisao.contentPlaceholder")}</span><textarea className="zf-input" value={newContent} placeholder={t("revisao.contentPlaceholder")} onChange={(e) => setNewContent(e.target.value)} rows={2} style={{ minHeight: "3lh" }} /></label>
          <div className="zf-row" style={{ justifyContent: "flex-end" }}>
            <button type="submit" className="zf-btn zf-btn--primary" disabled={saving || !newContent.trim()}>{saving ? <Spinner /> : t("revisao.addNoteBtn")}</button>
          </div>
        </div>
      </form>

      {loading ? <p className="zf-meta"><Spinner /> {t("revisao.loadingNotes")}</p>
      : filtered.length === 0 ? <p className="zf-meta">{t("revisao.emptyFiltered")}</p>
      : (
        <div className="zf-list" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
          {filtered.map((note) => (
            <div key={note.id} style={{ flexDirection: "column", alignItems: "stretch", gap: "var(--s2)" }}>
              <div className="zf-row" style={{ justifyContent: "space-between", width: "100%" }}>
                <div className="zf-row">
                  <span className={`zf-flag ${note.resolved ? "zf-flag--ok" : "zf-flag--warn"}`}>{note.resolved ? "✓" : "○"}</span>
                  <span style={{ fontWeight: 550 }}>{note.author}</span>
                  <span className="zf-meta">{t("revisao.atWord")} {note.path} · {timeAgo(note.created_at)}</span>
                </div>
                <div className="zf-row">
                  <button type="button" className="zf-btn" onClick={() => void toggleResolved(note)}>{note.resolved ? t("revisao.reopenBtn") : t("revisao.markResolvedBtn")}</button>
                  <button type="button" className="zf-btn zf-btn--danger" onClick={() => setConfirmDelete(note)}>{t("revisao.deleteBtn")}</button>
                </div>
              </div>
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{note.text}</p>
              {note.tags.length > 0 && (
                <div className="zf-chips">{note.tags.map((tg) => (<span key={tg} className="zf-chip" style={{ cursor: "default" }}>{tg}</span>))}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {confirmDelete && (
        <dialog open className="zf-modal" onClose={() => setConfirmDelete(null)}>
          <div className="zf-modal-hd"><span style={{ fontWeight: 600 }}>{t("revisao.deleteTitle")}</span><span className="zf-spacer" /><button type="button" className="zf-btn zf-btn--ghost" onClick={() => setConfirmDelete(null)}>✗</button></div>
          <div className="zf-modal-bd"><p>{t("revisao.deleteBodyPrefix")}<b>{confirmDelete.author}</b>?</p></div>
          <div className="zf-modal-ft">
            <button type="button" className="zf-btn zf-btn--danger" onClick={() => void handleDelete(confirmDelete)}>{t("revisao.confirmDeleteBtn")}</button>
            <button type="button" className="zf-btn" onClick={() => setConfirmDelete(null)}>{t("revisao.cancel")}</button>
          </div>
        </dialog>
      )}
    </div>
  )
}

export const Route = createFileRoute("/revisao")({
  component: RevisaoPage,
})

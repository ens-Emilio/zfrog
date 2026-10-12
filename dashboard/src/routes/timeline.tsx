import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"
import { api, ArchivedPage, SnapshotEntry, TimelineEntry } from "@/lib/api"
import { formatBytes, formatStamp } from "@/lib/utils"
import { Spinner } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

function TimelinePage() {
  const t = useT()
  const [sites, setSites] = useState<SnapshotEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [slug, setSlug] = useState("")
  const [entries, setEntries] = useState<TimelineEntry[]>([])
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [selectedRef, setSelectedRef] = useState("")
  const [pages, setPages] = useState<ArchivedPage[]>([])
  const [pagesLoading, setPagesLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState("")
  const [selectedPage, setSelectedPage] = useState<ArchivedPage | null>(null)
  const [pageLoading, setPageLoading] = useState(false)

  const loadSites = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getSnapshots()
      setSites(data)
      const slugs = Array.from(new Set(data.map((s) => s.slug)))
      setSlug((cur) => (cur && slugs.includes(cur) ? cur : slugs[0] ?? ""))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void loadSites() }, [loadSites])
  const slugs = Array.from(new Set(sites.map((s) => s.slug)))

  useEffect(() => {
    if (!slug) return
    let active = true
    setTimelineLoading(true); setSelectedRef(""); setPages([]); setSelectedPage(null)
    api.getTimeline(slug).then((res) => {
      if (!active) return
      setEntries(res.entries)
      if (res.entries.length > 0) setSelectedRef(res.entries[0].ref)
    }).catch(() => {}).finally(() => { if (active) setTimelineLoading(false) })
    return () => { active = false }
  }, [slug])

  useEffect(() => {
    if (!slug || !selectedRef) return
    let active = true
    setPagesLoading(true); setSelectedPage(null)
    api.getTimelinePages(slug, selectedRef).then((res) => {
      if (!active) return
      setPages(res)
      if (res.length > 0) setSelectedPath(res[0].path)
    }).catch(() => {}).finally(() => { if (active) setPagesLoading(false) })
    return () => { active = false }
  }, [slug, selectedRef])

  useEffect(() => {
    if (!slug || !selectedRef || !selectedPath) return
    let active = true
    setPageLoading(true)
    api.getTimelinePage(slug, selectedRef, selectedPath).then((p: ArchivedPage) => { if (active) setSelectedPage(p) }).catch(() => {}).finally(() => { if (active) setPageLoading(false) })
    return () => { active = false }
  }, [slug, selectedRef, selectedPath])

  return (
    <div className="zf-view">
      <div className="zf-head">
        <h1 className="zf-title">{t("timeline.title")}</h1>
        <span className="zf-meta">{t("timeline.subtitle")}</span>
      </div>

      {error && <div className="zf-panel" style={{ borderColor: "var(--error)" }}><div className="zf-panel-bd"><p style={{ color: "var(--error)", fontSize: "var(--fs-meta)" }}>✗ {t("timeline.error")}{error}</p></div></div>}

      <div className="zf-row" style={{ marginBottom: "var(--s4)" }}>
        {slugs.length > 0 && (
          <label className="zf-field" style={{ minWidth: 220 }}>
            <span className="zf-label">site</span>
            <select className="zf-input" value={slug} onChange={(e) => setSlug(e.target.value)}>
              {slugs.map((s) => (<option key={s} value={s}>{s}</option>))}
            </select>
          </label>
        )}
      </div>

      {loading ? <p className="zf-meta"><Spinner /> {t("timeline.loading")}</p>
      : slugs.length === 0 ? <p className="zf-meta">{t("timeline.emptySites")}</p>
      : (
        <div className="zf-split" style={{ gridTemplateColumns: "220px 280px minmax(0, 1fr)" }}>
          <div className="zf-panel" style={{ alignSelf: "start" }}>
            <div className="zf-panel-hd"><span className="zf-label">{t("timeline.versionsLabel")}</span></div>
            <div className="zf-panel-bd" style={{ padding: 0 }}>
              {timelineLoading ? <p className="zf-meta" style={{ padding: "var(--s4)" }}><Spinner /> {t("timeline.loadingShort")}</p>
              : entries.length === 0 ? <p className="zf-meta" style={{ padding: "var(--s4)" }}>{t("timeline.emptyVersions")}</p>
              : (
                <div className="zf-list">
                  {entries.map((en) => {
                    const isSel = en.ref === selectedRef
                    return (
                      <button key={en.ref} type="button" onClick={() => setSelectedRef(en.ref)} style={{ textAlign: "left", border: 0, background: isSel ? "var(--sel-bg)" : "transparent", boxShadow: isSel ? "inset 2px 0 0 var(--accent)" : "none", padding: "var(--s3) var(--s4)", display: "flex", flexDirection: "column", gap: 2, cursor: "pointer", width: "100%" }}>
                        <span style={{ fontWeight: isSel ? 600 : 400, color: isSel ? "var(--accent)" : "var(--fg)" }}>{formatStamp(en.captured_at)}</span>
                        <span className="zf-micro">{en.pages} {t("timeline.pagesSuffix")} · {formatBytes(en.size_bytes)}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="zf-panel" style={{ alignSelf: "start" }}>
            <div className="zf-panel-hd"><span className="zf-label">{t("timeline.pagesLabel")}</span></div>
            <div className="zf-panel-bd" style={{ padding: 0 }}>
              {pagesLoading ? <p className="zf-meta" style={{ padding: "var(--s4)" }}><Spinner /> {t("timeline.loadingPages")}</p>
              : pages.length === 0 ? <p className="zf-meta" style={{ padding: "var(--s4)" }}>{t("timeline.emptyPages")}</p>
              : (
                <div className="zf-list">
                  {pages.map((p) => {
                    const isSel = p.path === selectedPath
                    return (
                      <button key={p.path} type="button" onClick={() => setSelectedPath(p.path)} style={{ textAlign: "left", border: 0, borderBottom: "1px solid var(--border)", background: isSel ? "var(--sel-bg)" : "transparent", boxShadow: isSel ? "inset 2px 0 0 var(--accent)" : "none", padding: "var(--s3) var(--s4)", display: "flex", flexDirection: "column", gap: 2, cursor: "pointer", width: "100%" }}>
                        <span style={{ fontWeight: isSel ? 600 : 400, color: isSel ? "var(--accent)" : "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.title || p.path}</span>
                        <span className="zf-micro">{p.path}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="zf-panel" style={{ alignSelf: "start" }}>
            <div className="zf-panel-hd"><span className="zf-label">{t("timeline.copyLabel")}</span></div>
            <div className="zf-panel-bd">
              {pageLoading ? <p className="zf-meta"><Spinner /> {t("timeline.loadingContent")}</p>
              : selectedPage ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
                  <dl className="zf-kv">
                    <div className="zf-kv-row"><dt>{t("timeline.dtTitle")}</dt><dd>{selectedPage.title || "—"}</dd></div>
                    <div className="zf-kv-row"><dt>{t("timeline.dtPath")}</dt><dd><code>{selectedPage.path}</code></dd></div>
                    <div className="zf-kv-row"><dt>{t("timeline.dtSize")}</dt><dd>{formatBytes(selectedPage.size_bytes)}</dd></div>
                  </dl>
                  {selectedPage.text && <pre className="zf-pre" style={{ maxHeight: 380, overflowY: "auto" }}>{selectedPage.text}</pre>}
                </div>
              ) : <p className="zf-meta">{t("timeline.selectPrompt")}</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export const Route = createFileRoute("/timeline")({
  component: TimelinePage,
})

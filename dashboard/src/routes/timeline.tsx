import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"
import { api, ArchivedPage, SnapshotEntry, TimelineEntry } from "@/lib/api"
import { formatBytes, formatStamp } from "@/lib/utils"
import { Spinner, SYM } from "@/components/ui/tui"
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
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSites()
  }, [loadSites])

  const slugs = Array.from(new Set(sites.map((s) => s.slug)))

  useEffect(() => {
    if (!slug) return
    let active = true
    setTimelineLoading(true)
    setSelectedRef("")
    setPages([])
    setSelectedPage(null)
    api
      .getTimeline(slug)
      .then((res) => {
        if (!active) return
        setEntries(res.entries)
        if (res.entries.length > 0) {
          setSelectedRef(res.entries[0].ref)
        }
      })
      .catch(() => {})
      .finally(() => {
        if (active) setTimelineLoading(false)
      })
    return () => {
      active = false
    }
  }, [slug])

  useEffect(() => {
    if (!slug || !selectedRef) return
    let active = true
    setPagesLoading(true)
    setSelectedPage(null)
    api
      .getTimelinePages(slug, selectedRef)
      .then((res) => {
        if (!active) return
        setPages(res)
        if (res.length > 0) setSelectedPath(res[0].path)
      })
      .catch(() => {})
      .finally(() => {
        if (active) setPagesLoading(false)
      })
    return () => {
      active = false
    }
  }, [slug, selectedRef])

  useEffect(() => {
    if (!slug || !selectedRef || !selectedPath) return
    let active = true
    setPageLoading(true)
    api
      .getTimelinePage(slug, selectedRef, selectedPath)
      .then((p: ArchivedPage) => {
        if (active) setSelectedPage(p)
      })
      .catch(() => {})
      .finally(() => {
        if (active) setPageLoading(false)
      })
    return () => {
      active = false
    }
  }, [slug, selectedRef, selectedPath])

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("timeline.title")}</h1>
        <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
          {t("timeline.subtitle")}
        </span>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("timeline.error")}{error}</p>
        </div>
      )}

      {/* Site selector */}
      <div className="filters flex-wrap" style={{ gap: "1ch 1.5ch", marginTop: "0.5lh" }}>
        {slugs.length > 0 && (
          <select
            className="tui-select"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            style={{ width: "auto" }}
          >
            {slugs.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
      </div>

      {loading ? (
        <p className="empty"><Spinner /> {t("timeline.loading")}</p>
      ) : slugs.length === 0 ? (
        <p className="empty">{t("timeline.emptySites")}</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "24ch 32ch 1fr", gap: "1.5ch", marginTop: "0.5lh" }}>
          {/* Timeline points */}
          <div className="tui-panel" style={{ margin: 0, padding: "0.5lh 1ch" }}>
            <span className="tui-label">{t("timeline.versionsLabel")}</span>
            {timelineLoading ? (
              <p className="empty"><Spinner /> {t("timeline.loadingShort")}</p>
            ) : entries.length === 0 ? (
              <p className="empty" style={{ fontSize: 11 }}>{t("timeline.emptyVersions")}</p>
            ) : (
              <div className="rows" style={{ marginTop: "0.25lh" }}>
                {entries.map((en) => {
                  const isSel = en.ref === selectedRef
                  return (
                    <div
                      key={en.ref}
                      className={`runrow${isSel ? " sel" : ""}`}
                      onClick={() => setSelectedRef(en.ref)}
                      style={{ cursor: "pointer", gridTemplateColumns: "1fr" }}
                    >
                      <span style={{ fontWeight: isSel ? 500 : 400, color: isSel ? "var(--accent)" : "var(--fg)" }}>
                        {formatStamp(en.captured_at)}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>
                        {en.pages} {t("timeline.pagesSuffix")} · {formatBytes(en.size_bytes)}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Archived pages in this version */}
          <div className="tui-panel" style={{ margin: 0, padding: "0.5lh 1ch" }}>
            <span className="tui-label">{t("timeline.pagesLabel")}</span>
            {pagesLoading ? (
              <p className="empty"><Spinner /> {t("timeline.loadingPages")}</p>
            ) : pages.length === 0 ? (
              <p className="empty" style={{ fontSize: 11 }}>{t("timeline.emptyPages")}</p>
            ) : (
              <div className="rows" style={{ marginTop: "0.25lh" }}>
                {pages.map((p) => {
                  const isSel = p.path === selectedPath
                  return (
                    <div
                      key={p.path}
                      className={`runrow${isSel ? " sel" : ""}`}
                      onClick={() => setSelectedPath(p.path)}
                      style={{ cursor: "pointer", gridTemplateColumns: "1fr" }}
                    >
                      <span style={{ fontWeight: isSel ? 500 : 400, color: isSel ? "var(--accent)" : "var(--fg)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {p.title || p.path}
                      </span>
                      <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>
                        {p.path}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Archived page preview */}
          <div className="tui-panel" style={{ margin: 0, padding: "0.5lh 1ch" }}>
            <span className="tui-label">{t("timeline.copyLabel")}</span>
            {pageLoading ? (
              <p className="empty"><Spinner /> {t("timeline.loadingContent")}</p>
            ) : selectedPage ? (
              <div style={{ marginTop: "0.25lh" }}>
                <dl className="tui-kv">
                  <dt>{t("timeline.dtTitle")}</dt>
                  <dd>{selectedPage.title || "—"}</dd>
                  <dt>{t("timeline.dtPath")}</dt>
                  <dd><code>{selectedPage.path}</code></dd>
                  <dt>{t("timeline.dtSize")}</dt>
                  <dd>{formatBytes(selectedPage.size_bytes)}</dd>
                </dl>
                {selectedPage.text && (
                  <div style={{ marginTop: "0.5lh", border: "1px solid var(--line)", maxHeight: 380, overflowY: "auto", padding: "0.5lh 1ch", whiteSpace: "pre-wrap", fontSize: 12 }}>
                    {selectedPage.text}
                  </div>
                )}
              </div>
            ) : (
              <p className="empty" style={{ fontSize: 11 }}>{t("timeline.selectPrompt")}</p>
            )}
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/timeline")({
  component: TimelinePage,
})

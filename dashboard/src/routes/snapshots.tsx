import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useState } from "react"
import { api, DiffReport, SnapshotEntry } from "@/lib/api"
import { formatStamp } from "@/lib/utils"
import { Spinner } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

const MAX_ROWS = 200

function SnapshotsPage() {
  const t = useT()
  const [snapshots, setSnapshots] = useState<SnapshotEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [slug, setSlug] = useState("")
  const [selected, setSelected] = useState<string[]>([])
  const [report, setReport] = useState<DiffReport | null>(null)
  const [comparing, setComparing] = useState(false)
  const [compareError, setCompareError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getSnapshots()
      setSnapshots(data)
      const slugs = Array.from(new Set(data.map((s) => s.slug)))
      setSlug((cur) => (cur && slugs.includes(cur) ? cur : slugs[0] ?? ""))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const slugs = useMemo(() => Array.from(new Set(snapshots.map((s) => s.slug))), [snapshots])
  const items = useMemo(() => snapshots.filter((s) => s.slug === slug), [snapshots, slug])

  const toggleSelect = (file: string) => {
    setSelected((cur) => {
      if (cur.includes(file)) return cur.filter((f) => f !== file)
      if (cur.length >= 2) return [cur[1], file]
      return [...cur, file]
    })
  }

  const runCompare = async () => {
    if (selected.length !== 2) return
    setComparing(true)
    setCompareError(null)
    setReport(null)
    try {
      const diff = await api.diffSnapshots(selected[0], selected[1])
      setReport(diff)
    } catch (e) {
      setCompareError(e instanceof Error ? e.message : String(e))
    } finally {
      setComparing(false)
    }
  }

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("snapshots.title")}</h1>
        <span className="zf-meta">
          {snapshots.length} {t("snapshots.snapshotsWord")} {t("snapshots.inWord")} {slugs.length} {t("snapshots.sitesWord")}
        </span>
        <span style={{ flex: 1 }} />
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>✗ {t("snapshots.loadError")}{error}</p>
        </div>
      )}

      <div className="zf-filters" style={{ marginBottom: "var(--s5)" }}>
        {slugs.length > 0 && (
          <select
            className="zf-select"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value)
              setSelected([])
              setReport(null)
            }}
            style={{ width: "auto", minWidth: 180 }}
            aria-label={t("snapshots.selectSiteAria")}
          >
            {slugs.map((s) => (
              <option key={s} value={s}>
                {s} ({snapshots.filter((x) => x.slug === s).length} {t("snapshots.versions")})
              </option>
            ))}
          </select>
        )}

        <button
          type="button"
          className="zf-btn zf-btn--primary"
          disabled={selected.length !== 2 || comparing}
          onClick={() => void runCompare()}
        >
          {comparing ? <Spinner /> : `${t("snapshots.compareBtn")} (${selected.length}/2)`}
        </button>

        {selected.length > 0 && (
          <button
            type="button"
            className="zf-btn"
            onClick={() => {
              setSelected([])
              setReport(null)
            }}
          >
            {t("snapshots.clearSelection")}
          </button>
        )}
      </div>

      {loading ? (
        <div className="zf-empty"><Spinner /> {t("snapshots.loading")}</div>
      ) : items.length === 0 ? (
        <div className="zf-empty">{t("snapshots.empty")}</div>
      ) : (
        <div className="zf-split zf-split--2">
          <div className="zf-panel">
            <div className="zf-panel-hd">
              <span className="zf-micro">{t("snapshots.savedListLabel")}</span>
              <span style={{ flex: 1 }} />
              <span className="zf-micro">{items.length} {t("snapshots.versions")}</span>
            </div>
            <div className="zf-list">
              {items.map((snap) => {
                const isChecked = selected.includes(snap.file)
                return (
                  <button
                    key={snap.file}
                    type="button"
                    onClick={() => toggleSelect(snap.file)}
                    aria-pressed={isChecked}
                    className={isChecked ? "sel" : undefined}
                    style={{
                      textAlign: "left",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--s3)",
                      width: "100%",
                      border: "none",
                      background: isChecked ? "var(--sel-bg)" : "transparent",
                      boxShadow: isChecked ? "inset 2px 0 0 var(--accent)" : "none",
                      padding: "var(--s2) var(--s4)",
                      borderBottom: "1px solid var(--border)",
                      fontFamily: "var(--font-mono)",
                      fontSize: "var(--fs-meta)",
                    }}
                  >
                    <span style={{ color: isChecked ? "var(--accent)" : "var(--muted)", flexShrink: 0 }}>{isChecked ? "☑" : "☐"}</span>
                    <span style={{ flexShrink: 0 }}>{formatStamp(snap.captured_at)}</span>
                    <span style={{ color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                      {snap.file}
                    </span>
                    <span className="zf-micro" style={{ flexShrink: 0, textTransform: "none", letterSpacing: 0 }}>
                      {snap.pages} {t("snapshots.pagesSuffix")}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {report ? (
            <div className="zf-panel">
              <div className="zf-panel-hd">
                <span className="zf-micro">{t("snapshots.reportTitle")}</span>
                <span style={{ flex: 1 }} />
                <span className="zf-micro" style={{ textTransform: "none", letterSpacing: 0 }}>
                  {report.added.length} {t("snapshots.added")} · {report.removed.length} {t("snapshots.removed")} · {report.changed.length} {t("snapshots.changed")}
                </span>
              </div>
              <div className="zf-panel-bd">
                <dl className="zf-kv">
                  <dt>{t("snapshots.addedPlus")}</dt>
                  <dd style={{ color: "var(--ok)" }}>{report.added.length}</dd>
                  <dt>{t("snapshots.removedMinus")}</dt>
                  <dd style={{ color: "var(--error)" }}>{report.removed.length}</dd>
                  <dt>{t("snapshots.changedTilde")}</dt>
                  <dd style={{ color: "var(--warn)" }}>{report.changed.length}</dd>
                  <dt>{t("snapshots.unchanged")}</dt>
                  <dd>{report.unchanged.length}</dd>
                </dl>

                <div style={{ maxHeight: 320, overflowY: "auto", fontFamily: "var(--font-mono)", fontSize: "var(--fs-meta)", display: "flex", flexDirection: "column", gap: 2 }}>
                  {report.added.slice(0, MAX_ROWS).map((p) => (
                    <div key={p} style={{ color: "var(--ok)" }}>+ {p}</div>
                  ))}
                  {report.removed.slice(0, MAX_ROWS).map((p) => (
                    <div key={p} style={{ color: "var(--error)" }}>- {p}</div>
                  ))}
                  {report.changed.slice(0, MAX_ROWS).map((p) => (
                    <div key={p} style={{ color: "var(--warn)" }}>~ {p}</div>
                  ))}
                </div>
              </div>
            </div>
          ) : compareError ? (
            <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)" }}>
              <p style={{ color: "var(--error)", margin: 0 }}>✗ {t("snapshots.diffFailed")}{compareError}</p>
            </div>
          ) : (
            <div className="zf-panel">
              <div className="zf-panel-bd">
                <div className="zf-empty" style={{ margin: 0 }}>{t("snapshots.empty")}</div>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/snapshots")({
  component: SnapshotsPage,
})

import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useState } from "react"
import { api, DiffReport, SnapshotEntry } from "@/lib/api"
import { formatStamp } from "@/lib/utils"
import { Spinner, SYM } from "@/components/ui/tui"
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
      <div className="flex items-baseline justify-between">
        <h1>{t("snapshots.title")}</h1>
        <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
          {snapshots.length} {t("snapshots.snapshotsWord")} {t("snapshots.inWord")} {slugs.length} {t("snapshots.sitesWord")}
        </span>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("snapshots.loadError")}{error}</p>
        </div>
      )}

      {/* Site selector and actions */}
      <div className="filters flex-wrap" style={{ gap: "1ch 1.5ch", marginTop: "0.5lh" }}>
        {slugs.length > 0 && (
          <select
            className="tui-select"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value)
              setSelected([])
              setReport(null)
            }}
            style={{ width: "auto", padding: "0.1lh 0.75ch" }}
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
          className="tui-btn accent"
          disabled={selected.length !== 2 || comparing}
          onClick={() => void runCompare()}
        >
          {comparing ? <Spinner /> : `${t("snapshots.compareBtn")} (${selected.length}/2)`}
        </button>

        {selected.length > 0 && (
          <button
            type="button"
            className="tui-btn"
            onClick={() => {
              setSelected([])
              setReport(null)
            }}
          >
            {t("snapshots.clearSelection")}
          </button>
        )}
      </div>

      {/* Snapshot list for the site */}
      {loading ? (
        <p className="empty"><Spinner /> {t("snapshots.loading")}</p>
      ) : items.length === 0 ? (
        <p className="empty">{t("snapshots.empty")}</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: report ? "1fr 1fr" : "1fr", gap: "2ch", marginTop: "0.5lh" }}>
          <div>
            <span className="tui-label">{t("snapshots.savedListLabel")}</span>
            <div className="rows" style={{ marginTop: "0.25lh" }}>
              {items.map((snap) => {
                const isChecked = selected.includes(snap.file)
                return (
                  <div
                    key={snap.file}
                    className={`runrow${isChecked ? " sel" : ""}`}
                    onClick={() => toggleSelect(snap.file)}
                    style={{ cursor: "pointer", gridTemplateColumns: "2ch 16ch 1fr auto" }}
                  >
                    <span>{isChecked ? "[x]" : "[ ]"}</span>
                    <span>{formatStamp(snap.captured_at)}</span>
                    <span style={{ color: "var(--fg-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {snap.file}
                    </span>
                    <span style={{ color: "var(--fg-dim)" }}>
                      {snap.pages} {t("snapshots.pagesSuffix")}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Diff report */}
          {report && (
            <div className="tui-panel" style={{ marginTop: 0 }}>
              <div className="tui-panel-head">
                <span className="tui-label">{t("snapshots.reportTitle")}</span>
                <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>
                  {report.added.length} {t("snapshots.added")} · {report.removed.length} {t("snapshots.removed")} · {report.changed.length} {t("snapshots.changed")}
                </span>
              </div>

              <dl className="tui-kv">
                <dt>{t("snapshots.addedPlus")}</dt>
                <dd style={{ color: "var(--ok)" }}>{report.added.length}</dd>
                <dt>{t("snapshots.removedMinus")}</dt>
                <dd style={{ color: "var(--error)" }}>{report.removed.length}</dd>
                <dt>{t("snapshots.changedTilde")}</dt>
                <dd style={{ color: "var(--warn)" }}>{report.changed.length}</dd>
                <dt>{t("snapshots.unchanged")}</dt>
                <dd>{report.unchanged.length}</dd>
              </dl>

              <div style={{ maxHeight: "320px", overflowY: "auto", fontFamily: "inherit", fontSize: 12 }}>
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
          )}

          {compareError && (
            <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
              <p style={{ color: "var(--error)" }}>{SYM.fail} {t("snapshots.diffFailed")}{compareError}</p>
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

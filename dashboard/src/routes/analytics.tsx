import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useState } from "react"
import { api, AnalyticsTotals, EngineStats, Job } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { formatBytes, formatNumber } from "@/lib/utils"
import { Spinner, SYM } from "@/components/ui/tui"

const WEEKS = 8

type WeekBucket = {
  key: string
  label: string
  total: number
  completed: number
}

function weekStart(d: Date): Date {
  const start = new Date(d)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  return start
}

function weekBuckets(jobs: Job[]): WeekBucket[] {
  const thisWeek = weekStart(new Date())
  const buckets: WeekBucket[] = []
  for (let offset = WEEKS - 1; offset >= 0; offset--) {
    const start = new Date(thisWeek)
    start.setDate(thisWeek.getDate() - offset * 7)
    const k = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`
    buckets.push({ key: k, label: `S${WEEKS - offset}`, total: 0, completed: 0 })
  }
  const idx = new Map(buckets.map((b, i) => [b.key, i]))
  for (const job of jobs) {
    const created = new Date(job.created_at)
    if (Number.isNaN(created.getTime())) continue
    const wk = weekStart(created)
    const wkKey = `${wk.getFullYear()}-${String(wk.getMonth() + 1).padStart(2, "0")}-${String(wk.getDate()).padStart(2, "0")}`
    const pos = idx.get(wkKey)
    if (pos !== undefined) {
      buckets[pos].total += 1
      if (job.status === "completed") buckets[pos].completed += 1
    }
  }
  return buckets
}

function AnalyticsPage() {
  const t = useT()
  const [totals, setTotals] = useState<AnalyticsTotals | null>(null)
  const [engines, setEngines] = useState<EngineStats[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [totalsData, enginesData, jobsData] = await Promise.all([
        api.getAnalyticsTotals(),
        api.getEngineStats(),
        api.getJobs(),
      ])
      setTotals(totalsData)
      setEngines(enginesData)
      setJobs(jobsData)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const weeks = useMemo(() => weekBuckets(jobs), [jobs])
  const maxWeekTotal = useMemo(() => Math.max(...weeks.map((w) => w.total), 1), [weeks])

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("analytics.title")}</h1>
        <span className="spacer" style={{ flex: 1 }} />
        <button type="button" className="zf-btn" onClick={() => void load()}>
          {t("analytics.refresh")}
        </button>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>{SYM.fail} {t("analytics.readError")} {error}</p>
        </div>
      )}

      {loading ? (
        <div className="zf-empty"><Spinner /> {t("analytics.loading")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          {/* Consolidated totals as zf-stat cards */}
          {totals && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "var(--s3)" }}>
              <div className="zf-stat">
                <span className="v zf-num">{formatNumber(totals.runs)}</span>
                <span className="l">{t("analytics.totalRuns")}</span>
              </div>
              <div className="zf-stat">
                <span className="v zf-num" style={{ color: totals.success_rate >= 0.8 ? "var(--ok)" : "var(--warn)" }}>
                  {(totals.success_rate * 100).toFixed(1)}%
                </span>
                <span className="l">{t("analytics.globalSuccessRate")}</span>
              </div>
              <div className="zf-stat">
                <span className="v zf-num">{formatBytes(totals.bytes)}</span>
                <span className="l">{t("analytics.totalVolume")}</span>
              </div>
            </div>
          )}

          {/* Per-engine table */}
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("analytics.perEngine")}</span></div>
            <div style={{ overflowX: "auto" }}>
              <table className="zf-table">
                <thead>
                  <tr>
                    <th>{t("analytics.engine")}</th>
                    <th>{t("analytics.runs")}</th>
                    <th>{t("analytics.success")}</th>
                    <th>{t("analytics.avgDuration")}</th>
                  </tr>
                </thead>
                <tbody>
                  {engines.map((e) => (
                    <tr key={e.engine}>
                      <td style={{ fontWeight: 500 }}>{e.engine}</td>
                      <td className="zf-num">{formatNumber(e.runs)}</td>
                      <td style={{ color: e.success_rate >= 0.8 ? "var(--ok)" : "var(--warn)" }} className="zf-num">
                        {(e.success_rate * 100).toFixed(1)}%
                      </td>
                      <td className="zf-num" style={{ color: "var(--muted)" }}>{e.avg_duration_s.toFixed(1)}s</td>
                    </tr>
                  ))}
                  {engines.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ color: "var(--muted)" }}>{t("analytics.noMetrics")}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Weekly completion as zf-bars */}
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("analytics.weekCompletion")}</span></div>
            <div className="zf-panel-bd">
              <div className="zf-bars" role="img" aria-label={t("analytics.weekCompletion")}>
                {weeks.map((w) => {
                  const pct = w.total > 0 ? Math.round((w.completed / Math.max(w.total, 1)) * 100) : 0
                  const h = w.total > 0 ? `${Math.max(6, pct)}%` : "2px"
                  return (
                    <i
                      key={w.key}
                      title={`${w.label}: ${w.completed}/${w.total} (${pct}%)`}
                      style={{
                        height: h,
                        background: w.total > 0 ? "var(--accent-soft)" : "var(--border)",
                        borderTopColor: w.total > 0 ? "var(--accent)" : "var(--border)",
                        opacity: w.total > 0 ? 1 : 0.5,
                      }}
                    />
                  )
                })}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: "var(--s2)" }}>
                {weeks.map((w) => (
                  <span key={w.key} className="zf-micro" style={{ fontSize: 10 }}>{w.label}</span>
                ))}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: "var(--s3)" }}>
                {weeks.map((w) => {
                  const rate = w.total > 0 ? Math.round((w.completed / w.total) * 100) : null
                  return (
                    <div key={w.key} style={{ display: "flex", alignItems: "baseline", gap: "var(--s2)", fontSize: "var(--fs-meta)" }}>
                      <span className="zf-micro" style={{ width: "5ch" }}>{w.label}</span>
                      <span className="zf-num" style={{ color: w.total ? "var(--fg)" : "var(--muted)", minWidth: "14ch" }}>
                        {rate !== null ? `${rate}% (${w.completed}/${w.total})` : t("analytics.noRuns")}
                      </span>
                      <span className="zf-meta" style={{ marginLeft: "auto", fontSize: 11 }}>{w.total} runs</span>
                    </div>
                  )
                })}
              </div>
              {/* hidden max for a11y scaling reference */}
              <span style={{ display: "none" }}>{maxWeekTotal}</span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/analytics")({
  component: AnalyticsPage,
})

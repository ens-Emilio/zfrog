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

function pad(v: number): string {
  return String(v).padStart(2, "0")
}

function weekStart(d: Date): Date {
  const start = new Date(d)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  return start
}

function weekKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function weekBuckets(jobs: Job[]): WeekBucket[] {
  const thisWeek = weekStart(new Date())
  const buckets: WeekBucket[] = []
  for (let offset = WEEKS - 1; offset >= 0; offset--) {
    const start = new Date(thisWeek)
    start.setDate(thisWeek.getDate() - offset * 7)
    buckets.push({
      key: weekKey(start),
      label: `S${WEEKS - offset}`,
      total: 0,
      completed: 0,
    })
  }
  const idx = new Map(buckets.map((b, i) => [b.key, i]))
  for (const job of jobs) {
    const created = new Date(job.created_at)
    if (Number.isNaN(created.getTime())) continue
    const pos = idx.get(weekKey(weekStart(created)))
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

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("analytics.title")}</h1>
        <button type="button" className="tui-btn" onClick={() => void load()}>
          {t("analytics.refresh")}
        </button>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("analytics.readError")} {error}</p>
        </div>
      )}

      {loading ? (
        <p className="empty"><Spinner /> {t("analytics.loading")}</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1lh", marginTop: "0.5lh" }}>
          {totals && (
            <div className="tui-panel">
              <span className="tui-label">{t("analytics.consolidatedSummary")}</span>
              <dl className="tui-kv">
                <dt>{t("analytics.totalRuns")}</dt>
                <dd>{formatNumber(totals.runs)}</dd>
                <dt>{t("analytics.globalSuccessRate")}</dt>
                <dd style={{ color: totals.success_rate >= 0.8 ? "var(--ok)" : "var(--warn)" }}>
                  {(totals.success_rate * 100).toFixed(1)}%
                </dd>
                <dt>{t("analytics.totalVolume")}</dt>
                <dd>{formatBytes(totals.bytes)}</dd>
              </dl>
            </div>
          )}

          {/* Engines table */}
          <div className="tui-panel">
            <span className="tui-label">{t("analytics.perEngine")}</span>
            <table className="tui-table">
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
                    <td style={{ color: "var(--fg)" }}>{formatNumber(e.runs)}</td>
                    <td style={{ color: e.success_rate >= 0.8 ? "var(--ok)" : "var(--warn)" }}>
                      {(e.success_rate * 100).toFixed(1)}%
                    </td>
                    <td style={{ color: "var(--fg-dim)" }}>{e.avg_duration_s.toFixed(1)}s</td>
                  </tr>
                ))}
                {engines.length === 0 && (
                  <tr>
                    <td colSpan={4} style={{ color: "var(--fg-dim)" }}>{t("analytics.noMetrics")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Weekly success rate trend */}
          <div className="tui-panel">
            <span className="tui-label">{t("analytics.weekCompletion")}</span>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.25lh", marginTop: "0.5lh" }}>
              {weeks.map((w) => {
                const rate = w.total > 0 ? Math.round((w.completed / w.total) * 100) : null
                const bar = rate !== null ? "█".repeat(Math.round(rate / 5)) : ""
                return (
                  <div key={w.key} className="flex items-baseline text-[12px]">
                    <span style={{ color: "var(--fg-dim)", width: "6ch" }}>{w.label}</span>
                    <span style={{ color: "var(--accent)", marginRight: "1ch" }}>{bar || "·"}</span>
                    <span style={{ color: "var(--fg-dim)" }}>
                      {rate !== null ? `${rate}% (${w.completed}/${w.total})` : t("analytics.noRuns")}
                    </span>
                  </div>
                )
              })}
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

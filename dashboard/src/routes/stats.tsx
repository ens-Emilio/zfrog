import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useState } from "react"
import { api, AnalyticsTotals, Job, SystemStats } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { formatBytes, formatNumber } from "@/lib/utils"
import { Spinner, SYM } from "@/components/ui/tui"

const DAYS = 14
const TOP_DOMAINS = 8

/** Fill {name} placeholders in a translated string. */
function fmt(s: string, vars: Record<string, string | number>): string {
  return s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""))
}

type DayBucket = {
  key: string
  label: string
  value: number
}

function pad(v: number): string {
  return String(v).padStart(2, "0")
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function countByDay(jobs: Job[]): DayBucket[] {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const buckets: DayBucket[] = []
  for (let offset = DAYS - 1; offset >= 0; offset--) {
    const d = new Date(today)
    d.setDate(today.getDate() - offset)
    buckets.push({
      key: dayKey(d),
      label: `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`,
      value: 0,
    })
  }
  const idx = new Map(buckets.map((b, i) => [b.key, i]))
  for (const job of jobs) {
    const created = new Date(job.created_at)
    if (Number.isNaN(created.getTime())) continue
    const pos = idx.get(dayKey(created))
    if (pos !== undefined) buckets[pos].value += 1
  }
  return buckets
}

function countByDomain(jobs: Job[]): { host: string; value: number }[] {
  const counts = new Map<string, number>()
  for (const job of jobs) {
    let host = job.url
    try {
      host = new URL(job.url).host
    } catch {
      /* ignore invalid url */
    }
    if (!host) continue
    counts.set(host, (counts.get(host) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([host, value]) => ({ host, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, TOP_DOMAINS)
}

function StatsPage() {
  const t = useT()
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [totals, setTotals] = useState<AnalyticsTotals | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, t2, j] = await Promise.all([
        api.getStats(),
        api.getAnalyticsTotals(),
        api.getJobs(),
      ])
      setStats(s)
      setTotals(t2)
      setJobs(j)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const days = useMemo(() => countByDay(jobs), [jobs])
  const maxDay = useMemo(() => Math.max(...days.map((d) => d.value), 1), [days])
  const domains = useMemo(() => countByDomain(jobs), [jobs])

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("stats.title")}</h1>
        <button type="button" className="tui-btn" onClick={() => void load()}>
          {t("stats.refresh")}
        </button>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {fmt(t("stats.readError"), { msg: error })}</p>
        </div>
      )}

      {loading ? (
        <p className="empty"><Spinner /> {t("stats.loading")}</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1lh", marginTop: "0.5lh" }}>
          {/* System metrics */}
          <div className="tui-panel">
            <span className="tui-label">{t("stats.overview")}</span>
            <dl className="tui-kv">
              <dt>{t("stats.totalJobs")}</dt>
              <dd>{formatNumber(stats?.total_jobs ?? jobs.length)}</dd>
              <dt>{t("stats.successes")}</dt>
              <dd style={{ color: "var(--ok)" }}>{formatNumber(stats?.completed ?? 0)} ({SYM.ok})</dd>
              <dt>{t("stats.inProgress")}</dt>
              <dd style={{ color: "var(--warn)" }}>{formatNumber(stats?.running ?? 0)} ({SYM.on})</dd>
              <dt>{t("stats.failures")}</dt>
              <dd style={{ color: "var(--error)" }}>{formatNumber(stats?.failed ?? 0)} ({SYM.fail})</dd>
              <dt>{t("stats.concurrentSlots")}</dt>
              <dd>{stats?.concurrent_slots_available ?? "—"}</dd>
              <dt>{t("stats.requestRate")}</dt>
              <dd>{stats?.rate_limit_rps ?? 1.0} {t("stats.reqPerSec")}</dd>
              <dt>{t("stats.totalVolume")}</dt>
              <dd>
                {fmt(t("stats.volumeRuns"), {
                  bytes: formatBytes(totals?.bytes ?? 0),
                  runs: formatNumber(totals?.runs ?? 0),
                })}
              </dd>
            </dl>
          </div>

          {/* 14-day ASCII histogram */}
          <div className="tui-panel">
            <span className="tui-label">{t("stats.last14Days")}</span>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.15lh", marginTop: "0.5lh", fontFamily: "inherit" }}>
              {days.map((b) => {
                const barLen = Math.round((b.value / maxDay) * 24)
                const bar = "█".repeat(barLen)
                return (
                  <div key={b.key} className="flex items-baseline text-[12px]">
                    <span style={{ color: "var(--fg-dim)", width: "7ch" }}>{b.label}</span>
                    <span style={{ color: b.value > 0 ? "var(--accent)" : "var(--line)", marginRight: "1ch" }}>
                      {bar || "·"}
                    </span>
                    <span style={{ color: "var(--fg-dim)" }}>{b.value}</span>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Top domains */}
          {domains.length > 0 && (
            <div className="tui-panel">
              <span className="tui-label">{t("stats.topDomains")}</span>
              <table className="tui-table">
                <thead>
                  <tr>
                    <th>{t("stats.domain")}</th>
                    <th>{t("stats.captures")}</th>
                  </tr>
                </thead>
                <tbody>
                  {domains.map((d) => (
                    <tr key={d.host}>
                      <td style={{ fontWeight: 500 }}>{d.host}</td>
                      <td style={{ color: "var(--fg-dim)" }}>{d.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/stats")({
  component: StatsPage,
})

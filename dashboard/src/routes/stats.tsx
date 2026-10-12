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
    d.setDate(d.getDate() - offset)
    const k = dayKey(d)
    const label = `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`
    buckets.push({ key: k, label, value: 0 })
  }
  const idx = new Map(buckets.map((b, i) => [b.key, i]))
  for (const job of jobs) {
    const k = dayKey(new Date(job.created_at))
    const i = idx.get(k)
    if (i !== undefined) buckets[i].value += 1
  }
  return buckets
}

function countByDomain(jobs: Job[]): { host: string; value: number }[] {
  const m = new Map<string, number>()
  for (const j of jobs) {
    try {
      const h = new URL(j.url).host
      m.set(h, (m.get(h) ?? 0) + 1)
    } catch {
      const raw = j.url.replace(/^https?:\/\//, "").split("/")[0] || j.url
      m.set(raw, (m.get(raw) ?? 0) + 1)
    }
  }
  return [...m.entries()]
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
      <div className="zf-head">
        <h1 className="zf-title">{t("stats.title")}</h1>
        <span className="spacer" style={{ flex: 1 }} />
        <button type="button" className="zf-btn" onClick={() => void load()}>
          {t("stats.refresh")}
        </button>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>{SYM.fail} {fmt(t("stats.readError"), { msg: error })}</p>
        </div>
      )}

      {loading ? (
        <div className="zf-empty"><Spinner /> {t("stats.loading")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          {/* System metrics as stat cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(168px, 1fr))", gap: "var(--s3)" }}>
            <div className="zf-stat">
              <span className="v zf-num">{formatNumber(stats?.total_jobs ?? jobs.length)}</span>
              <span className="l">{t("stats.totalJobs")}</span>
            </div>
            <div className="zf-stat">
              <span className="v zf-num" style={{ color: "var(--ok)" }}>{formatNumber(stats?.completed ?? 0)}</span>
              <span className="l">{t("stats.successes")} {SYM.ok}</span>
            </div>
            <div className="zf-stat">
              <span className="v zf-num" style={{ color: "var(--warn)" }}>{formatNumber(stats?.running ?? 0)}</span>
              <span className="l">{t("stats.inProgress")} {SYM.on}</span>
            </div>
            <div className="zf-stat">
              <span className="v zf-num" style={{ color: "var(--error)" }}>{formatNumber(stats?.failed ?? 0)}</span>
              <span className="l">{t("stats.failures")} {SYM.fail}</span>
            </div>
            <div className="zf-stat">
              <span className="v zf-num">{stats?.concurrent_slots_available ?? "—"}</span>
              <span className="l">{t("stats.concurrentSlots")}</span>
            </div>
            <div className="zf-stat">
              <span className="v zf-num">{stats?.rate_limit_rps ?? 1.0}</span>
              <span className="l">{t("stats.requestRate")} · {t("stats.reqPerSec")}</span>
            </div>
            <div className="zf-stat">
              <span className="v zf-num">{formatBytes(totals?.bytes ?? 0)}</span>
              <span className="l">{t("stats.totalVolume").split("·")[0].trim() || t("stats.totalVolume")}</span>
              <span className="m">{fmt(t("stats.volumeRuns"), { bytes: formatBytes(totals?.bytes ?? 0), runs: formatNumber(totals?.runs ?? 0) })}</span>
            </div>
          </div>

          {/* 14-day bars */}
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("stats.last14Days")}</span><span className="zf-spacer" style={{ flex: 1 }} /><span className="zf-meta">{t("stats.last14Days")}</span></div>
            <div className="zf-panel-bd">
              <div className="zf-bars" role="img" aria-label={t("stats.last14Days")}>
                {days.map((b) => {
                  const pct = maxDay > 0 ? Math.max(2, Math.round((b.value / maxDay) * 100)) : 2
                  const h = b.value > 0 ? `${pct}%` : "2px"
                  return (
                    <i
                      key={b.key}
                      title={`${b.label}: ${b.value}`}
                      style={{ height: h, background: b.value > 0 ? "var(--accent-soft)" : "var(--border)", borderTopColor: b.value > 0 ? "var(--accent)" : "var(--border)" }}
                    />
                  )
                })}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: "var(--s2)" }}>
                {days.map((b) => (
                  <span key={b.key} className="zf-micro" style={{ fontSize: 10, color: "var(--muted)" }}>{b.label}</span>
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
                {days.map((b) => (
                  <span key={b.key} className="zf-num" style={{ fontSize: 11, color: b.value ? "var(--fg)" : "var(--muted)" }}>{b.value}</span>
                ))}
              </div>
            </div>
          </div>

          {/* Top domains */}
          {domains.length > 0 && (
            <div className="zf-panel">
              <div className="zf-panel-hd"><span className="zf-micro">{t("stats.topDomains")}</span></div>
              <div style={{ overflowX: "auto" }}>
                <table className="zf-table">
                  <thead>
                    <tr>
                      <th>{t("stats.domain")}</th>
                      <th className="num-col">{t("stats.captures")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {domains.map((d) => (
                      <tr key={d.host}>
                        <td style={{ fontWeight: 500 }}>{d.host}</td>
                        <td className="num-col zf-num">{d.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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

import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"
import { api, Job, RoiResult } from "@/lib/api"
import { formatNumber } from "@/lib/utils"
import { Spinner, SYM } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

function formatMoney(value: number | null, currency: string): string {
  if (value === null || !Number.isFinite(value)) return "—"
  const code = (currency || "").trim().toUpperCase()
  if (code) {
    try {
      return new Intl.NumberFormat("pt-BR", { style: "currency", currency: code }).format(value)
    } catch {
      return `${formatNumber(value)} ${code}`
    }
  }
  return formatNumber(value)
}

function RoiPage() {
  const t = useT()
  const [roi, setRoi] = useState<RoiResult | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [r, j] = await Promise.all([api.getRoi(), api.getJobs()])
      setRoi(r)
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

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("roi.title")}</h1>
        <span className="spacer" style={{ flex: 1 }} />
        <button type="button" className="zf-btn" onClick={() => void load()}>
          {t("roi.refresh")}
        </button>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>{SYM.fail} {t("roi.loadError")}{error}</p>
        </div>
      )}

      {loading ? (
        <div className="zf-empty"><Spinner /> {t("roi.loading")}</div>
      ) : (
        <div className="zf-panel">
          <div className="zf-panel-hd"><span className="zf-micro">{t("roi.estimateLabel")}</span></div>
          <div className="zf-panel-bd">
            <dl className="zf-kv">
              <dt>{t("roi.totalTime")}</dt>
              <dd style={{ color: "var(--ok)", fontWeight: 500 }}>
                {roi?.duration_s != null ? `${(roi.duration_s / 3600).toFixed(1)} ${t("roi.hours")}` : "—"}
              </dd>
              <dt>{t("roi.netSavings")}</dt>
              <dd style={{ color: "var(--ok)", fontWeight: 500 }}>
                {formatMoney(roi?.net ?? null, roi?.currency || "BRL")}
              </dd>
              <dt>{t("roi.pagesCaptured")}</dt>
              <dd className="zf-num">{formatNumber(roi?.pages ?? jobs.length)}</dd>
              <dt>{t("roi.basis")}</dt>
              <dd style={{ color: "var(--muted)" }}>{t("roi.basisDesc")}</dd>
            </dl>
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/roi")({
  component: RoiPage,
})

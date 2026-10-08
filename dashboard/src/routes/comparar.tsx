import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, CompetitiveComparison, TrendsResponse } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { SYM, Spinner, TuiPanel } from "@/components/ui/tui"

type ViewTab = "competitivo" | "tendencias"

function CompararPage() {
  const t = useT()
  const toast = useToast()
  const [tab, setTab] = useState<ViewTab>("competitivo")

  // ── Competitive State ──
  const [siteInputs, setSiteInputs] = useState<string[]>(["", ""])
  const [compResult, setCompResult] = useState<CompetitiveComparison | null>(null)

  // ── Trends State ──
  const [trendUrl, setTrendUrl] = useState("")
  const [trendTerms, setTrendTerms] = useState(t("comparar.defaultTerms"))
  const [trendResult, setTrendResult] = useState<TrendsResponse | null>(null)

  // List of already catalogued sites for convenience
  const catalogSitesQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  // Competitive benchmark mutation
  const compMutation = useMutation({
    mutationFn: async () => {
      const sitesMap: Record<string, string> = {}
      for (const raw of siteInputs) {
        const trimmed = raw.trim()
        if (!trimmed) continue
        const [label, path] = trimmed.includes("=")
          ? trimmed.split("=")
          : [trimmed.replace(/^output\//, ""), trimmed.startsWith("output/") ? trimmed : `output/${trimmed}`]
        sitesMap[label] = path
      }

      if (Object.keys(sitesMap).length < 2) {
        throw new Error(t("comparar.errorMinSites"))
      }

      return api.compareSites(sitesMap)
    },
    onSuccess: (data) => {
      setCompResult(data)
      toast(t("comparar.benchmarkDone"), "ok")
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("comparar.compareError").replace("{msg}", msg), "err")
    },
  })

  // Trends mutation
  const trendMutation = useMutation({
    mutationFn: async () => {
      const url = trendUrl.trim()
      if (!url) throw new Error(t("comparar.errorUrlRequired"))
      const terms = trendTerms
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
      if (terms.length === 0) throw new Error(t("comparar.errorTermRequired"))

      return api.getTrends(url, terms)
    },
    onSuccess: (data) => {
      setTrendResult(data)
      toast(t("comparar.trendsDone"), "ok")
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("comparar.trendsError").replace("{msg}", msg), "err")
    },
  })

  const addSiteField = () => {
    if (siteInputs.length < 5) {
      setSiteInputs([...siteInputs, ""])
    }
  }

  const updateSiteField = (idx: number, val: string) => {
    const next = [...siteInputs]
    next[idx] = val
    setSiteInputs(next)
  }

  const removeSiteField = (idx: number) => {
    if (siteInputs.length > 2) {
      setSiteInputs(siteInputs.filter((_, i) => i !== idx))
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <TuiPanel
        title={t("comparar.title")}
        action={
          <div className="toggles text-xs" role="group" aria-label={t("comparar.modeAria")}>
            <button
              type="button"
              className="tgl"
              aria-pressed={tab === "competitivo"}
              onClick={() => setTab("competitivo")}
            >
              {t("comparar.tabCompetitive")}
            </button>
            <button
              type="button"
              className="tgl"
              aria-pressed={tab === "tendencias"}
              onClick={() => setTab("tendencias")}
            >
              {t("comparar.tabTrends")}
            </button>
          </div>
        }
      >
        <p style={{ color: "var(--fg-muted)", fontSize: 13, marginBottom: "0.25lh" }}>
          {t("comparar.intro")}
        </p>

        {tab === "competitivo" ? (
          <div className="flex flex-col gap-3">
            <div className="tui-panel" style={{ margin: "0.25lh 0" }}>
              <div className="tui-panel-head">
                <span className="tui-panel-title">{t("comparar.step1")}</span>
              </div>

            <div className="flex flex-col gap-2 max-w-2xl">
              {siteInputs.map((siteVal, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <span className="w-16 text-[var(--fg-dim)]">{t("comparar.siteN").replace("{n}", String(idx + 1))}</span>
                  <input
                    type="text"
                    className="tui-input flex-1"
                    placeholder={t("comparar.sitePlaceholder")}
                    value={siteVal}
                    onChange={(e) => updateSiteField(idx, e.target.value)}
                  />
                  {catalogSitesQuery.data && catalogSitesQuery.data.length > 0 && (
                    <select
                      className="tui-select text-xs"
                      value=""
                      onChange={(e) => {
                        if (e.target.value) updateSiteField(idx, e.target.value)
                      }}
                    >
                      <option value="">{t("comparar.chooseFromCatalog")}</option>
                      {catalogSitesQuery.data.map((s) => (
                        <option key={s.site} value={s.site}>
                          {s.site}
                        </option>
                      ))}
                    </select>
                  )}
                  {siteInputs.length > 2 && (
                    <button
                      type="button"
                      className="tui-btn text-xs hover:border-[var(--error)]"
                      onClick={() => removeSiteField(idx)}
                      title={t("comparar.removeTitle")}
                    >
                      {SYM.fail}
                    </button>
                  )}
                </div>
              ))}

              <div className="flex items-center gap-3 mt-2 pt-2 border-t border-[var(--border)]">
                {siteInputs.length < 5 && (
                  <button type="button" className="tui-btn text-xs" onClick={addSiteField}>
                    {t("comparar.addSite")}
                  </button>
                )}
                <button
                  type="button"
                  className="tui-btn accent text-xs"
                  onClick={() => compMutation.mutate()}
                  disabled={compMutation.isPending}
                >
                  {compMutation.isPending ? <Spinner /> : SYM.ok} {t("comparar.runBenchmark")}
                </button>
              </div>
            </div>
          </div>

          {compResult && (
            <div className="tui-panel p-4 flex flex-col gap-4 text-xs">
              <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between">
                <span>{t("comparar.resultTitle")}</span>
                <span className="text-[var(--fg-dim)]">{t("comparar.sitesAnalyzed").replace("{count}", String(Object.keys(compResult.sites).length))}</span>
              </div>

              {compResult.summary && (
                <div className="p-3 bg-[var(--bg-panel)] border border-[var(--border)] leading-relaxed">
                  <span className="font-bold block mb-1">{t("comparar.execSummary")}</span>
                  {compResult.summary}
                </div>
              )}

              {/* Side-by-side matrix */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {Object.entries(compResult.sites).map(([siteKey, details]) => (
                  <div key={siteKey} className="border border-[var(--border)] p-3 rounded">
                    <div className="font-bold text-sm text-[var(--accent)] border-b border-[var(--border)] pb-1 mb-2">
                      {siteKey}
                    </div>
                    <div className="space-y-1.5">
                      <div>
                        <span className="text-[var(--fg-dim)]">{t("comparar.pages")}</span>
                        <b>{details.pages_count ?? "—"}</b>
                      </div>
                      {details.sentiment && (
                        <div>
                          <span className="text-[var(--fg-dim)]">{t("comparar.sentiment")}</span>
                          <span>
                            {details.sentiment.label} ({details.sentiment.score > 0 ? "+" : ""}
                            {details.sentiment.score.toFixed(2)})
                          </span>
                        </div>
                      )}
                      <div>
                        <span className="text-[var(--fg-dim)] block mb-1">{t("comparar.technologies")}</span>
                        <div className="flex flex-wrap gap-1">
                          {details.technologies?.length ? (
                            details.technologies.map((tech) => (
                              <span key={tech} className="px-1.5 py-0.5 bg-[var(--bg-panel)] border border-[var(--border)] text-[10px]">
                                {tech}
                              </span>
                            ))
                          ) : (
                            <span className="text-[var(--fg-dim)]">—</span>
                          )}
                        </div>
                      </div>
                      {details.dominant_colors && details.dominant_colors.length > 0 && (
                        <div>
                          <span className="text-[var(--fg-dim)] block mb-1">{t("comparar.colors")}</span>
                          <div className="flex items-center gap-1">
                            {details.dominant_colors.map((c, i) => (
                              <span
                                key={i}
                                className="w-4 h-4 border border-[var(--border)] inline-block"
                                style={{ backgroundColor: c }}
                                title={c}
                              />
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Trends tab */
        <div className="flex flex-col gap-4">
          <div className="tui-panel p-4 text-xs">
            <div className="font-bold border-b border-[var(--border)] pb-2 mb-3">
              {t("comparar.trendsHeader")}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-3xl">
              <div>
                <label className="text-[var(--fg-dim)] block mb-1">{t("comparar.urlLabel")}</label>
                <input
                  type="text"
                  className="tui-input w-full"
                  placeholder="https://exemplo.com.br"
                  value={trendUrl}
                  onChange={(e) => setTrendUrl(e.target.value)}
                />
              </div>
              <div>
                <label className="text-[var(--fg-dim)] block mb-1">{t("comparar.termsLabel")}</label>
                <input
                  type="text"
                  className="tui-input w-full"
                  placeholder={t("comparar.termsPlaceholder")}
                  value={trendTerms}
                  onChange={(e) => setTrendTerms(e.target.value)}
                />
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-[var(--border)]">
              <button
                type="button"
                className="tui-btn accent text-xs"
                onClick={() => trendMutation.mutate()}
                disabled={trendMutation.isPending}
              >
                {trendMutation.isPending ? <Spinner /> : SYM.ok} {t("comparar.calcTrends")}
              </button>
            </div>
          </div>

          {trendResult && (
            <div className="tui-panel p-4 flex flex-col gap-4 text-xs">
              <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between">
                <span>{t("comparar.trendReport").replace("{url}", trendResult.url)}</span>
                <span className="text-[var(--fg-dim)]">{t("comparar.termsAnalyzed").replace("{count}", String(trendResult.trends.length))}</span>
              </div>

              {trendResult.summary && (
                <div className="p-3 bg-[var(--bg-panel)] border border-[var(--border)] leading-relaxed">
                  <span className="font-bold block mb-1">{t("comparar.evolutionSummary")}</span>
                  {trendResult.summary}
                </div>
              )}

              <div className="flex flex-col gap-3">
                {trendResult.trends.map((item) => (
                  <div key={item.term} className="border border-[var(--border)] p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-sm">
                        “{item.term}”
                      </span>
                      <span className="px-2 py-0.5 border border-[var(--border)] text-[10px] uppercase font-semibold">
                        {t("comparar.trendLabel").replace("{trend}", item.trend)}
                      </span>
                    </div>

                    <div className="space-y-1">
                      {item.counts.map((c, i) => {
                        const maxCount = Math.max(...item.counts.map((x) => x.count), 1)
                        const barLen = Math.round((c.count / maxCount) * 20)
                        const bar = "█".repeat(barLen) + "░".repeat(Math.max(0, 20 - barLen))
                        return (
                          <div key={i} className="flex items-center gap-3 font-mono text-[11px]">
                            <span className="w-24 text-[var(--fg-dim)]">{c.date}</span>
                            <span className="text-[var(--accent)]">{bar}</span>
                            <span>{t("comparar.occurrences").replace("{count}", String(c.count))}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      </TuiPanel>
    </div>
  )
}

export const Route = createFileRoute("/comparar")({
  component: CompararPage,
})

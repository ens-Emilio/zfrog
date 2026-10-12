import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, CompetitiveComparison, TrendsResponse } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { Spinner, SYM } from "@/components/ui/tui"

type ViewTab = "competitivo" | "tendencias"

function CompararPage() {
  const t = useT()
  const toast = useToast()
  const [tab, setTab] = useState<ViewTab>("competitivo")

  const [siteInputs, setSiteInputs] = useState<string[]>(["", ""])
  const [compResult, setCompResult] = useState<CompetitiveComparison | null>(null)

  const [trendUrl, setTrendUrl] = useState("")
  const [trendTerms, setTrendTerms] = useState(t("comparar.defaultTerms"))
  const [trendResult, setTrendResult] = useState<TrendsResponse | null>(null)

  const catalogSitesQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

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
      if (Object.keys(sitesMap).length < 2) throw new Error(t("comparar.errorMinSites"))
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

  const trendMutation = useMutation({
    mutationFn: async () => {
      const url = trendUrl.trim()
      if (!url) throw new Error(t("comparar.errorUrlRequired"))
      const terms = trendTerms.split(",").map((x) => x.trim()).filter(Boolean)
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

  const addSiteField = () => { if (siteInputs.length < 5) setSiteInputs([...siteInputs, ""]) }
  const updateSiteField = (idx: number, val: string) => {
    const next = [...siteInputs]
    next[idx] = val
    setSiteInputs(next)
  }
  const removeSiteField = (idx: number) => {
    if (siteInputs.length > 2) setSiteInputs(siteInputs.filter((_, i) => i !== idx))
  }

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("comparar.title")}</h1>
        <span className="zf-meta">{t("comparar.intro")}</span>
        <span className="spacer" style={{ flex: 1 }} />
      </div>

      <div className="zf-tabs" role="tablist" aria-label={t("comparar.modeAria")}>
        <button type="button" role="tab" className="zf-tab" aria-selected={tab === "competitivo"} onClick={() => setTab("competitivo")}>
          {t("comparar.tabCompetitive")}
        </button>
        <button type="button" role="tab" className="zf-tab" aria-selected={tab === "tendencias"} onClick={() => setTab("tendencias")}>
          {t("comparar.tabTrends")}
        </button>
      </div>

      {tab === "competitivo" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("comparar.step1")}</span></div>
            <div className="zf-panel-bd">
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)", maxWidth: "64ch" }}>
                {siteInputs.map((siteVal, idx) => (
                  <div key={idx} style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
                    <span className="zf-meta" style={{ width: "6ch" }}>{t("comparar.siteN").replace("{n}", String(idx + 1))}</span>
                    <input
                      type="text"
                      className="zf-input"
                      style={{ flex: 1 }}
                      placeholder={t("comparar.sitePlaceholder")}
                      value={siteVal}
                      onChange={(e) => updateSiteField(idx, e.target.value)}
                    />
                    {catalogSitesQuery.data && catalogSitesQuery.data.length > 0 && (
                      <select
                        className="zf-select"
                        value=""
                        onChange={(e) => { if (e.target.value) updateSiteField(idx, e.target.value) }}
                        style={{ maxWidth: "22ch" }}
                      >
                        <option value="">{t("comparar.chooseFromCatalog")}</option>
                        {catalogSitesQuery.data.map((s) => (
                          <option key={s.site} value={s.site}>{s.site}</option>
                        ))}
                      </select>
                    )}
                    {siteInputs.length > 2 && (
                      <button type="button" className="zf-icon-btn" onClick={() => removeSiteField(idx)} title={t("comparar.removeTitle")} aria-label={t("comparar.removeTitle")}>
                        ✗
                      </button>
                    )}
                  </div>
                ))}
                <div style={{ display: "flex", gap: "var(--s2)", paddingTop: "var(--s2)", borderTop: "1px solid var(--border)", marginTop: "var(--s2)" }}>
                  {siteInputs.length < 5 && (
                    <button type="button" className="zf-btn" onClick={addSiteField}>{t("comparar.addSite")}</button>
                  )}
                  <button type="button" className="zf-btn zf-btn--primary" onClick={() => compMutation.mutate()} disabled={compMutation.isPending}>
                    {compMutation.isPending ? <Spinner /> : SYM.ok} {t("comparar.runBenchmark")}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {compResult && (
            <div className="zf-panel">
              <div className="zf-panel-hd">
                <span className="zf-micro">{t("comparar.resultTitle")}</span>
                <span className="zf-meta" style={{ marginLeft: "auto" }}>{t("comparar.sitesAnalyzed").replace("{count}", String(Object.keys(compResult.sites).length))}</span>
              </div>
              <div className="zf-panel-bd">
                {compResult.summary && (
                  <div className="zf-pre" style={{ background: "var(--surface)" }}>
                    <strong style={{ color: "var(--fg)" }}>{t("comparar.execSummary")}</strong>{"\n"}{compResult.summary}
                  </div>
                )}

                <div className="zf-split zf-split--2">
                  {Object.entries(compResult.sites).map(([siteKey, details]) => (
                    <div key={siteKey} className="zf-pane">
                      <div className="zf-pane-hd"><span className="zf-micro" style={{ color: "var(--accent)", fontWeight: 600 }}>{siteKey}</span></div>
                      <div className="zf-pane-bd" style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
                        <dl className="zf-kv">
                          <dt>{t("comparar.pages")}</dt><dd className="zf-num">{details.pages_count ?? "—"}</dd>
                          {details.sentiment && (
                            <>
                              <dt>{t("comparar.sentiment")}</dt>
                              <dd>{details.sentiment.label} ({details.sentiment.score > 0 ? "+" : ""}{details.sentiment.score.toFixed(2)})</dd>
                            </>
                          )}
                        </dl>
                        <div>
                          <div className="zf-micro" style={{ marginBottom: 4 }}>{t("comparar.technologies")}</div>
                          <div className="zf-chips">
                            {details.technologies?.length ? details.technologies.map((tech) => (
                              <span key={tech} className="zf-chip" style={{ cursor: "default" }}>{tech}</span>
                            )) : <span className="zf-meta">—</span>}
                          </div>
                        </div>
                        {details.dominant_colors && details.dominant_colors.length > 0 && (
                          <div>
                            <div className="zf-micro" style={{ marginBottom: 4 }}>{t("comparar.colors")}</div>
                            <div style={{ display: "flex", gap: 4 }}>
                              {details.dominant_colors.map((c, i) => (
                                <span key={i} title={c} style={{ width: 16, height: 16, borderRadius: 3, background: c, border: "1px solid var(--border)", display: "inline-block" }} />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {compResult.matrix && (
                  <div style={{ overflowX: "auto" }}>
                    <table className="zf-table">
                      <thead><tr><th>site</th>{Object.keys(compResult.matrix[Object.keys(compResult.matrix)[0]] ?? {}).map((k) => <th key={k}>{k}</th>)}</tr></thead>
                      <tbody>
                        {Object.entries(compResult.matrix).map(([row, cols]) => (
                          <tr key={row}><td style={{ fontWeight: 600 }}>{row}</td>{Object.values(cols as Record<string, number>).map((v, i) => <td key={i} className="zf-num">{typeof v === "number" ? v.toFixed(2) : String(v)}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("comparar.trendsHeader")}</span></div>
            <div className="zf-panel-bd">
              <div className="zf-split zf-split--2" style={{ maxWidth: "80ch" }}>
                <div className="zf-field">
                  <label className="zf-label">{t("comparar.urlLabel")}</label>
                  <input type="text" className="zf-input" placeholder="https://exemplo.com.br" value={trendUrl} onChange={(e) => setTrendUrl(e.target.value)} />
                </div>
                <div className="zf-field">
                  <label className="zf-label">{t("comparar.termsLabel")}</label>
                  <input type="text" className="zf-input" placeholder={t("comparar.termsPlaceholder")} value={trendTerms} onChange={(e) => setTrendTerms(e.target.value)} />
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", borderTop: "1px solid var(--border)", paddingTop: "var(--s3)", marginTop: "var(--s2)" }}>
                <button type="button" className="zf-btn zf-btn--primary" onClick={() => trendMutation.mutate()} disabled={trendMutation.isPending}>
                  {trendMutation.isPending ? <Spinner /> : SYM.ok} {t("comparar.calcTrends")}
                </button>
              </div>
            </div>
          </div>

          {trendResult && (
            <div className="zf-panel">
              <div className="zf-panel-hd">
                <span className="zf-micro">{t("comparar.trendReport").replace("{url}", trendResult.url)}</span>
                <span className="zf-meta" style={{ marginLeft: "auto" }}>{t("comparar.termsAnalyzed").replace("{count}", String(trendResult.trends.length))}</span>
              </div>
              <div className="zf-panel-bd">
                {trendResult.summary && (
                  <div className="zf-pre" style={{ background: "var(--surface)" }}>
                    <strong style={{ color: "var(--fg)" }}>{t("comparar.evolutionSummary")}</strong>{"\n"}{trendResult.summary}
                  </div>
                )}
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
                  {trendResult.trends.map((item) => (
                    <div key={item.term} className="zf-pane">
                      <div className="zf-pane-hd">
                        <span style={{ fontWeight: 600 }}>“{item.term}”</span>
                        <span className="zf-chip" style={{ marginLeft: "auto", cursor: "default" }}>{t("comparar.trendLabel").replace("{trend}", item.trend)}</span>
                      </div>
                      <div className="zf-pane-bd" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {item.counts.map((c, i) => {
                          const maxCount = Math.max(...item.counts.map((x) => x.count), 1)
                          const pct = Math.max(4, Math.round((c.count / maxCount) * 100))
                          return (
                            <div key={i} style={{ display: "flex", alignItems: "center", gap: "var(--s3)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                              <span style={{ width: "10ch", color: "var(--muted)" }}>{c.date}</span>
                              <div className="zf-bars" style={{ flex: 1, height: 18 }}>
                                <i style={{ width: `${pct}%`, flex: `0 0 ${pct}%` }} />
                              </div>
                              <span className="zf-num" style={{ width: "14ch", textAlign: "right" }}>{t("comparar.occurrences").replace("{count}", String(c.count))}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/comparar")({
  component: CompararPage,
})

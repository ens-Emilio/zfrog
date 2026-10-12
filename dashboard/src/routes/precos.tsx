import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api, PriceChange, PriceRecord } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

function PrecosPage() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [targetUrl, setTargetUrl] = useState("")
  const [selectorInput, setSelectorInput] = useState("")
  const [selectedSite, setSelectedSite] = useState("")

  const pricesQuery = useQuery({
    queryKey: ["prices", selectedSite],
    queryFn: () => (selectedSite ? api.getPrices(selectedSite) : Promise.resolve([])),
    enabled: Boolean(selectedSite),
  })

  const changesQuery = useQuery({
    queryKey: ["price-changes", selectedSite],
    queryFn: () => (selectedSite ? api.getPriceChanges(selectedSite) : Promise.resolve([])),
    enabled: Boolean(selectedSite),
  })

  const catalogQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  const catalogOptions = (catalogQuery.data ?? []).map((s) => ({
    value: `https://${s.site}`,
    label: s.site,
    detail: `${s.count} ${t("workers.pages")}`,
  }))

  const watchMutation = useMutation({
    mutationFn: async (url: string) => {
      const trimmed = url.trim()
      if (!trimmed) throw new Error(t("precos.watchUrlError"))
      return api.watchPrice(trimmed, selectorInput.trim() || undefined)
    },
    onSuccess: (_, url) => {
      toast(t("precos.watchOk"), "ok")
      setSelectedSite(url)
      setTargetUrl("")
      setSelectorInput("")
      void queryClient.invalidateQueries({ queryKey: ["prices"] })
      void queryClient.invalidateQueries({ queryKey: ["price-changes"] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(`${t("precos.watchError")}: ${msg}`, "err")
    },
  })

  const prices: PriceRecord[] = pricesQuery.data ?? []
  const changes: PriceChange[] = changesQuery.data ?? []

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("precos.title")}</h1>
        <span className="zf-meta">{t("precos.subtitle")}</span>
        <span style={{ flex: 1 }} />
        <span className="zf-micro">{t("precos.changesCount").replace("{{count}}", String(changes.length))}</span>
      </div>

      <div className="zf-split zf-split--form">
        <div className="zf-panel">
          <div className="zf-panel-hd">
            <span className="zf-micro">{t("precos.step1")}</span>
          </div>
          <div className="zf-panel-bd">
            <div className="zf-field">
              <label className="zf-label" htmlFor="precos-url">{t("precos.urlLabel")}</label>
              <input
                id="precos-url"
                type="text"
                className="zf-input"
                placeholder="https://loja.com/produto-xyz"
                value={targetUrl}
                onChange={(e) => setTargetUrl(e.target.value)}
              />
            </div>

            <div className="zf-field">
              <label className="zf-label" htmlFor="precos-selector">{t("precos.selectorLabel")}</label>
              <input
                id="precos-selector"
                type="text"
                className="zf-input"
                placeholder=".preco, .price-tag, [data-price]"
                value={selectorInput}
                onChange={(e) => setSelectorInput(e.target.value)}
              />
              <span className="zf-hint">{t("precos.selectorHint")}</span>
            </div>

            <button
              type="button"
              className="zf-btn zf-btn--primary"
              style={{ width: "100%" }}
              onClick={() => watchMutation.mutate(targetUrl)}
              disabled={watchMutation.isPending || !targetUrl.trim()}
            >
              {watchMutation.isPending ? <Spinner /> : "✓"} {t("precos.watchBtn")}
            </button>

            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--s4)", marginTop: "var(--s2)" }}>
              <span className="zf-micro" style={{ display: "block", marginBottom: "var(--s3)" }}>{t("precos.step2")}</span>
              <div className="zf-field">
                <label className="zf-label" htmlFor="precos-domain">{t("precos.chooseDomain")}</label>
                <select
                  id="precos-domain"
                  className="zf-select"
                  value={selectedSite}
                  onChange={(e) => setSelectedSite(e.target.value)}
                  aria-label={t("precos.chooseDomain")}
                >
                  <option value="">{t("precos.domainPlaceholder")}</option>
                  {catalogOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label} — {o.detail}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className="zf-panel">
          <div className="zf-panel-hd">
            <span className="zf-micro">
              {selectedSite ? t("precos.historyFor").replace("{{site}}", selectedSite) : t("precos.selectToView")}
            </span>
            <span style={{ flex: 1 }} />
            <span className="zf-micro">{t("precos.changesCount").replace("{{count}}", String(changes.length))}</span>
          </div>
          <div className="zf-panel-bd">
            {changes.length > 0 && (
              <div>
                <span className="zf-micro" style={{ color: "var(--accent)", display: "block", marginBottom: "var(--s2)" }}>
                  {t("precos.alertsTitle")}
                </span>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
                  {changes.map((ch, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "var(--s3)",
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius)",
                        background: "var(--bg)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "var(--s3)",
                        flexWrap: "wrap",
                      }}
                    >
                      <span style={{ fontSize: "var(--fs-body)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: "1 1 auto" }}>{ch.label}</span>
                      <span style={{ display: "flex", alignItems: "center", gap: "var(--s3)", flexShrink: 0, fontFamily: "var(--font-mono)", fontSize: "var(--fs-meta)" }}>
                        <span style={{ color: "var(--muted)" }}>{t("precos.was")} {ch.currency} {ch.before.toFixed(2)}</span>
                        <span>→</span>
                        <b style={{ color: ch.after - ch.before > 0 ? "var(--error)" : "var(--ok)" }}>
                          {ch.currency} {ch.after.toFixed(2)}
                        </b>
                        <span className={`zf-flag ${ch.after - ch.before > 0 ? "zf-flag--err" : "zf-flag--ok"}`}>
                          {ch.after - ch.before > 0 ? "▲ +" : "▼ "}
                          {ch.change_pct.toFixed(1)}%
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <span className="zf-micro" style={{ display: "block", marginBottom: "var(--s2)" }}>
                {t("precos.readingsTitle").replace("{{count}}", String(prices.length))}
              </span>
              {pricesQuery.isLoading && (
                <p className="zf-meta"><Spinner /> {t("precos.loadingPrices")}</p>
              )}
              {!pricesQuery.isLoading && prices.length === 0 && (
                <div className="zf-empty">{t("precos.empty")}</div>
              )}
              {prices.length > 0 && (
                <div style={{ overflowX: "auto", maxHeight: 350 }}>
                  <table className="zf-table">
                    <thead>
                      <tr>
                        <th>{t("precos.col.datetime")}</th>
                        <th>{t("precos.col.url")}</th>
                        <th style={{ textAlign: "right" }}>{t("precos.col.price")}</th>
                        <th>{t("precos.col.selector")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prices.map((p, idx) => (
                        <tr key={idx}>
                          <td className="zf-micro" style={{ whiteSpace: "nowrap", textTransform: "none", letterSpacing: 0 }}>{p.detected_at}</td>
                          <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "var(--fs-meta)" }}>{p.url}</td>
                          <td style={{ textAlign: "right", fontWeight: 600, color: "var(--accent)", fontFamily: "var(--font-mono)" }}>
                            {p.currency ?? "R$"} {p.price.toFixed(2)}
                          </td>
                          <td className="zf-micro" style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textTransform: "none", letterSpacing: 0 }}>{p.selector || t("precos.automatic")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export const Route = createFileRoute("/precos")({
  component: PrecosPage,
})

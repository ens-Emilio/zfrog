import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { api, PriceChange, PriceRecord } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { SYM, Spinner, TuiPanel, TuiCombobox } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

function PrecosPage() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [targetUrl, setTargetUrl] = useState("")
  const [selectorInput, setSelectorInput] = useState("")
  const [selectedSite, setSelectedSite] = useState("")

  // Fetch price history and changes for the selected site
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

  // Catalog sites for quick inspection
  const catalogQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  const catalogOptions = (catalogQuery.data ?? []).map((s) => ({
    value: `https://${s.site}`,
    label: s.site,
    detail: `${s.count} ${t("workers.pages")}`,
  }))

  // Mutation to watch a new product
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
    <TuiPanel
      title={t("precos.title")}
      action={
        <span style={{ color: "var(--fg-dim)", fontSize: "11px" }}>
          {t("precos.subtitle")}
        </span>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs mt-3">
        {/* Watch form */}
        <div className="border border-[var(--border)] bg-[var(--bg-panel)] p-4 flex flex-col gap-3">
          <div className="font-bold border-b border-[var(--border)] pb-1 uppercase tracking-wide">
            {t("precos.step1")}
          </div>

          <div>
            <label className="text-[var(--fg-dim)] block mb-1">{t("precos.urlLabel")}</label>
            <input
              type="text"
              className="tui-input w-full font-mono text-[11px]"
              placeholder="https://loja.com/produto-xyz"
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
            />
          </div>

          <div>
            <label className="text-[var(--fg-dim)] block mb-1">{t("precos.selectorLabel")}</label>
            <input
              type="text"
              className="tui-input w-full font-mono text-[11px]"
              placeholder=".preco, .price-tag, [data-price]"
              value={selectorInput}
              onChange={(e) => setSelectorInput(e.target.value)}
            />
            <span className="text-[10px] text-[var(--fg-dim)] block mt-1 leading-normal">
              {t("precos.selectorHint")}
            </span>
          </div>

          <button
            type="button"
            className="tui-btn accent w-full mt-2"
            onClick={() => watchMutation.mutate(targetUrl)}
            disabled={watchMutation.isPending || !targetUrl.trim()}
          >
            {watchMutation.isPending ? <Spinner /> : SYM.ok} {t("precos.watchBtn")}
          </button>

          {/* Select existing site to inspect */}
          <div className="border-t border-[var(--border)] pt-3 mt-3">
            <span className="font-bold block mb-1.5 uppercase tracking-wide">
              {t("precos.step2")}
            </span>
            <label className="text-[var(--fg-dim)] block mb-1.5">{t("precos.chooseDomain")}</label>
            <TuiCombobox
              value={selectedSite}
              onChange={setSelectedSite}
              options={catalogOptions}
              placeholder={t("precos.domainPlaceholder")}
              emptyLabel={t("tui.noOptions")}
              className="w-full"
            />
          </div>
        </div>

        {/* Price table and variations */}
        <div className="border border-[var(--border)] bg-[var(--bg-panel)] p-4 flex flex-col gap-4 lg:col-span-2">
          <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between items-baseline uppercase tracking-wide">
            <span>
              {selectedSite ? t("precos.historyFor").replace("{{site}}", selectedSite) : t("precos.selectToView")}
            </span>
            <span className="text-[var(--fg-dim)] font-mono text-[11px]">
              {t("precos.changesCount").replace("{{count}}", String(changes.length))}
            </span>
          </div>

          {/* Recent changes (deltas) */}
          {changes.length > 0 && (
            <div>
              <span className="font-bold text-[var(--accent)] block mb-1.5 uppercase text-[10px] tracking-wide">
                {t("precos.alertsTitle")}
              </span>
              <div className="space-y-1">
                {changes.map((ch, i) => {
                  const delta = ch.after - ch.before
                  const isUp = delta > 0
                  return (
                    <div
                      key={i}
                      className="p-2 border border-[var(--border)] bg-[var(--bg-raised)] flex items-center justify-between font-mono"
                    >
                      <div className="truncate flex-1 mr-2">
                        <span>{ch.label}</span>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className="text-[var(--fg-dim)]">{t("precos.was")} {ch.currency} {ch.before.toFixed(2)}</span>
                        <span>➔</span>
                        <b className={isUp ? "text-[var(--error)]" : "text-[var(--accent)]"}>
                          {ch.currency} {ch.after.toFixed(2)}
                        </b>
                        <span
                          className={`text-[10px] px-1 border ${
                            isUp ? "border-[var(--error)] text-[var(--error)]" : "border-[var(--accent)] text-[var(--accent)]"
                          }`}
                        >
                          {isUp ? "▲ +" : "▼ "}
                          {ch.change_pct.toFixed(1)}%
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Full history */}
          <div>
            <span className="font-bold block mb-1.5 text-[var(--fg-dim)] uppercase text-[10px] tracking-wide">
              {t("precos.readingsTitle").replace("{{count}}", String(prices.length))}
            </span>
            {pricesQuery.isLoading && (
              <p className="text-[var(--fg-dim)]"><Spinner /> {t("precos.loadingPrices")}</p>
            )}
            {!pricesQuery.isLoading && prices.length === 0 && (
              <p className="text-[var(--fg-dim)] py-6 text-center">
                {t("precos.empty")}
              </p>
            )}
            {prices.length > 0 && (
              <div className="overflow-x-auto max-h-[350px]">
                <table className="w-full text-left font-mono text-[11px] border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--border)] text-[var(--fg-dim)] uppercase text-[10px]">
                      <th className="p-1">{t("precos.col.datetime")}</th>
                      <th className="p-1">{t("precos.col.url")}</th>
                      <th className="p-1 text-right">{t("precos.col.price")}</th>
                      <th className="p-1">{t("precos.col.selector")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {prices.map((p, idx) => (
                      <tr key={idx} className="border-b border-[var(--border-subtle)] hover:bg-[var(--bg-raised)]">
                        <td className="p-1 text-[var(--fg-dim)] whitespace-nowrap">{p.detected_at}</td>
                        <td className="p-1 truncate max-w-xs">{p.url}</td>
                        <td className="p-1 text-right font-bold text-[var(--accent)]">
                          {p.currency ?? "R$"} {p.price.toFixed(2)}
                        </td>
                        <td className="p-1 text-[var(--fg-dim)] truncate max-w-xs">{p.selector || t("precos.automatic")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </TuiPanel>
  )
}

export const Route = createFileRoute("/precos")({
  component: PrecosPage,
})

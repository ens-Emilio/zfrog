import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, MarketplaceAsset } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner, SYM } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

const KINDS = [
  { value: "", key: "marketplace.kindAll" },
  { value: "workflow", key: "marketplace.kindWorkflows" },
  { value: "plugin", key: "marketplace.kindPlugins" },
  { value: "template", key: "marketplace.kindTemplates" },
] as const

function MarketplacePage() {
  const t = useT()
  const toast = useToast()

  const [assets, setAssets] = useState<MarketplaceAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [kind, setKind] = useState("")
  const [query, setQuery] = useState("")
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getMarketplace(kind || undefined, query.trim() || undefined)
      setAssets(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [kind])

  const handleInstall = async (asset: MarketplaceAsset) => {
    setBusyId(asset.id)
    try {
      await api.installAsset(asset.id)
      toast(`\u201C${asset.name}\u201D ${t("marketplace.installed")}`)
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("marketplace.installFailed"), "err")
    } finally {
      setBusyId(null)
    }
  }

  const handleUninstall = async (asset: MarketplaceAsset) => {
    setBusyId(asset.id)
    try {
      await api.uninstallAsset(asset.id)
      toast(`\u201C${asset.name}\u201D ${t("marketplace.removed")}`)
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("marketplace.removeFailed"), "err")
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("marketplace.title")}</h1>
        <span className="spacer" style={{ flex: 1 }} />
        <button type="button" className="zf-btn" onClick={() => void load()}>
          {t("marketplace.refresh")}
        </button>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>{SYM.fail} {t("marketplace.queryError")}{error}</p>
        </div>
      )}

      <div className="zf-filters">
        {KINDS.map((k) => (
          <button
            key={k.value}
            type="button"
            className="zf-pill"
            aria-pressed={kind === k.value}
            onClick={() => setKind(k.value)}
          >
            {t(k.key)}
          </button>
        ))}
        <span className="zf-spacer" style={{ flex: 1 }} />
        <div className="zf-prompt" style={{ minWidth: 220, flex: "0 1 280px" }}>
          <span style={{ color: "var(--muted)" }}>/</span>
          <input
            type="text"
            value={query}
            placeholder={t("marketplace.filterPlaceholder")}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void load()
            }}
          />
        </div>
      </div>

      {loading ? (
        <div className="zf-empty"><Spinner /> {t("marketplace.loading")}</div>
      ) : assets.length === 0 ? (
        <div className="zf-panel"><div className="zf-panel-bd"><p className="zf-meta" style={{ margin: 0 }}>{t("marketplace.empty")}</p></div></div>
      ) : (
        <div className="zf-rows">
          {assets.map((item) => (
            <div key={item.id} className="zf-run" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "var(--s3)", flexWrap: "wrap" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: "var(--s2)", flexWrap: "wrap" }}>
                  <span className="cmd" style={{ fontWeight: 600 }}>{item.name}</span>
                  <span className="zf-meta">v{item.version}</span>
                  <span className="zf-chip" style={{ cursor: "default" }}>[{item.kind}]</span>
                  <span className="zf-meta">{t("marketplace.by")}{item.author}</span>
                </div>
                <div style={{ display: "flex", gap: "var(--s2)" }}>
                  <button type="button" className="zf-btn zf-btn--primary" onClick={() => void handleInstall(item)} disabled={busyId === item.id}>
                    {busyId === item.id ? <Spinner /> : t("marketplace.install")}
                  </button>
                  <button type="button" className="zf-btn zf-btn--danger" onClick={() => void handleUninstall(item)} disabled={busyId === item.id}>
                    {t("marketplace.uninstall")}
                  </button>
                </div>
              </div>
              <p className="zf-meta" style={{ margin: 0, lineHeight: 1.5 }}>{item.description}</p>
              <div style={{ display: "flex", gap: "var(--s3)", fontSize: 11, color: "var(--muted)" }}>
                <span className="zf-num">★ {item.rating.toFixed(1)}</span>
                <span className="zf-num">{item.installs} {t("marketplace.installs")}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/marketplace")({
  component: MarketplacePage,
})

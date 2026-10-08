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
      toast(`“${asset.name}” ${t("marketplace.installed")}`)
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
      toast(`“${asset.name}” ${t("marketplace.removed")}`)
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("marketplace.removeFailed"), "err")
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("marketplace.title")}</h1>
        <button type="button" className="tui-btn" onClick={() => void load()}>
          {t("marketplace.refresh")}
        </button>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("marketplace.queryError")}{error}</p>
        </div>
      )}

      {/* Inline filters */}
      <div className="filters flex-wrap" style={{ gap: "1ch 1.5ch", marginTop: "0.5lh" }}>
        <div className="toggles">
          {KINDS.map((k) => (
            <button
              key={k.value}
              type="button"
              className="tgl"
              aria-pressed={kind === k.value}
              onClick={() => setKind(k.value)}
            >
              {t(k.key)}
            </button>
          ))}
        </div>

        <span className="searchline">
          <span className="slash">/</span>
          <input
            type="text"
            value={query}
            placeholder={t("marketplace.filterPlaceholder")}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void load()
            }}
          />
        </span>
      </div>

      {/* Marketplace item list */}
      {loading ? (
        <p className="empty"><Spinner /> {t("marketplace.loading")}</p>
      ) : assets.length === 0 ? (
        <p className="empty">{t("marketplace.empty")}</p>
      ) : (
        <div className="rows" style={{ marginTop: "0.5lh" }}>
          {assets.map((item) => (
            <div
              key={item.id}
              style={{
                borderBottom: "1px solid var(--line)",
                padding: "0.5lh 0",
                display: "flex",
                flexDirection: "column",
                gap: "0.25lh",
              }}
            >
              <div className="flex items-baseline justify-between">
                <div className="flex items-baseline gap-2">
                  <span style={{ fontWeight: 500, color: "var(--fg)" }}>{item.name}</span>
                  <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>v{item.version}</span>
                  <span style={{ color: "var(--accent)", fontSize: 11 }}>[{item.kind}]</span>
                  <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>{t("marketplace.by")}{item.author}</span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="tui-btn accent"
                    onClick={() => void handleInstall(item)}
                    disabled={busyId === item.id}
                    style={{ fontSize: 11 }}
                  >
                    {busyId === item.id ? <Spinner /> : t("marketplace.install")}
                  </button>
                  <button
                    type="button"
                    className="tui-btn danger"
                    onClick={() => void handleUninstall(item)}
                    disabled={busyId === item.id}
                    style={{ fontSize: 11 }}
                  >
                    {t("marketplace.uninstall")}
                  </button>
                </div>
              </div>

              <p style={{ color: "var(--fg-muted)", fontSize: 12 }}>{item.description}</p>

              <div className="flex gap-3 text-[11px]" style={{ color: "var(--fg-dim)" }}>
                <span>★ {item.rating.toFixed(1)}</span>
                <span>{item.installs} {t("marketplace.installs")}</span>
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

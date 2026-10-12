import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, GraphResponse, GraphNode } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { useToast } from "@/components/ToastRegion"
import { Spinner } from "@/components/ui/tui"

type NodeFilter = "all" | "page" | "entity" | "external" | "asset"

const FILTER_KEYS = {
  all: "grafo.filterAll",
  page: "grafo.filterPage",
  entity: "grafo.filterEntity",
  external: "grafo.filterExternal",
  asset: "grafo.filterAsset",
} as const

function GrafoPage() {
  const t = useT()
  const toast = useToast()
  const [selectedDir, setSelectedDir] = useState("")
  const [maxDepth, setMaxDepth] = useState(2)
  const [extractEntities, setExtractEntities] = useState(true)
  const [nodeFilter, setNodeFilter] = useState<NodeFilter>("all")
  const [graphData, setGraphData] = useState<GraphResponse | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)

  const catalogQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  const catalogOptions = (catalogQuery.data ?? []).map((s) => ({
    value: s.site,
    label: s.site,
    detail: `${s.count} ${t("grafo.catalogRefs")}`,
  }))

  const graphMutation = useMutation({
    mutationFn: async () => {
      const dir = selectedDir.trim()
      if (!dir) throw new Error(t("grafo.missingDir"))
      const finalDir = dir.startsWith("output/") ? dir : `output/${dir}`
      return api.getKnowledgeGraph(finalDir, maxDepth, extractEntities)
    },
    onSuccess: (data) => {
      setGraphData(data)
      setSelectedNode(null)
      toast(
        t("grafo.success").replace("{nodes}", String(data.nodes.length)).replace("{edges}", String(data.edges.length)),
        "ok",
      )
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("grafo.mapError").replace("{msg}", msg), "err")
    },
  })

  const nodes = graphData?.nodes ?? []
  const edges = graphData?.edges ?? []

  const filteredNodes = nodes.filter((n) => {
    if (nodeFilter === "all") return true
    return n.type === nodeFilter
  })

  const exportJSON = () => {
    if (!graphData) return
    const blob = new Blob([JSON.stringify(graphData, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `zfrog-grafo-${selectedDir.replace(/[^a-zA-Z0-9]/g, "_")}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("grafo.title")}</h1>
        <span className="zf-meta">{t("grafo.description")}</span>
        <span style={{ flex: 1 }} />
        {graphData && (
          <button type="button" className="zf-btn" onClick={exportJSON}>
            {t("grafo.exportMap")}
          </button>
        )}
      </div>

      <div className="zf-panel" style={{ marginBottom: "var(--s5)" }}>
        <div className="zf-panel-bd">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "var(--s4)", alignItems: "end" }}>
            <div className="zf-field" style={{ gridColumn: "span 2" }}>
              <label className="zf-label" htmlFor="grafo-dir">{t("grafo.siteDirLabel")}</label>
              <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
                <input
                  id="grafo-dir"
                  type="text"
                  className="zf-input"
                  style={{ flex: 1, minWidth: 200 }}
                  placeholder={t("grafo.dirPlaceholder")}
                  value={selectedDir}
                  onChange={(e) => setSelectedDir(e.target.value)}
                />
                {catalogOptions.length > 0 && (
                  <select
                    className="zf-select"
                    value={selectedDir.replace(/^output\//, "")}
                    onChange={(e) => setSelectedDir(e.target.value ? `output/${e.target.value}` : "")}
                    aria-label={t("grafo.pickFromCollection")}
                    style={{ minWidth: 160 }}
                  >
                    <option value="">{t("grafo.pickFromCollection")}</option>
                    {catalogOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label} — {o.detail}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            <div className="zf-field">
              <span className="zf-label">{t("grafo.depthLabel")}</span>
              <div style={{ display: "flex", gap: "var(--s1)" }}>
                {[1, 2, 3].map((d) => (
                  <button
                    key={d}
                    type="button"
                    className="zf-pill"
                    aria-pressed={maxDepth === d}
                    onClick={() => setMaxDepth(d)}
                  >
                    {d} {d === 1 ? t("grafo.levelOne") : t("grafo.levelMany")}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
              <label className="zf-check">
                <input
                  type="checkbox"
                  checked={extractEntities}
                  onChange={(e) => setExtractEntities(e.target.checked)}
                />
                <span>{t("grafo.extractEntities")}</span>
              </label>
              <button
                type="button"
                className="zf-btn zf-btn--primary"
                style={{ width: "100%" }}
                onClick={() => graphMutation.mutate()}
                disabled={graphMutation.isPending}
              >
                {graphMutation.isPending ? <Spinner /> : "✓"} {t("grafo.mapConnections")}
              </button>
            </div>
          </div>
        </div>
      </div>

      {graphData && (
        <div className="zf-split" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
          <div className="zf-panel">
            <div className="zf-panel-hd">
              <span className="zf-micro">
                {t("grafo.mappedElements").replace("{count}", String(filteredNodes.length))}
              </span>
              <span className="zf-micro" style={{ color: "var(--muted)" }}>
                {t("grafo.totalConnections").replace("{count}", String(edges.length))}
              </span>
              <span style={{ flex: 1 }} />
              <div role="group" aria-label={t("grafo.nodeFilterAria")} style={{ display: "flex", gap: "var(--s1)", flexWrap: "wrap" }}>
                {(["all", "page", "entity", "external", "asset"] as NodeFilter[]).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className="zf-pill"
                    aria-pressed={nodeFilter === f}
                    onClick={() => setNodeFilter(f)}
                  >
                    {t(FILTER_KEYS[f])}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ maxHeight: 460, overflowY: "auto", display: "flex", flexDirection: "column", gap: 1, padding: "var(--s2)" }}>
              {filteredNodes.length === 0 && (
                <div className="zf-empty" style={{ margin: "var(--s4) 0" }}>{t("grafo.noNodesMatch")}</div>
              )}
              {filteredNodes.map((n) => {
                const incomingEdges = edges.filter((e) => e.target === n.id).length
                const outgoingEdges = edges.filter((e) => e.source === n.id).length
                const isSelected = selectedNode?.id === n.id

                return (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => setSelectedNode(n)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "var(--s2) var(--s3)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "var(--s3)",
                      background: isSelected ? "var(--sel-bg)" : "var(--surface)",
                      borderColor: isSelected ? "var(--accent)" : "var(--border)",
                      fontWeight: isSelected ? 600 : 400,
                    }}
                  >
                    <span style={{ display: "flex", alignItems: "center", gap: "var(--s2)", minWidth: 0 }}>
                      <span style={{ color: "var(--accent)", fontSize: "var(--fs-meta)" }}>
                        {n.type === "page" ? "📄" : n.type === "entity" ? "🏷️" : "🔗"}
                      </span>
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-mono)", fontSize: "var(--fs-meta)" }}>{n.label || n.id}</span>
                      <span className="zf-micro" style={{ textTransform: "uppercase" }}>
                        [{n.type in FILTER_KEYS ? t(FILTER_KEYS[n.type as NodeFilter]) : n.type}]
                      </span>
                    </span>
                    <span className="zf-micro" style={{ display: "flex", gap: "var(--s3)", flexShrink: 0, textTransform: "none", letterSpacing: 0 }}>
                      <span>{t("grafo.receives").replace("{count}", String(incomingEdges))}</span>
                      <span>{t("grafo.points").replace("{count}", String(outgoingEdges))}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="zf-panel">
            <div className="zf-panel-hd">
              <span className="zf-micro">{t("grafo.selectionDetails")}</span>
            </div>
            <div className="zf-panel-bd">
              {selectedNode ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
                  <div className="zf-field">
                    <span className="zf-label">{t("grafo.addressId")}</span>
                    <div className="zf-num" style={{ fontSize: "var(--fs-meta)", wordBreak: "break-all", fontWeight: 600 }}>{selectedNode.id}</div>
                  </div>
                  <div className="zf-field">
                    <span className="zf-label">{t("grafo.category")}</span>
                    <span className="zf-pill" style={{ alignSelf: "flex-start", cursor: "default" }}>
                      {selectedNode.type in FILTER_KEYS ? t(FILTER_KEYS[selectedNode.type as NodeFilter]) : selectedNode.type}
                    </span>
                  </div>

                  <div style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--s3)" }}>
                    <span className="zf-micro" style={{ display: "block", marginBottom: "var(--s2)", textTransform: "none", letterSpacing: 0, fontWeight: 600 }}>
                      {t("grafo.outgoing").replace("{count}", String(edges.filter((e) => e.source === selectedNode.id).length))}
                    </span>
                    <div style={{ maxHeight: 144, overflowY: "auto", display: "flex", flexDirection: "column", gap: "var(--s1)" }}>
                      {edges
                        .filter((e) => e.source === selectedNode.id)
                        .map((e, i) => (
                          <div key={i} className="zf-pre" style={{ padding: "var(--s2)", fontSize: "var(--fs-micro)" }}>
                            ➔ {e.target} <span style={{ color: "var(--muted)" }}>({e.type})</span>
                          </div>
                        ))}
                    </div>
                  </div>

                  <div style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--s3)" }}>
                    <span className="zf-micro" style={{ display: "block", marginBottom: "var(--s2)", textTransform: "none", letterSpacing: 0, fontWeight: 600 }}>
                      {t("grafo.incoming").replace("{count}", String(edges.filter((e) => e.target === selectedNode.id).length))}
                    </span>
                    <div style={{ maxHeight: 144, overflowY: "auto", display: "flex", flexDirection: "column", gap: "var(--s1)" }}>
                      {edges
                        .filter((e) => e.target === selectedNode.id)
                        .map((e, i) => (
                          <div key={i} className="zf-pre" style={{ padding: "var(--s2)", fontSize: "var(--fs-micro)" }}>
                            ⬅ {e.source}
                          </div>
                        ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="zf-empty">{t("grafo.selectToInspect")}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/grafo")({
  component: GrafoPage,
})

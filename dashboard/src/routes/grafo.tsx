import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, GraphResponse, GraphNode } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { useToast } from "@/components/ToastRegion"
import { SYM, Spinner, TuiPanel, TuiCombobox } from "@/components/ui/tui"

type NodeFilter = "all" | "page" | "entity" | "external" | "asset"

const FILTER_KEYS = {
  all: "grafo.filterAll",
  page: "grafo.filterPage",
  entity: "grafo.filterEntity",
  external: "grafo.filterExternal",
  asset: "grafo.filterAsset",
} as const

/** Fill {name} placeholders in a translated string. */
function fmt(s: string, vars: Record<string, string | number>): string {
  return s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""))
}

function GrafoPage() {
  const t = useT()
  const toast = useToast()
  const [selectedDir, setSelectedDir] = useState("")
  const [maxDepth, setMaxDepth] = useState(2)
  const [extractEntities, setExtractEntities] = useState(true)
  const [nodeFilter, setNodeFilter] = useState<NodeFilter>("all")
  const [graphData, setGraphData] = useState<GraphResponse | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)

  // Catalog sites for quick filling
  const catalogQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  const catalogOptions = (catalogQuery.data ?? []).map((s) => ({
    value: s.site,
    label: s.site,
    detail: `${s.count} ${t("grafo.catalogRefs")}`,
  }))

  // Graph mutation
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
        fmt(t("grafo.success"), { nodes: data.nodes.length, edges: data.edges.length }),
        "ok",
      )
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(fmt(t("grafo.mapError"), { msg }), "err")
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
    <TuiPanel
      title={t("grafo.title")}
      action={
        <div className="flex items-center gap-2">
          {graphData && (
            <button type="button" className="tui-btn text-xs" onClick={exportJSON}>
              {t("grafo.exportMap")}
            </button>
          )}
        </div>
      }
    >
      <div className="text-xs text-[var(--fg-dim)] border-b border-[var(--border)] pb-2 mb-3">
        {t("grafo.description")}
      </div>

      {/* Top configuration panel */}
      <div className="border border-[var(--border)] bg-[var(--bg-panel)] p-4 mb-4 text-xs">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div className="md:col-span-2">
            <label className="text-[var(--fg-dim)] block mb-1.5">{t("grafo.siteDirLabel")}</label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                className="tui-input flex-1 min-w-[200px]"
                placeholder={t("grafo.dirPlaceholder")}
                value={selectedDir}
                onChange={(e) => setSelectedDir(e.target.value)}
              />
              {catalogOptions.length > 0 && (
                <TuiCombobox
                  value={selectedDir.replace(/^output\//, "")}
                  onChange={(val) => setSelectedDir(val ? `output/${val}` : "")}
                  options={catalogOptions}
                  placeholder={t("grafo.pickFromCollection")}
                  emptyLabel={t("tui.noOptions")}
                />
              )}
            </div>
          </div>

          <div>
            <label className="text-[var(--fg-dim)] block mb-1">
              {t("grafo.depthLabel")}
            </label>
            <div className="flex items-center gap-2">
              {[1, 2, 3].map((d) => (
                <button
                  key={d}
                  type="button"
                  className={`tgl px-2 py-0.5 ${maxDepth === d ? "font-bold" : ""}`}
                  aria-pressed={maxDepth === d}
                  onClick={() => setMaxDepth(d)}
                >
                  {d} {d === 1 ? t("grafo.levelOne") : t("grafo.levelMany")}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-1.5 cursor-pointer text-[11px]">
              <input
                type="checkbox"
                checked={extractEntities}
                onChange={(e) => setExtractEntities(e.target.checked)}
              />
              <span>{t("grafo.extractEntities")}</span>
            </label>
            <button
              type="button"
              className="tui-btn accent text-xs w-full"
              onClick={() => graphMutation.mutate()}
              disabled={graphMutation.isPending}
            >
              {graphMutation.isPending ? <Spinner /> : SYM.ok} {t("grafo.mapConnections")}
            </button>
          </div>
        </div>
      </div>

      {graphData && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs">
          {/* Columns 1 and 2: nodes and TUI visualization */}
          <div className="tui-panel lg:col-span-2 p-4 flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] pb-2">
              <div className="font-bold flex items-center gap-3">
                <span className="uppercase tracking-wide">
                  {fmt(t("grafo.mappedElements"), { count: filteredNodes.length })}
                </span>
                <span className="text-[var(--fg-dim)]">
                  {fmt(t("grafo.totalConnections"), { count: edges.length })}
                </span>
              </div>
              <div className="toggles text-[10px]" role="group" aria-label={t("grafo.nodeFilterAria")}>
                {(["all", "page", "entity", "external", "asset"] as NodeFilter[]).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className="tgl"
                    aria-pressed={nodeFilter === f}
                    onClick={() => setNodeFilter(f)}
                  >
                    {t(FILTER_KEYS[f])}
                  </button>
                ))}
              </div>
            </div>

            {/* Matrix / node list with centrality */}
            <div className="overflow-y-auto max-h-[460px] space-y-1 pr-1 font-mono text-[11px]">
              {filteredNodes.length === 0 && (
                <p className="text-[var(--fg-dim)] py-4">{t("grafo.noNodesMatch")}</p>
              )}
              {filteredNodes.map((n) => {
                const incomingEdges = edges.filter((e) => e.target === n.id).length
                const outgoingEdges = edges.filter((e) => e.source === n.id).length
                const isSelected = selectedNode?.id === n.id

                return (
                  <button
                    key={n.id}
                    type="button"
                    className={`w-full text-left p-1.5 border flex items-center justify-between gap-2 ${
                      isSelected
                        ? "border-[var(--accent)] bg-[var(--bg-raised)] font-bold"
                        : "border-[var(--border-subtle)] hover:border-[var(--border)]"
                    }`}
                    onClick={() => setSelectedNode(n)}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <span className="text-[var(--accent)]">
                        {n.type === "page" ? "📄" : n.type === "entity" ? "🏷️" : "🔗"}
                      </span>
                      <span className="truncate">{n.label || n.id}</span>
                      <span className="text-[10px] text-[var(--fg-dim)] uppercase">
                        [{n.type in FILTER_KEYS ? t(FILTER_KEYS[n.type as NodeFilter]) : n.type}]
                      </span>
                    </div>
                    <div className="text-[10px] text-[var(--fg-dim)] shrink-0 flex gap-2">
                      <span>{fmt(t("grafo.receives"), { count: incomingEdges })}</span>
                      <span>{fmt(t("grafo.points"), { count: outgoingEdges })}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Column 3: selected node details */}
          <div className="tui-panel lg:col-span-1 p-4 flex flex-col gap-3">
            <div className="font-bold border-b border-[var(--border)] pb-1 uppercase tracking-wide">
              {t("grafo.selectionDetails")}
            </div>

            {selectedNode ? (
              <div className="space-y-3">
                <div>
                  <span className="text-[var(--fg-dim)] block text-[10px]">{t("grafo.addressId")}</span>
                  <div className="font-mono break-all font-semibold">{selectedNode.id}</div>
                </div>
                <div>
                  <span className="text-[var(--fg-dim)] block text-[10px]">{t("grafo.category")}</span>
                  <span className="px-1.5 py-0.5 border border-[var(--border)] font-mono uppercase text-[10px]">
                    {selectedNode.type in FILTER_KEYS
                      ? t(FILTER_KEYS[selectedNode.type as NodeFilter])
                      : selectedNode.type}
                  </span>
                </div>

                {/* Outgoing connections */}
                <div className="border-t border-[var(--border)] pt-2">
                  <span className="text-[var(--fg-dim)] block font-semibold mb-1">
                    {fmt(t("grafo.outgoing"), {
                      count: edges.filter((e) => e.source === selectedNode.id).length,
                    })}
                  </span>
                  <div className="max-h-36 overflow-y-auto space-y-1 font-mono text-[10px]">
                    {edges
                      .filter((e) => e.source === selectedNode.id)
                      .map((e, i) => (
                        <div key={i} className="truncate p-1 bg-[var(--bg-raised)] border border-[var(--border-subtle)]">
                          ➔ {e.target} <span className="text-[var(--fg-dim)]">({e.type})</span>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Incoming connections */}
                <div className="border-t border-[var(--border)] pt-2">
                  <span className="text-[var(--fg-dim)] block font-semibold mb-1">
                    {fmt(t("grafo.incoming"), {
                      count: edges.filter((e) => e.target === selectedNode.id).length,
                    })}
                  </span>
                  <div className="max-h-36 overflow-y-auto space-y-1 font-mono text-[10px]">
                    {edges
                      .filter((e) => e.target === selectedNode.id)
                      .map((e, i) => (
                        <div key={i} className="truncate p-1 bg-[var(--bg-raised)] border border-[var(--border-subtle)]">
                          ⬅ {e.source}
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-[var(--fg-dim)] py-8 text-center">
                {t("grafo.selectToInspect")}
              </div>
            )}
          </div>
        </div>
      )}
    </TuiPanel>
  )
}

export const Route = createFileRoute("/grafo")({
  component: GrafoPage,
})

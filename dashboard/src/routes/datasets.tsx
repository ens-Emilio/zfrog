import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, DatasetStats, DatasetExportResponse } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner } from "@/components/ui/tui"
import { useT, type I18nKey } from "@/lib/i18n"

const FORMATS: { id: string; name: I18nKey; desc: I18nKey }[] = [
  { id: "chat", name: "datasets.formats.chat.name", desc: "datasets.formats.chat.desc" },
  { id: "sharegpt", name: "datasets.formats.sharegpt.name", desc: "datasets.formats.sharegpt.desc" },
  { id: "alpaca", name: "datasets.formats.alpaca.name", desc: "datasets.formats.alpaca.desc" },
  { id: "raw", name: "datasets.formats.raw.name", desc: "datasets.formats.raw.desc" },
]

function DatasetsPage() {
  const t = useT()
  const toast = useToast()
  const [selectedSite, setSelectedSite] = useState("")
  const [pagesInput, setPagesInput] = useState("")
  const [kind, setKind] = useState("qa")
  const [format, setFormat] = useState("chat")

  const [buildStats, setBuildStats] = useState<DatasetStats | null>(null)
  const [exportInfo, setExportInfo] = useState<DatasetExportResponse | null>(null)

  // Catalogued sites for suggestions
  const catalogQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  const siteOptions = (catalogQuery.data ?? []).map((s) => ({
    value: s.site,
    label: s.site,
    detail: `${s.count} ${t("workers.pages")}`,
  }))

  // Build dataset
  const buildMutation = useMutation({
    mutationFn: async () => {
      let pages = pagesInput
        .split("\n")
        .map((p) => p.trim())
        .filter(Boolean)

      if (pages.length === 0 && selectedSite.trim()) {
        pages = [`output/${selectedSite.trim()}`]
      }

      if (pages.length === 0) {
        throw new Error(t("datasets.selectSiteError"))
      }

      return api.buildDataset(pages, kind)
    },
    onSuccess: (data) => {
      setBuildStats(data)
      toast(t("datasets.buildOk").replace("{{count}}", String(data.added)), "ok")
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(`${t("datasets.buildError")}: ${msg}`, "err")
    },
  })

  // Export dataset to file
  const exportMutation = useMutation({
    mutationFn: async () => {
      return api.exportDataset(format)
    },
    onSuccess: (data) => {
      setExportInfo(data)
      toast(`${t("datasets.exportOk")}: ${data.path}`, "ok")
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(`${t("datasets.exportError")}: ${msg}`, "err")
    },
  })

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("datasets.title")}</h1>
        <span className="zf-meta">{t("datasets.subtitle")}</span>
        <span style={{ flex: 1 }} />
        {buildStats && <span className="zf-micro">{buildStats.added} {t("datasets.pairsProcessed")}</span>}
      </div>

      <div className="zf-split zf-split--form">
        {/* Configuration panel */}
        <div className="zf-panel">
          <div className="zf-panel-hd">
            <span className="zf-micro">{t("datasets.step1")}</span>
          </div>
          <div className="zf-panel-bd">
            <div className="zf-field">
              <label className="zf-label" htmlFor="ds-site">{t("datasets.chooseSite")}</label>
              <select
                id="ds-site"
                className="zf-select"
                value={selectedSite}
                onChange={(e) => setSelectedSite(e.target.value)}
                aria-label={t("datasets.chooseSite")}
              >
                <option value="">{t("datasets.sitePlaceholder")}</option>
                {siteOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label} — {o.detail}
                  </option>
                ))}
              </select>
            </div>

            <div className="zf-field">
              <label className="zf-label" htmlFor="ds-files">{t("datasets.orFiles")}</label>
              <textarea
                id="ds-files"
                className="zf-textarea"
                placeholder="output/exemplo.com/index.html&#10;output/exemplo.com/artigo.html"
                value={pagesInput}
                onChange={(e) => setPagesInput(e.target.value)}
                rows={5}
              />
            </div>

            <div className="zf-label" style={{ marginTop: "var(--s2)" }}>{t("datasets.step2")}</div>

            <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
              {([
                {
                  id: "qa",
                  label: t("datasets.kind.qa.label"),
                  desc: t("datasets.kind.qa.desc"),
                },
                {
                  id: "summary",
                  label: t("datasets.kind.summary.label"),
                  desc: t("datasets.kind.summary.desc"),
                },
                {
                  id: "text",
                  label: t("datasets.kind.text.label"),
                  desc: t("datasets.kind.text.desc"),
                },
              ] as const).map((k) => (
                <label key={k.id} className="zf-check" style={{ alignItems: "flex-start", padding: "var(--s2)", border: "1px solid var(--border)", borderRadius: "var(--radius)", background: kind === k.id ? "var(--sel-bg)" : "transparent" }}>
                  <input
                    type="radio"
                    name="dataset-kind"
                    checked={kind === k.id}
                    onChange={() => setKind(k.id)}
                  />
                  <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                    <span style={{ fontWeight: 550, fontSize: "var(--fs-body)" }}>{k.label}</span>
                    <span className="zf-micro" style={{ textTransform: "none", letterSpacing: 0 }}>{k.desc}</span>
                  </span>
                </label>
              ))}
            </div>

            <button
              type="button"
              className="zf-btn zf-btn--primary"
              style={{ width: "100%", marginTop: "var(--s2)" }}
              onClick={() => buildMutation.mutate()}
              disabled={buildMutation.isPending}
            >
              {buildMutation.isPending ? <Spinner /> : "✓"} {t("datasets.buildBtn")}
            </button>
          </div>
        </div>

        {/* Format & preview */}
        <div className="zf-panel">
          <div className="zf-panel-hd">
            <span className="zf-micro">{t("datasets.step3")}</span>
            <span style={{ flex: 1 }} />
            {buildStats && <span className="zf-num" style={{ color: "var(--accent)", fontSize: "var(--fs-meta)" }}>{buildStats.added} {t("datasets.pairsProcessed")}</span>}
          </div>
          <div className="zf-panel-bd">
            <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
              {FORMATS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className="zf-pill"
                  aria-pressed={format === f.id}
                  onClick={() => setFormat(f.id)}
                  style={{ flexDirection: "column", alignItems: "flex-start", padding: "var(--s3) var(--s4)", height: "auto", borderRadius: "var(--radius)" }}
                >
                  <span style={{ fontWeight: 600, fontSize: "var(--fs-body)" }}>{t(f.name)}</span>
                  <span className="zf-micro" style={{ textTransform: "none", letterSpacing: 0 }}>{t(f.desc)}</span>
                </button>
              ))}
            </div>

            <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "var(--s4)", background: "var(--bg)" }}>
              <div className="zf-micro" style={{ marginBottom: "var(--s2)" }}>
                {t("datasets.structurePreview").replace("{{format}}", format)}
              </div>
              {format === "chat" && (
                <pre className="zf-pre">{`{"messages": [\n  {"role": "user", "content": "${t("datasets.example.chat.q")}"},\n  {"role": "assistant", "content": "${t("datasets.example.chat.a")}"}\n]}`}</pre>
              )}
              {format === "sharegpt" && (
                <pre className="zf-pre">{`{"conversations": [\n  {"from": "human", "value": "${t("datasets.example.sharegpt.q")}"},\n  {"from": "gpt", "value": "${t("datasets.example.sharegpt.a")}"}\n]}`}</pre>
              )}
              {format === "alpaca" && (
                <pre className="zf-pre">{`{\n  "instruction": "${t("datasets.example.alpaca.instruction")}",\n  "input": "${t("datasets.example.alpaca.input")}",\n  "output": "${t("datasets.example.alpaca.output")}"\n}`}</pre>
              )}
              {format === "raw" && (
                <pre className="zf-pre">{`{\n  "text": "${t("datasets.example.raw.text")}",\n  "metadata": {"url": "https://exemplo.com/termos", "tokens": 420}\n}`}</pre>
              )}
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: "var(--s3)", paddingTop: "var(--s3)", borderTop: "1px solid var(--border)" }}>
              <span className="zf-micro" style={{ textTransform: "none", letterSpacing: 0 }}>{t("datasets.jsonlNote")}</span>
              <button
                type="button"
                className="zf-btn zf-btn--primary"
                onClick={() => exportMutation.mutate()}
                disabled={exportMutation.isPending}
              >
                {exportMutation.isPending ? <Spinner /> : "✓"} {t("datasets.exportBtn")}
              </button>
            </div>

            {exportInfo && (
              <div style={{ padding: "var(--s4)", border: "1px solid var(--accent)", borderRadius: "var(--radius)", background: "var(--accent-soft)" }}>
                <div style={{ fontWeight: 600, color: "var(--accent)", marginBottom: "var(--s2)" }}>{t("datasets.exportSuccess")}</div>
                <div className="zf-num" style={{ fontSize: "var(--fs-meta)", marginBottom: "var(--s2)" }}>{t("datasets.local")}: {exportInfo.path}</div>
                <div className="zf-micro" style={{ textTransform: "none", letterSpacing: 0 }}>
                  {t("datasets.pairs")}: {exportInfo.summary.pairs} · {t("datasets.format")}: {exportInfo.summary.format}
                  {exportInfo.summary.size_bytes ? ` · ${t("datasets.size")}: ${(exportInfo.summary.size_bytes / 1024).toFixed(1)} KB` : null}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

export const Route = createFileRoute("/datasets")({
  component: DatasetsPage,
})

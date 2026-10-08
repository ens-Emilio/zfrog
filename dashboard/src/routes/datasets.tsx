import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, DatasetStats, DatasetExportResponse } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { SYM, Spinner, CodeBlock, TuiPanel, TuiCombobox } from "@/components/ui/tui"
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
    <TuiPanel
      title={t("datasets.title")}
      action={
        <span style={{ color: "var(--fg-dim)", fontSize: "11px" }}>
          {t("datasets.subtitle")}
        </span>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs mt-3">
        {/* Configuration panel */}
        <div className="border border-[var(--border)] bg-[var(--bg-panel)] p-4 flex flex-col gap-4">
          <div className="font-bold border-b border-[var(--border)] pb-1 uppercase tracking-wide">
            {t("datasets.step1")}
          </div>

          <div>
            <label className="text-[var(--fg-dim)] block mb-1.5">{t("datasets.chooseSite")}</label>
            <TuiCombobox
              value={selectedSite}
              onChange={setSelectedSite}
              options={siteOptions}
              placeholder={t("datasets.sitePlaceholder")}
              emptyLabel={t("tui.noOptions")}
              className="w-full"
            />
          </div>

          <div>
            <label className="text-[var(--fg-dim)] block mb-1">
              {t("datasets.orFiles")}
            </label>
            <textarea
              className="tui-input w-full font-mono text-[11px] h-24 p-2"
              placeholder="output/exemplo.com/index.html&#10;output/exemplo.com/artigo.html"
              value={pagesInput}
              onChange={(e) => setPagesInput(e.target.value)}
            />
          </div>

          <div className="font-bold border-b border-[var(--border)] pb-1 pt-2 uppercase tracking-wide">
            {t("datasets.step2")}
          </div>

          <div className="flex flex-col gap-1.5">
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
              <label key={k.id} className="flex items-start gap-2 cursor-pointer p-1.5 hover:bg-[var(--bg-raised)] border border-transparent hover:border-[var(--border)]">
                <input
                  type="radio"
                  name="dataset-kind"
                  checked={kind === k.id}
                  onChange={() => setKind(k.id)}
                  className="mt-0.5"
                />
                <div>
                  <div className="font-semibold">{k.label}</div>
                  <div className="text-[10px] text-[var(--fg-dim)] mt-0.5">{k.desc}</div>
                </div>
              </label>
            ))}
          </div>

          <button
            type="button"
            className="tui-btn accent w-full mt-2"
            onClick={() => buildMutation.mutate()}
            disabled={buildMutation.isPending}
          >
            {buildMutation.isPending ? <Spinner /> : SYM.ok} {t("datasets.buildBtn")}
          </button>
        </div>

        {/* Center panel: format & stats */}
        <div className="border border-[var(--border)] bg-[var(--bg-panel)] p-4 flex flex-col gap-4 lg:col-span-2">
          <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between items-baseline uppercase tracking-wide">
            <span>{t("datasets.step3")}</span>
            {buildStats && (
              <span className="text-[var(--accent)] font-mono">{buildStats.added} {t("datasets.pairsProcessed")}</span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {FORMATS.map((f) => (
              <button
                key={f.id}
                type="button"
                className={`p-2.5 text-left border ${
                  format === f.id
                    ? "border-[var(--accent)] bg-[var(--bg-raised)] font-semibold"
                    : "border-[var(--border)] hover:border-[var(--border-subtle)]"
                }`}
                onClick={() => setFormat(f.id)}
              >
                <div className="flex items-center justify-between mb-1">
                  <span>{t(f.name)}</span>
                  {format === f.id && <span className="text-[var(--accent)]">●</span>}
                </div>
                <div className="text-[10px] text-[var(--fg-dim)]">{t(f.desc)}</div>
              </button>
            ))}
          </div>

          {/* Example of the selected format's structure */}
          <div className="border border-[var(--border)] p-3 bg-[var(--bg-raised)]">
            <div className="text-[10px] font-bold uppercase text-[var(--fg-dim)] mb-1">
              {t("datasets.structurePreview").replace("{{format}}", format)}
            </div>
            {format === "chat" && (
              <CodeBlock code={[`{"messages": [`, `  {"role": "user", "content": "${t("datasets.example.chat.q")}"},`, `  {"role": "assistant", "content": "${t("datasets.example.chat.a")}"}`, `]}`]} />
            )}
            {format === "sharegpt" && (
              <CodeBlock code={[`{"conversations": [`, `  {"from": "human", "value": "${t("datasets.example.sharegpt.q")}"},`, `  {"from": "gpt", "value": "${t("datasets.example.sharegpt.a")}"}`, `]}`]} />
            )}
            {format === "alpaca" && (
              <CodeBlock code={[`{`, `  "instruction": "${t("datasets.example.alpaca.instruction")}",`, `  "input": "${t("datasets.example.alpaca.input")}",`, `  "output": "${t("datasets.example.alpaca.output")}"`, `}`]} />
            )}
            {format === "raw" && (
              <CodeBlock code={[`{`, `  "text": "${t("datasets.example.raw.text")}",`, `  "metadata": {"url": "https://exemplo.com/termos", "tokens": 420}`, `}`]} />
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between pt-2 border-t border-[var(--border)] mt-auto gap-2">
            <span className="text-[var(--fg-dim)] text-[11px]">
              {t("datasets.jsonlNote")}
            </span>
            <button
              type="button"
              className="tui-btn accent"
              onClick={() => exportMutation.mutate()}
              disabled={exportMutation.isPending}
            >
              {exportMutation.isPending ? <Spinner /> : SYM.ok} {t("datasets.exportBtn")}
            </button>
          </div>

          {exportInfo && (
            <div className="p-3 border border-[var(--accent)] bg-[var(--bg-raised)] mt-2">
              <div className="font-bold text-[var(--accent)] mb-1">{t("datasets.exportSuccess")}</div>
              <div className="font-mono text-[11px] mb-2 text-[var(--fg)]">{t("datasets.local")}: {exportInfo.path}</div>
              <div className="text-[10px] text-[var(--fg-dim)]">
                {t("datasets.pairs")}: {exportInfo.summary.pairs} · {t("datasets.format")}: {exportInfo.summary.format}
                {exportInfo.summary.size_bytes && ` · ${t("datasets.size")}: ${(exportInfo.summary.size_bytes / 1024).toFixed(1)} KB`}
              </div>
            </div>
          )}
        </div>
      </div>
    </TuiPanel>
  )
}

export const Route = createFileRoute("/datasets")({
  component: DatasetsPage,
})

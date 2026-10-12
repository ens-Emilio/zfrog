import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, GraphQLResult } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner, SYM } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

const SNIPPETS: { key: "graphql.snippetJobsLabel" | "graphql.snippetCatalogLabel" | "graphql.snippetStatsLabel" | "graphql.snippetEnginesLabel"; descKey: "graphql.snippetJobsDesc" | "graphql.snippetCatalogDesc" | "graphql.snippetStatsDesc" | "graphql.snippetEnginesDesc"; query: string }[] = [
  {
    key: "graphql.snippetJobsLabel",
    descKey: "graphql.snippetJobsDesc",
    query: `query ListJobs {\n  jobs {\n    id\n    url\n    mode\n    status\n    createdAt\n  }\n}`,
  },
  {
    key: "graphql.snippetCatalogLabel",
    descKey: "graphql.snippetCatalogDesc",
    query: `query GetCatalog {\n  catalog(limit: 5) {\n    total\n    cards {\n      id\n      site\n      palette\n      title\n    }\n  }\n}`,
  },
  {
    key: "graphql.snippetStatsLabel",
    descKey: "graphql.snippetStatsDesc",
    query: `query SystemStats {\n  stats {\n    totalJobs\n    diskUsageBytes\n    uptimeSeconds\n  }\n}`,
  },
  {
    key: "graphql.snippetEnginesLabel",
    descKey: "graphql.snippetEnginesDesc",
    query: `query EngineCosts {\n  engines {\n    name\n    jobsProcessed\n    avgDurationSeconds\n  }\n}`,
  },
]

function GraphQLPage() {
  const t = useT()
  const toast = useToast()
  const [tab, setTab] = useState<"query" | "schema">("query")
  const [queryText, setQueryText] = useState(SNIPPETS[0].query)
  const [variablesText, setVariablesText] = useState("{}")
  const [result, setResult] = useState<GraphQLResult | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)

  const schemaQuery = useQuery({
    queryKey: ["graphql-schema"],
    queryFn: () => api.getGraphQLSchema(),
    enabled: tab === "schema",
  })

  const queryMutation = useMutation({
    mutationFn: async () => {
      let varsObj: Record<string, unknown> | undefined
      if (variablesText.trim() && variablesText.trim() !== "{}") {
        try {
          varsObj = JSON.parse(variablesText) as Record<string, unknown>
        } catch {
          throw new Error(t("graphql.invalidVars"))
        }
      }
      const start = performance.now()
      const res = await api.executeGraphQL(queryText.trim(), varsObj)
      const duration = Math.round(performance.now() - start)
      setElapsedMs(duration)
      return res
    },
    onSuccess: (data) => {
      setResult(data)
      if (data.errors && data.errors.length > 0) {
        toast(`${t("graphql.errorsPrefix")}${data.errors.length}${t("graphql.errorsSuffix")}`, "err")
      } else {
        toast(t("graphql.okToast"), "ok")
      }
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(`${t("graphql.errorToastPrefix")}${msg}`, "err")
    },
  })

  const schemaSDL = schemaQuery.data?.sdl ?? ""

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("graphql.title")}</h1>
        <span className="zf-meta">{t("graphql.subtitle")}</span>
        <span className="spacer" style={{ flex: 1 }} />
      </div>

      <div className="zf-tabs" role="tablist" aria-label={t("graphql.modeAria")}>
        <button type="button" role="tab" className="zf-tab" aria-selected={tab === "query"} onClick={() => setTab("query")}>
          {t("graphql.tabQuery")}
        </button>
        <button type="button" role="tab" className="zf-tab" aria-selected={tab === "schema"} onClick={() => setTab("schema")}>
          {t("graphql.tabSchema")}
        </button>
      </div>

      {tab === "query" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          <div className="zf-filters" style={{ padding: 0, border: 0, background: "transparent" }}>
            <span className="zf-meta">{t("graphql.readyExamples")}</span>
            {SNIPPETS.map((s) => (
              <button key={s.key} type="button" className="zf-btn" style={{ fontSize: 11 }} onClick={() => setQueryText(s.query)} title={t(s.descKey)}>
                {t(s.key)}
              </button>
            ))}
          </div>

          <div className="zf-split zf-split--2">
            <div className="zf-pane" style={{ display: "flex", flexDirection: "column" }}>
              <div className="zf-pane-hd">
                <span className="zf-micro">{t("graphql.editorTitle")}</span>
                <span className="zf-meta" style={{ marginLeft: "auto" }}>{t("graphql.ctrlHint")}</span>
              </div>
              <div className="zf-pane-bd" style={{ display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
                <textarea
                  className="zf-textarea"
                  style={{ fontFamily: "var(--font-mono)", fontSize: 11, minHeight: 220, lineHeight: 1.6 }}
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault()
                      queryMutation.mutate()
                    }
                  }}
                  placeholder="query { ... }"
                />
                <div className="zf-field">
                  <label className="zf-label">{t("graphql.varsLabel")}</label>
                  <textarea
                    className="zf-textarea"
                    style={{ fontFamily: "var(--font-mono)", fontSize: 11, minHeight: 72 }}
                    value={variablesText}
                    onChange={(e) => setVariablesText(e.target.value)}
                    placeholder="{}"
                  />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid var(--border)", paddingTop: "var(--s3)" }}>
                  <span className="zf-meta">{t("graphql.endpoint")}<code>POST /graphql</code></span>
                  <button type="button" className="zf-btn zf-btn--primary" onClick={() => queryMutation.mutate()} disabled={queryMutation.isPending || !queryText.trim()}>
                    {queryMutation.isPending ? <Spinner /> : SYM.ok} {t("graphql.runBtn")}
                  </button>
                </div>
              </div>
            </div>

            <div className="zf-pane" style={{ display: "flex", flexDirection: "column" }}>
              <div className="zf-pane-hd">
                <span className="zf-micro">{t("graphql.resultTitle")}</span>
                {elapsedMs !== null && <span className="zf-meta" style={{ marginLeft: "auto" }}>{elapsedMs}ms</span>}
              </div>
              <div className="zf-pane-bd" style={{ minHeight: 260 }}>
                {queryMutation.isPending ? (
                  <div className="zf-empty"><Spinner /> {t("graphql.processing")}</div>
                ) : result ? (
                  <pre className="zf-pre" style={{ maxHeight: 420, overflow: "auto" }}>{JSON.stringify(result, null, 2)}</pre>
                ) : (
                  <div className="zf-empty">{t("graphql.emptyResult")}</div>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="zf-pane">
          <div className="zf-pane-hd">
            <span className="zf-micro">{t("graphql.schemaTitle")}</span>
            <span className="zf-meta" style={{ marginLeft: "auto" }}>{t("graphql.schemaHint")}</span>
          </div>
          <div className="zf-pane-bd">
            {schemaQuery.isLoading ? (
              <div className="zf-empty"><Spinner /> {t("graphql.loadingSchema")}</div>
            ) : schemaSDL ? (
              <pre className="zf-pre" style={{ maxHeight: 550, overflow: "auto" }}>{schemaSDL}</pre>
            ) : (
              <p className="zf-meta" style={{ textAlign: "center", padding: "var(--s5) 0", margin: 0 }}>{t("graphql.schemaEmpty")}</p>
            )}
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/graphql")({
  component: GraphQLPage,
})

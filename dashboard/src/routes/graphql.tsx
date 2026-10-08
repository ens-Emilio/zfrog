import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, GraphQLResult } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { SYM, Spinner, CodeBlock } from "@/components/ui/tui"
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

  // Schema SDL query
  const schemaQuery = useQuery({
    queryKey: ["graphql-schema"],
    queryFn: () => api.getGraphQLSchema(),
    enabled: tab === "schema",
  })

  // Mutation to run the query
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
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[var(--border)] pb-2 mb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">{t("graphql.title")}</h1>
          <span className="text-xs text-[var(--fg-dim)]">
            {t("graphql.subtitle")}
          </span>
        </div>
        <div className="toggles text-xs" role="group" aria-label={t("graphql.modeAria")}>
          <button
            type="button"
            className="tgl"
            aria-pressed={tab === "query"}
            onClick={() => setTab("query")}
          >
            {t("graphql.tabQuery")}
          </button>
          <button
            type="button"
            className="tgl"
            aria-pressed={tab === "schema"}
            onClick={() => setTab("schema")}
          >
            {t("graphql.tabSchema")}
          </button>
        </div>
      </div>

      {tab === "query" ? (
        <div className="flex flex-col gap-4 text-xs">
          {/* Quick snippets bar */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[var(--fg-dim)]">{t("graphql.readyExamples")}</span>
            {SNIPPETS.map((s) => (
              <button
                key={s.key}
                type="button"
                className="tui-btn text-[11px]"
                onClick={() => setQueryText(s.query)}
                title={t(s.descKey)}
              >
                {t(s.key)}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Query editor */}
            <div className="tui-panel p-4 flex flex-col gap-3">
              <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between">
                <span>{t("graphql.editorTitle")}</span>
                <span className="text-[var(--fg-dim)]">{t("graphql.ctrlHint")}</span>
              </div>

              <textarea
                className="tui-input font-mono text-[11px] h-64 p-2 w-full leading-relaxed"
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

              <div>
                <label className="text-[var(--fg-dim)] block mb-1">{t("graphql.varsLabel")}</label>
                <textarea
                  className="tui-input font-mono text-[11px] h-20 p-2 w-full"
                  value={variablesText}
                  onChange={(e) => setVariablesText(e.target.value)}
                  placeholder="{}"
                />
              </div>

              <div className="flex justify-between items-center pt-2 border-t border-[var(--border)]">
                <span className="text-[var(--fg-dim)] text-[10px]">
                  {t("graphql.endpoint")}<code>POST /graphql</code>
                </span>
                <button
                  type="button"
                  className="tui-btn accent text-xs"
                  onClick={() => queryMutation.mutate()}
                  disabled={queryMutation.isPending || !queryText.trim()}
                >
                  {queryMutation.isPending ? <Spinner /> : SYM.ok} {t("graphql.runBtn")}
                </button>
              </div>
            </div>

            {/* Results panel */}
            <div className="tui-panel p-4 flex flex-col gap-3">
              <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between">
                <span>{t("graphql.resultTitle")}</span>
                {elapsedMs !== null && (
                  <span className="text-[var(--fg-dim)]">{elapsedMs}ms</span>
                )}
              </div>

              {queryMutation.isPending ? (
                <div className="py-20 text-center text-[var(--fg-dim)]">
                  <Spinner /> {t("graphql.processing")}
                </div>
              ) : result ? (
                <div className="overflow-y-auto max-h-[420px]">
                  <CodeBlock
                    code={JSON.stringify(result, null, 2).split("\n")}
                  />
                </div>
              ) : (
                <div className="py-20 text-center text-[var(--fg-dim)]">
                  {t("graphql.emptyResult")}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* Schema SDL tab */
        <div className="tui-panel p-4 flex flex-col gap-3 text-xs">
          <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between">
            <span>{t("graphql.schemaTitle")}</span>
            <span className="text-[var(--fg-dim)]">{t("graphql.schemaHint")}</span>
          </div>

          {schemaQuery.isLoading ? (
            <div className="py-12 text-center text-[var(--fg-dim)]">
              <Spinner /> {t("graphql.loadingSchema")}
            </div>
          ) : schemaSDL ? (
            <div className="overflow-y-auto max-h-[550px]">
              <CodeBlock code={schemaSDL.split("\n")} />
            </div>
          ) : (
            <p className="text-[var(--fg-dim)] py-6 text-center">{t("graphql.schemaEmpty")}</p>
          )}
        </div>
      )}
    </div>
  )
}

export const Route = createFileRoute("/graphql")({
  component: GraphQLPage,
})

import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useMemo, useState } from "react"
import { api, SearchHit, SearchResponse } from "@/lib/api"
import { Spinner, SYM } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

type SearchMode = "fulltext" | "semantic"

function hostOf(hit: SearchHit) {
  if (hit.url) {
    try {
      return new URL(hit.url).host
    } catch {
      // relative or malformed
    }
  }
  return hit.path
}

function formatScore(score: number) {
  if (!Number.isFinite(score)) return "—"
  if (score === 0) return "0"
  if (score >= 0.01) return score.toFixed(2)
  return score.toExponential(1)
}

function BuscaPage() {
  const t = useT()
  const [query, setQuery] = useState("")
  const [mode, setMode] = useState<SearchMode>("fulltext")
  const [titlesOnly, setTitlesOnly] = useState(false)
  const [dir, setDir] = useState("")

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const runSearch = useCallback(
    async (nextTerm = query, nextMode = mode) => {
      const term = nextTerm.trim()
      if (!term) return
      setLoading(true)
      setError(null)
      try {
        const res = await api.search(term, nextMode, dir.trim() || undefined)
        setResult(res)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [query, mode, titlesOnly, dir],
  )

  const hits = useMemo(() => {
    const all = result?.hits ?? []
    if (!titlesOnly || !result) return all
    const needle = result.query.toLocaleLowerCase("pt-BR")
    return all.filter((hit) => (hit.title || hit.path).toLocaleLowerCase("pt-BR").includes(needle))
  }, [result, titlesOnly])

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("busca.title")}</h1>
        <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
          {loading ? (
            <span><Spinner /> {t("busca.searching")}</span>
          ) : result ? (
            `${hits.length} ${t("busca.resultsCount")}`
          ) : (
            t("busca.subtitle")
          )}
        </span>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("busca.error")} {error}</p>
        </div>
      )}

      {/* TUI search bar */}
      <div className="filters flex-wrap" style={{ gap: "1ch 1.5ch", marginTop: "0.5lh" }}>
        <span className="searchline">
          <span className="slash">/</span>
          <input
            type="text"
            value={query}
            placeholder={t("busca.queryPlaceholder")}
            aria-label={t("busca.queryAria")}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch()
            }}
            style={{ width: "32ch" }}
            autoFocus
          />
        </span>

        <button
          type="button"
          className="tui-btn accent"
          onClick={() => void runSearch()}
          disabled={loading || !query.trim()}
        >
          {t("busca.submit")}
        </button>

        <div className="toggles" role="group" aria-label={t("busca.modeAria")}>
          <button
            type="button"
            className="tgl"
            aria-pressed={mode === "fulltext"}
            onClick={() => {
              setMode("fulltext")
              if (query.trim()) void runSearch(query, "fulltext")
            }}
          >
            full-text
          </button>
          <button
            type="button"
            className="tgl"
            aria-pressed={mode === "semantic"}
            onClick={() => {
              setMode("semantic")
              if (query.trim()) void runSearch(query, "semantic")
            }}
          >
            {t("busca.modeSemantic")}
          </button>
          <button
            type="button"
            className="tgl"
            aria-pressed={titlesOnly}
            onClick={() => setTitlesOnly((v) => !v)}
          >
            {t("busca.titlesOnly")}
          </button>
        </div>

        <input
          type="text"
          className="tui-input"
          value={dir}
          placeholder={t("busca.dirPlaceholder")}
          aria-label={t("busca.dirAria")}
          onChange={(e) => setDir(e.target.value)}
          style={{ width: "20ch", padding: "0.1lh 0.75ch", fontSize: 12 }}
        />
      </div>

      {/* Results */}
      {loading ? (
        <p className="empty"><Spinner /> {t("busca.scanning")}</p>
      ) : !result ? (
        <div className="tui-panel" style={{ marginTop: "1lh", color: "var(--fg-dim)", padding: "12px 16px" }}>
          <p style={{ margin: 0 }}>
            {t("busca.emptyIntro")}
          </p>
        </div>
      ) : result && hits.length === 0 ? (
        <div className="tui-panel">
          <p style={{ color: "var(--fg-muted)" }}>
            {t("busca.noResults")} <b>“{result.query}”</b>.
          </p>
          {result.mode === "semantic" && (
            <p className="tui-hint" style={{ marginTop: "0.25lh" }}>
              {t("busca.semanticNote")}
            </p>
          )}
        </div>
      ) : hits.length > 0 ? (
        <div className="rows" style={{ marginTop: "0.5lh" }}>
          {hits.map((hit, i) => {
            const host = hostOf(hit)
            return (
              <div
                key={hit.path + i}
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
                    <span style={{ fontWeight: 500, color: "var(--fg)" }}>
                      {hit.title || host}
                    </span>
                    <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>
                      {hit.path}
                    </span>
                  </div>
                  <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>
                    {t("busca.score")} {formatScore(hit.score)}
                  </span>
                </div>

                {hit.snippet && (
                  <p
                    style={{
                      color: "var(--fg-muted)",
                      fontSize: 12,
                      paddingLeft: "1ch",
                      borderLeft: "2px solid var(--line)",
                      margin: "0.25lh 0",
                    }}
                  >
                    {hit.snippet}
                  </p>
                )}

                {hit.url && (
                  <div>
                    <a
                      href={hit.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: "var(--accent)", fontSize: 12, textDecoration: "none" }}
                    >
                      {SYM.sub} {hit.url}
                    </a>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="empty">
          {t("busca.emptyHint")}
        </p>
      )}
    </>
  )
}

export const Route = createFileRoute("/busca")({
  component: BuscaPage,
})

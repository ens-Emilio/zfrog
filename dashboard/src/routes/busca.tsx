import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useMemo, useState } from "react"
import { api, SearchHit, SearchResponse } from "@/lib/api"
import { Spinner } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

type SearchMode = "fulltext" | "semantic"

function hostOf(hit: SearchHit) {
  if (hit.url) {
    try {
      return new URL(hit.url).hostname
    } catch {
      return hit.url
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
      <div className="zf-head">
        <h1 className="zf-title">{t("busca.title")}</h1>
        <span className="zf-meta">{t("busca.subtitle")}</span>
        <span className="spacer" style={{ flex: 1 }} />
        <span className="zf-micro">
          {loading ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <Spinner /> {t("busca.searching")}
            </span>
          ) : result ? (
            `${hits.length} ${t("busca.resultsCount")}`
          ) : (
            "—"
          )}
        </span>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>✗ {t("busca.error")} {error}</p>
        </div>
      )}

      <div className="zf-filters" style={{ marginBottom: "var(--s5)" }}>
        <div className="zf-prompt" style={{ flex: 1, minWidth: 220 }}>
          <span className="zf-meta">⌕</span>
          <input
            type="text"
            value={query}
            placeholder={t("busca.queryPlaceholder")}
            aria-label={t("busca.queryAria")}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch()
            }}
            autoFocus
          />
        </div>

        <button
          type="button"
          className="zf-btn zf-btn--primary"
          onClick={() => void runSearch()}
          disabled={loading || !query.trim()}
        >
          {t("busca.submit")}
        </button>

        <div role="group" aria-label={t("busca.modeAria")} style={{ display: "flex", gap: "var(--s1)", flexWrap: "wrap" }}>
          <button
            type="button"
            className="zf-pill"
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
            className="zf-pill"
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
            className="zf-pill"
            aria-pressed={titlesOnly}
            onClick={() => setTitlesOnly((v) => !v)}
          >
            {t("busca.titlesOnly")}
          </button>
        </div>

        <input
          type="text"
          className="zf-input"
          value={dir}
          placeholder={t("busca.dirPlaceholder")}
          aria-label={t("busca.dirAria")}
          onChange={(e) => setDir(e.target.value)}
          style={{ width: "22ch" }}
        />
      </div>

      {loading ? (
        <div className="zf-empty">
          <Spinner /> {t("busca.scanning")}
        </div>
      ) : !result ? (
        <div className="zf-panel">
          <div className="zf-panel-bd">
            <p className="zf-meta" style={{ margin: 0 }}>
              {t("busca.emptyIntro")}
            </p>
          </div>
        </div>
      ) : result && hits.length === 0 ? (
        <div className="zf-panel">
          <div className="zf-panel-bd">
            <p style={{ color: "var(--muted)", margin: 0 }}>
              {t("busca.noResults")} <b>“{result.query}”</b>.
            </p>
            {result.mode === "semantic" && <p className="zf-hint">{t("busca.semanticNote")}</p>}
          </div>
        </div>
      ) : hits.length > 0 ? (
        <div className="zf-list" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--surface)", overflow: "hidden" }}>
          {hits.map((hit, i) => {
            const host = hostOf(hit)
            return (
              <div
                key={hit.path + i}
                style={{
                  padding: "var(--s3) var(--s4)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--s2)",
                  borderBottom: i < hits.length - 1 ? "1px solid var(--border)" : "none",
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "var(--s3)", flexWrap: "wrap" }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: "var(--s2)", minWidth: 0 }}>
                    <span style={{ fontWeight: 550, color: "var(--fg)", fontSize: "var(--fs-body)" }}>{hit.title || host}</span>
                    <span className="zf-meta" style={{ fontSize: "var(--fs-micro)" }}>
                      {hit.path}
                    </span>
                  </div>
                  <span className="zf-micro" style={{ whiteSpace: "nowrap" }}>
                    {t("busca.score")} <span className="zf-num">{formatScore(hit.score)}</span>
                  </span>
                </div>

                {hit.snippet && (
                  <p
                    style={{
                      color: "var(--muted)",
                      fontSize: "var(--fs-meta)",
                      paddingLeft: "var(--s3)",
                      borderLeft: "2px solid var(--border)",
                      margin: 0,
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
                      style={{ color: "var(--accent)", fontSize: "var(--fs-meta)", textDecoration: "none" }}
                    >
                      ⎿ {hit.url}
                    </a>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="zf-empty">{t("busca.emptyHint")}</div>
      )}
    </>
  )
}

export const Route = createFileRoute("/busca")({
  component: BuscaPage,
})

"use client"

import { useCallback, useMemo, useState } from "react"
import { api, SearchHit, SearchResponse } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/ds"
import { EmptyState } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Icon } from "@/lib/icons"

type SearchMode = "fulltext" | "semantic"
/** The three chips of the filter rail; `titles` narrows the same search to titles. */
type RailOption = SearchMode | "titles"

const MODE_LABEL: Record<SearchMode, string> = {
  fulltext: "Full-text",
  semantic: "Semântica",
}

/** The request the visible result belongs to, so the rail can re-run it. */
interface Attempt {
  term: string
  mode: SearchMode
  titlesOnly: boolean
}

/** Where a hit came from: the host of its URL, or the file path when there is none. */
function hostOf(hit: SearchHit) {
  if (hit.url) {
    try {
      return new URL(hit.url).host
    } catch {
      // A relative or malformed URL still has a usable path below.
    }
  }
  return hit.path
}

/**
 * The relevance score as the engine returned it.
 *
 * Full-text scores sit orders of magnitude below 1, where two decimals would print
 * "0.00" for every row; only small values fall back to exponent notation.
 */
function formatScore(score: number) {
  if (!Number.isFinite(score)) return "—"
  if (score === 0) return "0"
  if (score >= 0.01) return score.toFixed(2)
  return score.toExponential(1)
}

export default function BuscaPage() {
  const [query, setQuery] = useState("")
  const [mode, setMode] = useState<SearchMode>("fulltext")
  const [titlesOnly, setTitlesOnly] = useState(false)
  const [dir, setDir] = useState("")

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState<Attempt | null>(null)

  const runSearch = useCallback(
    async (rawTerm: string, nextMode: SearchMode, nextTitlesOnly: boolean) => {
      const term = rawTerm.trim()
      if (!term) return
      setAttempt({ term, mode: nextMode, titlesOnly: nextTitlesOnly })
      setLoading(true)
      setError(null)
      setResult(null)
      try {
        setResult(await api.search(term, nextMode, dir.trim() || undefined))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [dir]
  )

  /** Chip click: switch the mode, or flip the titles-only narrowing, and re-run. */
  const pick = (option: RailOption) => {
    const nextMode: SearchMode = option === "titles" ? mode : option
    const nextTitlesOnly = option === "titles" ? !titlesOnly : false
    setMode(nextMode)
    setTitlesOnly(nextTitlesOnly)
    if (attempt) void runSearch(attempt.term, nextMode, nextTitlesOnly)
  }

  const hits = useMemo(() => {
    const all = result?.hits ?? []
    if (!titlesOnly || !result) return all
    const needle = result.query.toLocaleLowerCase("pt-BR")
    return all.filter((hit) => (hit.title || hit.path).toLocaleLowerCase("pt-BR").includes(needle))
  }, [result, titlesOnly])

  const emptyDescription =
    result?.mode === "semantic"
      ? "A busca semântica precisa de um modelo de IA configurado; sem ele ela não encontra nada. Enquanto isso, use Full-text, que procura as palavras exatas."
      : titlesOnly
        ? `Nenhum título tem “${result?.query ?? ""}”. Procure em todo o texto da página.`
        : `Nenhuma página indexada tem “${result?.query ?? ""}”. Tente uma palavra mais curta, ou informe a pasta onde o site foi baixado.`

  return (
    <div className="view-grid">
      <Topbar
        title="Busca"
        description="Procure uma palavra ou uma frase dentro de tudo que você já baixou. A busca só enxerga conteúdo que já foi clonado — informe uma pasta para indexar e procurar só ali."
      />

      <form
        className="toolbar"
        role="search"
        aria-label="Buscar no conteúdo baixado"
        onSubmit={(event) => {
          event.preventDefault()
          void runSearch(query, mode, titlesOnly)
        }}
      >
        <div className="search-wrap">
          <Icon name="i-search" />
          <input
            className="input"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="O que você procura?"
            placeholder="O que você procura?"
            autoComplete="off"
          />
        </div>

        <div className="filter-rail" role="group" aria-label="Como procurar">
          <Chip active={mode === "fulltext" && !titlesOnly} onClick={() => pick("fulltext")}>
            Full-text
          </Chip>
          <Chip active={mode === "semantic" && !titlesOnly} onClick={() => pick("semantic")}>
            Semântica
          </Chip>
          <Chip active={titlesOnly} onClick={() => pick("titles")}>
            Só títulos
          </Chip>
        </div>

        <input
          className="input input-mono"
          style={{ flex: "1 1 190px", minWidth: 0, maxWidth: "320px" }}
          value={dir}
          onChange={(event) => setDir(event.target.value)}
          aria-label="Pasta (opcional): indexar e procurar só dentro dela"
          placeholder="Pasta (opcional)"
        />

        <Button type="submit" className="od-touch" loading={loading} disabled={!query.trim()}>
          <Icon name="i-search" size="sm" /> Buscar
        </Button>
      </form>

      {result && !error && (
        <p className="list-meta">
          <span>
            {hits.length} {hits.length === 1 ? "resultado" : "resultados"} para “{result.query}”
          </span>
          <span>
            {MODE_LABEL[result.mode]}
            {titlesOnly ? " · só títulos" : ""}
          </span>
        </p>
      )}

      {loading && (
        <div className="stack-sm" aria-busy="true">
          <Skeleton className="h-[92px]" />
          <Skeleton className="h-[92px]" />
          <Skeleton className="h-[92px]" />
        </div>
      )}

      {error && (
        <div className="card stack-sm" role="alert">
          <h2 className="card-title od-row" style={{ ["--od-gap" as string]: "8px" }}>
            <Icon name="i-alert" /> Não foi possível buscar
          </h2>
          <p className="card-sub">{error}</p>
          <p className="hint">
            Confira se a API está no ar e se a pasta informada existe. Se o site ainda não foi baixado, nada aparece
            aqui.
          </p>
          <div className="od-row">
            <Button
              variant="secondary"
              onClick={() => {
                if (attempt) void runSearch(attempt.term, attempt.mode, attempt.titlesOnly)
              }}
            >
              <Icon name="i-refresh" size="sm" /> Tentar de novo
            </Button>
          </div>
        </div>
      )}

      {result?.error && <p className="error-text">{result.error}</p>}

      {!loading && hits.length > 0 && (
        <div className="stack-sm">
          {hits.map((hit, index) => {
            const host = hostOf(hit)
            return (
              <article
                key={`${hit.path}-${index}`}
                className="job-row"
                style={{ gridTemplateColumns: "minmax(0,1fr)" }}
              >
                <div className="job-meta">
                  <div className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
                    {hit.url ? (
                      <a
                        className="job-url od-truncate"
                        style={{ color: "var(--text-1)" }}
                        href={hit.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {hit.title || hit.path}
                      </a>
                    ) : (
                      <span className="job-url od-truncate">{hit.title || hit.path}</span>
                    )}
                    <span
                      className="mono text-[var(--fs-12)] text-[var(--text-3)]"
                      title="Nota de relevância devolvida pela busca"
                    >
                      {formatScore(hit.score)}
                    </span>
                  </div>
                  <span className="detail-url od-truncate">{host}</span>
                  <span className="job-sub">{hit.snippet || hit.path}</span>
                </div>
              </article>
            )
          })}
        </div>
      )}

      {!loading && !error && result && hits.length === 0 && (
        <EmptyState
          icon={<Icon name="i-search" size="lg" />}
          title="Nada encontrado"
          description={emptyDescription}
          action={titlesOnly ? { label: "Procurar em todo o texto", onClick: () => pick("fulltext") } : undefined}
        />
      )}

      {!loading && !error && !result && (
        <EmptyState
          icon={<Icon name="i-search" size="lg" />}
          title="Digite algo para começar"
          description="Escreva uma palavra ou frase e pressione Enter. Os trechos onde ela aparece voltam com um pedaço do texto em volta e a nota de relevância."
        />
      )}
    </div>
  )
}

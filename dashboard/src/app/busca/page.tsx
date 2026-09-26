"use client"
import { useState } from "react"
import { api, SearchResponse, SearchHit } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Search, Sparkles, Globe, FolderOpen, FileText, SearchX, AlertTriangle, Check } from "lucide-react"

type SearchMode = "fulltext" | "semantic"

/** Short, plain-language description of each search mode. */
const MODE_INFO: Record<SearchMode, { label: string; icon: typeof Search; what: string }> = {
  fulltext: {
    label: "Texto exato",
    icon: Search,
    what: "Procura as palavras que você digitou, exatamente como escreveu. É rápido e funciona sempre.",
  },
  semantic: {
    label: "Semântico",
    icon: Sparkles,
    what: "Procura pelo sentido da frase, então encontra páginas que falam do assunto mesmo usando outras palavras.",
  },
}

export default function BuscaPage() {
  const [query, setQuery] = useState("")
  const [mode, setMode] = useState<SearchMode>("fulltext")
  const [dir, setDir] = useState("")

  const [searching, setSearching] = useState(false)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSearch = async () => {
    const term = query.trim()
    if (!term) return
    setSearching(true)
    setError(null)
    setResult(null)
    try {
      setResult(await api.search(term, mode, dir.trim() || undefined))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSearching(false)
    }
  }

  const hits: SearchHit[] = result?.hits ?? []
  const modeInfo = MODE_INFO[mode]

  return (
    <div className="space-y-6 max-w-[1000px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Busca"
        description="Procure uma palavra ou uma frase dentro de tudo que você já baixou. A busca só enxerga conteúdo que já foi clonado."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" /> O que você procura?
          </CardTitle>
          <CardDescription>{modeInfo.what}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Palavra ou frase"
                placeholder="ex.: política de privacidade"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                leftIcon={<Search className="h-4 w-4" />}
              />
            </div>
            <Button onClick={handleSearch} loading={searching} disabled={!query.trim()} className="sm:mb-0">
              <Search className="h-4 w-4" /> Buscar
            </Button>
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-[12.5px] font-medium text-foreground/80">Como procurar</label>
            <div className="grid sm:grid-cols-2 gap-2">
              {(Object.keys(MODE_INFO) as SearchMode[]).map((m) => {
                const info = MODE_INFO[m]
                const Icon = info.icon
                const active = mode === m
                return (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className={`text-left rounded-[10px] border p-3 transition-all ${
                      active ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "hover:bg-accent"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2 text-[13px] font-medium">
                        <Icon className="h-3.5 w-3.5" /> {info.label}
                      </span>
                      {active && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
                    </div>
                  </button>
                )
              })}
            </div>
            <p className="text-[12px] text-muted-foreground">
              <strong className="text-foreground/80">A diferença:</strong> Texto exato acha as palavras digitadas;
              Semântico acha também páginas que tratam do mesmo assunto com outras palavras.
            </p>
          </div>

          <Input
            label="Pasta (opcional)"
            placeholder="output/meusite"
            value={dir}
            onChange={(e) => setDir(e.target.value)}
            leftIcon={<FolderOpen className="h-4 w-4" />}
            hint="Preencha para procurar só dentro de uma pasta. Em branco, procura em tudo que já foi indexado."
          />

          {error && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível buscar.</p>
              <p className="mt-1">{error}</p>
            </div>
          )}

          {result?.error && (
            <div className="rounded-[12px] bg-amber-500/10 border border-amber-500/20 p-3 text-[13px] text-amber-700 dark:text-amber-400">
              <p className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="h-3.5 w-3.5" /> A busca não pôde ser concluída do jeito pedido.
              </p>
              <p className="mt-1">{result.error}</p>
              {result.mode === "semantic" && (
                <p className="mt-1 text-muted-foreground">
                  O modo Semântico precisa de um modelo de IA configurado. Enquanto isso, use{" "}
                  <strong className="text-foreground/80">Texto exato</strong>.
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {result && !result.error && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-4 w-4" /> Resultados
            </CardTitle>
            <CardDescription>
              {hits.length === 0
                ? `Nada encontrado para “${result.query}”.`
                : `${hits.length} resultado(s) para “${result.query}” no modo ${MODE_INFO[result.mode].label}.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {hits.length === 0 ? (
              <div className="rounded-[12px] border border-dashed p-10 text-center">
                <SearchX className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
                <p className="text-[13px] font-medium">Nada encontrado para “{result.query}”.</p>
                <p className="text-[12.5px] text-muted-foreground mt-1 max-w-md mx-auto">
                  Confira se o site já foi baixado e se a busca está no modo certo. Tente uma palavra mais curta ou
                  menos específica.
                </p>
              </div>
            ) : (
              <div className="rounded-[12px] border divide-y">
                {hits.map((hit) => (
                  <div key={`${hit.path}-${hit.url}`} className="px-4 py-3 space-y-1.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-[13.5px] font-medium truncate" title={hit.title || hit.path}>
                          {hit.title || hit.path}
                        </p>
                        <a
                          href={hit.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 text-[11.5px] text-primary hover:underline break-all"
                        >
                          <Globe className="h-3 w-3 shrink-0" />
                          {hit.url || hit.path}
                        </a>
                      </div>
                      <span className="shrink-0 rounded-full bg-secondary px-2.5 py-1 text-[11px] font-mono text-muted-foreground">
                        {hit.score.toFixed(2)}
                      </span>
                    </div>
                    <p className="text-[12.5px] text-muted-foreground leading-relaxed">{hit.snippet}</p>
                    <p className="text-[11px] font-mono text-muted-foreground/70 break-all">{hit.path}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!result && !error && !searching && (
        <Card className="border-dashed">
          <CardContent className="p-10 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <Search className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">Digite algo para começar</h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
              Escreva uma palavra ou frase e clique em <strong className="text-foreground">Buscar</strong>. Os
              trechos onde ela aparece são mostrados com um pedaço do texto em volta.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

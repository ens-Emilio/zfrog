"use client"
import { useEffect, useState } from "react"
import { api, DiffReport, SnapshotEntry } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { RefreshCw, History, GitCompare, FilePlus2, FileMinus2, FilePen, CheckCircle2, AlertTriangle } from "lucide-react"

/** How a single page fared between the two snapshots. */
type PageChange = { path: string; kind: "added" | "removed" | "changed" | "unchanged"; diffLines?: number }

const changeStyle: Record<PageChange["kind"], { label: string; className: string; icon: typeof FilePlus2 }> = {
  added: { label: "Adicionada", className: "text-emerald-600 dark:text-emerald-400", icon: FilePlus2 },
  removed: { label: "Removida", className: "text-red-600 dark:text-red-400", icon: FileMinus2 },
  changed: { label: "Alterada", className: "text-amber-600 dark:text-amber-400", icon: FilePen },
  unchanged: { label: "Igual", className: "text-muted-foreground", icon: CheckCircle2 },
}

export default function SnapshotsPage() {
  const [snapshots, setSnapshots] = useState<SnapshotEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [slug, setSlug] = useState<string>("")
  const [olderRef, setOlderRef] = useState("")
  const [newerRef, setNewerRef] = useState("")

  const [report, setReport] = useState<DiffReport | null>(null)
  const [comparing, setComparing] = useState(false)
  const [compareError, setCompareError] = useState<string | null>(null)

  const fetchSnapshots = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getSnapshots()
      setSnapshots(data)
      const slugs = Array.from(new Set(data.map((s) => s.slug)))
      setSlug((current) => (current && slugs.includes(current) ? current : slugs[0] ?? ""))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSnapshots()
  }, [])

  const slugs = Array.from(new Set(snapshots.map((s) => s.slug)))
  const forSlug = snapshots.filter((s) => s.slug === slug)

  // Default to comparing the two most recent captures of the chosen site.
  useEffect(() => {
    if (forSlug.length >= 2) {
      const last = forSlug[forSlug.length - 1]
      const prev = forSlug[forSlug.length - 2]
      setOlderRef(`${prev.slug}/${prev.file}`)
      setNewerRef(`${last.slug}/${last.file}`)
    } else {
      setOlderRef("")
      setNewerRef("")
    }
  }, [slug, snapshots.length])

  const handleCompare = async () => {
    setComparing(true)
    setCompareError(null)
    setReport(null)
    try {
      setReport(await api.diffSnapshots(olderRef, newerRef))
    } catch (e) {
      setCompareError(e instanceof Error ? e.message : String(e))
    } finally {
      setComparing(false)
    }
  }

  const selectedSite = forSlug[0]?.url
  const pageChanges: PageChange[] = report
    ? [
        ...report.added.map((path) => ({ path, kind: "added" as const })),
        ...report.removed.map((path) => ({ path, kind: "removed" as const })),
        ...report.changed.map((path) => ({
          path,
          kind: "changed" as const,
          diffLines: report.details.find((d) => d.path === path)?.text_diff_lines,
        })),
        ...report.unchanged.map((path) => ({ path, kind: "unchanged" as const })),
      ]
    : []

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Histórico e mudanças"
        description="Cada cópia de site (modo Site completo ou Site com JavaScript) guarda uma versão. Compare duas para ver o que mudou."
        action={
          <Button onClick={fetchSnapshots} loading={loading} size="sm" variant="outline">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      {error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar o histórico.</p>
            <p className="mt-1">{error}</p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && snapshots.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <History className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">Nenhuma versão guardada ainda</h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
              Faça uma cópia nos modos <strong>Site completo</strong> ou <strong>Site com JavaScript</strong>. Cada
              cópia vira uma versão que pode ser comparada depois.
            </p>
          </CardContent>
        </Card>
      )}

      {snapshots.length > 0 && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-4 w-4" /> Versões guardadas
              </CardTitle>
              <CardDescription>
                {snapshots.length} versão(ões) de {slugs.length} site(s). A mais recente aparece por último.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {slugs.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSlug(s)}
                    className={`rounded-[10px] border px-3 py-1.5 text-[12.5px] font-medium transition-all ${
                      slug === s ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "hover:bg-accent"
                    }`}
                  >
                    {snapshots.find((x) => x.slug === s)?.url || s}
                  </button>
                ))}
              </div>

              <div className="rounded-[12px] border divide-y">
                {forSlug.map((s) => (
                  <div key={s.file} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="text-[12.5px] font-mono">{s.file}</span>
                    <span className="text-[12px] text-muted-foreground">
                      {new Date(s.captured_at).toLocaleString("pt-BR")}
                    </span>
                    <span className="text-[12px] text-muted-foreground">{s.pages} página(s)</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitCompare className="h-4 w-4" /> Comparar duas versões
              </CardTitle>
              <CardDescription>
                A comparação é feita entre a versão antiga e a nova. Já vem preenchida com as duas últimas.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12.5px] font-medium text-foreground/80">Versão antiga</span>
                  <select
                    value={olderRef}
                    onChange={(e) => setOlderRef(e.target.value)}
                    className="h-9 rounded-[10px] border bg-background px-3 text-[13px]"
                  >
                    {forSlug.map((s) => (
                      <option key={s.file} value={`${s.slug}/${s.file}`}>
                        {s.file}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[12.5px] font-medium text-foreground/80">Versão nova</span>
                  <select
                    value={newerRef}
                    onChange={(e) => setNewerRef(e.target.value)}
                    className="h-9 rounded-[10px] border bg-background px-3 text-[13px]"
                  >
                    {forSlug.map((s) => (
                      <option key={s.file} value={`${s.slug}/${s.file}`}>
                        {s.file}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <Button
                onClick={handleCompare}
                loading={comparing}
                disabled={!olderRef || !newerRef || forSlug.length < 2}
              >
                <GitCompare className="h-4 w-4" /> Comparar
              </Button>

              {forSlug.length < 2 && (
                <p className="text-[12px] text-muted-foreground">
                  É preciso ter pelo menos duas versões deste site para comparar.
                </p>
              )}

              {compareError && (
                <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                  <p className="font-medium">Não foi possível comparar.</p>
                  <p className="mt-1">{compareError}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {report && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" /> O que mudou
            </CardTitle>
            <CardDescription>
              {selectedSite || report.url} — {Math.round(report.change_ratio * 100)}% das páginas mudaram.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {(
                [
                  ["Adicionadas", report.added.length, "text-emerald-600 dark:text-emerald-400"],
                  ["Removidas", report.removed.length, "text-red-600 dark:text-red-400"],
                  ["Alteradas", report.changed.length, "text-amber-600 dark:text-amber-400"],
                  ["Iguais", report.unchanged.length, "text-muted-foreground"],
                ] as const
              ).map(([label, count, color]) => (
                <div key={label} className="rounded-[12px] border bg-secondary/40 p-3">
                  <p className="text-[11px] uppercase tracking-widest text-muted-foreground font-medium">{label}</p>
                  <p className={`text-[20px] font-semibold ${color}`}>{count}</p>
                </div>
              ))}
            </div>

            {pageChanges.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">
                Nenhuma página para comparar — as duas versões estão vazias.
              </p>
            ) : (
              <div className="rounded-[12px] border divide-y">
                {pageChanges.map((page) => {
                  const style = changeStyle[page.kind]
                  const Icon = style.icon
                  return (
                    <div key={`${page.kind}-${page.path}`} className="flex items-center gap-3 px-4 py-2.5">
                      <Icon className={`h-3.5 w-3.5 shrink-0 ${style.className}`} />
                      <span className="text-[12.5px] font-mono truncate flex-1" title={page.path}>
                        {page.path}
                      </span>
                      {page.diffLines != null && (
                        <span className="text-[11.5px] text-muted-foreground shrink-0">
                          {page.diffLines} linha(s)
                        </span>
                      )}
                      <span className={`text-[12px] font-medium shrink-0 ${style.className}`}>{style.label}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

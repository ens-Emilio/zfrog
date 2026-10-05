"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { api, DiffReport, SnapshotEntry } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { EmptyState } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Icon } from "@/lib/icons"
import { formatStamp } from "@/lib/utils"

/**
 * Histórico de capturas de um site e comparação entre duas delas.
 *
 * Cada linha do tempo é uma lista de capturas guardadas; escolher duas libera a
 * comparação, que devolve o que foi adicionado, removido, alterado e o que
 * permaneceu igual entre a mais antiga e a mais recente das duas.
 */

/** Quantas linhas do diff são desenhadas antes de avisar que a lista continua. */
const MAX_ROWS = 200

/** Uma linha do bloco `.diff`: o sinal, o caminho e, quando houver, as linhas mexidas. */
type DiffRow = { kind: "add" | "del" | "same"; sign: string; path: string; lines?: number }

/** Falha de leitura ou de ação: diz o que aconteceu e oferece como tentar de novo. */
function ErrorBlock({ title, message, onRetry }: { title: string; message: string; onRetry?: () => void }) {
  return (
    <div className="card stack-sm" style={{ borderColor: "var(--danger)" }}>
      <span className="badge badge-danger">
        <span className="dot" aria-hidden="true" />
        Erro
      </span>
      <h3 className="card-title">{title}</h3>
      <p className="card-sub">{message}</p>
      {onRetry && (
        <div>
          <Button variant="secondary" size="sm" className="od-touch" onClick={onRetry}>
            <Icon name="i-refresh" size="sm" />
            Tentar de novo
          </Button>
        </div>
      )}
    </div>
  )
}

/** A silhueta da tela enquanto as capturas chegam. */
function PageSkeleton() {
  return (
    <div className="stack-lg" aria-hidden="true">
      <div className="card">
        <Skeleton className="h-10 w-full max-w-[320px]" />
      </div>
      <div className="two-col">
        <div className="card stack-md">
          <Skeleton className="h-4 w-32" />
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-16 w-full" />
          ))}
        </div>
        <div className="card stack-md">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </div>
    </div>
  )
}

export default function SnapshotsPage() {
  const [snapshots, setSnapshots] = useState<SnapshotEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [slug, setSlug] = useState("")

  /** Os `file` das duas capturas escolhidas, na ordem em que foram marcadas. */
  const [selected, setSelected] = useState<string[]>([])
  const [report, setReport] = useState<DiffReport | null>(null)
  const [comparing, setComparing] = useState(false)
  const [compareError, setCompareError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getSnapshots()
      setSnapshots(data)
      const slugs = Array.from(new Set(data.map((entry) => entry.slug)))
      setSlug((current) => (current && slugs.includes(current) ? current : (slugs[0] ?? "")))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const slugs = useMemo(() => Array.from(new Set(snapshots.map((entry) => entry.slug))), [snapshots])

  /** As capturas do site escolhido, da mais recente para a mais antiga. */
  const captures = useMemo(
    () =>
      snapshots
        .filter((entry) => entry.slug === slug)
        .sort((a, b) => new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime()),
    [snapshots, slug]
  )

  // Ao trocar de site (ou recarregar a lista) a escolha volta para as duas capturas mais recentes.
  useEffect(() => {
    setSelected(captures.slice(0, 2).map((entry) => entry.file))
    setReport(null)
    setCompareError(null)
  }, [captures])

  /** Marca ou desmarca uma captura; ao marcar a terceira, a mais antiga sai. */
  const toggleCapture = (file: string) => {
    setReport(null)
    setCompareError(null)
    setSelected((previous) => {
      if (previous.includes(file)) return previous.filter((item) => item !== file)
      if (previous.length < 2) return [...previous, file]
      const chosen = captures.filter((entry) => previous.includes(entry.file))
      // `captures` vem da mais recente para a mais antiga: a última é a mais antiga marcada.
      const keep = chosen.length ? chosen[0].file : previous[previous.length - 1]
      return [keep, file]
    })
  }

  const chosen = useMemo(
    () => captures.filter((entry) => selected.includes(entry.file)),
    [captures, selected]
  )
  /** Mais antiga → mais recente, que é a ordem que a comparação espera. */
  const older = chosen.length === 2 ? chosen[1] : null
  const newer = chosen.length === 2 ? chosen[0] : null

  const compare = async () => {
    if (!older || !newer) return
    setComparing(true)
    setCompareError(null)
    setReport(null)
    try {
      setReport(await api.diffSnapshots(`${older.slug}/${older.file}`, `${newer.slug}/${newer.file}`))
    } catch (e) {
      setCompareError(e instanceof Error ? e.message : String(e))
    } finally {
      setComparing(false)
    }
  }

  const rows: DiffRow[] = useMemo(() => {
    if (!report) return []
    const linesOf = (path: string) => report.details.find((detail) => detail.path === path)?.text_diff_lines
    return [
      ...report.added.map((path) => ({ kind: "add" as const, sign: "+", path })),
      ...report.removed.map((path) => ({ kind: "del" as const, sign: "-", path })),
      ...report.changed.map((path) => ({ kind: "same" as const, sign: "~", path, lines: linesOf(path) })),
    ]
  }, [report])

  const visibleRows = rows.slice(0, MAX_ROWS)

  return (
    <div className="view-grid">
      <Topbar
        title="Histórico"
        description="Cada cópia guardada de um site é uma captura. Escolha duas na linha do tempo para ver o que mudou entre elas."
        action={
          <Button variant="secondary" size="sm" className="od-touch" loading={loading} onClick={() => void load()}>
            <Icon name="i-refresh" size="sm" />
            Atualizar
          </Button>
        }
      />

      {loading && <PageSkeleton />}

      {!loading && error && (
        <ErrorBlock
          title="Não foi possível carregar o histórico."
          message={error}
          onRetry={() => void load()}
        />
      )}

      {!loading && !error && snapshots.length === 0 && (
        <EmptyState
          icon={<Icon name="i-history" size="lg" />}
          title="Nenhuma captura guardada ainda"
          description="Faça uma extração nos modos Site completo ou Site com JavaScript. Cada cópia vira uma captura desta linha do tempo."
          href={{ label: "Ir para Nova extração", href: "/" }}
        />
      )}

      {!loading && !error && snapshots.length > 0 && (
        <>
          <div className="card">
            <div className="row-between">
              <div className="od-field" style={{ ["--od-gap" as string]: "6px", maxWidth: "320px" }}>
                <Select
                  label="Site acompanhado"
                  value={slug}
                  onChange={setSlug}
                  options={slugs.map((item) => ({
                    value: item,
                    label: snapshots.find((entry) => entry.slug === item)?.url || item,
                  }))}
                />
              </div>
              <Button
                className="od-touch"
                disabled={!older || !newer || comparing}
                loading={comparing}
                onClick={() => void compare()}
              >
                <Icon name="i-scale" size="sm" />
                Comparar capturas
              </Button>
            </div>
          </div>

          <div className="two-col">
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-4)" }}>
                Linha do tempo
              </h3>
              {captures.length === 0 ? (
                <p className="card-sub">Nenhuma captura guardada para este site.</p>
              ) : (
                <div className="timeline">
                  {captures.map((entry, index) => {
                    const isSelected = selected.includes(entry.file)
                    const parsed = new Date(entry.captured_at)
                    const readable = isNaN(parsed.getTime())
                    const date = readable ? entry.file : parsed.toLocaleDateString("pt-BR")
                    const hour = readable
                      ? ""
                      : parsed.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
                    return (
                      <div key={entry.file} className={isSelected ? "tl-item is-selected" : "tl-item"}>
                        <button
                          type="button"
                          className="tl-btn od-touch"
                          aria-pressed={isSelected}
                          onClick={() => toggleCapture(entry.file)}
                        >
                          <span className="od-row" style={{ ["--od-gap" as string]: "8px", flexWrap: "wrap" }}>
                            <strong style={{ fontSize: "var(--fs-14)" }}>{date}</strong>
                            {index === 0 && <Badge variant="accent">atual</Badge>}
                          </span>
                          <span className="job-sub">
                            <span>
                              {entry.pages} {entry.pages === 1 ? "página" : "páginas"}
                            </span>
                            {hour && <span aria-hidden="true">·</span>}
                            {hour && <span>{hour}</span>}
                            <span aria-hidden="true">·</span>
                            <span className="mono od-truncate">{entry.file}</span>
                          </span>
                        </button>
                      </div>
                    )
                  })}
                </div>
              )}
              {captures.length > 0 && (
                <p className="hint" style={{ marginTop: "var(--sp-4)" }}>
                  {chosen.length === 2
                    ? "Duas capturas marcadas. Toque em outra para trocar a mais antiga."
                    : "Marque duas capturas para comparar."}
                </p>
              )}
            </div>

            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
                O que mudou
              </h3>
              <p className="card-sub" style={{ marginBottom: "var(--sp-3)" }}>
                {older && newer
                  ? `Comparando ${formatStamp(older.captured_at)} → ${formatStamp(newer.captured_at)} (mais antiga → mais recente).`
                  : "Selecione duas capturas na linha do tempo para ver o que mudou."}
              </p>

              {compareError && (
                <div className="stack-sm" style={{ marginBottom: "var(--sp-3)" }}>
                  <span className="error-text">
                    <Icon name="i-alert" size="sm" />
                    {compareError}
                  </span>
                  <div>
                    <Button variant="secondary" size="sm" className="od-touch" onClick={() => void compare()}>
                      <Icon name="i-refresh" size="sm" />
                      Tentar de novo
                    </Button>
                  </div>
                </div>
              )}

              {report && (
                <>
                  <div className="od-cluster" style={{ marginBottom: "var(--sp-3)" }}>
                    <Badge variant="success">+{report.added.length} adicionadas</Badge>
                    <Badge variant="danger">-{report.removed.length} removidas</Badge>
                    <Badge variant="warning">{report.changed.length} alteradas</Badge>
                    <Badge variant="neutral">{report.unchanged.length} sem mudança</Badge>
                  </div>

                  <div className="diff" role="region" aria-label="Lista de páginas alteradas entre as duas capturas" aria-live="polite">
                    {visibleRows.length === 0 ? (
                      <div className="diff-row same">
                        <span className="sign"> </span>
                        <span>Nenhuma diferença entre as duas capturas.</span>
                      </div>
                    ) : (
                      visibleRows.map((row) => (
                        <div key={`${row.kind}-${row.path}`} className={`diff-row ${row.kind}`}>
                          <span className="sign">{row.sign}</span>
                          <span>
                            {row.path}
                            {row.lines != null && ` · ${row.lines} ${row.lines === 1 ? "linha" : "linhas"}`}
                          </span>
                        </div>
                      ))
                    )}
                  </div>

                  {rows.length > visibleRows.length && (
                    <p className="hint" style={{ marginTop: "var(--sp-2)" }}>
                      Mostrando {visibleRows.length} de {rows.length} páginas com mudança.
                    </p>
                  )}
                  <p className="list-meta" style={{ marginTop: "var(--sp-3)" }}>
                    <span>
                      {Math.round(report.change_ratio * 100)}% das páginas mudaram desde a captura mais antiga.
                    </span>
                    <span className="mono od-truncate">{report.url}</span>
                  </p>
                </>
              )}

              {!report && !compareError && (
                <div className="diff" aria-hidden="true">
                  <div className="diff-row same">
                    <span className="sign"> </span>
                    <span>A comparação aparece aqui depois de escolher duas capturas e tocar em Comparar capturas.</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

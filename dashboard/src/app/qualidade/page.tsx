"use client"

import { useState } from "react"
import { api, SafetyFinding, SafetyScanResult } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { StatCard, StatStrip } from "@/components/ui/stat-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Icon } from "@/lib/icons"
import { timeAgo } from "@/lib/utils"

/** Severity of a finding, as the design system spells it: label plus badge variant. */
const SEVERITY: Record<string, { label: string; variant: "danger" | "warning" | "info" }> = {
  high: { label: "Alta", variant: "danger" },
  medium: { label: "Média", variant: "warning" },
  low: { label: "Baixa", variant: "info" },
}

/** Worst first; used to pick the severity of a group and to sort the list. */
const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 }

const RISK: Record<string, { label: string; variant: "success" | "warning" | "danger"; what: string }> = {
  clean: {
    label: "Sem riscos",
    variant: "success",
    what: "Nada suspeito foi encontrado no que está guardado.",
  },
  low: {
    label: "Risco baixo",
    variant: "warning",
    what: "Foram encontrados indícios fracos. Vale conferir os itens abaixo.",
  },
  medium: {
    label: "Risco médio",
    variant: "warning",
    what: "Há itens que merecem atenção antes de abrir os arquivos.",
  },
  high: {
    label: "Risco alto",
    variant: "danger",
    what: "Foi encontrado algo perigoso. Não abra esses arquivos sem conferir.",
  },
}

/** Nome em português de cada tipo de risco encontrado. */
const FINDING_LABELS: Record<string, string> = {
  obfuscated_js: "Script disfarçado",
  crypto_miner: "Minerador de criptomoeda",
  iframe_hidden: "Iframe escondido",
  form_exfil: "Formulário que envia dados para fora",
  meta_refresh_external: "Redirecionamento para outro site",
  known_bad_tld: "Link para domínio suspeito",
  data_uri_script: "Script escondido em link",
  suspicious_download: "Download perigoso",
  atob_eval: "Código escondido em base64",
}

/** One row of the "Achados" list: every occurrence of a kind, with its worst severity. */
interface FindingGroup {
  kind: string
  label: string
  detail: string
  evidence: string
  severity: string
  files: string[]
  count: number
}

/**
 * Fold the flat findings into one row per kind.
 *
 * The scan reports one entry per file, which makes a directory-wide problem read as
 * a dozen identical lines; grouping keeps the count and the list of files.
 */
function groupFindings(findings: SafetyFinding[]): FindingGroup[] {
  const groups = new Map<string, FindingGroup>()
  for (const finding of findings) {
    const group = groups.get(finding.kind) ?? {
      kind: finding.kind,
      label: FINDING_LABELS[finding.kind] ?? finding.kind,
      detail: finding.detail,
      evidence: finding.evidence,
      severity: finding.severity,
      files: [],
      count: 0,
    }
    group.count += 1
    if (!group.files.includes(finding.file)) group.files.push(finding.file)
    if ((SEVERITY_RANK[finding.severity] ?? 99) < (SEVERITY_RANK[group.severity] ?? 99)) {
      group.severity = finding.severity
    }
    groups.set(finding.kind, group)
  }
  return [...groups.values()].sort(
    (a, b) => (SEVERITY_RANK[a.severity] ?? 99) - (SEVERITY_RANK[b.severity] ?? 99)
  )
}

export default function QualidadePage() {
  const [dir, setDir] = useState("")
  const [scanning, setScanning] = useState(false)
  const [result, setResult] = useState<SafetyScanResult | null>(null)
  const [scannedDir, setScannedDir] = useState("")
  const [scannedAt, setScannedAt] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const runScan = async (target: string) => {
    const path = target.trim()
    if (!path) return
    setScanning(true)
    setError(null)
    setResult(null)
    try {
      const scan = await api.scanSafety(path)
      setResult(scan)
      setScannedDir(path)
      setScannedAt(new Date().toISOString())
      setExpanded(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setScanning(false)
    }
  }

  const findings = result?.findings ?? []
  const groups = groupFindings(findings)
  const highCount = findings.filter((finding) => finding.severity === "high").length
  // The scan is directory-scoped and findings carry paths relative to it, so the
  // closest real measure is how many files the findings touch.
  const affectedFiles = new Set(findings.map((finding) => finding.file)).size
  const risk = result ? RISK[result.risk] ?? { label: result.risk, variant: "warning" as const, what: "" } : null

  return (
    <div className="view-grid">
      <Topbar title="Qualidade" description="PII e riscos de segurança" />

      <form
        className="card od-stack"
        style={{ ["--od-gap" as string]: "var(--sp-3)" }}
        onSubmit={(event) => {
          event.preventDefault()
          void runScan(dir)
        }}
      >
        <div className="field" style={{ ["--od-gap" as string]: "6px" }}>
          <h2 className="card-title od-row" style={{ ["--od-gap" as string]: "8px" }}>
            <Icon name="i-shield" /> Verificar uma pasta
          </h2>
          <p className="card-sub">
            Procura sinais de página perigosa no que você baixou: iframes escondidos, mineradores de criptomoeda,
            scripts disfarçados e formulários que enviam dados para outro site. A verificação roda só quando você pede.
          </p>
        </div>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="sm:flex-1">
            <Input
              label="Pasta para verificar"
              id="safety-dir"
              aria-describedby="safety-dir-hint"
              placeholder="output/meusite"
              value={dir}
              onChange={(event) => setDir(event.target.value)}
            />
            <p className="hint" id="safety-dir-hint" style={{ marginTop: 6 }}>
              A pasta de uma extração já feita. Em branco não dá para verificar.
            </p>
          </div>
          <Button type="submit" className="od-touch" loading={scanning} disabled={!dir.trim()}>
            <Icon name="i-shield" size="sm" /> Verificar riscos
          </Button>
        </div>
      </form>

      {error && (
        <div className="card od-stack" style={{ ["--od-gap" as string]: "var(--sp-3)" }} role="alert">
          <h2 className="card-title od-row" style={{ ["--od-gap" as string]: "8px" }}>
            <Icon name="i-alert" /> Não foi possível verificar essa pasta
          </h2>
          <p className="card-sub">{error}</p>
          <p className="hint">
            Confira se o caminho existe e se está escrito igual ao que aparece em Execuções.
          </p>
          <div className="od-row">
            <Button variant="secondary" onClick={() => void runScan(dir)}>
              <Icon name="i-refresh" size="sm" /> Tentar de novo
            </Button>
          </div>
        </div>
      )}

      {scanning && (
        <StatStrip>
          {[0, 1, 2, 3].map((cell) => (
            <div className="stat" key={cell}>
              <Skeleton className="mb-2 h-7 w-16" />
              <Skeleton className="h-3 w-24" />
            </div>
          ))}
        </StatStrip>
      )}

      {result && !scanning && (
        <StatStrip>
          <StatCard
            label="Achados abertos"
            value={findings.length}
            trend={risk?.label ?? "—"}
          />
          <StatCard
            label="Alta severidade"
            value={highCount}
            trend={highCount > 0 ? "ação recomendada" : "nada urgente"}
          />
          <StatCard
            label="Páginas varridas"
            value={result.files_scanned}
            trend={scannedAt ? `verificado ${timeAgo(scannedAt)}` : "—"}
          />
          <StatCard
            label="Arquivos afetados"
            value={affectedFiles}
            trend={scannedDir ? `em ${scannedDir}` : "—"}
          />
        </StatStrip>
      )}

      {result && !scanning && (
        <Card>
          <CardHeader>
            <CardTitle className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
              Achados
              {risk && (
                <Badge variant={risk.variant}>
                  <span className="dot" aria-hidden="true" />
                  {risk.label}
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              {result.files_scanned === 0
                ? `Nenhuma página ou script em ${scannedDir} — não havia o que verificar.`
                : `${result.summary} A varredura passou por ${result.files_scanned} ${
                    result.files_scanned === 1 ? "arquivo" : "arquivos"
                  } de ${scannedDir}.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {result.files_scanned === 0 ? (
              <EmptyState
                icon={<Icon name="i-folder" size="lg" />}
                title="Nada para verificar nessa pasta"
                description="Nenhuma página ou script foi encontrado ali. Confira o caminho ou faça uma extração primeiro em Nova extração."
              />
            ) : groups.length === 0 ? (
              <EmptyState
                icon={<Icon name="i-check-circle" size="lg" />}
                title="Nenhum achado"
                description="Nenhum sinal de página perigosa nos arquivos verificados. Eles parecem seguros para abrir."
              />
            ) : (
              <div className="stack-sm">
                {groups.map((group) => {
                  const severity = SEVERITY[group.severity] ?? {
                    label: group.severity,
                    variant: "info" as const,
                  }
                  const filesLabel =
                    group.files.length === 1 ? group.files[0] : `${group.files.length} arquivos`
                  return (
                    <article
                      key={group.kind}
                      className="job-row"
                      style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}
                    >
                      <div className="job-meta">
                        <div className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
                          <span className="job-url">{group.label}</span>
                          <Badge variant={severity.variant} className="od-fixed">
                            {severity.label}
                          </Badge>
                        </div>
                        <span className="job-sub">
                          <span className="detail-url od-truncate">{filesLabel}</span>
                          <span aria-hidden="true">·</span>
                          <span>
                            {group.count} {group.count === 1 ? "achado" : "achados"}
                          </span>
                        </span>
                        <span className="hint">{group.detail}</span>
                      </div>
                      <div className="job-actions">
                        <Button
                          variant="secondary"
                          size="sm"
                          aria-label={`Detalhar: ${group.label}`}
                          aria-expanded={expanded === group.kind}
                          aria-controls={`achado-${group.kind}`}
                          onClick={() => setExpanded(expanded === group.kind ? null : group.kind)}
                        >
                          Detalhar
                        </Button>
                      </div>
                      {expanded === group.kind && (
                        <dl className="kv" id={`achado-${group.kind}`} style={{ gridColumn: "1 / -1" }}>
                          <dt>Tipo</dt>
                          <dd className="mono">{group.kind}</dd>
                          <dt>Gravidade</dt>
                          <dd>
                            {severity.label} · {group.count}{" "}
                            {group.count === 1 ? "ocorrência" : "ocorrências"}
                          </dd>
                          <dt>Arquivos</dt>
                          <dd className="mono">
                            {group.files.map((file) => (
                              <span key={file} className="od-truncate">
                                {file}
                              </span>
                            ))}
                          </dd>
                          <dt>Exemplo encontrado</dt>
                          <dd className="mono">{group.evidence || "—"}</dd>
                        </dl>
                      )}
                    </article>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!result && !scanning && !error && (
        <EmptyState
          icon={<Icon name="i-shield" size="lg" />}
          title="Nenhuma varredura ainda"
          description="Informe a pasta de uma extração já feita e clique em Verificar riscos. O resultado mostra o risco geral, quantos arquivos foram lidos e o que apareceu em cada um."
        />
      )}
    </div>
  )
}

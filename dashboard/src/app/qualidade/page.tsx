"use client"
import { useState } from "react"
import { api, SafetyFinding, SafetyScanResult } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ShieldCheck, ShieldAlert, FolderOpen, AlertTriangle, SearchX, CheckCircle2 } from "lucide-react"

const SEVERITY: Record<string, { label: string; className: string }> = {
  high: {
    label: "Alto",
    className: "bg-red-500/10 text-red-600 dark:text-red-400 ring-red-500/20",
  },
  medium: {
    label: "Médio",
    className: "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20",
  },
  low: {
    label: "Baixo",
    className: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20",
  },
}

const RISK: Record<string, { label: string; className: string; ring: string; what: string }> = {
  clean: {
    label: "Sem riscos",
    className: "text-emerald-600 dark:text-emerald-400",
    ring: "bg-emerald-500/10 ring-emerald-500/20",
    what: "Nada suspeito foi encontrado no que está guardado.",
  },
  low: {
    label: "Risco baixo",
    className: "text-amber-600 dark:text-amber-400",
    ring: "bg-amber-500/10 ring-amber-500/20",
    what: "Foram encontrados indícios fracos. Vale conferir os itens abaixo.",
  },
  medium: {
    label: "Risco médio",
    className: "text-orange-600 dark:text-orange-400",
    ring: "bg-orange-500/10 ring-orange-500/20",
    what: "Há itens que merecem atenção antes de abrir os arquivos.",
  },
  high: {
    label: "Risco alto",
    className: "text-red-600 dark:text-red-400",
    ring: "bg-red-500/10 ring-red-500/20",
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

export default function QualidadePage() {
  const [safetyDir, setSafetyDir] = useState("")
  const [safetyScanning, setSafetyScanning] = useState(false)
  const [safetyResult, setSafetyResult] = useState<SafetyScanResult | null>(null)
  const [safetyError, setSafetyError] = useState<string | null>(null)

  const handleScanSafety = async () => {
    setSafetyScanning(true)
    setSafetyError(null)
    setSafetyResult(null)
    try {
      setSafetyResult(await api.scanSafety(safetyDir.trim()))
    } catch (e) {
      setSafetyError(e instanceof Error ? e.message : String(e))
    } finally {
      setSafetyScanning(false)
    }
  }

  const risk = safetyResult
    ? RISK[safetyResult.risk] ?? {
        label: safetyResult.risk,
        className: "",
        ring: "bg-secondary ring-border",
        what: "",
      }
    : null

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Qualidade e segurança"
        description="Confira o que você baixou antes de usar: sinais de página perigosa em uma pasta já extraída. A verificação roda só quando você pede."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" /> Segurança
          </CardTitle>
          <CardDescription>
            Procura sinais de página perigosa no que você baixou: iframes escondidos, mineradores de criptomoeda,
            scripts disfarçados e formulários que enviam dados para outro site.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
            <div className="flex-1">
              <Input
                label="Pasta para verificar"
                placeholder="output/meusite"
                value={safetyDir}
                onChange={(e) => setSafetyDir(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && safetyDir.trim() && handleScanSafety()}
                leftIcon={<FolderOpen className="h-4 w-4" />}
                hint="A pasta de uma extração já feita. Em branco não dá para verificar."
              />
            </div>
            <Button onClick={handleScanSafety} loading={safetyScanning} disabled={!safetyDir.trim()}>
              <ShieldCheck className="h-4 w-4" /> Verificar riscos
            </Button>
          </div>

          {safetyError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível verificar essa pasta.</p>
              <p className="mt-1">{safetyError}</p>
              <p className="mt-1 text-muted-foreground">
                Confira se o caminho existe e se está escrito igual ao que aparece em{" "}
                <strong className="text-foreground/80">Execuções</strong>.
              </p>
            </div>
          )}

          {safetyResult && safetyResult.files_scanned === 0 && (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <SearchX className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
              <p className="text-[13px] font-medium">Nada para verificar nessa pasta</p>
              <p className="text-[12.5px] text-muted-foreground mt-1 max-w-md mx-auto">
                Nenhuma página ou script foi encontrado ali. Confira o caminho ou faça uma extração primeiro em{" "}
                <strong className="text-foreground">Nova extração</strong>.
              </p>
            </div>
          )}

          {safetyResult && safetyResult.files_scanned > 0 && (
            <>
              <div className={`rounded-[12px] p-4 ring-1 ring-inset flex items-start gap-3 ${risk?.ring}`}>
                {safetyResult.risk === "clean" ? (
                  <CheckCircle2 className={`h-5 w-5 shrink-0 mt-0.5 ${risk?.className}`} />
                ) : (
                  <ShieldAlert className={`h-5 w-5 shrink-0 mt-0.5 ${risk?.className}`} />
                )}
                <div className="min-w-0">
                  <p className={`text-[15px] font-semibold ${risk?.className}`}>
                    {risk?.label ?? safetyResult.risk}
                  </p>
                  <p className="text-[12.5px] text-muted-foreground mt-1">{risk?.what}</p>
                  <p className="text-[12.5px] text-muted-foreground mt-1">
                    {safetyResult.summary} {safetyResult.files_scanned} arquivo(s) verificado(s).
                  </p>
                </div>
              </div>

              {safetyResult.findings.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">
                  Nenhum sinal de página perigosa. Os arquivos parecem seguros para abrir.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-[12px] border">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                        <th className="px-4 py-3 font-medium">Gravidade</th>
                        <th className="px-4 py-3 font-medium">O que foi encontrado</th>
                        <th className="px-4 py-3 font-medium">Arquivo</th>
                        <th className="px-4 py-3 font-medium">Trecho</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/60">
                      {safetyResult.findings.map((finding: SafetyFinding, index) => {
                        const severity = SEVERITY[finding.severity] ?? {
                          label: finding.severity,
                          className: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20",
                        }
                        return (
                          <tr key={`${finding.kind}-${finding.file}-${index}`} className="hover:bg-accent/50">
                            <td className="px-4 py-3">
                              <span
                                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap ${severity.className}`}
                              >
                                {severity.label}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-col gap-0.5 min-w-[170px]">
                                <span className="text-[12.5px] font-medium">
                                  {FINDING_LABELS[finding.kind] ?? finding.kind}
                                </span>
                                <span className="text-[11.5px] text-muted-foreground">{finding.detail}</span>
                              </div>
                            </td>
                            <td className="px-4 py-3 text-[12px] font-mono text-muted-foreground break-all">
                              {finding.file}
                            </td>
                            <td className="px-4 py-3">
                              <span
                                className="text-[11.5px] font-mono text-muted-foreground/80 block max-w-[280px] truncate"
                                title={finding.evidence}
                              >
                                {finding.evidence}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

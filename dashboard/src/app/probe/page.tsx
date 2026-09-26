"use client"
import { useState } from "react"
import Link from "next/link"
import { api, ProbeResult, JobMode } from "@/lib/api"
import { MODES, MODE_ORDER } from "@/lib/labels"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Search,
  Sparkles,
  Globe,
  Cpu,
  Layers,
  FileType,
  ArrowRight,
  Check,
  Zap,
  HelpCircle,
  Package,
  MousePointerClick,
} from "lucide-react"

const engineToMode: Record<ProbeResult["suggested_engine"], JobMode> = {
  wget: "mirror",
  playwright: "scrape",
  static_file: "singlepage",
}

/**
 * Modes that actually crawl beyond the given URL. `singlepage`/`extract` never
 * follow links, and `pdf`/`summarize` only ever read the root URL — offering a
 * depth slider for those would be a control that does nothing.
 */
const MODES_WITH_DEPTH: JobMode[] = ["mirror", "scrape", "analyze", "compare", "ask"]

export default function ProbePage() {
  const [probeUrl, setProbeUrl] = useState("")
  const [probing, setProbing] = useState(false)
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null)
  const [probeError, setProbeError] = useState<string | null>(null)

  const [createUrl, setCreateUrl] = useState("")
  const [createMode, setCreateMode] = useState<JobMode>("scrape")
  const [createDepth, setCreateDepth] = useState(1)
  const [createPdfName, setCreatePdfName] = useState("")
  const [creating, setCreating] = useState(false)
  const [createSuccess, setCreateSuccess] = useState<string | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)

  const handleProbe = async () => {
    if (!probeUrl) return
    setProbing(true)
    setProbeError(null)
    setProbeResult(null)
    try {
      const res = await api.probe(probeUrl)
      setProbeResult(res)
      setCreateUrl(probeUrl)
      setCreateMode(engineToMode[res.suggested_engine] ?? "singlepage")
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : String(e))
    } finally {
      setProbing(false)
    }
  }

  const handleCreate = async () => {
    if (!createUrl) return
    setCreating(true)
    setCreateSuccess(null)
    setCreateError(null)
    try {
      const job = await api.createJob({
        url: createUrl,
        mode: createMode,
        max_depth: createDepth,
        ...(createMode === "pdf" && createPdfName.trim() ? { pdf_filename: createPdfName.trim() } : {}),
      })
      setCreateSuccess(job.id)
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  const selected = MODES[createMode]
  const depthExplained =
    createDepth === 0
      ? "Só a página que você indicou."
      : createDepth === 1
        ? "A página indicada e os links que saem dela."
        : `Links até ${createDepth} níveis de distância — pode gerar muitos arquivos.`

  return (
    <div className="space-y-6 max-w-[1200px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Nova extração"
        description="Informe o endereço do site, escolha o que quer receber e inicie. Leva alguns segundos."
        action={
          <Link href="/captura">
            <Button size="sm" variant="outline">
              <MousePointerClick className="h-4 w-4" /> Escolher o que pegar na página
            </Button>
          </Link>
        }
      />

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Passo 1 — analisar */}
        <Card className="relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-violet-500/0 via-violet-500/50 to-violet-500/0" />
          <CardHeader>
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-[10px] bg-violet-500/10 flex items-center justify-center text-violet-600">
                <Search className="h-4 w-4" />
              </div>
              <div>
                <CardTitle>Passo 1 — Analisar o endereço (opcional)</CardTitle>
                <CardDescription>
                  Descobre como o site foi feito e qual modo funciona melhor nele. Se preferir, pule direto para o
                  passo 2.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <div className="flex-1">
                <Input
                  placeholder="https://exemplo.com.br"
                  value={probeUrl}
                  onChange={(e) => setProbeUrl(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleProbe()}
                  leftIcon={<Globe className="h-4 w-4" />}
                />
              </div>
              <Button onClick={handleProbe} loading={probing} disabled={!probeUrl}>
                <Sparkles className="h-4 w-4" />
                Analisar
              </Button>
            </div>

            {probeError && (
              <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                <p className="font-medium">Não conseguimos acessar esse endereço.</p>
                <p className="mt-1">{probeError}</p>
                <p className="mt-1 text-muted-foreground">
                  Confira se o endereço está completo (com <span className="font-mono">https://</span>).
                </p>
              </div>
            )}

            {probeResult && (
              <div className="space-y-3 animate-[scale-in_0.25s_ease]">
                <div className="rounded-[12px] border bg-secondary/50 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground">
                      Resultado
                    </span>
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 text-emerald-600 px-2.5 py-1 text-[11px] font-medium ring-1 ring-emerald-500/20">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      Site acessível
                    </span>
                  </div>

                  <div className="rounded-[10px] bg-primary/10 border border-primary/20 p-3">
                    <div className="flex items-center gap-2 text-[11px] text-primary uppercase tracking-wide font-medium">
                      <Zap className="h-3 w-3" /> Modo recomendado
                    </div>
                    <div className="mt-1 text-[14px] font-semibold text-primary">
                      {MODES[engineToMode[probeResult.suggested_engine]].icon}{" "}
                      {MODES[engineToMode[probeResult.suggested_engine]].label}
                    </div>
                    <p className="mt-1 text-[12px] text-muted-foreground">
                      {MODES[engineToMode[probeResult.suggested_engine]].what}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-[10px] bg-card border p-3">
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground uppercase tracking-wide">
                        <Cpu className="h-3 w-3" /> Precisa de navegador?
                      </div>
                      <div className="mt-1 text-[13.5px] font-medium">
                        {probeResult.suggested_engine === "playwright" ? "Sim" : "Não"}
                      </div>
                    </div>
                    <div className="rounded-[10px] bg-card border p-3">
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground uppercase tracking-wide">
                        <Layers className="h-3 w-3" /> Tecnologia
                      </div>
                      <div className="mt-1 text-[13.5px] font-medium capitalize">
                        {probeResult.framework || "Site comum"}
                      </div>
                    </div>
                    <div className="rounded-[10px] bg-card border p-3">
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground uppercase tracking-wide">
                        <FileType className="h-3 w-3" /> Tipo de conteúdo
                      </div>
                      <div className="mt-1 text-[12px] font-mono truncate">{probeResult.content_type || "—"}</div>
                    </div>
                    <div className="rounded-[10px] bg-card border p-3">
                      <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Resposta</div>
                      <div className="mt-1 text-[13.5px] font-medium">
                        {probeResult.status_code ?? "—"}
                        {probeResult.status_code === 200 ? " · ok" : ""}
                      </div>
                    </div>
                  </div>

                  {probeResult.final_url && probeResult.final_url !== probeResult.url && (
                    <div className="text-[12px] text-muted-foreground">
                      O endereço redireciona para{" "}
                      <span className="font-mono text-foreground break-all">{probeResult.final_url}</span>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 text-[12px] text-violet-600 dark:text-violet-400 bg-violet-500/10 border border-violet-500/20 rounded-[10px] p-2.5">
                  <Check className="h-4 w-4 shrink-0" />
                  Já preenchemos o passo 2 com o modo recomendado. É só clicar em Iniciar.
                </div>
              </div>
            )}

            {!probeResult && !probeError && !probing && (
              <div className="rounded-[12px] border border-dashed p-8 text-center">
                <Globe className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
                <p className="text-[13px] text-muted-foreground">
                  Cole o endereço acima e clique em <strong className="text-foreground">Analisar</strong>.
                </p>
                <p className="text-[12px] text-muted-foreground mt-1">
                  Não sabe qual modo escolher?{" "}
                  <Link href="/ajuda" className="text-primary underline">
                    veja o guia
                  </Link>
                  .
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Passo 2 — iniciar */}
        <Card className="relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-emerald-500/0 via-emerald-500/50 to-emerald-500/0" />
          <CardHeader>
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-[10px] bg-emerald-500/10 flex items-center justify-center text-emerald-600">
                <Zap className="h-4 w-4" />
              </div>
              <div>
                <CardTitle>Passo 2 — Escolher e iniciar</CardTitle>
                <CardDescription>Onde salvar e o quanto do site percorrer.</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <Input
              label="Endereço do site"
              placeholder="https://exemplo.com.br"
              value={createUrl}
              onChange={(e) => setCreateUrl(e.target.value)}
              leftIcon={<Globe className="h-4 w-4" />}
              hint="O endereço completo, começando com https://"
            />

            <div className="flex flex-col gap-2">
              <label className="text-[12.5px] font-medium text-foreground/80">
                O que você quer receber?
              </label>
              <div className="grid sm:grid-cols-2 gap-2">
                {MODE_ORDER.map((m) => {
                  const info = MODES[m]
                  const active = createMode === m
                  return (
                    <button
                      key={m}
                      onClick={() => setCreateMode(m)}
                      className={`text-left rounded-[10px] border p-3 transition-all ${
                        active ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "hover:bg-accent"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[13px] font-medium">
                          {info.icon} {info.label}
                        </span>
                        {active && <Check className="h-3.5 w-3.5 text-primary shrink-0" />}
                      </div>
                      <p className="text-[11.5px] text-muted-foreground mt-1 leading-snug">{info.what}</p>
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="rounded-[10px] bg-secondary/60 border p-3 space-y-2">
              <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-muted-foreground font-medium">
                <Package className="h-3 w-3" /> O que você vai receber
              </div>
              <p className="text-[12.5px]">{selected.output}</p>
              <p className="text-[11.5px] text-muted-foreground">
                <strong className="text-foreground/80">Quando usar:</strong> {selected.when}
              </p>
            </div>

            {MODES_WITH_DEPTH.includes(createMode) && (
              <div className="flex flex-col gap-1.5">
                <label className="text-[12.5px] font-medium text-foreground/80">
                  Quantas páginas percorrer?
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min={0}
                    max={5}
                    value={createDepth}
                    onChange={(e) => setCreateDepth(parseInt(e.target.value))}
                    className="flex-1 accent-primary"
                  />
                  <span className="h-9 w-12 rounded-[10px] border bg-secondary flex items-center justify-center text-[13px] font-mono font-medium">
                    {createDepth}
                  </span>
                </div>
                <p className="text-[11.5px] text-muted-foreground">{depthExplained}</p>
              </div>
            )}

            {createMode === "pdf" && (
              <Input
                label="Nome do arquivo (opcional)"
                placeholder="index"
                value={createPdfName}
                onChange={(e) => setCreatePdfName(e.target.value)}
                hint="Vira o nome do PDF. Caracteres especiais são trocados por _."
              />
            )}

            <Button onClick={handleCreate} loading={creating} disabled={!createUrl} className="w-full">
              Iniciar extração <ArrowRight className="h-4 w-4" />
            </Button>

            {createError && (
              <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                <p className="font-medium">Não foi possível iniciar.</p>
                <p className="mt-1">{createError}</p>
              </div>
            )}

            {createSuccess && (
              <div className="rounded-[12px] bg-emerald-500/10 border border-emerald-500/20 p-3 animate-[scale-in_0.2s_ease]">
                <div className="flex items-start gap-2.5">
                  <div className="h-6 w-6 rounded-full bg-emerald-500 flex items-center justify-center text-white shrink-0">
                    <Check className="h-3.5 w-3.5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-medium text-emerald-700 dark:text-emerald-400">
                      Extração iniciada!
                    </p>
                    <p className="text-[12px] text-muted-foreground mt-0.5">
                      Você pode acompanhar o andamento e baixar o resultado.
                    </p>
                    <p className="text-[11px] font-mono mt-1 break-all text-muted-foreground">{createSuccess}</p>
                    <div className="flex gap-2 mt-2.5">
                      <Link href={`/jobs/${createSuccess}`}>
                        <Button size="sm" variant="primary">
                          Acompanhar
                        </Button>
                      </Link>
                      <Link href="/">
                        <Button size="sm" variant="outline">
                          Ver todas
                        </Button>
                      </Link>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="bg-secondary/40">
        <CardContent className="p-4 flex items-start gap-3">
          <HelpCircle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
          <div className="text-[12.5px] text-muted-foreground leading-relaxed">
            <strong className="text-foreground">Em dúvida?</strong> Comece com{" "}
            <strong className="text-foreground">Página única</strong> para testar: é rápido e mostra se o conteúdo vem
            completo. Se vier vazio, o site precisa de{" "}
            <strong className="text-foreground">Site com JavaScript</strong>. O{" "}
            <Link href="/ajuda" className="text-primary underline">
              guia completo
            </Link>{" "}
            compara os quatro modos lado a lado.
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

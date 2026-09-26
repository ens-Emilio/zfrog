"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { api, AppConfig } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { DetailRow } from "@/components/DetailRow"
import { Skeleton } from "@/components/ui/skeleton"
import { Database, Sliders, Globe, Shield, Save, Check, Gauge } from "lucide-react"

export default function ConfigPage() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rps, setRps] = useState("")
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const fetchConfig = async () => {
    setLoading(true)
    try {
      const data = await api.getConfig()
      setConfig(data)
      if (data.rate_limit_rps) setRps(String(data.rate_limit_rps))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setTimeout(fetchConfig, 0)
  }, [])

  const handleSave = async () => {
    const val = parseFloat(rps)
    setSaveError(null)
    if (isNaN(val) || val <= 0) {
      setSaveError("Informe um número maior que zero.")
      return
    }
    setSaving(true)
    try {
      await api.updateRateLimit(val)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      fetchConfig()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const speedVerdict = (() => {
    const v = parseFloat(rps)
    if (isNaN(v)) return null
    if (v <= 1) return "Bem devagar e discreto. Recomendado para sites com proteção."
    if (v <= 3) return "Equilíbrio entre velocidade e discrição. Bom para a maioria dos sites."
    if (v <= 10) return "Rápido. Use apenas em sites próprios ou que você tem permissão."
    return "Muito rápido. Alto risco de bloqueio pelo site."
  })()

  return (
    <div className="space-y-6 max-w-[900px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Configurações"
        description="Como o Zfrog se comporta ao baixar. As mudanças valem imediatamente, sem reiniciar."
      />

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : error ? (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar as configurações.</p>
            <p className="mt-1">{error}</p>
          </CardContent>
        </Card>
      ) : config ? (
        <>
          <div className="grid md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-4 w-4" /> Onde os arquivos ficam
                </CardTitle>
                <CardDescription>Armazenamento e organização</CardDescription>
              </CardHeader>
              <CardContent className="px-5">
                <DetailRow
                  label="Pasta de saída"
                  value={<span className="font-mono text-[12px]">{config.output_dir}</span>}
                  hint="Cada extração cria uma subpasta com o próprio identificador dentro dela."
                />
                <DetailRow
                  label="Extrações simultâneas"
                  value={config.max_concurrent_jobs}
                  hint="Quantos downloads podem rodar ao mesmo tempo. Números altos consomem mais memória."
                />
                <DetailRow
                  label="Processos paralelos"
                  value={config.worker_concurrency}
                  hint="Quantos trabalhos o servidor executa em paralelo. Aumente se tiver CPU sobrando."
                />
                <DetailRow
                  label="Servidor de filas"
                  value={<span className="font-mono text-[12px]">{config.redis_url}</span>}
                  hint="Serviço que organiza a fila de extrações. Precisa estar no ar para vários downloads ao mesmo tempo."
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Globe className="h-4 w-4" /> Como se conectar
                </CardTitle>
                <CardDescription>Rede, identidade e limites de tempo</CardDescription>
              </CardHeader>
              <CardContent className="px-5">
                <DetailRow
                  label="Intermediário (proxy)"
                  value={
                    config.proxy_url ? <span className="font-mono text-[12px]">{config.proxy_url}</span> : "Nenhum"
                  }
                  hint="Endereço opcional que esconde sua conexão de origem. Deixe vazio para conectar direto."
                />
                <DetailRow
                  label="Velocidade"
                  value={`${config.rate_limit_rps} pedidos/s`}
                  hint="Quantos pedidos por segundo o Zfrog envia ao site. Ajuste abaixo."
                />
                <DetailRow
                  label="Espera para conectar"
                  value={`${config.http_timeout_connect}s`}
                  hint="Tempo máximo para estabelecer a conexão antes de desistir."
                />
                <DetailRow
                  label="Espera para ler"
                  value={`${config.http_timeout_read}s`}
                  hint="Tempo máximo esperando a resposta de um site lento."
                />
              </CardContent>
            </Card>
          </div>

          <Card className="overflow-hidden border-primary/20">
            <div className="h-[1px] bg-gradient-to-r from-primary/0 via-primary/50 to-primary/0" />
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sliders className="h-4 w-4" /> Velocidade dos pedidos
              </CardTitle>
              <CardDescription>
                O ajuste mais importante para não ser bloqueado. Vale na hora, sem reiniciar.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-3 items-end flex-wrap">
                <div className="flex-1 min-w-[200px] max-w-[240px]">
                  <Input
                    label="Pedidos por segundo"
                    type="number"
                    min={0.1}
                    step={0.1}
                    value={rps}
                    onChange={(e) => setRps(e.target.value)}
                    hint="Use 0.5 a 2 em sites com proteção."
                    error={saveError ?? undefined}
                  />
                </div>
                <Button onClick={handleSave} loading={saving} className="mb-[18px]">
                  <Save className="h-4 w-4" />
                  Salvar
                </Button>
                {saved && (
                  <span className="mb-[22px] inline-flex items-center gap-1.5 text-[12.5px] text-emerald-600 font-medium animate-[scale-in_0.2s_ease]">
                    <Check className="h-4 w-4" /> Velocidade atualizada
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={0.5}
                  max={20}
                  step={0.5}
                  value={parseFloat(rps) || 1}
                  onChange={(e) => setRps(e.target.value)}
                  className="flex-1 accent-primary max-w-[320px]"
                />
                <span className="text-[12px] text-muted-foreground whitespace-nowrap">{rps || "—"} pedidos/s</span>
              </div>

              {speedVerdict && (
                <div className="flex items-start gap-2.5 rounded-[10px] bg-secondary p-3">
                  <Gauge className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                  <p className="text-[12px] text-muted-foreground leading-relaxed">{speedVerdict}</p>
                </div>
              )}

              <div className="rounded-[10px] bg-secondary p-3 flex gap-2.5">
                <Shield className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                <p className="text-[12px] text-muted-foreground leading-relaxed">
                  Pedidos rápidos demais fazem o site identificar o Zfrog como robô e bloquear o acesso. Se receber
                  erros de bloqueio, reduza este valor. Saiba mais no{" "}
                  <Link href="/ajuda" className="text-primary underline">
                    guia
                  </Link>
                  .
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-[13px]">Dados brutos do servidor</CardTitle>
              <CardDescription>
                Os mesmos valores acima, para conferência ou suporte.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="text-[11.5px] font-mono bg-secondary rounded-[12px] p-4 overflow-auto max-h-[320px] border">
                {JSON.stringify(config, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  )
}

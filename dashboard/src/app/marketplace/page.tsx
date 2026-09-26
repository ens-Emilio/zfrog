"use client"
import { useEffect, useState } from "react"
import { api, MarketplaceAsset, MarketplaceInstall } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  Store,
  Search,
  Star,
  Download,
  Trash2,
  RefreshCw,
  Check,
  AlertTriangle,
  PackageOpen,
  User,
  Tag,
} from "lucide-react"

/**
 * Fluxos, plugins e modelos publicados por outras pessoas. Instalar copia o
 * item para dentro do seu sistema; remover apaga essa cópia.
 */

/** Filtros de tipo. O valor vazio significa "todos". */
const KIND_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "Todos" },
  { value: "workflow", label: "Fluxos" },
  { value: "plugin", label: "Plugins" },
  { value: "template", label: "Modelos" },
]

/** Nome em português de cada tipo, incluindo os que a tela ainda não conhece. */
const KIND_LABELS: Record<string, string> = {
  workflow: "Fluxo",
  plugin: "Plugin",
  template: "Modelo",
}

/** Cor do rótulo de tipo, para dar de relance qual é qual. */
const KIND_STYLES: Record<string, string> = {
  workflow: "bg-blue-500/10 text-blue-600 dark:text-blue-400 ring-blue-500/20",
  plugin: "bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-violet-500/20",
  template: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20",
}

const FALLBACK_KIND_STYLE = "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20"

export default function MarketplacePage() {
  const [assets, setAssets] = useState<MarketplaceAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [kind, setKind] = useState("")
  const [query, setQuery] = useState("")

  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [installs, setInstalls] = useState<Record<string, MarketplaceInstall>>({})
  const [removed, setRemoved] = useState<Record<string, string>>({})
  const [ratingId, setRatingId] = useState<string | null>(null)

  const fetchAssets = async () => {
    setLoading(true)
    setError(null)
    try {
      setAssets(await api.getMarketplace(kind || undefined, query.trim() || undefined))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  // Espera a pessoa parar de digitar antes de pedir a lista de novo.
  useEffect(() => {
    const timer = setTimeout(fetchAssets, 300)
    return () => clearTimeout(timer)
  }, [kind, query])

  const handleInstall = async (asset: MarketplaceAsset) => {
    setBusyId(asset.id)
    setActionError(null)
    try {
      const result = await api.installAsset(asset.id)
      setInstalls((current) => ({ ...current, [asset.id]: result }))
      setRemoved((current) => {
        const next = { ...current }
        delete next[asset.id]
        return next
      })
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
    }
  }

  const handleUninstall = async (asset: MarketplaceAsset) => {
    setBusyId(asset.id)
    setActionError(null)
    try {
      await api.uninstallAsset(asset.id)
      setRemoved((current) => ({ ...current, [asset.id]: "A cópia instalada foi removida." }))
      setInstalls((current) => {
        const next = { ...current }
        delete next[asset.id]
        return next
      })
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyId(null)
    }
  }

  const handleRate = async (asset: MarketplaceAsset, score: number) => {
    setRatingId(asset.id)
    setActionError(null)
    try {
      const updated = await api.rateAsset(asset.id, score)
      setAssets((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setRatingId(null)
    }
  }

  const filtered = kind !== "" || query.trim() !== ""

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Marketplace"
        description="São fluxos, plugins e modelos prontos que outras pessoas publicaram: em vez de montar tudo do zero, você instala com um clique e usa aqui mesmo. A nota e o número de instalações ajudam a escolher."
        action={
          <Button onClick={fetchAssets} loading={loading} size="sm" variant="outline">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" /> Procurar
          </CardTitle>
          <CardDescription>
            Escolha o tipo ou procure pelo nome e pela descrição. A lista se atualiza sozinha enquanto você digita.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {KIND_FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setKind(option.value)}
                aria-pressed={kind === option.value}
                className={cn(
                  "rounded-[10px] border px-3 py-1.5 text-[12.5px] font-medium transition-all",
                  kind === option.value
                    ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                    : "text-muted-foreground hover:bg-accent"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <Input
            placeholder="ex.: backup diário, SEO, planilha"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            leftIcon={<Search className="h-4 w-4" />}
            hint="Em branco, mostra tudo que está publicado."
          />
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">Não foi possível carregar o marketplace.</p>
            <p className="mt-1">{error}</p>
            <p className="mt-1 text-muted-foreground">
              Confira se o sistema está no ar e clique em <strong className="text-foreground/80">Atualizar</strong>.
            </p>
          </CardContent>
        </Card>
      )}

      {actionError && (
        <Card className="border-destructive/20 bg-destructive/5">
          <CardContent className="p-4 text-[13px] text-destructive">
            <p className="font-medium">A ação não deu certo.</p>
            <p className="mt-1">{actionError}</p>
          </CardContent>
        </Card>
      )}

      {!loading && !error && assets.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="p-12 text-center">
            <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mx-auto mb-4">
              <PackageOpen className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-[15px] font-semibold">
              {filtered ? "Nada encontrado com esse filtro" : "Nada publicado ainda"}
            </h3>
            <p className="text-[13px] text-muted-foreground mt-1 max-w-md mx-auto">
              {filtered
                ? "Tente outro tipo, ou procure por uma palavra mais curta."
                : "Quando alguém publicar um fluxo, um plugin ou um modelo, ele aparece aqui para você instalar."}
            </p>
          </CardContent>
        </Card>
      )}

      {assets.length > 0 && (
        <>
          <p className="text-[12.5px] text-muted-foreground">
            {assets.length} item(ns) {filtered ? "com esse filtro" : "publicado(s)"}.
          </p>

          <div className="grid gap-4 md:grid-cols-2">
            {assets.map((asset) => {
              const install = installs[asset.id]
              const stars = Math.round(asset.rating)
              return (
                <Card key={asset.id} className="flex flex-col">
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <CardTitle className="min-w-0 break-words">{asset.name}</CardTitle>
                      <span
                        className={cn(
                          "shrink-0 inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap",
                          KIND_STYLES[asset.kind] ?? FALLBACK_KIND_STYLE
                        )}
                      >
                        {KIND_LABELS[asset.kind] ?? asset.kind}
                      </span>
                    </div>
                    <CardDescription className="flex flex-wrap items-center gap-3">
                      <span className="inline-flex items-center gap-1">
                        <User className="h-3 w-3" /> {asset.author || "sem autor"}
                      </span>
                      <span className="font-mono text-[11.5px]">versão {asset.version}</span>
                      <span className="inline-flex items-center gap-1">
                        <Download className="h-3 w-3" /> {asset.installs} instalação(ões)
                      </span>
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="flex-1 flex flex-col gap-3">
                    <p className="text-[13px] text-muted-foreground">{asset.description || "Sem descrição."}</p>

                    {asset.tags.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Tag className="h-3 w-3 text-muted-foreground" />
                        {asset.tags.map((tag) => (
                          <Badge key={tag} className="bg-secondary text-secondary-foreground">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    )}

                    <div className="flex flex-wrap items-center gap-2">
                      <div className="flex items-center gap-1">
                        {[1, 2, 3, 4, 5].map((score) => (
                          <button
                            key={score}
                            type="button"
                            aria-label={`Dar nota ${score} de 5`}
                            title={`Dar nota ${score} de 5`}
                            disabled={ratingId !== null}
                            onClick={() => handleRate(asset, score)}
                            className="disabled:opacity-50"
                          >
                            <Star
                              className={cn(
                                "h-4 w-4",
                                score <= stars ? "text-amber-500" : "text-muted-foreground/40"
                              )}
                              fill={score <= stars ? "currentColor" : "none"}
                            />
                          </button>
                        ))}
                      </div>
                      <span className="text-[12px] text-muted-foreground">
                        {asset.rating.toFixed(1)} de 5 · {asset.rating_count} avaliação(ões)
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      <Button
                        size="sm"
                        variant="primary"
                        loading={busyId === asset.id && !removed[asset.id]}
                        disabled={busyId !== null && busyId !== asset.id}
                        onClick={() => handleInstall(asset)}
                      >
                        <Download className="h-3.5 w-3.5" /> Instalar
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={busyId === asset.id && Boolean(removed[asset.id])}
                        disabled={busyId !== null && busyId !== asset.id}
                        onClick={() => handleUninstall(asset)}
                        title="Remover a cópia instalada"
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Remover
                      </Button>
                    </div>

                    {install && (
                      <div className="rounded-[10px] bg-emerald-500/10 border border-emerald-500/20 p-2.5 text-[12px] text-emerald-700 dark:text-emerald-400">
                        <p className="flex items-center gap-1.5 font-medium">
                          <Check className="h-3.5 w-3.5" />
                          {install.installed ? "Instalado" : "Já estava instalado"}
                        </p>
                        <p className="mt-1 break-all">
                          Guardado em <span className="font-mono">{install.target}</span>
                        </p>
                        <p className="mt-0.5">{install.detail}</p>
                      </div>
                    )}

                    {removed[asset.id] && !install && (
                      <p className="text-[12px] text-muted-foreground flex items-center gap-1.5">
                        <AlertTriangle className="h-3.5 w-3.5" /> {removed[asset.id]}
                      </p>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </>
      )}

      {loading && assets.length === 0 && !error && (
        <Card>
          <CardContent className="p-10 text-center">
            <Store className="h-6 w-6 mx-auto text-muted-foreground/40 mb-2 animate-pulse" />
            <p className="text-[13px] text-muted-foreground">Carregando o que está publicado…</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

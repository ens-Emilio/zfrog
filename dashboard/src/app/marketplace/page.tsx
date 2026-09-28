"use client"
import { useEffect, useState } from "react"
import { api, MarketplaceAsset, MarketplaceIndex, MarketplaceInstall } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Chip } from "@/components/ui/ds"
import { EmptyState } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ToastRegion"
import { Icon } from "@/lib/icons"
import { cn, formatNumber, formatStamp } from "@/lib/utils"
import { Star } from "lucide-react"

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

/** Quantos itens do índice aparecem antes do botão "mostrar todos". */
const INDEX_PREVIEW = 12

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

/** Falha de leitura ou de ação: o rótulo diz o que aconteceu e há como tentar de novo. */
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

/** Enquanto a vitrine chega, cartões com a mesma silhueta dos itens. */
function CardsSkeleton() {
  return (
    <div className="grid-cards" aria-hidden="true">
      {[0, 1, 2, 3].map((row) => (
        <div key={row} className="card stack-sm">
          <div className="row-between">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-5 w-16" />
          </div>
          <Skeleton className="h-3.5 w-full" />
          <Skeleton className="h-3.5 w-3/4" />
        </div>
      ))}
    </div>
  )
}

export default function MarketplacePage() {
  const toast = useToast()

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

  const [index, setIndex] = useState<MarketplaceIndex | null>(null)
  const [indexLoading, setIndexLoading] = useState(true)
  const [indexError, setIndexError] = useState<string | null>(null)
  const [showAllIndex, setShowAllIndex] = useState(false)

  const [indexUrl, setIndexUrl] = useState("")
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<{
    added: number
    updated: number
    unchanged: number
    skipped: number
    errors: string[]
  } | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

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

  const fetchIndex = async () => {
    setIndexLoading(true)
    try {
      setIndex(await api.getMarketplaceIndex())
      setIndexError(null)
    } catch (e) {
      setIndexError(e instanceof Error ? e.message : String(e))
    } finally {
      setIndexLoading(false)
    }
  }

  useEffect(() => {
    void fetchIndex()
  }, [])

  // Espera a pessoa parar de digitar antes de pedir a lista de novo.
  useEffect(() => {
    const timer = setTimeout(() => void fetchAssets(), 300)
    return () => clearTimeout(timer)
  }, [kind, query])

  const handleSync = async () => {
    const url = indexUrl.trim()
    if (!url) return
    setSyncing(true)
    setSyncError(null)
    setSyncResult(null)
    try {
      const result = await api.syncMarketplace(url)
      setSyncResult(result)
      toast(`${result.added} item(ns) novo(s), ${result.updated} atualizado(s).`)
      await Promise.all([fetchAssets(), fetchIndex()])
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : String(e))
    } finally {
      setSyncing(false)
    }
  }

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
      toast(result.installed ? `${result.name} instalado.` : `${result.name} já estava instalado.`)
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
      toast(`A cópia de ${asset.name} foi removida.`)
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
      toast(`Nota ${score} registrada em ${updated.name}.`)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setRatingId(null)
    }
  }

  const filtered = kind !== "" || query.trim() !== ""
  const indexEntries = index ? (showAllIndex ? index.assets : index.assets.slice(0, INDEX_PREVIEW)) : []

  return (
    <div className="view-grid">
      <Topbar
        title="Marketplace"
        description="Fluxos, plugins e modelos prontos que outras pessoas publicaram: instale com um clique em vez de montar tudo do zero."
        action={
          <Button
            variant="secondary"
            size="sm"
            className="od-touch"
            loading={loading}
            onClick={() => void fetchAssets()}
          >
            <Icon name="i-refresh" size="sm" />
            Atualizar
          </Button>
        }
      />

      <section className="card stack-md">
        <div className="od-field" style={{ ["--od-gap" as string]: "2px" }}>
          <h2 className="card-title">Procurar</h2>
          <p className="card-sub">
            Escolha o tipo ou procure pelo nome e pela descrição. A lista se atualiza sozinha enquanto você digita.
          </p>
        </div>

        <div className="toolbar">
          <div className="search-wrap">
            <Icon name="i-search" />
            <input
              className="input"
              type="search"
              aria-label="Procurar no marketplace"
              placeholder="ex.: backup diário, SEO, planilha"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div className="filter-rail">
            {KIND_FILTERS.map((option) => (
              <Chip key={option.value} active={kind === option.value} onClick={() => setKind(option.value)}>
                {option.label}
              </Chip>
            ))}
          </div>
        </div>
        <p className="hint">Em branco, mostra tudo que está publicado.</p>
      </section>

      {error && (
        <ErrorBlock
          title="Não foi possível carregar o marketplace."
          message={error}
          onRetry={() => void fetchAssets()}
        />
      )}

      {actionError && <ErrorBlock title="A ação não deu certo." message={actionError} />}

      <section className="card stack-md">
        <div className="od-field" style={{ ["--od-gap" as string]: "2px" }}>
          <h2 className="card-title">Índice do marketplace</h2>
          <p className="card-sub">
            O índice é a lista publicada de itens. Sincronizar busca o índice de um endereço e incorpora o que ainda não
            está aqui.
          </p>
        </div>

        <div className="od-row" style={{ ["--od-gap" as string]: "12px", alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="od-fill">
            <Input
              label="Endereço do índice"
              placeholder="ex.: https://exemplo.com/marketplace/index.json"
              value={indexUrl}
              onChange={(e) => setIndexUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void handleSync()}
              className="input-mono"
              hint="O endereço de onde a lista publicada deve ser lida."
            />
          </div>
          <Button
            className="od-touch"
            loading={syncing}
            disabled={indexUrl.trim() === ""}
            onClick={() => void handleSync()}
          >
            <Icon name="i-database" />
            Sincronizar
          </Button>
        </div>

        {syncError && (
          <div className="od-stack" style={{ ["--od-gap" as string]: "4px" }}>
            <span className="error-text">
              <Icon name="i-alert" size="sm" />
              Não foi possível sincronizar o índice.
            </span>
            <span className="hint">{syncError}</span>
          </div>
        )}

        {syncResult && (
          <div className="od-stack" style={{ ["--od-gap" as string]: "6px" }}>
            <div className="od-cluster">
              <Badge variant="success">
                <span className="dot" aria-hidden="true" />
                {syncResult.added} novo(s)
              </Badge>
              <Badge variant="accent">{syncResult.updated} atualizado(s)</Badge>
              <Badge variant="neutral">{syncResult.unchanged} sem mudança</Badge>
              {syncResult.skipped > 0 && <Badge variant="warning">{syncResult.skipped} ignorado(s)</Badge>}
            </div>
            {syncResult.errors.length > 0 && (
              <ul className="stack-sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {syncResult.errors.map((message) => (
                  <li key={message} className="error-text">
                    <Icon name="i-alert" size="sm" />
                    {message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {indexError && (
          <div className="od-stack" style={{ ["--od-gap" as string]: "4px" }}>
            <span className="error-text">
              <Icon name="i-alert" size="sm" />
              Não foi possível ler o índice.
            </span>
            <span className="hint">{indexError}</span>
            <div>
              <Button variant="secondary" size="sm" className="od-touch" onClick={() => void fetchIndex()}>
                <Icon name="i-refresh" size="sm" />
                Tentar de novo
              </Button>
            </div>
          </div>
        )}

        {indexLoading && !index && (
          <div className="od-stack" style={{ ["--od-gap" as string]: "8px" }} aria-hidden="true">
            <Skeleton className="h-3.5 w-48" />
            <Skeleton className="h-3.5 w-64" />
          </div>
        )}

        {index && (
          <>
            <dl className="kv">
              <dt>Versão do índice</dt>
              <dd>{index.version}</dd>
              <dt>Gerado em</dt>
              <dd>{formatStamp(index.generated_at)}</dd>
              <dt>Origem</dt>
              <dd className="mono break-all">{index.source || "sem origem informada"}</dd>
              <dt>Itens</dt>
              <dd>{formatNumber(index.count)}</dd>
            </dl>

            {index.assets.length === 0 ? (
              <p className="hint">O índice está vazio: nada foi publicado ainda.</p>
            ) : (
              <>
                <div className="job-list">
                  {indexEntries.map((entry) => (
                    <article
                      key={entry.id}
                      className="job-row"
                      style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}
                    >
                      <div className="job-meta">
                        <div className="od-row" style={{ ["--od-gap" as string]: "8px", flexWrap: "wrap" }}>
                          <span className="job-url od-truncate">{entry.name}</span>
                          <Badge variant="accent">{kindLabel(entry.kind)}</Badge>
                        </div>
                        <span className="job-sub">
                          <span>{entry.author || "sem autor"}</span>
                          <span aria-hidden="true">·</span>
                          <span>versão {entry.version}</span>
                          <span aria-hidden="true">·</span>
                          <span>nota {entry.rating.toFixed(1)}</span>
                          <span aria-hidden="true">·</span>
                          <span>{formatNumber(entry.installs)} instalação(ões)</span>
                        </span>
                        <span className="job-sub mono od-truncate">{entry.id}</span>
                      </div>
                      <span className="hint od-nowrap">{formatStamp(entry.published_at)}</span>
                    </article>
                  ))}
                </div>

                {index.assets.length > INDEX_PREVIEW && (
                  <div>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="od-touch"
                      onClick={() => setShowAllIndex((current) => !current)}
                    >
                      <Icon name="i-layers" size="sm" />
                      {showAllIndex
                        ? `Mostrar só os ${INDEX_PREVIEW} primeiros`
                        : `Mostrar todos os ${formatNumber(index.assets.length)}`}
                    </Button>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </section>

      {loading && assets.length === 0 && !error && <CardsSkeleton />}

      {!loading && !error && assets.length === 0 && (
        <EmptyState
          icon={<Icon name="i-store" size="lg" />}
          title={filtered ? "Nada encontrado com esse filtro" : "Nada publicado ainda"}
          description={
            filtered
              ? "Tente outro tipo, ou procure por uma palavra mais curta."
              : "Quando alguém publicar um fluxo, um plugin ou um modelo, ele aparece aqui para você instalar."
          }
        />
      )}

      {assets.length > 0 && (
        <section className="stack-md">
          <p className="list-meta">
            <span>
              {assets.length} item(ns) {filtered ? "com esse filtro" : "publicado(s)"}
            </span>
            {filtered && (
              <Button
                variant="ghost"
                size="sm"
                className="od-touch"
                onClick={() => {
                  setKind("")
                  setQuery("")
                }}
              >
                <Icon name="i-x" size="sm" />
                Limpar filtros
              </Button>
            )}
          </p>

          <div className="grid-cards">
            {assets.map((asset) => {
              const install = installs[asset.id]
              const stars = Math.round(asset.rating)
              const busyElsewhere = busyId !== null && busyId !== asset.id
              return (
                <article key={asset.id} className="card stack-sm">
                  <div className="row-between">
                    <h3 className="card-title break-words">{asset.name}</h3>
                    <Badge variant="accent">{kindLabel(asset.kind)}</Badge>
                  </div>

                  <p className="card-sub">{asset.description || "Sem descrição."}</p>

                  <span className="hint">
                    {asset.author || "sem autor"} · versão {asset.version} · {formatNumber(asset.installs)}{" "}
                    instalação(ões)
                  </span>

                  {asset.tags.length > 0 && (
                    <div className="od-cluster">
                      {asset.tags.map((tag) => (
                        <Badge key={tag} variant="neutral">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  )}

                  <div className="row-between">
                    <div className="od-stack" style={{ ["--od-gap" as string]: "4px" }}>
                      <span className="hint">
                        nota {asset.rating.toFixed(1)} · {formatNumber(asset.rating_count)} avaliação(ões)
                      </span>
                      <div className="od-row" style={{ ["--od-gap" as string]: "2px" }} role="group" aria-label={`Dar nota a ${asset.name}`}>
                        {[1, 2, 3, 4, 5].map((score) => (
                          <button
                            key={score}
                            type="button"
                            className="btn btn-ghost btn-sm icon-btn"
                            aria-label={`Dar nota ${score} de 5`}
                            title={`Dar nota ${score} de 5`}
                            disabled={ratingId !== null}
                            onClick={() => void handleRate(asset, score)}
                          >
                            <Star
                              className={cn(
                                "ic ic-sm",
                                score <= stars ? "text-[var(--warning)]" : "text-[var(--text-3)]"
                              )}
                              fill={score <= stars ? "currentColor" : "none"}
                            />
                          </button>
                        ))}
                      </div>
                    </div>

                    <Button
                      size="sm"
                      className="od-touch"
                      loading={busyId === asset.id && !removed[asset.id]}
                      disabled={busyElsewhere}
                      onClick={() => void handleInstall(asset)}
                    >
                      <Icon name="i-download" size="sm" />
                      Instalar
                    </Button>
                  </div>

                  {install && (
                    <div className="od-stack" style={{ ["--od-gap" as string]: "4px" }}>
                      <span className="badge badge-success">
                        <span className="dot" aria-hidden="true" />
                        {install.installed ? "Instalado" : "Já estava instalado"}
                      </span>
                      <span className="hint break-all">
                        Guardado em <span className="mono">{install.target}</span>
                      </span>
                      <span className="hint">{install.detail}</span>
                    </div>
                  )}

                  <div className="od-row" style={{ ["--od-gap" as string]: "8px", flexWrap: "wrap" }}>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="od-touch"
                      loading={busyId === asset.id && Boolean(removed[asset.id])}
                      disabled={busyElsewhere}
                      title="Remover a cópia instalada"
                      onClick={() => void handleUninstall(asset)}
                    >
                      <Icon name="i-trash" size="sm" />
                      Remover
                    </Button>
                    {removed[asset.id] && !install && <span className="hint">{removed[asset.id]}</span>}
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}

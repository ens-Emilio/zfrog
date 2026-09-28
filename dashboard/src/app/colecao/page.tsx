"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Topbar } from "@/components/Navbar"
import { Icon } from "@/lib/icons"
import { api, CatalogCard } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/ds"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Modal } from "@/components/ui/modal"
import { useToast } from "@/components/ToastRegion"
import { formatNumber } from "@/lib/utils"

/**
 * The moodboard: every captured reference as a card, with the screenshots as the
 * protagonists — the plan's "o visual é o protagonista".
 *
 * Three ways in, because they answer different questions: free-text search over the
 * origin, the site list, and the chips (tags and colours) that come from the captures
 * themselves. All of them combine.
 */
export default function CollectionPage() {
  const toast = useToast()

  const [cards, setCards] = useState<CatalogCard[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [tags, setTags] = useState<{ tag: string; count: number }[]>([])
  const [colors, setColors] = useState<{ hex: string; count: number }[]>([])
  const [sites, setSites] = useState<{ site: string; count: number }[]>([])

  const [tag, setTag] = useState<string | null>(null)
  const [color, setColor] = useState<string | null>(null)
  const [site, setSite] = useState<string | null>(null)
  const [text, setText] = useState("")

  const [described, setDescribed] = useState<string | null>(null)
  const [scores, setScores] = useState<Record<string, number>>({})
  const [selected, setSelected] = useState<CatalogCard | null>(null)
  const [confirming, setConfirming] = useState<CatalogCard | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [page, tagList, colorList, siteList] = await Promise.all([
        api.getCatalog({
          tag: tag ?? undefined,
          color: color ?? undefined,
          site: site ?? undefined,
          query: text || undefined,
          limit: 200,
        }),
        api.getCatalogTags(),
        api.getCatalogColors(24),
        api.getCatalogSites(),
      ])
      setCards(page.cards)
      setTotal(page.total)
      setTags(tagList)
      setColors(colorList)
      setSites(siteList)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [tag, color, site, text])

  useEffect(() => {
    void load()
  }, [load])

  /** Descriptive search ranks by relevance, so it replaces the list rather than filtering it. */
  const runDescriptive = async () => {
    const query = text.trim()
    if (!query) {
      setDescribed(null)
      setScores({})
      void load()
      return
    }
    setLoading(true)
    try {
      const result = await api.searchCatalog(query, 60)
      setCards(result.hits)
      setDescribed(query)
      setScores(Object.fromEntries(result.hits.map((hit) => [hit.id, hit.score])))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const clearFilters = () => {
    setTag(null)
    setColor(null)
    setSite(null)
    setText("")
    setDescribed(null)
    setScores({})
  }

  const hasFilters = tag !== null || color !== null || site !== null || text !== ""

  const removeCard = async (card: CatalogCard) => {
    setConfirming(null)
    try {
      await api.deleteCatalogCard(card.id)
      toast("Referência removida do catálogo.")
      setSelected(null)
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : "Não foi possível remover.", "err")
    }
  }

  const summary = useMemo(() => {
    if (described) return `${cards.length} referência(s) para “${described}”`
    if (hasFilters) return `${cards.length} de ${formatNumber(total)} referências`
    return `${formatNumber(total)} referência(s) no catálogo`
  }, [described, hasFilters, cards.length, total])

  return (
    <div className="view-grid">
      <Topbar
        title="Coleção"
        description="As referências de design que você capturou. Busque por descrição, etiqueta, cor ou site."
        action={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            <Icon name="i-refresh" size="sm" /> Atualizar
          </Button>
        }
      />

      {error && (
        <div className="card">
          <p className="error-text" role="alert">
            <Icon name="i-alert" size="sm" /> Não foi possível falar com o servidor: {error}
          </p>
          <p className="hint mt-2">
            Verifique se a API está rodando (<span className="mono">./zfrog dev</span>).
          </p>
          <Button size="sm" variant="secondary" className="mt-3" onClick={() => void load()}>
            Tentar de novo
          </Button>
        </div>
      )}

      <div className="card stack-md">
        <div className="toolbar">
          <div className="search-wrap">
            <Icon name="i-search" />
            <input
              className="input"
              type="search"
              value={text}
              placeholder="Buscar por endereço, título ou descrição visual…"
              aria-label="Buscar referências"
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void runDescriptive()}
            />
          </div>
          <Button onClick={() => void runDescriptive()}>
            <Icon name="i-sparkles" size="sm" /> Buscar por descrição
          </Button>
          {hasFilters && (
            <Button variant="ghost" onClick={clearFilters}>
              <Icon name="i-x" size="sm" /> Limpar
            </Button>
          )}
        </div>

        {tags.length > 0 && (
          <div className="filter-rail" role="group" aria-label="Filtrar por etiqueta">
            {tags.map((entry) => (
              <Chip
                key={entry.tag}
                active={tag === entry.tag}
                onClick={() => setTag(tag === entry.tag ? null : entry.tag)}
              >
                {entry.tag}
                <span className="hint">{entry.count}</span>
              </Chip>
            ))}
          </div>
        )}

        {colors.length > 0 && (
          <div className="filter-rail" role="group" aria-label="Filtrar por cor">
            {colors.map((entry) => (
              <button
                key={entry.hex}
                type="button"
                className="chip"
                aria-pressed={color === entry.hex}
                title={`${entry.hex} em ${entry.count} referência(s)`}
                onClick={() => setColor(color === entry.hex ? null : entry.hex)}
              >
                <span
                  className="h-3.5 w-3.5 rounded-full border"
                  style={{ background: entry.hex, borderColor: "var(--glass-border-strong)" }}
                  aria-hidden="true"
                />
                <span className="mono">{entry.hex}</span>
              </button>
            ))}
          </div>
        )}

        {sites.length > 0 && (
          <div className="search-wrap" style={{ flex: "0 1 320px" }}>
            <label className="field">
              <span className="label">Site</span>
              <span className="select-wrap">
                <select
                  className="select"
                  value={site ?? ""}
                  onChange={(event) => setSite(event.target.value || null)}
                >
                  <option value="">Todos os sites</option>
                  {sites.map((entry) => (
                    <option key={entry.site} value={entry.site}>
                      {entry.site} ({entry.count})
                    </option>
                  ))}
                </select>
                <Icon name="i-chevron" />
              </span>
            </label>
          </div>
        )}
      </div>

      <p className="list-meta">
        <span>{loading ? "Carregando…" : summary}</span>
        {described && <span>ranking por relevância da descrição</span>}
      </p>

      {loading && cards.length === 0 ? (
        <div className="grid-cards">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} style={{ height: 260 }} />
          ))}
        </div>
      ) : cards.length === 0 ? (
        <EmptyState
          icon={<Icon name="i-layers" size="lg" />}
          title={hasFilters ? "Nenhuma referência com esses filtros" : "A coleção está vazia"}
          description={
            hasFilters
              ? "Ajuste a busca, a etiqueta, a cor ou o site."
              : "Capture uma página com o comando jump para ela virar uma referência aqui."
          }
          action={hasFilters ? { label: "Limpar filtros", onClick: clearFilters } : undefined}
          href={hasFilters ? undefined : { label: "Nova extração", href: "/probe" }}
        />
      ) : (
        <div className="grid-cards">
          {cards.map((card) => (
            <CardTile
              key={card.id}
              card={card}
              score={scores[card.id]}
              onOpen={() => setSelected(card)}
            />
          ))}
        </div>
      )}

      {selected && (
        <CardDetail
          card={selected}
          onClose={() => setSelected(null)}
          onDelete={() => setConfirming(selected)}
          onChanged={() => {
            void load()
            void api.getCatalogCard(selected.id).then(setSelected).catch(() => setSelected(null))
          }}
        />
      )}

      <Modal
        open={confirming !== null}
        title="Remover esta referência?"
        body={
          confirming
            ? `A referência de ${confirming.site} sai do catálogo. Os arquivos capturados continuam em disco.`
            : ""
        }
        confirmLabel="Remover"
        danger
        onConfirm={() => confirming && void removeCard(confirming)}
        onClose={() => setConfirming(null)}
      />
    </div>
  )
}

/** One capture in the grid: the screenshot is the card. */
function CardTile({
  card,
  score,
  onOpen,
}: {
  card: CatalogCard
  score?: number
  onOpen: () => void
}) {
  return (
    <article className="card stack-sm" style={{ padding: 0, overflow: "hidden" }}>
      <button
        type="button"
        onClick={onOpen}
        className="block w-full text-left"
        aria-label={`Abrir a referência de ${card.site}`}
      >
        <div
          style={{
            aspectRatio: "16 / 10",
            background: "var(--glass-strong)",
            borderBottom: "1px solid var(--glass-border)",
            overflow: "hidden",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- served by the local API, not Next's optimiser */}
          <img
            src={api.catalogScreenshotUrl(card.id)}
            alt={`Captura de ${card.site}`}
            loading="lazy"
            style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top" }}
          />
        </div>
      </button>

      <div className="stack-sm px-4 pb-4">
        <div className="row-between">
          <span className="job-url od-truncate">{card.site}</span>
          {card.dominant && (
            <span
              className="h-4 w-4 rounded-full border shrink-0"
              style={{ background: card.dominant, borderColor: "var(--glass-border-strong)" }}
              title={`Cor dominante ${card.dominant}`}
              aria-label={`Cor dominante ${card.dominant}`}
            />
          )}
        </div>

        <span className="hint od-truncate">{card.title || card.url}</span>

        {typeof score === "number" && (
          <span className="badge badge-accent" title="Relevância da busca por descrição">
            relevância {score.toFixed(2)}
          </span>
        )}

        {card.palette.length > 0 && (
          <div className="flex gap-1" aria-label="Paleta da captura">
            {card.palette.slice(0, 6).map((hex) => (
              <span
                key={hex}
                className="h-4 flex-1 rounded-[4px] border"
                style={{ background: hex, borderColor: "var(--glass-border)" }}
                title={hex}
              />
            ))}
          </div>
        )}

        <div className="job-sub">
          <span>{card.captured_at}</span>
          <span aria-hidden="true">·</span>
          <span>{card.mode}</span>
        </div>

        {card.tags.length > 0 && (
          <div className="flex gap-1 flex-wrap">
            {card.tags.map((tag) => (
              <span key={tag} className="badge badge-neutral">
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  )
}

/**
 * The reference in full: screenshot, palette, typography and the raw tokens.
 *
 * Rendered as a panel rather than a route so the grid stays on screen — comparing
 * references is the point of a moodboard.
 */
function CardDetail({
  card,
  onClose,
  onDelete,
  onChanged,
}: {
  card: CatalogCard
  onClose: () => void
  onDelete: () => void
  onChanged: () => void
}) {
  const toast = useToast()
  const [tagDraft, setTagDraft] = useState("")
  const [note, setNote] = useState(card.note)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose])

  const tokens = card.tokens ?? {}

  const addTag = async () => {
    const value = tagDraft.trim()
    if (!value) return
    try {
      await api.setCatalogTags(card.id, [value])
      setTagDraft("")
      toast(`Etiqueta “${value}” adicionada.`)
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : "Não foi possível etiquetar.", "err")
    }
  }

  const saveNote = async () => {
    try {
      await api.setCatalogNote(card.id, note)
      toast("Nota salva.")
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : "Não foi possível salvar a nota.", "err")
    }
  }

  return (
    <div
      className="modal-scrim"
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div
        className="modal glass"
        role="dialog"
        aria-modal="true"
        aria-label={`Referência de ${card.site}`}
        style={{ maxWidth: 860, maxHeight: "88vh", overflowY: "auto" }}
      >
        <div className="row-between">
          <div className="stack-sm">
            <h3 className="card-title">{card.title || card.site}</h3>
            <a href={card.url} target="_blank" rel="noreferrer" className="detail-url">
              {card.url}
            </a>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Fechar">
            <Icon name="i-x" size="sm" />
          </Button>
        </div>

        {/* eslint-disable-next-line @next/next/no-img-element -- served by the local API */}
        <img
          src={api.catalogScreenshotUrl(card.id)}
          alt={`Captura de ${card.site}`}
          style={{ width: "100%", borderRadius: "var(--r-control)", border: "1px solid var(--glass-border)" }}
        />

        <dl className="kv">
          <dt>Capturado</dt>
          <dd>{card.captured_at}</dd>
          <dt>Modo</dt>
          <dd>
            {card.mode} · {card.engine}
          </dd>
          <dt>Elementos</dt>
          <dd>{formatNumber(tokens.element_count ?? 0)}</dd>
          <dt>Tamanho</dt>
          <dd>{formatNumber(card.bytes)} bytes</dd>
        </dl>

        {(tokens.palette?.length ?? 0) > 0 && (
          <div className="stack-sm">
            <span className="label">Paleta</span>
            <div className="od-cluster" style={{ ["--od-gap" as string]: "8px" }}>
              {tokens.palette?.slice(0, 16).map((entry) => (
                <span key={entry.hex} className="od-row" style={{ ["--od-gap" as string]: "6px" }}>
                  <span
                    className="h-4 w-4 rounded-[4px] border"
                    style={{ background: entry.hex, borderColor: "var(--glass-border-strong)" }}
                    aria-hidden="true"
                  />
                  <span className="mono text-[12px]">{entry.hex}</span>
                  <span className="hint">×{entry.count}</span>
                  {entry.role && <span className="badge badge-accent">{entry.role}</span>}
                </span>
              ))}
            </div>
            {(tokens.unreadable_colors ?? 0) > 0 && (
              <span className="hint">
                {tokens.unreadable_colors} uso(s) de cor em sintaxe não suportada ficaram fora.
              </span>
            )}
          </div>
        )}

        {(tokens.fonts?.length ?? 0) > 0 && (
          <div className="stack-sm">
            <span className="label">Tipografia</span>
            {tokens.fonts?.slice(0, 6).map((font) => (
              <div key={font.family} className="row-between">
                <span className="text-[13px]">{font.family}</span>
                <span className="hint mono">
                  {Object.keys(font.sizes ?? {}).slice(0, 4).join(" · ") || "—"}
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="stack-sm">
          <span className="label">Etiquetas</span>
          <div className="flex gap-1 flex-wrap">
            {card.tags.length > 0 ? (
              card.tags.map((tag) => (
                <span key={tag} className="badge badge-neutral">
                  {tag}
                </span>
              ))
            ) : (
              <span className="hint">Nenhuma ainda.</span>
            )}
          </div>
          <div className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
            <input
              className="input"
              value={tagDraft}
              placeholder="nova etiqueta"
              aria-label="Nova etiqueta"
              onChange={(event) => setTagDraft(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void addTag()}
            />
            <Button size="sm" variant="secondary" onClick={() => void addTag()} disabled={!tagDraft.trim()}>
              Adicionar
            </Button>
          </div>
        </div>

        <div className="field">
          <label className="label" htmlFor="card-note">
            Nota
          </label>
          <textarea
            id="card-note"
            className="textarea"
            value={note}
            placeholder="O que chamou atenção nesta referência?"
            onChange={(event) => setNote(event.target.value)}
          />
          <Button size="sm" variant="secondary" onClick={() => void saveNote()}>
            Salvar nota
          </Button>
        </div>

        <div className="modal-actions">
          <Button variant="destructive" onClick={onDelete}>
            <Icon name="i-trash" size="sm" /> Remover
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Fechar
          </Button>
        </div>
      </div>
    </div>
  )
}

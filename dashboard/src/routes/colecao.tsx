import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, CatalogCard } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { formatNumber } from "@/lib/utils"
import { CodeBlock, Gut, Spinner, Swatch, SYM, TuiModal } from "@/components/ui/tui"

/**
 * Collection in TUI: mono grid of references with real screenshots,
 * keyboard navigation shortcuts (j/k / enter), technical legend and
 * detailed token inspection with CSS export (DESIGN.md §6.2).
 */
function CollectionPage() {
  const t = useT()
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
  const [sel, setSel] = useState<number>(-1)
  const [selected, setSelected] = useState<CatalogCard | null>(null)
  const [confirming, setConfirming] = useState<CatalogCard | null>(null)

  const searchInputRef = useRef<HTMLInputElement>(null)

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
    setSel(-1)
  }

  const hasFilters = tag !== null || color !== null || site !== null || text !== "" || described !== null

  const removeCard = async (card: CatalogCard) => {
    setConfirming(null)
    try {
      await api.deleteCatalogCard(card.id)
      toast(t("colecao.removedToast"))
      setSelected(null)
      void load()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("colecao.removeError"), "err")
    }
  }

  // Keyboard navigation: j/k, arrows, Enter opens, Esc closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (selected || confirming) return
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        if (e.key === "Escape") {
          e.preventDefault()
          ;(e.target as HTMLElement).blur()
        }
        return
      }

      if (e.key === "j" || e.key === "ArrowDown" || e.key === "ArrowRight") {
        e.preventDefault()
        setSel((prev) => Math.min(prev + 1, cards.length - 1))
      } else if (e.key === "k" || e.key === "ArrowUp" || e.key === "ArrowLeft") {
        e.preventDefault()
        setSel((prev) => Math.max(prev - 1, 0))
      } else if (e.key === "Enter") {
        if (sel >= 0 && cards[sel]) {
          e.preventDefault()
          setSelected(cards[sel])
        }
      } else if (e.key === "/") {
        e.preventDefault()
        searchInputRef.current?.focus()
      } else if (e.key === "Escape") {
        if (hasFilters) {
          e.preventDefault()
          clearFilters()
        }
      }
    }

    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [cards, sel, selected, confirming, hasFilters])

  return (
    <>
      <div className="flex items-baseline justify-between">
        <h1>{t("colecao.title")}</h1>
        <span className="text-[12px]" style={{ color: "var(--fg-dim)" }}>
          {loading ? (
            <span>
              <Spinner /> {t("colecao.loading")}
            </span>
          ) : described ? (
            t("colecao.resultsFor").replace("{count}", String(cards.length)).replace("{query}", described)
          ) : hasFilters ? (
            t("colecao.filteredCount").replace("{count}", String(cards.length)).replace("{total}", formatNumber(total))
          ) : (
            t("colecao.totalCount").replace("{total}", formatNumber(total))
          )}
        </span>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("colecao.apiError").replace("{error}", error)}</p>
          <div>
            <button type="button" className="tui-btn" onClick={() => void load()}>
              {t("colecao.retry")}
            </button>
          </div>
        </div>
      )}

      {/* Monospace filter bar */}
      <div className="filters flex-wrap" style={{ gap: "1ch 1.5ch" }}>
        <span className="searchline">
          <span className="slash">/</span>
          <input
            ref={searchInputRef}
            type="text"
            value={text}
            placeholder={t("colecao.searchPlaceholder")}
            aria-label={t("colecao.searchAria")}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runDescriptive()
            }}
            style={{ width: "28ch" }}
          />
        </span>

        <button type="button" className="tui-btn accent" onClick={() => void runDescriptive()}>
          {t("colecao.searchByDescription")}
        </button>

        {sites.length > 0 && (
          <select
            className="tui-select"
            value={site ?? ""}
            onChange={(e) => setSite(e.target.value || null)}
            style={{ width: "auto", padding: "0.1lh 0.75ch" }}
            aria-label={t("colecao.filterBySite")}
          >
            <option value="">{t("colecao.allSites").replace("{count}", String(sites.length))}</option>
            {sites.map((s) => (
              <option key={s.site} value={s.site}>
                {s.site} ({s.count})
              </option>
            ))}
          </select>
        )}

        {hasFilters && (
          <button type="button" className="tui-btn" onClick={clearFilters}>
            {t("colecao.clearFilters")}
          </button>
        )}
      </div>

      {/* Secondary rails: Tags and Colors in TUI */}
      {(tags.length > 0 || colors.length > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.25lh", margin: "0.25lh 0 0.5lh" }}>
          {tags.length > 0 && (
            <div className="tui-tags" role="group" aria-label={t("colecao.tagsAria")}>
              <span className="tui-label" style={{ marginRight: "0.5ch" }}>{t("colecao.tagsLabel")}</span>
              {tags.slice(0, 16).map((entry) => (
                <button
                  key={entry.tag}
                  type="button"
                  className={`tui-tag${tag === entry.tag ? " active" : ""}`}
                  onClick={() => setTag(tag === entry.tag ? null : entry.tag)}
                >
                  {entry.tag} <span style={{ color: "var(--fg-dim)" }}>{entry.count}</span>
                </button>
              ))}
            </div>
          )}

          {colors.length > 0 && (
            <div className="tui-tags" role="group" aria-label={t("colecao.colorsAria")}>
              <span className="tui-label" style={{ marginRight: "0.5ch" }}>{t("colecao.colorsLabel")}</span>
              {colors.slice(0, 16).map((entry) => (
                <button
                  key={entry.hex}
                  type="button"
                  className={`tui-tag${color === entry.hex ? " active" : ""}`}
                  onClick={() => setColor(color === entry.hex ? null : entry.hex)}
                  title={`${entry.hex} (${entry.count})`}
                >
                  <span
                    style={{
                      display: "inline-block",
                      width: 9,
                      height: 9,
                      background: entry.hex,
                      outline: "1px solid var(--line)",
                      outlineOffset: -1,
                    }}
                  />
                  {entry.hex}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Mono image grid */}
      {loading && cards.length === 0 ? (
        <p className="empty">
          <Spinner /> {t("colecao.loadingCatalog")}
        </p>
      ) : cards.length === 0 ? (
        <p className="empty">
          {hasFilters ? (
            <>
              {t("colecao.noResults")} <button type="button" className="tui-btn" onClick={clearFilters}>{t("colecao.clearFilters")}</button>
            </>
          ) : (
            <>
              {t("colecao.emptyCatalog")}
            </>
          )}
        </p>
      ) : (
        <div className="tui-grid" role="list">
          {cards.map((card, i) => {
            const isSel = i === sel
            const score = scores[card.id]
            return (
              <div
                key={card.id}
                role="listitem"
                tabIndex={0}
                className={`tui-card${isSel ? " sel" : ""}`}
                onClick={() => {
                  setSel(i)
                  setSelected(card)
                }}
                onMouseEnter={() => setSel(i)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setSelected(card)
                }}
              >
                <div className="tui-card-img">
                  <Gut active={isSel} />
                  <img
                    src={api.catalogScreenshotUrl(card.id)}
                    alt={t("colecao.screenshotAlt").replace("{site}", card.site)}
                    loading="lazy"
                  />
                </div>
                <div className="tui-card-body">
                  <div className="tui-card-head">
                    <span className="tui-card-site">{card.site}</span>
                    {card.dominant && (
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          background: card.dominant,
                          outline: "1px solid var(--line)",
                          outlineOffset: -1,
                          flexShrink: 0,
                        }}
                        title={t("colecao.dominantTitle").replace("{hex}", card.dominant)}
                      />
                    )}
                  </div>

                  <span className="tui-card-sub">{card.title || card.url}</span>

                  {typeof score === "number" && (
                    <span style={{ color: "var(--accent)", fontSize: 11 }}>
                      {t("colecao.relevance").replace("{score}", score.toFixed(2))}
                    </span>
                  )}

                  {card.palette.length > 0 && <Swatch colors={card.palette} n={6} />}

                  <div className="tui-card-meta">
                    <span>{card.captured_at}</span>
                    <span>{card.mode}</span>
                  </div>

                  {card.tags.length > 0 && (
                    <div className="tui-tags" style={{ marginTop: "0.125lh" }}>
                      {card.tags.map((t) => (
                        <span key={t} className="tui-tag" style={{ cursor: "default" }}>
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Reference detail and tokens modal */}
      {selected && (
        <ReferenceDetailModal
          card={selected}
          onClose={() => setSelected(null)}
          onDelete={() => setConfirming(selected)}
          onChanged={() => {
            void load()
            void api.getCatalogCard(selected.id).then(setSelected).catch(() => setSelected(null))
          }}
        />
      )}

      {/* Delete confirmation */}
      {confirming && (
        <TuiModal
          open={true}
          title={t("colecao.removeTitle")}
          onClose={() => setConfirming(null)}
        >
          <p>
            {t("colecao.removeBody")
              .split("{site}")
              .map((part, i, arr) => (i < arr.length - 1 ? [part, <b key={i}>{confirming.site}</b>] : [part]))
              .flat()}
          </p>
          <div className="flex gap-2 justify-end" style={{ marginTop: "0.5lh" }}>
            <button type="button" className="tui-btn danger" onClick={() => void removeCard(confirming)}>
              {t("colecao.confirmRemoval")}
            </button>
            <button type="button" className="tui-btn" onClick={() => setConfirming(null)}>
              {t("colecao.cancel")}
            </button>
          </div>
        </TuiModal>
      )}
    </>
  )
}

function ReferenceDetailModal({
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
  const t = useT()
  const toast = useToast()
  const [tagDraft, setTagDraft] = useState("")
  const [note, setNote] = useState(card.note)

  const tokens = card.tokens ?? {}

  const addTag = async () => {
    const value = tagDraft.trim()
    if (!value) return
    try {
      await api.setCatalogTags(card.id, [value])
      setTagDraft("")
      toast(t("colecao.tagAddedToast").replace("{tag}", value))
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("colecao.tagError"), "err")
    }
  }

  const saveNote = async () => {
    try {
      await api.setCatalogNote(card.id, note)
      toast(t("colecao.noteSavedToast"))
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : t("colecao.noteError"), "err")
    }
  }

  const cssTokens = useMemo(() => {
    if (!card.palette?.length) return []
    const prefix = card.site.replace(/[^a-z0-9]/gi, "").slice(0, 8).toLowerCase() || "site"
    return card.palette.map((hex, i) => `--${prefix}-color-${i + 1}: ${hex};`)
  }, [card])

  return (
    <TuiModal open={true} title={t("colecao.detailTitle").replace("{site}", card.site)} onClose={onClose}>
      <div style={{ maxHeight: "360px", overflow: "hidden", border: "1px solid var(--line)" }}>
        <img
          src={api.catalogScreenshotUrl(card.id)}
          alt={t("colecao.fullCaptureAlt").replace("{site}", card.site)}
          style={{ width: "100%", display: "block" }}
        />
      </div>

      <dl className="tui-kv">
        <dt>url</dt>
        <dd>
          <a
            href={card.url}
            target="_blank"
            rel="noreferrer"
            style={{ color: "var(--accent)", textDecoration: "none" }}
          >
            {card.url}
          </a>
        </dd>
        <dt>{t("colecao.capture")}</dt>
        <dd>{card.captured_at} · {t("colecao.mode").replace("{mode}", card.mode).replace("{engine}", card.engine)}</dd>
        <dt>{t("colecao.elements")}</dt>
        <dd>{t("colecao.elementCount").replace("{count}", formatNumber(tokens.element_count ?? 0))}</dd>
        <dt>{t("colecao.size")}</dt>
        <dd>{formatNumber(card.bytes)} bytes</dd>
      </dl>

      {/* Extracted palette & tokens */}
      {(tokens.palette?.length ?? 0) > 0 && (
        <div>
          <span className="tui-label">{t("colecao.paletteLabel").replace("{count}", String(tokens.palette?.length ?? 0))}</span>
          <div className="tui-tags" style={{ marginTop: "0.25lh" }}>
            {tokens.palette?.slice(0, 16).map((entry) => (
              <span key={entry.hex} className="tui-tag" style={{ cursor: "default" }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 9,
                    height: 9,
                    background: entry.hex,
                    outline: "1px solid var(--line)",
                    outlineOffset: -1,
                  }}
                />
                {entry.hex}
                <span style={{ color: "var(--fg-dim)" }}>×{entry.count}</span>
                {entry.role && <span style={{ color: "var(--accent)" }}>[{entry.role}]</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Exportable CSS block */}
      {cssTokens.length > 0 && (
        <div>
          <span className="tui-label">{t("colecao.cssTokens")}</span>
          <CodeBlock code={cssTokens} />
        </div>
      )}

      {/* Typography */}
      {(tokens.fonts?.length ?? 0) > 0 && (
        <div>
          <span className="tui-label">{t("colecao.typography")}</span>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25lh", marginTop: "0.25lh" }}>
            {tokens.fonts?.slice(0, 6).map((font) => (
              <div key={font.family} className="flex justify-between text-[12px]">
                <span style={{ color: "var(--fg)" }}>{font.family}</span>
                <span style={{ color: "var(--fg-dim)" }}>
                  {Object.keys(font.sizes ?? {}).slice(0, 5).join(" · ") || "—"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tags */}
      <div>
        <span className="tui-label">{t("colecao.tags")}</span>
        <div className="tui-tags" style={{ margin: "0.25lh 0" }}>
          {card.tags.length > 0 ? (
            card.tags.map((t) => (
              <span key={t} className="tui-tag" style={{ cursor: "default" }}>
                {t}
              </span>
            ))
          ) : (
            <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>{t("colecao.noTags")}</span>
          )}
        </div>
        <div className="flex gap-2" style={{ marginTop: "0.25lh" }}>
          <input
            className="tui-input"
            value={tagDraft}
            placeholder={t("colecao.newTagPlaceholder")}
            aria-label={t("colecao.newTagAria")}
            onChange={(e) => setTagDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void addTag()
            }}
            style={{ maxWidth: "24ch" }}
          />
          <button type="button" className="tui-btn" onClick={() => void addTag()} disabled={!tagDraft.trim()}>
            {t("colecao.add")}
          </button>
        </div>
      </div>

      {/* Note */}
      <div className="tui-field">
        <label className="tui-label" htmlFor="card-note">{t("colecao.note")}</label>
        <textarea
          id="card-note"
          className="tui-textarea"
          value={note}
          placeholder={t("colecao.notePlaceholder")}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
        />
        <div>
          <button type="button" className="tui-btn" onClick={() => void saveNote()}>
            {t("colecao.saveNote")}
          </button>
        </div>
      </div>

      <div className="flex justify-between" style={{ marginTop: "0.5lh", borderTop: "1px solid var(--line)", paddingTop: "0.5lh" }}>
        <button type="button" className="tui-btn danger" onClick={onDelete}>
          {SYM.fail} {t("colecao.remove")}
        </button>
        <button type="button" className="tui-btn" onClick={onClose}>
          {t("colecao.close")}
        </button>
      </div>
    </TuiModal>
  )
}

export const Route = createFileRoute("/colecao")({
  component: CollectionPage,
})

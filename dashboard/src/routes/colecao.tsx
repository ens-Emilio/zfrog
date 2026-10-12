import { createFileRoute } from "@tanstack/react-router"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, CatalogCard } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { formatNumber } from "@/lib/utils"
import { Spinner } from "@/components/ui/tui"

/**
 * Collection in zf: grid of references with screenshots,
 * keyboard navigation j/k / enter, facet chips and detail tokens
 * with CSS export.
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

  const headerCount = loading ? (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <Spinner /> {t("colecao.loading")}
    </span>
  ) : described ? (
    t("colecao.resultsFor").replace("{count}", String(cards.length)).replace("{query}", described)
  ) : hasFilters ? (
    t("colecao.filteredCount").replace("{count}", String(cards.length)).replace("{total}", formatNumber(total))
  ) : (
    t("colecao.totalCount").replace("{total}", formatNumber(total))
  )

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("colecao.title")}</h1>
        <span className="zf-meta">
          grid · busca + facetas · <kbd>j</kbd> <kbd>k</kbd> · <kbd>↵</kbd> abrir · <kbd>/</kbd> buscar
        </span>
        <span className="spacer" style={{ flex: 1 }} />
        <span className="zf-micro">{headerCount}</span>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>✗ {t("colecao.apiError").replace("{error}", error)}</p>
          <div style={{ marginTop: "var(--s2)" }}>
            <button type="button" className="zf-btn" onClick={() => void load()}>
              {t("colecao.retry")}
            </button>
          </div>
        </div>
      )}

      <div
        className="zf-panel"
        style={{
          padding: "var(--s3) var(--s4)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--s3)",
          marginBottom: "var(--s4)",
        }}
      >
        <div style={{ display: "flex", gap: "var(--s3)", alignItems: "center", flexWrap: "wrap" }}>
          <div className="zf-prompt" style={{ flex: 1, minWidth: 220 }}>
            <span className="zf-meta">⌕</span>
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
            />
            {described && (
              <span className="zf-micro" style={{ whiteSpace: "nowrap" }}>
                {cards.length} hit{cards.length === 1 ? "" : "s"}
              </span>
            )}
          </div>

          <button type="button" className="zf-btn zf-btn--primary" onClick={() => void runDescriptive()}>
            {t("colecao.searchByDescription")}
          </button>

          {sites.length > 0 && (
            <select
              className="zf-select"
              value={site ?? ""}
              onChange={(e) => setSite(e.target.value || null)}
              style={{ width: 160 }}
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
            <button type="button" className="zf-btn zf-btn--ghost" onClick={clearFilters}>
              {t("colecao.clearFilters")}
            </button>
          )}
        </div>

        {tags.length > 0 && (
          <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap", alignItems: "center" }}>
            <span className="zf-micro" style={{ marginRight: 4 }}>
              {t("colecao.tagsLabel")}
            </span>
            {tags.slice(0, 16).map((entry) => (
              <button
                key={entry.tag}
                type="button"
                className="zf-chip"
                aria-pressed={tag === entry.tag}
                onClick={() => setTag(tag === entry.tag ? null : entry.tag)}
              >
                {entry.tag} <span style={{ color: "var(--muted)" }}>{entry.count}</span>
              </button>
            ))}
          </div>
        )}

        {colors.length > 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span className="zf-micro">{t("colecao.colorsLabel")}</span>
            {colors.slice(0, 16).map((entry) => (
              <button
                key={entry.hex}
                type="button"
                className="zf-chip"
                aria-pressed={color === entry.hex}
                onClick={() => setColor(color === entry.hex ? null : entry.hex)}
                title={`${entry.hex} (${entry.count})`}
                style={{ paddingLeft: 8 }}
              >
                <i
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: "50%",
                    background: entry.hex,
                    border: "1px solid var(--border)",
                  }}
                />
                {entry.hex}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && cards.length === 0 ? (
        <div className="zf-empty">
          <Spinner /> {t("colecao.loadingCatalog")}
        </div>
      ) : cards.length === 0 ? (
        <div className="zf-empty">
          {hasFilters ? (
            <span style={{ display: "inline-flex", gap: "var(--s3)", alignItems: "center", flexWrap: "wrap" }}>
              {t("colecao.noResults")}{" "}
              <button type="button" className="zf-btn" onClick={clearFilters}>
                {t("colecao.clearFilters")}
              </button>
            </span>
          ) : (
            <>{t("colecao.emptyCatalog")}</>
          )}
        </div>
      ) : (
        <div className="zf-grid" role="list">
          {cards.map((card, i) => {
            const isSel = i === sel
            const score = scores[card.id]
            return (
              <button
                key={card.id}
                role="listitem"
                type="button"
                className="zf-card"
                aria-label={card.title || card.site}
                onClick={() => {
                  setSel(i)
                  setSelected(card)
                }}
                onMouseEnter={() => setSel(i)}
                style={{
                  textAlign: "left",
                  outline: isSel ? "2px solid var(--accent)" : "none",
                  outlineOffset: 1,
                }}
              >
                <div className="zf-card-sw" aria-hidden="true">
                  {card.palette.length > 0 ? (
                    card.palette.slice(0, 3).map((hex, idx) => (
                      <i key={idx} style={{ background: hex, flex: 1 }} />
                    ))
                  ) : (
                    <>
                      <i style={{ background: card.dominant || "var(--border)" }} />
                      <i style={{ background: "var(--bg)" }} />
                      <i style={{ background: "var(--surface)" }} />
                    </>
                  )}
                  <img
                    src={api.catalogScreenshotUrl(card.id)}
                    alt={t("colecao.screenshotAlt").replace("{site}", card.site)}
                    loading="lazy"
                    style={{ display: "none" }}
                  />
                </div>
                <div className="zf-card-bd">
                  <div className="zf-micro" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <span>{card.site}</span>
                    <span style={{ opacity: 0.4 }}>·</span>
                    <span>{card.captured_at}</span>
                    <span className="zf-spacer" style={{ flex: 1 }} />
                    {card.dominant && (
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: "50%",
                          background: card.dominant,
                          border: "1px solid var(--border)",
                          flexShrink: 0,
                        }}
                        title={t("colecao.dominantTitle").replace("{hex}", card.dominant)}
                      />
                    )}
                  </div>

                  <h3>{card.title || card.url}</h3>

                  {typeof score === "number" && (
                    <span style={{ color: "var(--accent)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
                      {t("colecao.relevance").replace("{score}", score.toFixed(2))}
                    </span>
                  )}

                  {card.palette.length > 0 && (
                    <div style={{ display: "flex", gap: 4 }}>
                      {card.palette.slice(0, 6).map((hex) => (
                        <span
                          key={hex}
                          style={{
                            width: 14,
                            height: 14,
                            borderRadius: "50%",
                            background: hex,
                            border: "1px solid var(--border)",
                          }}
                        />
                      ))}
                    </div>
                  )}

                  <div className="zf-meta" style={{ display: "flex", gap: 8, justifyContent: "space-between" }}>
                    <span className="zf-num">{card.mode}</span>
                  </div>

                  {card.tags.length > 0 && (
                    <div className="zf-chips">
                      {card.tags.map((tg) => (
                        <span key={tg} className="zf-chip" style={{ cursor: "default" }}>
                          {tg}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}

      {cards.length > 0 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--s3)",
            justifyContent: "center",
            marginTop: "var(--s5)",
          }}
        >
          <span className="zf-meta">
            <span className="zf-num">
              {cards.length} / {formatNumber(total)}
            </span>
          </span>
        </div>
      )}

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

      {confirming && (
        <dialog
          open
          className="zf-modal"
          aria-label={t("colecao.removeTitle")}
          onClose={() => setConfirming(null)}
          onClick={(e) => {
            if (e.target === e.currentTarget) setConfirming(null)
          }}
        >
          <div className="zf-modal-hd">
            <span className="zf-h2">{t("colecao.removeTitle")}</span>
            <span className="zf-spacer" style={{ flex: 1 }} />
            <button type="button" className="zf-icon-btn" onClick={() => setConfirming(null)} aria-label="Fechar">
              ×
            </button>
          </div>
          <div className="zf-modal-bd">
            <p>
              {t("colecao.removeBody")
                .split("{site}")
                .map((part, i, arr) =>
                  i < arr.length - 1 ? [part, <b key={i}>{confirming.site}</b>] : [part],
                )
                .flat()}
            </p>
          </div>
          <div className="zf-modal-ft">
            <button type="button" className="zf-btn zf-btn--ghost" onClick={() => setConfirming(null)}>
              {t("colecao.cancel")}
            </button>
            <button type="button" className="zf-btn zf-btn--danger" onClick={() => void removeCard(confirming)}>
              {t("colecao.confirmRemoval")}
            </button>
          </div>
        </dialog>
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
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const d = dialogRef.current
    if (!d) return
    if (!d.open) {
      try {
        d.showModal()
      } catch {
        // already open
      }
    }
    const onCancel = (e: Event) => {
      e.preventDefault()
      onClose()
    }
    d.addEventListener("cancel", onCancel)
    return () => d.removeEventListener("cancel", onCancel)
  }, [onClose])

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
    <dialog
      ref={dialogRef}
      className="zf-modal"
      aria-label={t("colecao.detailTitle").replace("{site}", card.site)}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose()
      }}
    >
      <div className="zf-modal-hd">
        <span className="zf-h2">{card.title || card.site}</span>
        <span className="zf-spacer" style={{ flex: 1 }} />
        <span className="zf-micro">{card.site}</span>
        <button type="button" className="zf-icon-btn" onClick={onClose} aria-label="Fechar">
          ×
        </button>
      </div>
      <div className="zf-modal-bd">
        <div
          style={{
            maxHeight: 360,
            overflow: "hidden",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
          }}
        >
          <img
            src={api.catalogScreenshotUrl(card.id)}
            alt={t("colecao.fullCaptureAlt").replace("{site}", card.site)}
            style={{ width: "100%", display: "block" }}
          />
        </div>

        <dl className="zf-kv">
          <dt>url</dt>
          <dd>
            <a href={card.url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
              {card.url}
            </a>
          </dd>
          <dt>{t("colecao.capture")}</dt>
          <dd>
            {card.captured_at} · {t("colecao.mode").replace("{mode}", card.mode).replace("{engine}", card.engine)}
          </dd>
          <dt>{t("colecao.elements")}</dt>
          <dd>{t("colecao.elementCount").replace("{count}", formatNumber(tokens.element_count ?? 0))}</dd>
          <dt>{t("colecao.size")}</dt>
          <dd>{formatNumber(card.bytes)} bytes</dd>
        </dl>

        {(tokens.palette?.length ?? 0) > 0 && (
          <div>
            <span className="zf-micro">
              {t("colecao.paletteLabel").replace("{count}", String(tokens.palette?.length ?? 0))}
            </span>
            <div className="zf-chips" style={{ marginTop: "var(--s2)" }}>
              {tokens.palette?.slice(0, 16).map((entry) => (
                <span key={entry.hex} className="zf-chip" style={{ cursor: "default", paddingLeft: 8 }}>
                  <span
                    style={{
                      display: "inline-block",
                      width: 9,
                      height: 9,
                      borderRadius: "50%",
                      background: entry.hex,
                      border: "1px solid var(--border)",
                    }}
                  />
                  {entry.hex}
                  <span style={{ color: "var(--muted)" }}>×{entry.count}</span>
                  {entry.role && <span style={{ color: "var(--accent)" }}>[{entry.role}]</span>}
                </span>
              ))}
            </div>
          </div>
        )}

        {cssTokens.length > 0 && (
          <div>
            <div className="zf-micro" style={{ marginBottom: 6 }}>
              {t("colecao.cssTokens")}
            </div>
            <pre className="zf-pre">{cssTokens.join("\n")}</pre>
          </div>
        )}

        {(tokens.fonts?.length ?? 0) > 0 && (
          <div>
            <span className="zf-micro">{t("colecao.typography")}</span>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--s1)", marginTop: "var(--s2)" }}>
              {tokens.fonts?.slice(0, 6).map((font) => (
                <div key={font.family} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span style={{ color: "var(--fg)" }}>{font.family}</span>
                  <span style={{ color: "var(--muted)" }}>
                    {Object.keys(font.sizes ?? {}).slice(0, 5).join(" · ") || "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div>
          <span className="zf-micro">{t("colecao.tags")}</span>
          <div className="zf-chips" style={{ margin: "var(--s2) 0" }}>
            {card.tags.length > 0 ? (
              card.tags.map((tg) => (
                <span key={tg} className="zf-chip" style={{ cursor: "default" }}>
                  {tg}
                </span>
              ))
            ) : (
              <span style={{ color: "var(--muted)", fontSize: 12 }}>{t("colecao.noTags")}</span>
            )}
          </div>
          <div style={{ display: "flex", gap: "var(--s2)", marginTop: "var(--s2)" }}>
            <input
              className="zf-input"
              value={tagDraft}
              placeholder={t("colecao.newTagPlaceholder")}
              aria-label={t("colecao.newTagAria")}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void addTag()
              }}
              style={{ maxWidth: "24ch" }}
            />
            <button type="button" className="zf-btn" onClick={() => void addTag()} disabled={!tagDraft.trim()}>
              {t("colecao.add")}
            </button>
          </div>
        </div>

        <div className="zf-field">
          <label className="zf-label" htmlFor="card-note">
            {t("colecao.note")}
          </label>
          <textarea
            id="card-note"
            className="zf-textarea"
            value={note}
            placeholder={t("colecao.notePlaceholder")}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
          />
          <div>
            <button type="button" className="zf-btn" onClick={() => void saveNote()}>
              {t("colecao.saveNote")}
            </button>
          </div>
        </div>
      </div>
      <div className="zf-modal-ft">
        <button type="button" className="zf-btn zf-btn--danger" onClick={onDelete}>
          ✗ {t("colecao.remove")}
        </button>
        <span style={{ flex: 1 }} />
        <button type="button" className="zf-btn zf-btn--ghost" onClick={onClose}>
          {t("colecao.close")}
        </button>
      </div>
    </dialog>
  )
}

export const Route = createFileRoute("/colecao")({
  component: CollectionPage,
})

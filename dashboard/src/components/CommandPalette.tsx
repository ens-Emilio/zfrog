import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { useT } from "@/lib/i18n"

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  onTheme: () => void
}

export function CommandPalette({ open, onClose, onTheme }: CommandPaletteProps) {
  const t = useT()
  const navigate = useNavigate()
  const [q, setQ] = useState("")
  const [idx, setIdx] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const routes = useMemo(
    () => [
      { id: "theme", label: t("palette.theme"), desc: t("palette.themeDesc"), kbd: "tema", run: onTheme },
      { id: "chat", label: t("palette.chat"), desc: t("palette.chatDesc"), kbd: "chat", to: "/chat" },
      { id: "runs", label: t("palette.home"), desc: t("palette.homeDesc"), kbd: "runs", to: "/" },
      { id: "colecao", label: t("palette.colecao"), desc: t("palette.colecaoDesc"), kbd: "pond", to: "/colecao" },
      { id: "busca", label: t("palette.busca"), desc: t("palette.buscaDesc"), kbd: "busca", to: "/busca" },
      { id: "probe", label: t("palette.probe"), desc: t("palette.probeDesc"), kbd: "jump", to: "/probe" },
      { id: "comparar", label: t("palette.comparar"), desc: t("palette.compararDesc"), kbd: "cmp", to: "/comparar" },
      { id: "datasets", label: t("palette.datasets"), desc: t("palette.datasetsDesc"), kbd: "datasets", to: "/datasets" },
      { id: "grafo", label: t("palette.grafo"), desc: t("palette.grafoDesc"), kbd: "grafo", to: "/grafo" },
      { id: "precos", label: t("palette.precos"), desc: t("palette.precosDesc"), kbd: "precos", to: "/precos" },
      { id: "captura", label: t("palette.captura"), desc: t("palette.capturaDesc"), kbd: "captura", to: "/captura" },
      { id: "qualidade", label: t("palette.qualidade"), desc: t("palette.qualidadeDesc"), kbd: "qualidade", to: "/qualidade" },
      { id: "workers", label: t("palette.workers"), desc: t("palette.workersDesc"), kbd: "workers", to: "/workers" },
      { id: "fluxos", label: t("palette.fluxos"), desc: t("palette.fluxosDesc"), kbd: "fluxos", to: "/fluxos" },
      { id: "snapshots", label: t("palette.snapshots"), desc: t("palette.snapshotsDesc"), kbd: "snapshots", to: "/snapshots" },
      { id: "timeline", label: t("palette.timeline"), desc: t("palette.timelineDesc"), kbd: "timeline", to: "/timeline" },
      { id: "revisao", label: t("palette.revisao"), desc: t("palette.revisaoDesc"), kbd: "revisao", to: "/revisao" },
      { id: "stats", label: t("palette.stats"), desc: t("palette.statsDesc"), kbd: "stats", to: "/stats" },
      { id: "analytics", label: t("palette.analytics"), desc: t("palette.analyticsDesc"), kbd: "analytics", to: "/analytics" },
      { id: "roi", label: t("palette.roi"), desc: t("palette.roiDesc"), kbd: "roi", to: "/roi" },
      { id: "webhooks", label: t("palette.webhooks"), desc: t("palette.webhooksDesc"), kbd: "webhooks", to: "/webhooks" },
      { id: "equipe", label: t("palette.equipe"), desc: t("palette.equipeDesc"), kbd: "equipe", to: "/equipe" },
      { id: "marketplace", label: t("palette.marketplace"), desc: t("palette.marketplaceDesc"), kbd: "market", to: "/marketplace" },
      { id: "graphql", label: t("palette.graphql"), desc: t("palette.graphqlDesc"), kbd: "gql", to: "/graphql" },
      { id: "config", label: t("palette.config"), desc: t("palette.configDesc"), kbd: "config", to: "/config" },
      { id: "ajuda", label: t("palette.ajuda"), desc: t("palette.ajudaDesc"), kbd: "ajuda", to: "/ajuda" },
      { id: "design", label: t("palette.design"), desc: t("palette.designDesc"), kbd: "design", to: "/design" },
    ],
    [onTheme, t]
  )

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return needle
      ? routes.filter(
          (c) =>
            c.label.toLowerCase().includes(needle) ||
            c.desc.toLowerCase().includes(needle) ||
            c.kbd.toLowerCase().includes(needle)
        )
      : routes
  }, [q, routes])

  useEffect(() => {
    if (open) {
      setQ("")
      setIdx(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  useEffect(() => {
    if (listRef.current && listRef.current.children[idx]) {
      ;(listRef.current.children[idx] as HTMLElement).scrollIntoView({
        block: "nearest",
      })
    }
  }, [idx])

  if (!open) return null

  const runItem = (i: number) => {
    const item = filtered[i]
    if (!item) return
    if (item.to) navigate({ to: item.to }).catch(() => {})
    else item.run?.()
    onClose()
  }

  return (
    <div
      className="scrim open"
      role="dialog"
      aria-modal="true"
      aria-label={t("palette.label")}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="palette">
        <div className="palette-search">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
          >
            <path d="M21 21 16 16" />
            <circle cx="11" cy="11" r="6" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={q}
            autoComplete="off"
            spellCheck={false}
            placeholder={t("palette.commandPlaceholder")}
            aria-label={t("palette.searchLabel")}
            onChange={(e) => {
              setQ(e.target.value)
              setIdx(0)
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault()
                setIdx((i) => Math.min(i + 1, filtered.length - 1))
              } else if (e.key === "ArrowUp") {
                e.preventDefault()
                setIdx((i) => Math.max(i - 1, 0))
              } else if (e.key === "Enter") {
                e.preventDefault()
                runItem(idx)
              } else if (e.key === "Escape") {
                e.preventDefault()
                onClose()
              }
            }}
          />
          <span className="p-kbd">ESC</span>
        </div>

        <div className="palette-list" ref={listRef}>
          {filtered.map((c, i) => (
            <button
              key={c.id}
              type="button"
              className={`p-item ${i === idx ? "sel" : ""}`}
              onMouseDown={(e) => {
                e.preventDefault()
                runItem(i)
              }}
              onMouseEnter={() => setIdx(i)}
            >
              <span className="p-ic">›</span>
              <span className="p-main">
                <strong>{c.label}</strong>
                <span>{c.desc}</span>
              </span>
              <span className="p-kbd">{c.kbd}</span>
            </button>
          ))}

          {!filtered.length && (
            <div
              className="small"
              style={{ padding: "12px", color: "var(--fg-dim)" }}
            >
              {t("palette.empty")}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

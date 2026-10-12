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
      role="dialog"
      aria-modal="true"
      aria-label={t("palette.label")}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: "10vh",
        background: "oklch(18% 0.01 250 / .38)",
        backdropFilter: "blur(2px)",
      }}
    >
      <div className="zf-panel" style={{ width: "min(640px, calc(100vw - 32px))", maxHeight: "min(70vh, 560px)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" style={{ flex: "none", color: "var(--muted)" }}>
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
            className="zf-input"
            style={{ flex: 1, border: 0, background: "transparent", padding: 0, height: "auto", boxShadow: "none" }}
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
          <kbd style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--muted)", border: "1px solid var(--border)", borderRadius: "4px", padding: "2px 6px" }}>ESC</kbd>
        </div>

        <div ref={listRef} style={{ overflowY: "auto", padding: "8px" }}>
          {filtered.map((c, i) => (
            <button
              key={c.id}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                runItem(i)
              }}
              onMouseEnter={() => setIdx(i)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "12px",
                width: "100%",
                textAlign: "left",
                padding: "8px 10px",
                borderRadius: "var(--radius)",
                border: "1px solid transparent",
                background: i === idx ? "var(--sel-bg)" : "transparent",
                boxShadow: i === idx ? "inset 2px 0 0 var(--accent)" : "none",
              }}
            >
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent)", width: "14px", textAlign: "center" }}>›</span>
              <span style={{ display: "flex", flexDirection: "column", gap: "2px", minWidth: 0, flex: 1 }}>
                <strong style={{ fontSize: "14px", fontWeight: 550 }}>{c.label}</strong>
                <span className="zf-micro zf-muted" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.desc}</span>
              </span>
              <kbd style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--muted)", border: "1px solid var(--border)", borderRadius: "4px", padding: "2px 6px", flex: "none" }}>{c.kbd}</kbd>
            </button>
          ))}

          {!filtered.length && (
            <div className="zf-micro zf-muted" style={{ padding: "12px" }}>
              {t("palette.empty")}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from "react"
import { useNavigate, useLocation } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { api, ChatConversationSummary } from "@/lib/api"
import { SideFlyout, FlyoutData } from "./SideFlyout"

const COLLAPSE_KEY = "zfrog-sidebar-collapsed"

interface ShellSidebarProps {
  theme: "light" | "dark"
  onOpenPalette: () => void
}

export function ShellSidebar({ theme, onOpenPalette }: ShellSidebarProps) {
  const navigate = useNavigate()
  const pathname = useLocation({ select: (l) => l.pathname })

  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1"
    } catch {
      return false
    }
  })

  const [flyoutData, setFlyoutData] = useState<FlyoutData | null>(null)
  const hideTimerRef = useRef<number | null>(null)

  // Toggle collapse and persist
  const toggleCollapse = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0")
      } catch {
        /* ignore */
      }
      return next
    })
    setFlyoutData(null)
  }

  // Keyboard shortcut "["
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const isInput =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        target?.isContentEditable
      if (e.key === "[" && !e.metaKey && !e.ctrlKey && !e.altKey && !isInput) {
        e.preventDefault()
        toggleCollapse()
      } else if (e.key === "Escape") {
        setFlyoutData(null)
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [])

  // Window resize cancels flyout
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth <= 700) setFlyoutData(null)
    }
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])

  // Fetch real chat conversations
  const convsQuery = useQuery({
    queryKey: ["chat-conversations"],
    queryFn: () => api.getChatConversations(),
  })

  const conversations = convsQuery.data ?? []

  // Handle flyout triggers
  const showFlyout = (
    el: HTMLElement,
    item: { label: string; title: string; sub?: string; kbd?: string; meta?: string }
  ) => {
    if (!collapsed || window.innerWidth <= 700) return
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
    const rect = el.getBoundingClientRect()
    setFlyoutData({
      ...item,
      rect,
    })
  }

  const scheduleHideFlyout = () => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
    hideTimerRef.current = window.setTimeout(() => {
      setFlyoutData(null)
    }, 90)
  }

  const cancelHideFlyout = () => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
  }

  const handleNewChat = () => {
    window.dispatchEvent(new CustomEvent("zfrog:new-chat"))
    if (pathname !== "/chat") {
      navigate({ to: "/chat" }).catch(() => {})
    }
  }

  const handleOpenConv = (conv: ChatConversationSummary) => {
    window.dispatchEvent(
      new CustomEvent("zfrog:open-conv", { detail: { id: conv.id } })
    )
    if (pathname !== "/chat") {
      navigate({ to: "/chat" }).catch(() => {})
    }
  }

  const handleQuickCommand = (prompt: string) => {
    window.dispatchEvent(
      new CustomEvent("zfrog:insert-prompt", { detail: { text: prompt } })
    )
    if (pathname !== "/chat") {
      navigate({ to: "/chat" }).catch(() => {})
    }
  }

  return (
    <>
      <aside
        id="sidebar"
        className={`zf-sidebar ${collapsed ? "collapsed" : ""}`}
        aria-label="Barra lateral"
      >
        <div className="zf-side-scroll" id="sideScroll">
          <div className="zf-collapse-row">
            <span
              className="zf-collapse-title"
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "11px",
                letterSpacing: ".06em",
                textTransform: "uppercase",
                color: "var(--fg-muted)",
              }}
            >
              Navegação
            </span>
            <button
              type="button"
              className="zf-collapse-btn"
              onClick={toggleCollapse}
              aria-label={collapsed ? "Expandir barra lateral" : "Recolher barra lateral"}
              aria-controls="sidebar"
              aria-expanded={!collapsed}
              title={collapsed ? "Expandir ( [ )" : "Recolher ( [ )"}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
              >
                {collapsed ? (
                  <path d="M9 18 15 12 9 6" />
                ) : (
                  <path d="M15 18 9 12 15 6" />
                )}
              </svg>
            </button>
          </div>

          <button
            type="button"
            className="zf-btn-primary"
            onClick={handleNewChat}
            title="Nova conversa"
            onMouseEnter={(e) =>
              showFlyout(e.currentTarget, {
                label: "Ação",
                title: "Nova conversa",
                sub: "Limpa o thread e inicia uma nova conversa. Histórico preservado.",
                kbd: "+",
                meta: "clique para criar",
              })
            }
            onMouseLeave={scheduleHideFlyout}
          >
            <span aria-hidden="true">+</span>
            <span className="zf-btn-label">Nova conversa</span>
          </button>

          <div>
            <div className="zf-side-label">
              <span>Histórico</span>
              <span
                style={{
                  color: "var(--fg-dim)",
                  fontSize: "11px",
                  textTransform: "none",
                  letterSpacing: 0,
                }}
              >
                {conversations.length} conversas
              </span>
            </div>

            <div className="zf-side-list">
              {conversations.slice(0, 8).map((c) => {
                const siteLabel = c.sites?.[0] || "Geral"
                const title = `Chat: ${siteLabel}`
                return (
                  <button
                    key={c.id}
                    type="button"
                    className="zf-side-item"
                    onClick={() => handleOpenConv(c)}
                    title={title}
                    onMouseEnter={(e) =>
                      showFlyout(e.currentTarget, {
                        label: "Histórico",
                        title,
                        sub: `${c.turns} turnos · ${siteLabel}`,
                        meta: "abrir conversa →",
                      })
                    }
                    onMouseLeave={scheduleHideFlyout}
                  >
                    <span className="zf-nav-dot" />
                    <span className="zf-side-icon">◫</span>
                    <span className="zf-t">{siteLabel}</span>
                    <span className="zf-count">{c.turns}</span>
                  </button>
                )
              })}

              {!conversations.length && (
                <div
                  className="small"
                  style={{
                    color: "var(--fg-dim)",
                    padding: "6px 8px",
                    fontFamily: "var(--font-mono)",
                    fontSize: "11px",
                  }}
                >
                  nenhuma salva
                </div>
              )}
            </div>
          </div>

          <div className="zf-divider" />

          <div>
            <div className="zf-side-label" style={{ marginTop: "2px" }}>
              Atalhos — iniciar
            </div>
            <div className="zf-side-list">
              <button
                type="button"
                className="zf-side-item"
                onClick={() => handleQuickCommand("/jump https://")}
                title="Inspecionar URL /jump"
                onMouseEnter={(e) =>
                  showFlyout(e.currentTarget, {
                    label: "Atalho",
                    title: "Inspecionar URL",
                    kbd: "/jump",
                    sub: "Screenshot + tokens + WCAG de qualquer URL.",
                    meta: "inserir no chat →",
                  })
                }
                onMouseLeave={scheduleHideFlyout}
              >
                <span className="zf-nav-dot" />
                <span className="zf-side-icon">↗</span>
                <span className="zf-t">Inspecionar URL</span>
                <span className="zf-d">/jump</span>
              </button>

              <button
                type="button"
                className="zf-side-item"
                onClick={() => handleQuickCommand("/comparar ")}
                title="Comparar sites /cmp"
                onMouseEnter={(e) =>
                  showFlyout(e.currentTarget, {
                    label: "Atalho",
                    title: "Comparar sites",
                    kbd: "/cmp",
                    sub: "Diff visual e de tokens entre dois domínios.",
                    meta: "inserir no chat →",
                  })
                }
                onMouseLeave={scheduleHideFlyout}
              >
                <span className="zf-nav-dot" />
                <span className="zf-side-icon">⇄</span>
                <span className="zf-t">Comparar sites</span>
                <span className="zf-d">/cmp</span>
              </button>

              <button
                type="button"
                className="zf-side-item"
                onClick={() => handleQuickCommand("/busca ")}
                title="Busca /busca"
                onMouseEnter={(e) =>
                  showFlyout(e.currentTarget, {
                    label: "Atalho",
                    title: "Busca semântica",
                    kbd: "/busca",
                    sub: "Busca fulltext e vetorial no acervo.",
                    meta: "inserir no chat →",
                  })
                }
                onMouseLeave={scheduleHideFlyout}
              >
                <span className="zf-nav-dot" />
                <span className="zf-side-icon">⌕</span>
                <span className="zf-t">Busca</span>
                <span className="zf-d">/busca</span>
              </button>
            </div>
          </div>
        </div>

        <div className="zf-side-foot">
          <div
            className="zf-side-foot-meta row small"
            style={{
              justifyContent: "space-between",
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              color: "var(--fg-dim)",
            }}
          >
            <span>pt-BR</span>
            <span>·</span>
            <span>{theme === "dark" ? "escuro" : "claro"}</span>
            <span>·</span>
            <span>100% local</span>
          </div>

          <button
            type="button"
            className="zf-btn-ghost"
            style={{ width: "100%" }}
            onClick={onOpenPalette}
            title="Paleta — 27 rotas (⌘K)"
            aria-label="Paleta — 27 rotas (⌘K)"
            onMouseEnter={(e) =>
              showFlyout(e.currentTarget, {
                label: "Paleta",
                title: "Paleta — 27 rotas",
                kbd: "⌘ K",
                sub: "Busca global por rota ou comando.",
                meta: "abrir paleta →",
              })
            }
            onMouseLeave={scheduleHideFlyout}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
            >
              <path d="M21 21 16 16" />
              <circle cx="11" cy="11" r="6" />
            </svg>
            <span className="zf-btn-ghost-label">Paleta — 27 rotas</span>
          </button>
        </div>
      </aside>

      <SideFlyout
        data={flyoutData}
        onMouseEnter={cancelHideFlyout}
        onMouseLeave={scheduleHideFlyout}
      />
    </>
  )
}

import { useEffect, useRef, useState } from "react"
import { Link, useLocation, useNavigate } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { api, ChatConversationSummary } from "@/lib/api"
import { SideFlyout, FlyoutData } from "./SideFlyout"

interface ShellSidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
  onOpenPalette: () => void
}

export function ShellSidebar({ collapsed, onToggleCollapsed, onOpenPalette }: ShellSidebarProps) {
  const navigate = useNavigate()
  const pathname = useLocation({ select: (l) => l.pathname })

  const [flyoutData, setFlyoutData] = useState<FlyoutData | null>(null)
  const hideTimerRef = useRef<number | null>(null)

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth <= 700) setFlyoutData(null)
    }
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  }, [])

  const convsQuery = useQuery({
    queryKey: ["chat-conversations"],
    queryFn: () => api.getChatConversations(),
  })

  const conversations = convsQuery.data ?? []

  const showFlyout = (
    el: HTMLElement,
    item: { label: string; title: string; sub?: string; kbd?: string; meta?: string }
  ) => {
    if (!collapsed || window.innerWidth <= 700) return
    clearTimeout(hideTimerRef.current as unknown as number)
    const rect = el.getBoundingClientRect()
    setFlyoutData({
      ...item,
      rect,
    })
  }

  const scheduleHideFlyout = () => {
    clearTimeout(hideTimerRef.current as unknown as number)
    hideTimerRef.current = window.setTimeout(() => {
      setFlyoutData(null)
    }, 90)
  }

  const cancelHideFlyout = () => {
    clearTimeout(hideTimerRef.current as unknown as number)
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

  // keep references to preserve original handlers for flyout context
  void conversations
  void handleOpenConv
  void handleQuickCommand
  void handleNewChat
  void onOpenPalette

  const isActive = (to: string) => {
    if (to === "/") return pathname === "/"
    return pathname === to || pathname.startsWith(to + "/")
  }

  return (
    <>
      <nav className="zf-rail" aria-label={pathname.startsWith("/chat") ? "Chat" : pathname === "/" || ["/probe","/captura","/workers","/fluxos","/qualidade","/revisao","/timeline","/jobs"].some(p=>pathname.startsWith(p)) ? "Operação" : "Navegação"}>
        <div className="zf-rail-group">
          <button
            type="button"
            className="zf-rail-item"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expandir barra lateral" : "Recolher barra lateral"}
            aria-expanded={!collapsed}
            title={collapsed ? "Expandir ( [ )" : "Recolher ( [ )"}
            onMouseEnter={(e) =>
              showFlyout(e.currentTarget, {
                label: "Barra lateral",
                title: collapsed ? "Expandir" : "Recolher",
                kbd: "[",
                sub: collapsed ? "Mostrar rótulos da barra lateral." : "Recolher para ícones apenas.",
                meta: "alternar →",
              })
            }
            onMouseLeave={scheduleHideFlyout}
          >
            <span className="zf-glyph">{collapsed ? "›" : "‹"}</span>
            <span>{collapsed ? "Expandir" : "Recolher"} [</span>
          </button>
        </div>

        <div className="zf-rail-group">
          <div className="zf-micro zf-rail-label">Operação</div>
          <Link to="/" className="zf-rail-item" aria-current={isActive("/") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Jobs",kbd:"▣",sub:"Fila e histórico de execuções.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">▣</span><span>Jobs</span>
          </Link>
          <Link to="/probe" className="zf-rail-item" aria-current={isActive("/probe") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Probe",kbd:"⌖",sub:"Inspeção e detecção.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">⌖</span><span>Probe</span>
          </Link>
          <Link to="/captura" className="zf-rail-item" aria-current={isActive("/captura") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Captura",kbd:"⬢",sub:"Captura de páginas.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">⬢</span><span>Captura</span>
          </Link>
          <Link to="/workers" className="zf-rail-item" aria-current={isActive("/workers") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Workers",kbd:"◈",sub:"Pool de workers.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">◈</span><span>Workers</span>
          </Link>
          <Link to="/fluxos" className="zf-rail-item" aria-current={isActive("/fluxos") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Fluxos",kbd:"⧉",sub:"Orquestração de fluxos.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">⧉</span><span>Fluxos</span>
          </Link>
          <Link to="/qualidade" className="zf-rail-item" aria-current={isActive("/qualidade") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Qualidade",kbd:"◎",sub:"Checks de qualidade.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">◎</span><span>Qualidade</span>
          </Link>
          <Link to="/revisao" className="zf-rail-item" aria-current={isActive("/revisao") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Revisão",kbd:"✎",sub:"Fila de revisão humana.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">✎</span><span>Revisão</span>
          </Link>
          <Link to="/timeline" className="zf-rail-item" aria-current={isActive("/timeline") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Operação",title:"Timeline",kbd:"◷",sub:"Linha do tempo.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">◷</span><span>Timeline</span>
          </Link>
        </div>

        <div className="zf-rail-group">
          <div className="zf-micro zf-rail-label">Biblioteca</div>
          <Link to="/colecao" className="zf-rail-item" aria-current={isActive("/colecao") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Biblioteca",title:"Coleção",kbd:"▤",sub:"Acervo curado.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">▤</span><span>Coleção</span>
          </Link>
          <Link to="/busca" className="zf-rail-item" aria-current={isActive("/busca") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Biblioteca",title:"Busca",kbd:"⌕",sub:"Busca semântica e fulltext.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">⌕</span><span>Busca</span>
          </Link>
          <Link to="/datasets" className="zf-rail-item" aria-current={isActive("/datasets") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Biblioteca",title:"Datasets",kbd:"◇",sub:"Conjuntos de dados.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">◇</span><span>Datasets</span>
          </Link>
          <Link to="/grafo" className="zf-rail-item" aria-current={isActive("/grafo") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Biblioteca",title:"Grafo",kbd:"⬡",sub:"Grafo de conhecimento.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">⬡</span><span>Grafo</span>
          </Link>
          <Link to="/precos" className="zf-rail-item" aria-current={isActive("/precos") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Biblioteca",title:"Preços",kbd:"◐",sub:"Monitor de preços.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">◐</span><span>Preços</span>
          </Link>
          <Link to="/snapshots" className="zf-rail-item" aria-current={isActive("/snapshots") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Biblioteca",title:"Snapshots",kbd:"◫",sub:"Snapshots do acervo.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">◫</span><span>Snapshots</span>
          </Link>
        </div>

        <div className="zf-rail-group" style={{ marginTop: "auto" }}>
          <Link to="/stats" className="zf-rail-item" aria-current={isActive("/stats") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Outros",title:"Stats",kbd:"◫",sub:"Métricas do sistema.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">◫</span><span>Stats</span>
          </Link>
          <Link to="/ajuda" className="zf-rail-item" aria-current={isActive("/ajuda") ? "page" : undefined} onMouseEnter={(e)=>showFlyout(e.currentTarget,{label:"Outros",title:"Voltar ao índice",kbd:"≡",sub:"Ajuda e índice de rotas.",meta:"abrir →"})} onMouseLeave={scheduleHideFlyout}>
            <span className="zf-glyph">≡</span><span>Voltar ao índice</span>
          </Link>
        </div>
      </nav>

      <SideFlyout
        data={flyoutData}
        onMouseEnter={cancelHideFlyout}
        onMouseLeave={scheduleHideFlyout}
      />
    </>
  )
}

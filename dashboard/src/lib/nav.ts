import type { IconName } from "./icons"

/**
 * The navigation of the panel: the 20 routes of the product, grouped.
 *
 * Kept in one place because four surfaces read it — the sidebar, the mobile
 * bottom bar, the mobile sheet and the command palette — and the design system
 * defines the group order and labels.
 */
export type NavGroup = "trabalho" | "referencias" | "gerenciar" | "integracoes"

export interface NavItem {
  href: string
  label: string
  title: string
  icon: IconName
  group: NavGroup
  /** Shown in the sidebar; hidden items only exist for the palette. */
  hidden?: boolean
}

export const NAV_GROUP_ORDER: NavGroup[] = ["trabalho", "referencias", "gerenciar", "integracoes"]

export const NAV_GROUP_LABEL: Record<NavGroup, string> = {
  trabalho: "Trabalho",
  referencias: "Referências",
  gerenciar: "Gerenciar",
  integracoes: "Integrações",
}

export const NAV: NavItem[] = [
  { href: "/", label: "Execuções", title: "Tudo que você já baixou", icon: "i-dashboard", group: "trabalho" },
  { href: "/probe", label: "Nova extração", title: "Baixar um site ou extrair dados", icon: "i-download", group: "trabalho" },
  { href: "/busca", label: "Busca", title: "Buscar no conteúdo baixado", icon: "i-search", group: "trabalho" },
  { href: "/fluxos", label: "Fluxos", title: "Sequências de passos automáticas", icon: "i-repeat", group: "trabalho" },
  { href: "/captura", label: "Captura", title: "Escolher o que pegar na página", icon: "i-target", group: "trabalho" },
  { href: "/snapshots", label: "Histórico", title: "Versões guardadas e o que mudou", icon: "i-history", group: "referencias" },
  { href: "/timeline", label: "Máquina do tempo", title: "Ver um site em uma data passada", icon: "i-calendar", group: "referencias" },
  { href: "/revisao", label: "Revisão", title: "Comentários e anotações nas cópias", icon: "i-message", group: "referencias" },
  { href: "/jobs/[id]", label: "Detalhe da execução", title: "Acompanhe o progresso em tempo real", icon: "i-eye", group: "gerenciar", hidden: true },
  { href: "/stats", label: "Estatísticas", title: "Números do sistema", icon: "i-stats", group: "gerenciar" },
  { href: "/analytics", label: "Analytics", title: "Desempenho por motor de captura", icon: "i-activity", group: "gerenciar" },
  { href: "/roi", label: "ROI", title: "Economia do trabalho automatizado", icon: "i-scale", group: "gerenciar" },
  { href: "/workers", label: "Workers", title: "Máquinas que processam as execuções", icon: "i-server", group: "gerenciar" },
  { href: "/qualidade", label: "Qualidade", title: "PII e riscos de segurança", icon: "i-shield", group: "gerenciar" },
  { href: "/config", label: "Configurações", title: "Velocidade, limites e aparência", icon: "i-settings", group: "gerenciar" },
  { href: "/webhooks", label: "Webhooks", title: "Avisos para outros sistemas", icon: "i-webhook", group: "integracoes" },
  { href: "/equipe", label: "Equipe", title: "Usuários e organizações", icon: "i-users", group: "integracoes" },
  { href: "/marketplace", label: "Marketplace", title: "Fluxos e plugins prontos", icon: "i-store", group: "integracoes" },
  { href: "/ajuda", label: "Ajuda", title: "Como usar e qual modo escolher", icon: "i-help", group: "integracoes" },
  { href: "/design", label: "Design system", title: "Tokens e componentes do zfrog", icon: "i-palette", group: "integracoes" },
]

/** Sidebar and sheet items: everything that has a place in the navigation. */
export const NAV_VISIBLE = NAV.filter((item) => !item.hidden)

/** Title and subtitle each route shows in the topbar. */
export const ROUTE_TITLES: Record<string, [string, string]> = {
  "/": ["Execuções", "Tudo que você já baixou"],
  "/probe": ["Nova extração", "Baixar um site ou extrair dados"],
  "/snapshots": ["Histórico", "Versões guardadas e o que mudou"],
  "/stats": ["Estatísticas", "Números do sistema"],
  "/config": ["Configurações", "Velocidade, limites e aparência"],
  "/ajuda": ["Ajuda", "Como usar e qual modo escolher"],
  "/analytics": ["Analytics", "Desempenho por motor de captura"],
  "/timeline": ["Máquina do tempo", "Veja o site como era em uma data"],
  "/busca": ["Busca", "Full-text e semântica no que foi baixado"],
  "/fluxos": ["Fluxos", "Sequências de passos automáticas"],
  "/revisao": ["Revisão", "Comentários e anotações nas cópias"],
  "/marketplace": ["Marketplace", "Fluxos e plugins prontos para usar"],
  "/qualidade": ["Qualidade", "PII e riscos de segurança"],
  "/webhooks": ["Webhooks", "Avisos para outros sistemas"],
  "/equipe": ["Equipe", "Usuários e organizações"],
  "/workers": ["Workers", "Máquinas que processam e regiões"],
  "/roi": ["ROI", "Economia do trabalho automatizado"],
  "/captura": ["Captura", "Escolher o que pegar na página"],
  "/design": ["Design system", "Fundamentos visuais do zfrog"],
}

/** The bottom bar on phones: the first four items plus the "more" sheet. */
export const BOTTOM_NAV = NAV_VISIBLE.slice(0, 4)
export const SHEET_NAV = NAV_VISIBLE.slice(3)

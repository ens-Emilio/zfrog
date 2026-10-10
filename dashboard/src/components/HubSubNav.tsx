import { Link, useLocation } from "@tanstack/react-router"
import { useT } from "@/lib/i18n"

export function HubSubNav() {
  const t = useT()
  const pathname = useLocation({ select: (l) => l.pathname })

  const isBiblioteca = [
    "/colecao",
    "/busca",
    "/datasets",
    "/grafo",
    "/precos",
    "/snapshots",
  ].some((p) => pathname.startsWith(p))

  const isOperacao = [
    "/probe",
    "/captura",
    "/workers",
    "/fluxos",
    "/qualidade",
    "/revisao",
    "/timeline",
    "/jobs",
  ].some((p) => pathname.startsWith(p)) || pathname === "/"

  const isOther = [
    "/stats",
    "/analytics",
    "/roi",
    "/webhooks",
    "/equipe",
    "/marketplace",
    "/graphql",
    "/config",
    "/ajuda",
    "/design",
  ].some((p) => pathname.startsWith(p))

  if (pathname === "/chat") return null

  if (isBiblioteca) {
    return (
      <nav className="zf-subnav" aria-label="Biblioteca">
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            color: "var(--fg-dim)",
            textTransform: "uppercase",
            letterSpacing: ".05em",
            marginRight: "4px",
          }}
        >
          Biblioteca ›
        </span>
        <Link
          to="/colecao"
          className={`zf-subnav-pill ${pathname === "/colecao" ? "active" : ""}`}
        >
          {t("nav.collection")}
        </Link>
        <Link
          to="/busca"
          className={`zf-subnav-pill ${pathname === "/busca" ? "active" : ""}`}
        >
          {t("nav.search")}
        </Link>
        <Link
          to="/datasets"
          className={`zf-subnav-pill ${pathname === "/datasets" ? "active" : ""}`}
        >
          {t("nav.datasets")}
        </Link>
        <Link
          to="/grafo"
          className={`zf-subnav-pill ${pathname === "/grafo" ? "active" : ""}`}
        >
          {t("nav.graph")}
        </Link>
        <Link
          to="/precos"
          className={`zf-subnav-pill ${pathname === "/precos" ? "active" : ""}`}
        >
          {t("nav.prices")}
        </Link>
        <Link
          to="/snapshots"
          className={`zf-subnav-pill ${pathname === "/snapshots" ? "active" : ""}`}
        >
          Snapshots
        </Link>
      </nav>
    )
  }

  if (isOperacao) {
    return (
      <nav className="zf-subnav" aria-label="Operação">
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            color: "var(--fg-dim)",
            textTransform: "uppercase",
            letterSpacing: ".05em",
            marginRight: "4px",
          }}
        >
          Operação ›
        </span>
        <Link
          to="/"
          className={`zf-subnav-pill ${pathname === "/" ? "active" : ""}`}
        >
          {t("nav.runs")}
        </Link>
        <Link
          to="/probe"
          className={`zf-subnav-pill ${pathname === "/probe" ? "active" : ""}`}
        >
          {t("nav.extract")}
        </Link>
        <Link
          to="/captura"
          className={`zf-subnav-pill ${pathname === "/captura" ? "active" : ""}`}
        >
          Captura
        </Link>
        <Link
          to="/workers"
          className={`zf-subnav-pill ${pathname === "/workers" ? "active" : ""}`}
        >
          Workers
        </Link>
        <Link
          to="/fluxos"
          className={`zf-subnav-pill ${pathname === "/fluxos" ? "active" : ""}`}
        >
          Fluxos
        </Link>
        <Link
          to="/qualidade"
          className={`zf-subnav-pill ${pathname === "/qualidade" ? "active" : ""}`}
        >
          Qualidade
        </Link>
        <Link
          to="/revisao"
          className={`zf-subnav-pill ${pathname === "/revisao" ? "active" : ""}`}
        >
          Revisão
        </Link>
        <Link
          to="/timeline"
          className={`zf-subnav-pill ${pathname === "/timeline" ? "active" : ""}`}
        >
          Timeline
        </Link>
      </nav>
    )
  }

  if (isOther) {
    return (
      <nav className="zf-subnav" aria-label="Navegação secundária">
        <Link
          to="/chat"
          className="zf-subnav-pill"
          style={{ color: "var(--accent)", fontWeight: 500 }}
        >
          ← Voltar ao chat
        </Link>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            color: "var(--fg-dim)",
            margin: "0 6px",
          }}
        >
          |
        </span>
        <Link
          to="/config"
          className={`zf-subnav-pill ${pathname === "/config" ? "active" : ""}`}
        >
          {t("nav.config")}
        </Link>
        <Link
          to="/stats"
          className={`zf-subnav-pill ${pathname === "/stats" ? "active" : ""}`}
        >
          Stats
        </Link>
        <Link
          to="/analytics"
          className={`zf-subnav-pill ${pathname === "/analytics" ? "active" : ""}`}
        >
          Analytics
        </Link>
        <Link
          to="/roi"
          className={`zf-subnav-pill ${pathname === "/roi" ? "active" : ""}`}
        >
          ROI
        </Link>
        <Link
          to="/webhooks"
          className={`zf-subnav-pill ${pathname === "/webhooks" ? "active" : ""}`}
        >
          Webhooks
        </Link>
        <Link
          to="/equipe"
          className={`zf-subnav-pill ${pathname === "/equipe" ? "active" : ""}`}
        >
          Equipe
        </Link>
        <Link
          to="/marketplace"
          className={`zf-subnav-pill ${pathname === "/marketplace" ? "active" : ""}`}
        >
          Marketplace
        </Link>
        <Link
          to="/graphql"
          className={`zf-subnav-pill ${pathname === "/graphql" ? "active" : ""}`}
        >
          {t("nav.graphql")}
        </Link>
        <Link
          to="/design"
          className={`zf-subnav-pill ${pathname === "/design" ? "active" : ""}`}
        >
          Design System
        </Link>
      </nav>
    )
  }

  return null
}

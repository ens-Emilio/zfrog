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
        <span className="zf-micro zf-muted" style={{ textTransform: "uppercase", letterSpacing: ".05em", marginRight: "4px" }}>
          Biblioteca ›
        </span>
        <Link
          to="/colecao"
          className={`zf-pill ${pathname === "/colecao" ? "is-active" : ""}`}
        >
          {t("nav.collection")}
        </Link>
        <Link
          to="/busca"
          className={`zf-pill ${pathname === "/busca" ? "is-active" : ""}`}
        >
          {t("nav.search")}
        </Link>
        <Link
          to="/datasets"
          className={`zf-pill ${pathname === "/datasets" ? "is-active" : ""}`}
        >
          {t("nav.datasets")}
        </Link>
        <Link
          to="/grafo"
          className={`zf-pill ${pathname === "/grafo" ? "is-active" : ""}`}
        >
          {t("nav.graph")}
        </Link>
        <Link
          to="/precos"
          className={`zf-pill ${pathname === "/precos" ? "is-active" : ""}`}
        >
          {t("nav.prices")}
        </Link>
        <Link
          to="/snapshots"
          className={`zf-pill ${pathname === "/snapshots" ? "is-active" : ""}`}
        >
          Snapshots
        </Link>
      </nav>
    )
  }

  if (isOperacao) {
    return (
      <nav className="zf-subnav" aria-label="Operação">
        <span className="zf-micro zf-muted" style={{ textTransform: "uppercase", letterSpacing: ".05em", marginRight: "4px" }}>
          Operação ›
        </span>
        <Link
          to="/"
          className={`zf-pill ${pathname === "/" ? "is-active" : ""}`}
        >
          {t("nav.runs")}
        </Link>
        <Link
          to="/probe"
          className={`zf-pill ${pathname === "/probe" ? "is-active" : ""}`}
        >
          {t("nav.extract")}
        </Link>
        <Link
          to="/captura"
          className={`zf-pill ${pathname === "/captura" ? "is-active" : ""}`}
        >
          Captura
        </Link>
        <Link
          to="/workers"
          className={`zf-pill ${pathname === "/workers" ? "is-active" : ""}`}
        >
          Workers
        </Link>
        <Link
          to="/fluxos"
          className={`zf-pill ${pathname === "/fluxos" ? "is-active" : ""}`}
        >
          Fluxos
        </Link>
        <Link
          to="/qualidade"
          className={`zf-pill ${pathname === "/qualidade" ? "is-active" : ""}`}
        >
          Qualidade
        </Link>
        <Link
          to="/revisao"
          className={`zf-pill ${pathname === "/revisao" ? "is-active" : ""}`}
        >
          Revisão
        </Link>
        <Link
          to="/timeline"
          className={`zf-pill ${pathname === "/timeline" ? "is-active" : ""}`}
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
          className="zf-pill"
          style={{ color: "var(--accent)", fontWeight: 500 }}
        >
          ← Voltar ao chat
        </Link>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            color: "var(--muted)",
            margin: "0 6px",
          }}
        >
          |
        </span>
        <Link
          to="/config"
          className={`zf-pill ${pathname === "/config" ? "is-active" : ""}`}
        >
          {t("nav.config")}
        </Link>
        <Link
          to="/stats"
          className={`zf-pill ${pathname === "/stats" ? "is-active" : ""}`}
        >
          Stats
        </Link>
        <Link
          to="/analytics"
          className={`zf-pill ${pathname === "/analytics" ? "is-active" : ""}`}
        >
          Analytics
        </Link>
        <Link
          to="/roi"
          className={`zf-pill ${pathname === "/roi" ? "is-active" : ""}`}
        >
          ROI
        </Link>
        <Link
          to="/webhooks"
          className={`zf-pill ${pathname === "/webhooks" ? "is-active" : ""}`}
        >
          Webhooks
        </Link>
        <Link
          to="/equipe"
          className={`zf-pill ${pathname === "/equipe" ? "is-active" : ""}`}
        >
          Equipe
        </Link>
        <Link
          to="/marketplace"
          className={`zf-pill ${pathname === "/marketplace" ? "is-active" : ""}`}
        >
          Marketplace
        </Link>
        <Link
          to="/graphql"
          className={`zf-pill ${pathname === "/graphql" ? "is-active" : ""}`}
        >
          {t("nav.graphql")}
        </Link>
        <Link
          to="/design"
          className={`zf-pill ${pathname === "/design" ? "is-active" : ""}`}
        >
          Design System
        </Link>
      </nav>
    )
  }

  return null
}

import { Link, useLocation } from "@tanstack/react-router"
import { useT } from "@/lib/i18n"

interface ShellHeaderProps {
  apiOk: boolean
  workerOk: boolean
  redisOk: boolean
  theme: "light" | "dark"
  onToggleTheme: () => void
  onOpenPalette: () => void
}

export function ShellHeader({
  apiOk,
  workerOk,
  redisOk,
  theme,
  onToggleTheme,
  onOpenPalette,
}: ShellHeaderProps) {
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

  const isChat = pathname === "/chat" || (!isBiblioteca && !isOperacao && pathname === "/chat")

  return (
    <header className="zf-topbar" data-od-id="topbar">
      <div className="zf-brand" data-od-id="brand">
        <div className="zf-brand-mark">▦</div>
        <span className="zf-brand-name">zfrog</span>
        <span className="zf-micro" style={{ marginLeft: "6px", opacity: .7 }}>
          dashboard
        </span>
      </div>

      <nav className="zf-hubs" aria-label={t("a11y.sections")}>
        <Link
          to="/colecao"
          className={`zf-pill ${isBiblioteca ? "is-active" : ""}`}
          aria-current={isBiblioteca ? "page" : undefined}
        >
          {t("nav.collection")}
        </Link>
        <Link
          to="/"
          className={`zf-pill ${isOperacao && !isChat ? "is-active" : ""}`}
          aria-current={isOperacao && !isChat ? "page" : undefined}
        >
          {t("nav.runs")}
        </Link>
        <Link
          to="/chat"
          className={`zf-pill ${isChat ? "is-active" : ""}`}
          aria-current={isChat ? "page" : undefined}
        >
          {t("nav.chat")}
        </Link>
      </nav>

      <div className="zf-tools">
        <span className="zf-svc">
          <i className={`zf-dot ${apiOk ? "" : "zf-dot--err"}`} /> api
        </span>
        <span className="zf-svc">
          <i className={`zf-dot ${workerOk ? "" : "zf-dot--idle"}`} /> worker
        </span>
        <span className="zf-svc">
          <i className={`zf-dot ${redisOk ? "" : "zf-dot--idle"}`} /> redis
        </span>

        <button
          type="button"
          className="zf-btn zf-btn--ghost"
          style={{ height: "30px", paddingInline: "10px" }}
          onClick={onOpenPalette}
          aria-label={t("palette.label")}
        >
          ⌘K
        </button>

        <button
          type="button"
          className="zf-icon-btn"
          onClick={onToggleTheme}
          aria-label={t("nav.theme")}
          title={`Tema: ${theme}`}
        >
          ◐
        </button>

        <Link
          to="/ajuda"
          className="zf-icon-btn"
          aria-label={t("nav.help")}
          title={t("nav.help")}
          style={{ display: "grid", placeItems: "center" }}
        >
          ◎
        </Link>
      </div>
    </header>
  )
}

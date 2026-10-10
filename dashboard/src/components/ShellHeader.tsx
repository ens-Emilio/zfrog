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
        <span className="zf-brand-mark">zf</span>
        <span>zfrog</span>

        <nav className="zf-topbar-nav" role="tablist" aria-label={t("a11y.sections")}>
          <Link
            to="/chat"
            className={`zf-nav-pill ${isChat ? "active" : ""}`}
            role="tab"
            aria-selected={isChat}
          >
            {t("nav.chat")}
          </Link>
          <Link
            to="/colecao"
            className={`zf-nav-pill ${isBiblioteca ? "active" : ""}`}
            role="tab"
            aria-selected={isBiblioteca}
          >
            {t("nav.collection")}
          </Link>
          <Link
            to="/"
            search={{ view: "runs" }}
            className={`zf-nav-pill ${isOperacao && !isChat ? "active" : ""}`}
            role="tab"
            aria-selected={isOperacao && !isChat}
          >
            {t("nav.runs")}
          </Link>
        </nav>
      </div>

      <div className="zf-topbar-right">
        <span
          className="zf-meta"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            display: "inline-flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <i className={`zf-dot ${apiOk ? "ok" : "err"}`} /> API
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <i className={`zf-dot ${workerOk ? "ok" : "warn"}`} /> worker
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <i className={`zf-dot ${redisOk ? "ok" : "off"}`} /> redis
          </span>
        </span>

        <button
          type="button"
          className="zf-kbd-hint"
          onClick={onOpenPalette}
          style={{ cursor: "pointer", border: "1px solid var(--line)" }}
          aria-label={t("palette.label")}
        >
          <span>⌘</span>
          <span>K</span>
          <span style={{ color: "var(--fg-dim)" }}>· paleta</span>
        </button>

        <button
          type="button"
          className="zf-icon-btn"
          onClick={onToggleTheme}
          aria-label={t("nav.theme")}
          title={`Tema: ${theme}`}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
          >
            <path d="M12 3a6 6 0 0 0 9 9c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9Z" />
          </svg>
        </button>

        <Link
          to="/ajuda"
          className="zf-icon-btn"
          aria-label={t("nav.help")}
          title={t("nav.help")}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
          >
            <circle cx="12" cy="12" r="9" />
            <path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.8-2.5 2-2.5 4" />
            <path d="M12 17h.01" />
          </svg>
        </Link>
      </div>
    </header>
  )
}

"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"
import { BrandMark } from "@/components/BrandMark"
import { Icon } from "@/lib/icons"
import { BOTTOM_NAV, NAV_GROUP_LABEL, NAV_GROUP_ORDER, NAV_VISIBLE, SHEET_NAV } from "@/lib/nav"
import { useTheme } from "@/lib/prefs"
import { api } from "@/lib/api"
import { clearApiKey } from "@/lib/auth"
import { MoreHorizontal, RefreshCw, Search, X } from "lucide-react"

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/"
  if (href === "/jobs/[id]") return pathname.startsWith("/jobs/")
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function Navbar() {
  const pathname = usePathname()
  const [theme, toggleTheme] = useTheme()
  const [sheetOpen, setSheetOpen] = useState(false)

  // A route change closes the sheet: leaving it open would hide the page the user
  // just asked for.
  useEffect(() => {
    setSheetOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!sheetOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSheetOpen(false)
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [sheetOpen])

  return (
    <>
      <aside className="sidebar" aria-label="Navegação principal">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <BrandMark className="ic ic-lg" />
          </span>
          <span>
            <span className="brand-name">zfrog</span>
            <span className="brand-sub">Capturar e adaptar referências</span>
          </span>
        </div>

        <nav className="nav" aria-label="Seções">
          {NAV_GROUP_ORDER.map((group) => {
            const items = NAV_VISIBLE.filter((item) => item.group === group)
            if (items.length === 0) return null
            return (
              <div key={group} className="contents">
                <span className="nav-label">{NAV_GROUP_LABEL[group]}</span>
                {items.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={item.title}
                    className="nav-item"
                    aria-current={isActive(pathname, item.href) ? "page" : undefined}
                  >
                    <Icon name={item.icon} />
                    <span>{item.label}</span>
                  </Link>
                ))}
              </div>
            )
          })}
        </nav>

        <div className="sidebar-foot">
          <button
            className="cmd-btn"
            type="button"
            aria-label="Abrir comandos rápidos"
            onClick={() => window.dispatchEvent(new CustomEvent("zfrog:palette"))}
          >
            <Search className="ic ic-sm" aria-hidden="true" />
            <span className="flex-1 text-left">Buscar ou comando</span>
            <span className="kbd">Ctrl K</span>
          </button>
          <button className="btn btn-ghost cmd-btn" type="button" onClick={toggleTheme} aria-label="Alternar tema">
            <Icon name={theme === "dark" ? "i-sun" : "i-moon"} />
            <span className="flex-1 text-left">{theme === "dark" ? "Tema claro" : "Tema escuro"}</span>
          </button>
          <Link className="cmd-btn" href="/design" style={{ textDecoration: "none" }}>
            <Icon name="i-palette" />
            <span className="flex-1 text-left">Design system</span>
          </Link>
          <ServerStatus />
          <SignOut />
        </div>
      </aside>

      <nav className="bottomnav" aria-label="Navegação principal (celular)">
        <div className="bottomnav-inner">
          {BOTTOM_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-label={item.label}
              aria-current={isActive(pathname, item.href) ? "page" : undefined}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </Link>
          ))}
          <button type="button" onClick={() => setSheetOpen(true)} aria-label="Mais opções">
            <MoreHorizontal className="ic" aria-hidden="true" />
            <span>Mais</span>
          </button>
        </div>
      </nav>

      {sheetOpen && (
        <div className="sheet-scrim" onClick={(event) => event.target === event.currentTarget && setSheetOpen(false)}>
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Mais seções">
            <span className="sheet-grip" aria-hidden="true" />
            {SHEET_NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="nav-item"
                aria-current={isActive(pathname, item.href) ? "page" : undefined}
              >
                <Icon name={item.icon} />
                <span>{item.label}</span>
              </Link>
            ))}
            <button className="nav-item" type="button" onClick={toggleTheme}>
              <Icon name={theme === "dark" ? "i-sun" : "i-moon"} />
              <span>{theme === "dark" ? "Tema claro" : "Tema escuro"}</span>
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => setSheetOpen(false)}>
              <X className="ic ic-sm" aria-hidden="true" /> Fechar
            </button>
          </div>
        </div>
      )}
    </>
  )
}

type Health = "checking" | "online" | "offline"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function ServerStatus() {
  const [health, setHealth] = useState<Health>("checking")
  const [checkedAt, setCheckedAt] = useState<number | null>(null)

  const ping = async () => {
    try {
      const res = await fetch(`${API_URL}/health`)
      setHealth(res.ok ? "online" : "offline")
    } catch {
      setHealth("offline")
    }
    setCheckedAt(Date.now())
  }

  useEffect(() => {
    ping()
    const id = setInterval(ping, 30000)
    return () => clearInterval(id)
  }, [])

  const label = { checking: "Verificando servidor…", online: "Servidor conectado", offline: "Servidor fora do ar" }[health]

  return (
    <div className="status-card">
      <div className="status-row">
        <span className={`status-dot ${health === "online" ? "online" : health === "offline" ? "offline" : ""}`} aria-hidden="true" />
        <span>{label}</span>
      </div>
      {health === "offline" ? (
        <p className="status-help">
          Inicie a API com <span className="mono">./zfrog dev</span> ou <span className="mono">./zfrog serve</span>.
        </p>
      ) : (
        <>
          <p className="status-help">
            API em <span className="mono">{API_URL.replace(/^https?:\/\//, "")}</span>
            {checkedAt !== null ? ` · verificado ${secondsAgo(checkedAt)}` : ""}
          </p>
          <button className="btn btn-ghost btn-sm" type="button" onClick={ping}>
            <RefreshCw className="ic ic-sm" aria-hidden="true" /> verificar de novo
          </button>
        </>
      )}
    </div>
  )
}

/** "há 12 s" style label the design system shows under the status dot. */
function secondsAgo(then: number) {
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return `há ${seconds} s`
  return `há ${Math.round(seconds / 60)} min`
}

/**
 * Signs out. Clears both credentials: the stored key and the server-side session
 * cookie, so a shared machine does not keep the next person logged in.
 *
 * Whether to show at all is decided by the server, not by localStorage: an SSO
 * login leaves no key behind, so keying off that would hide the button from
 * exactly the people who need it.
 */
function SignOut() {
  const [needed, setNeeded] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .getAuthConfig()
      .then((config) => {
        if (!cancelled) setNeeded(Boolean(config.auth_enabled))
      })
      .catch(() => {
        // Unreachable API: the status card above already says so.
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!needed) return null

  return (
    <button
      className="cmd-btn"
      type="button"
      onClick={async () => {
        clearApiKey()
        try {
          await api.logout()
        } catch {
          // The cookie may already be gone; the reload below is what matters.
        }
        window.location.reload()
      }}
    >
      <Icon name="i-x-circle" />
      <span className="flex-1 text-left">Sair</span>
    </button>
  )
}

/**
 * The page header. Rendered by each page so it can carry its own actions.
 *
 * The quick-command button and the theme toggle belong to the shell, not to any
 * one page, so they are always here; `action` adds whatever the route needs. The
 * topbar is full-bleed and sticky above the padded content area, the way the
 * design system shows it.
 */
export function Topbar({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  const [theme, toggleTheme] = useTheme()

  return (
    <header className="topbar topbar-inline">
      <div className="topbar-title">
        <h1 tabIndex={-1}>{title}</h1>
        {description && <span className="topbar-sub">{description}</span>}
      </div>
      <div className="topbar-actions">
        <button
          className="btn btn-ghost icon-btn"
          type="button"
          aria-label="Comandos rápidos"
          onClick={() => window.dispatchEvent(new CustomEvent("zfrog:palette"))}
        >
          <Search className="ic" aria-hidden="true" />
        </button>
        <button
          className="btn btn-ghost icon-btn mobile-only"
          type="button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"}
        >
          <Icon name={theme === "dark" ? "i-sun" : "i-moon"} />
        </button>
        {action}
      </div>
    </header>
  )
}

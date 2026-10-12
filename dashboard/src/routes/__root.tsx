import { useCallback, useEffect, useState } from "react"
import { Outlet, useLocation, createRootRoute } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { QueryClientProvider } from "@tanstack/react-query"
import "@fontsource/iosevka/400.css"
import "@fontsource/iosevka/500.css"
import "../styles/tui.css"
import "../styles/zfrog.css"
import { queryClient } from "@/lib/query-client"
import { AuthGate } from "@/components/AuthGate"
import { ToastRegion } from "@/components/ToastRegion"
import { API_URL, api } from "@/lib/api"
import { effectiveApiUrl, desktopHeaders, isDesktop, resolveDesktopConfig } from "@/lib/desktop"
import { check as checkUpdate } from "@tauri-apps/plugin-updater"
import { useTheme } from "@/lib/prefs"
import { initLang, useT } from "@/lib/i18n"
import { Spinner } from "@/components/ui/tui"
import { ShellHeader } from "@/components/ShellHeader"
import { ShellSidebar } from "@/components/ShellSidebar"
import { HubSubNav } from "@/components/HubSubNav"
import { CommandPalette } from "@/components/CommandPalette"
type Health = "checking" | "ok" | "degraded" | "offline"

function useServerHealth(): { api: Health; redis: Health; worker: Health } {
  const q = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      // Ensure desktop sidecar is resolved before first health check — otherwise
      // the Tauri WebView races `fetch` against the 8s Rust health poll.
      try {
        await resolveDesktopConfig(3000)
      } catch {
        // not in Tauri or sidecar not ready yet; fall back to VITE_API_URL
      }
      const base = effectiveApiUrl(API_URL)
      try {
        const r = await fetch(`${base}/health`, { headers: { ...desktopHeaders() } })
        const raw = (await r.json()) as unknown
        if (raw !== null && typeof raw === "object" && "checks" in raw) {
          const body = raw as { checks?: Record<string, { ok?: boolean }> }
          return {
            api: true as const,
            redis: body.checks?.redis?.ok === true,
          }
        }
        return { api: false as const, redis: false as const }
      } catch {
        return { api: false as const, redis: false as const }
      }
    },
    refetchInterval: 15000,
    staleTime: 10000,
  })
  return {
    api: q.isPending ? "checking" : q.data?.api ? "ok" : "offline",
    redis: q.data?.redis ? "ok" : "offline",
    worker: "offline", // worker state needs /ws or metrics; not faked
  }
}


// Desktop-only: shown when Playwright cannot launch a browser on first run.
// Polls once per page load; dismiss leaves an auto-recheck at 30s.
function BrowsersBanner() {
  const t = useT()
  const [s, setS] = useState<{ available: boolean; has_system_channel: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  useEffect(() => {
    if (!isDesktop()) return
    let alive = true
    const check = () => { api.getBrowsersStatus().then((r) => { if (alive) setS(r) }).catch(() => {}) }
    check()
    const id = window.setInterval(check, 30_000)
    return () => { alive = false; window.clearInterval(id) }
  }, [])
  if (!isDesktop() || !s || s.available || dismissed) return null
  const onInstall = async () => {
    setBusy(true)
    try { await api.installBrowsers(); setS({ ...s, available: false }) } catch { /* keep banner */ } finally { setBusy(false) }
  }
  const msg = s.has_system_channel ? t("browsers.hasSystem") : busy ? t("browsers.downloading") : t("browsers.missing")
  return (
    <div className="zf-panel" style={{ borderColor: s.has_system_channel ? "var(--border)" : "var(--warn)", margin: "var(--s2) 0", display: "flex", gap: "var(--s2)", alignItems: "center", flexWrap: "wrap", padding: "var(--s3) var(--s4)" }}>
      <span style={{ color: "var(--muted)" }}>{msg}</span>
      {!s.has_system_channel && (
        <button className="zf-btn zf-btn--primary" onClick={onInstall} disabled={busy} style={{ marginLeft: "auto" }}>
          {busy ? <Spinner /> : null} {t("browsers.install")}
        </button>
      )}
      <button className="zf-btn" onClick={() => api.getBrowsersStatus().then(setS).catch(() => {})} disabled={busy}>{t("browsers.retry")}</button>
      <button className="zf-btn" onClick={() => setDismissed(true)}>{t("browsers.dismiss")}</button>
    </div>
  )
}

// Desktop auto-update — checks GitHub Releases via tauri-plugin-updater.
// Silent outside Tauri (checks `isDesktop()` first).
function UpdaterBanner() {
  const [state, setState] = useState<"idle" | "available" | "downloading" | "ready">("idle")
  const [version, setVersion] = useState("")
  const [progress, setProgress] = useState(0)
  const check = useCallback(async () => {
    if (!isDesktop()) return
    try {
      const update = await checkUpdate()
      if (update) { setVersion(update.version || ""); setState("available") }
    } catch { /* offline or no updater config */ }
  }, [])
  useEffect(() => { void check() }, [check])
  const install = useCallback(async () => {
    setState("downloading")
    try {
      const update = await checkUpdate()
      if (!update) { setState("idle"); return }
      await update.downloadAndInstall((ev: unknown) => {
        if (ev !== null && typeof ev === "object" && "event" in ev && ev.event === "Progress") { setProgress((v) => Math.min(99, v + 1)) }
      })
      setState("ready")
    } catch { setState("idle") }
  }, [])
  if (state === "idle") return null
  if (state === "ready") return <div style={{ padding: "var(--s2) var(--s4)", borderBottom: "1px solid var(--border)", background: "var(--surface)" }}><span className="zf-meta">Atualização v{version} instalada — reinicie o app.</span></div>
  if (state === "downloading") return <div style={{ padding: "var(--s2) var(--s4)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "var(--s3)", background: "var(--surface)" }}><Spinner /><span className="zf-meta">Baixando v{version}… {progress}%</span></div>
  return <div style={{ padding: "var(--s2) var(--s4)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "var(--s3)", background: "var(--surface)" }}><span className="zf-meta">Nova versão v{version} disponível.</span><button className="zf-btn" onClick={install} style={{ fontSize: "12px", padding: "4px 10px" }}>Atualizar agora</button><button className="zf-btn" onClick={() => setState("idle")} style={{ fontSize: "12px", padding: "4px 10px" }}>Depois</button></div>
}

const RAIL_COLLAPSE_KEY = "zfrog-sidebar-collapsed"

function Shell() {
  const pathname = useLocation({ select: (l) => l.pathname })
  const [theme, toggleTheme] = useTheme()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const health = useServerHealth()
  const [railCollapsed, setRailCollapsed] = useState(() => {
    try {
      return localStorage.getItem(RAIL_COLLAPSE_KEY) === "1"
    } catch {
      return false
    }
  })

  const toggleRail = useCallback(() => {
    setRailCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(RAIL_COLLAPSE_KEY, next ? "1" : "0")
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])

  useEffect(() => {
    initLang()
  }, [])

  // ctrl+k / cmd+k palette shortcut + "[" rail toggle
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const isInput =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        Boolean(target?.isContentEditable)
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      } else if (e.key === "[" && !e.metaKey && !e.ctrlKey && !e.altKey && !isInput) {
        e.preventDefault()
        toggleRail()
      } else if (e.key === "Escape") {
        setPaletteOpen(false)
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [toggleRail])

  const closePalette = useCallback(() => setPaletteOpen(false), [])

  return (
    <>
      <ShellHeader
        apiOk={health.api === "ok"}
        workerOk={health.worker === "ok"}
        redisOk={health.redis === "ok"}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenPalette={() => setPaletteOpen(true)}
      />

      <BrowsersBanner />
      <UpdaterBanner />

      <div className="zf-body" data-rail={railCollapsed ? "collapsed" : "open"} id="shell">
        <ShellSidebar
          collapsed={railCollapsed}
          onToggleCollapsed={toggleRail}
          onOpenPalette={() => setPaletteOpen(true)}
        />

        <div className="zf-main">
          <HubSubNav />
          <div className={pathname === "/chat" ? "zf-view zf-view--full" : "zf-view"} id="conteudo">
            <AuthGate>
              <Outlet />
            </AuthGate>
          </div>
        </div>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={closePalette}
        onTheme={toggleTheme}
      />
    </>
  )
}

function RootComponent() {
  const t = useT()
  return (
    <QueryClientProvider client={queryClient}>
      <ToastRegion>
        <a className="skip-link" href="#conteudo">
          {t("a11y.skip")}
        </a>
        <AuthGate>
          <Shell />
        </AuthGate>
      </ToastRegion>
    </QueryClientProvider>
  )
}

export const Route = createRootRoute({
  component: RootComponent,
})

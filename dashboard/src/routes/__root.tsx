import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, Outlet, useLocation, useNavigate, createRootRoute } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { QueryClientProvider } from "@tanstack/react-query"
import "@fontsource/iosevka/400.css"
import "@fontsource/iosevka/500.css"
import "../styles/tui.css"
import "../globals.css"
import { queryClient } from "@/lib/query-client"
import { AuthGate } from "@/components/AuthGate"
import { ToastRegion } from "@/components/ToastRegion"
import { API_URL } from "@/lib/api"
import { effectiveApiUrl, desktopHeaders, resolveDesktopConfig } from "@/lib/desktop"
import { useTheme } from "@/lib/prefs"
import { getLang, initLang, setLang, useT, type I18nKey } from "@/lib/i18n"
import { LANG_LABEL, LANG_ORDER } from "@/lib/lang"
import { SYM } from "@/components/ui/tui"

/* Tabs of the header. Hidden routes stay reachable from the palette (DESIGN.md §12). */
const TABS: { to: string; key: I18nKey }[] = [
  { to: "/", key: "nav.runs" },
  { to: "/colecao", key: "nav.collection" },
  { to: "/busca", key: "nav.search" },
  { to: "/probe", key: "nav.extract" },
  { to: "/chat", key: "nav.chat" },
  { to: "/comparar", key: "nav.compare" },
  { to: "/datasets", key: "nav.datasets" },
  { to: "/grafo", key: "nav.graph" },
  { to: "/precos", key: "nav.prices" },
  { to: "/graphql", key: "nav.graphql" },
  { to: "/config", key: "nav.config" },
]

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
        let body: { checks?: Record<string, { ok?: boolean }> } | null = null
        try {
          body = (await r.json()) as { checks?: Record<string, { ok?: boolean }> }
        } catch {
          return { api: false as const, redis: false as const }
        }
        return {
          api: true as const,
          redis: body?.checks?.redis?.ok === true,
        }
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

function Dot({ on, label }: { on: boolean; label: string }) {
  return (
    <span>
      <span className={on ? "dot-on" : "dot-off"}>{on ? SYM.on : SYM.off}</span> {label}
    </span>
  )
}

function Palette({
  open,
  onClose,
  onTheme,
}: {
  open: boolean
  onClose: () => void
  onTheme: () => void
}) {
  const t = useT()
  const navigate = useNavigate()
  const [q, setQ] = useState("")
  const [idx, setIdx] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const items = useMemo(
    () => [
      { cmd: t("palette.theme"), desc: t("palette.themeDesc"), run: onTheme },
      { cmd: t("palette.home"), desc: t("palette.homeDesc"), to: "/" },
      { cmd: t("palette.colecao"), desc: t("palette.colecaoDesc"), to: "/colecao" },
      { cmd: t("palette.busca"), desc: t("palette.buscaDesc"), to: "/busca" },
      { cmd: t("palette.probe"), desc: t("palette.probeDesc"), to: "/probe" },
      { cmd: t("palette.chat"), desc: t("palette.chatDesc"), to: "/chat" },
      { cmd: t("palette.comparar"), desc: t("palette.compararDesc"), to: "/comparar" },
      { cmd: t("palette.datasets"), desc: t("palette.datasetsDesc"), to: "/datasets" },
      { cmd: t("palette.grafo"), desc: t("palette.grafoDesc"), to: "/grafo" },
      { cmd: t("palette.precos"), desc: t("palette.precosDesc"), to: "/precos" },
      { cmd: t("palette.captura"), desc: t("palette.capturaDesc"), to: "/captura" },
      { cmd: t("palette.qualidade"), desc: t("palette.qualidadeDesc"), to: "/qualidade" },
      { cmd: t("palette.workers"), desc: t("palette.workersDesc"), to: "/workers" },
      { cmd: t("palette.graphql"), desc: t("palette.graphqlDesc"), to: "/graphql" },
      { cmd: t("palette.config"), desc: t("palette.configDesc"), to: "/config" },
      { cmd: t("palette.fluxos"), desc: t("palette.fluxosDesc"), to: "/fluxos" },
      { cmd: t("palette.snapshots"), desc: t("palette.snapshotsDesc"), to: "/snapshots" },
      { cmd: t("palette.timeline"), desc: t("palette.timelineDesc"), to: "/timeline" },
      { cmd: t("palette.revisao"), desc: t("palette.revisaoDesc"), to: "/revisao" },
      { cmd: t("palette.stats"), desc: t("palette.statsDesc"), to: "/stats" },
      { cmd: t("palette.analytics"), desc: t("palette.analyticsDesc"), to: "/analytics" },
      { cmd: t("palette.roi"), desc: t("palette.roiDesc"), to: "/roi" },
      { cmd: t("palette.webhooks"), desc: t("palette.webhooksDesc"), to: "/webhooks" },
      { cmd: t("palette.equipe"), desc: t("palette.equipeDesc"), to: "/equipe" },
      { cmd: t("palette.marketplace"), desc: t("palette.marketplaceDesc"), to: "/marketplace" },
      { cmd: t("palette.ajuda"), desc: t("palette.ajudaDesc"), to: "/ajuda" },
      { cmd: t("palette.design"), desc: t("palette.designDesc"), to: "/design" },
    ],
    [onTheme, t],
  )

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return needle ? items.filter((c) => c.cmd.toLowerCase().includes(needle)) : items
  }, [q, items])

  useEffect(() => {
    if (open) {
      setQ("")
      setIdx(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  if (!open) return null
  const run = (i: number) => {
    const item = filtered[i]
    if (!item) return
    if (item.to) navigate({ to: item.to })
    else item.run?.()
    onClose()
  }

  return (
    <div className="palette open" role="dialog" aria-label={t("palette.label")} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="box">
        <input
          ref={inputRef}
          type="text"
          value={q}
          autoComplete="off"
          spellCheck={false}
          placeholder={t("palette.commandPlaceholder")}
          aria-label={t("palette.searchLabel")}
          onChange={(e) => { setQ(e.target.value); setIdx(0) }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, filtered.length - 1)) }
            else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)) }
            else if (e.key === "Enter") run(idx)
            else if (e.key === "Escape") onClose()
          }}
        />
        <div className="plist">
          {filtered.map((c, i) => (
            <div
              key={c.cmd}
              className={`pitem${i === idx ? " hi" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); run(i) }}
              onMouseEnter={() => setIdx(i)}
            >
              <span className="pcmd">{c.cmd}</span>
              <span className="pdesc">{c.desc}</span>
            </div>
          ))}
          {!filtered.length && <div className="pitem"><span className="pdesc">{t("palette.empty")}</span></div>}
        </div>
      </div>
    </div>
  )
}

function Shell() {
  const t = useT()
  const pathname = useLocation({ select: (l) => l.pathname })
  const [theme, toggleTheme] = useTheme()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const health = useServerHealth()

  useEffect(() => {
    initLang()
  }, [])

  // ctrl+k palette, from any screen, outside inputs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      } else if (e.key === "?" && !(e.target instanceof HTMLInputElement)) {
        setHelpOpen((v) => !v)
      } else if (e.key === "Escape") {
        setPaletteOpen(false)
        setHelpOpen(false)
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])

  const closePalette = useCallback(() => setPaletteOpen(false), [])

  return (
    <div className="tui" style={{ minHeight: "100vh", display: "grid", gridTemplateRows: "auto minmax(0, 1fr) auto auto" }}>
      <header className="tui-header">
        <span className="brand">zfrog</span>
        <nav className="tabs" aria-label={t("a11y.sections")}>
          {TABS.map((tab) => (
            <Link key={tab.to} to={tab.to} className="tab" aria-current={pathname === tab.to || (tab.to !== "/" && pathname.startsWith(tab.to)) ? "page" : undefined}>
              {t(tab.key)}
            </Link>
          ))}
        </nav>
        <span className="spring" />
        <button className="tab" onClick={() => setPaletteOpen(true)} style={{ color: "var(--fg-dim)" }}>
          ctrl+k
        </button>
      </header>

      <main className="tui-main" id="conteudo">
        <div className="tui-col">
          <AuthGate>
            <Outlet />
          </AuthGate>
        </div>
      </main>

      {helpOpen && (
        <div className="tui-help">{t("help.bar")}</div>
      )}

      <div className="promptbox">
        <PromptGlobal onPalette={() => setPaletteOpen(true)} />
      </div>

      <footer className="statusbar">
        <Dot on={health.api === "ok"} label="api" />
        <Dot on={health.redis === "ok"} label="redis" />
        <Dot on={health.worker === "ok"} label="worker" />
        <span className="spring" />
        <span role="group" aria-label="language / idioma">
          {LANG_ORDER.map((l) => (
            <button
              key={l}
              className="pendbtn"
              onClick={() => setLang(l)}
              aria-pressed={getLang() === l}
              style={getLang() === l ? { color: "var(--fg)" } : undefined}
            >
              {LANG_LABEL[l]}
            </button>
          ))}
        </span>
        <button className="pendbtn" onClick={toggleTheme}>{t("nav.theme")}: {theme}</button>
        <button className="pendbtn" onClick={() => setHelpOpen((v) => !v)}>{t("nav.help")}</button>
      </footer>

      <Palette open={paletteOpen} onClose={closePalette} onTheme={toggleTheme} />
    </div>
  )
}

/** The bottom prompt: `❯ jump <url>` runs, `❯ <palavra>` filters the current screen. */
function PromptGlobal({ onPalette }: { onPalette: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  const [value, setValue] = useState("")

  const run = (raw: string) => {
    const v = raw.trim()
    setValue("")
    if (!v) return
    const [name, ...rest] = v.split(/\s+/)
    const cmd = name.toLowerCase()
    const arg = rest.join(" ")

    if ((cmd === "jump" || cmd === "tongue") && arg) {
      navigate({ to: "/probe", search: { url: arg } }).catch(() => {})
      return
    }
    if (cmd === "jump" || cmd === "tongue" || cmd === "probe") {
      navigate({ to: "/probe" })
      return
    }
    if (cmd === "chat" || cmd === "ask") {
      navigate({ to: "/chat" })
      return
    }
    if (cmd === "comparar" || cmd === "compare" || cmd === "trends") {
      navigate({ to: "/comparar" })
      return
    }
    if (cmd === "datasets" || cmd === "dataset") {
      navigate({ to: "/datasets" })
      return
    }
    if (cmd === "grafo" || cmd === "graph") {
      navigate({ to: "/grafo" })
      return
    }
    if (cmd === "precos" || cmd === "preco" || cmd === "prices" || cmd === "price") {
      navigate({ to: "/precos" })
      return
    }
    if (cmd === "graphql" || cmd === "gql") {
      navigate({ to: "/graphql" })
      return
    }
    if (cmd === "colecao" || cmd === "pond" || cmd === "cards") {
      navigate({ to: "/colecao" })
      return
    }
    if (cmd === "busca" || cmd === "search") {
      navigate({ to: "/busca", search: arg ? { q: arg } : undefined }).catch(() => {})
      return
    }
    if (cmd === "captura") {
      navigate({ to: "/captura" })
      return
    }
    if (cmd === "qualidade" || cmd === "arweave" || cmd === "ipfs") {
      navigate({ to: "/qualidade" })
      return
    }
    if (cmd === "workers" || cmd === "dispatch") {
      navigate({ to: "/workers" })
      return
    }
    if (cmd === "ajuda" || cmd === "help" || cmd === "?") {
      navigate({ to: "/ajuda" })
      return
    }
    if (cmd === "config") {
      navigate({ to: "/config" })
      return
    }

    // Any other text: treat as a text filter on the runs screen
    navigate({ to: "/", search: { q: v } }).catch(() => {})
  }

  return (
    <div className="tui-prompt">
      <span className="caret">❯</span>
      <input
        type="text"
        value={value}
        autoComplete="off"
        spellCheck={false}
        placeholder={t("prompt.placeholder")}
        aria-label={t("prompt.aria")}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") run(value)
          else if (e.key === "Escape") { setValue(""); onPalette() }
        }}
      />
    </div>
  )
}

export const Route = createRootRoute({
  component: () => {
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
  },
})

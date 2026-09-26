"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"
import { api } from "@/lib/api"
import { clearApiKey } from "@/lib/auth"
import { LayoutDashboard, Download, History, Search, Workflow, Store, Webhook, ShieldCheck, Users, MessageSquare, Cpu, TrendingUp, Coins, Clock, BarChart3, Settings, HelpCircle, Zap, RefreshCw } from "lucide-react"

const nav = [
  { href: "/", label: "Execuções", title: "Tudo que você já baixou", icon: LayoutDashboard },
  { href: "/probe", label: "Nova extração", title: "Baixar um site ou extrair dados", icon: Download },
  { href: "/timeline", label: "Máquina do tempo", title: "Ver o site como era numa data passada", icon: Clock },
  { href: "/snapshots", label: "Histórico", title: "Versões guardadas e o que mudou", icon: History },
  { href: "/busca", label: "Busca", title: "Procurar dentro do que já foi baixado", icon: Search },
  { href: "/fluxos", label: "Fluxos", title: "Montar sequências de passos", icon: Workflow },
  { href: "/revisao", label: "Revisão", title: "Comentários nas cópias", icon: MessageSquare },
  { href: "/marketplace", label: "Marketplace", title: "Fluxos e plugins prontos para instalar", icon: Store },
  { href: "/qualidade", label: "Qualidade", title: "Dados pessoais e riscos de segurança", icon: ShieldCheck },
  { href: "/webhooks", label: "Avisos", title: "Avisar outro sistema quando algo acontece", icon: Webhook },
  { href: "/equipe", label: "Equipe", title: "Usuários e organizações", icon: Users },
  { href: "/workers", label: "Workers", title: "Máquinas que processam e onde ficam", icon: Cpu },
  { href: "/analytics", label: "Desempenho", title: "Qual motor funciona melhor", icon: BarChart3 },
  { href: "/roi", label: "Retorno", title: "Quanto o trabalho automatizado economizou", icon: Coins },
  { href: "/stats", label: "Estatísticas", title: "Números do sistema", icon: TrendingUp },
  { href: "/config", label: "Configurações", title: "Velocidade e limites", icon: Settings },
  { href: "/ajuda", label: "Ajuda", title: "Como usar e qual modo escolher", icon: HelpCircle },
]

export function Navbar() {
  const pathname = usePathname()

  return (
    <>
      {/* Barra lateral (desktop) */}
      <aside className="hidden md:flex fixed left-0 top-0 h-screen w-[240px] flex-col border-r bg-card z-30">
        <div className="h-[64px] flex items-center gap-3 px-5 border-b">
          <div className="h-8 w-8 rounded-[10px] bg-primary flex items-center justify-center text-primary-foreground">
            <Zap className="h-4 w-4" />
          </div>
          <div className="flex flex-col">
            <span className="text-[13.5px] font-semibold tracking-tight leading-none">Zfrog</span>
            <span className="text-[11px] text-muted-foreground">Copiar e extrair sites</span>
          </div>
        </div>

        <nav className="flex-1 p-3 flex flex-col gap-1 overflow-y-auto">
          {nav.map((item) => {
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href))
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.title}
                className={cn(
                  "flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-[13.5px] font-medium transition-all",
                  active
                    ? "bg-primary text-primary-foreground shadow-sm shadow-primary/20"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent"
                )}
              >
                <item.icon className="h-4 w-4 shrink-0" />
                {item.label}
              </Link>
            )
          })}

          <div className="mt-auto pt-4">
            <ServerStatus />
            <SignOut />
          </div>
        </nav>
      </aside>

      {/* Cabeçalho (celular) */}
      <header className="md:hidden fixed top-0 left-0 right-0 h-[56px] border-b bg-card/80 backdrop-blur-xl z-30 flex items-center justify-between px-4">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-[9px] bg-primary flex items-center justify-center text-primary-foreground">
            <Zap className="h-3.5 w-3.5" />
          </div>
          <span className="text-[14px] font-semibold">Zfrog</span>
        </div>
        <div className="flex items-center gap-1">
          {nav.map((item) => {
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href))
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.title}
                className={cn(
                  "h-8 w-8 rounded-[10px] flex items-center justify-center",
                  active ? "bg-primary text-primary-foreground" : "text-muted-foreground"
                )}
              >
                <item.icon className="h-4 w-4" />
              </Link>
            )
          })}
        </div>
      </header>

      <div className="md:hidden h-[56px]" />
    </>
  )
}

type Health = "checking" | "online" | "offline"

function ServerStatus() {
  const [health, setHealth] = useState<Health>("checking")

  const ping = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/health`)
      setHealth(res.ok ? "online" : "offline")
    } catch {
      setHealth("offline")
    }
  }

  useEffect(() => {
    setTimeout(ping, 0)
    const id = setInterval(ping, 30000)
    return () => clearInterval(id)
  }, [])

  const dot = { checking: "bg-zinc-400", online: "bg-emerald-500 animate-pulse", offline: "bg-red-500" }[health]
  const text = { checking: "Verificando servidor…", online: "Servidor conectado", offline: "Servidor fora do ar" }[health]

  return (
    <div className="rounded-[12px] bg-secondary p-3">
      <div className="flex items-center gap-2 text-[12px] font-medium">
        <div className={cn("h-2 w-2 rounded-full shrink-0", dot)} />
        {text}
      </div>
      {health === "offline" ? (
        <p className="text-[11px] text-muted-foreground mt-1 leading-snug">
          Inicie a API com <span className="font-mono">./zfrog dev</span> ou{" "}
          <span className="font-mono">./zfrog serve</span>.
        </p>
      ) : (
        <button
          onClick={ping}
          className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          <RefreshCw className="h-3 w-3" /> verificar de novo
        </button>
      )}
    </div>
  )
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
        // Unreachable API: the status box above already says so.
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!needed) return null

  return (
    <button
      onClick={async () => {
        clearApiKey()
        try {
          await api.logout()
        } catch {
          // The cookie may already be gone; the reload below is what matters.
        }
        window.location.reload()
      }}
      className="mt-2 w-full text-left text-[11px] text-muted-foreground hover:text-foreground transition-colors"
    >
      Sair
    </button>
  )
}

export function Topbar({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-[13.5px] text-muted-foreground mt-1">{description}</p>}
      </div>
      {action && <div className="flex items-center gap-2 flex-wrap">{action}</div>}
    </div>
  )
}

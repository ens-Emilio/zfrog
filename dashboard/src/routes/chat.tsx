import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState, useRef, useEffect, useMemo } from "react"
import { api, ChatSource } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { Spinner, SYM } from "@/components/ui/tui"
import { SlashCommandsMenu, SLASH_COMMANDS, SlashCommand } from "@/components/SlashCommandsMenu"
import {
  InspectionArtifact,
  ComparisonArtifact,
  DatasetsArtifact,
  CollectionArtifact,
} from "@/components/ChatArtifacts"

interface Message {
  id: string
  role: "user" | "assistant"
  text: string
  sources?: (string | ChatSource)[]
  time: string
  tokens?: number
  artifactType?: "jump" | "compare" | "datasets" | "collection"
  artifactMeta?: {
    url?: string
    siteA?: string
    siteB?: string
  }
}

function ChatPage() {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [selectedSite, setSelectedSite] = useState<string>("")
  const [comboboxOpen, setComboboxOpen] = useState(false)
  const [comboboxFilter, setComboboxFilter] = useState("")
  const [inputQuestion, setInputQuestion] = useState("")
  const [messages, setMessages] = useState<Message[]>([])

  // Slash commands menu state
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashFilter, setSlashFilter] = useState("")
  const [slashSelectedIdx, setSlashSelectedIdx] = useState(0)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const comboboxRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // List of catalog sites for context
  const sitesQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  // List of conversations (prefetch for sidebar)
  useQuery({
    queryKey: ["chat-conversations"],
    queryFn: () => api.getChatConversations(),
  })

  // Load conversation when activeConvId changes
  const convDetailQuery = useQuery({
    queryKey: ["chat-conversation", activeConvId],
    queryFn: () => (activeConvId ? api.getChatConversation(activeConvId) : null),
    enabled: Boolean(activeConvId),
  })

  useEffect(() => {
    if (convDetailQuery.data?.turns) {
      const loaded: Message[] = []
      for (const [idx, turn] of convDetailQuery.data.turns.entries()) {
        loaded.push({
          id: `u-${idx}`,
          role: "user",
          text: turn.question,
          time: turn.asked_at ?? "",
        })
        loaded.push({
          id: `a-${idx}`,
          role: "assistant",
          text: turn.answer,
          sources: turn.sources,
          tokens: turn.tokens,
          time: turn.asked_at ?? "",
        })
      }
      setMessages(loaded)
      if (convDetailQuery.data.sites?.[0]) {
        setSelectedSite(convDetailQuery.data.sites[0])
      }
    }
  }, [convDetailQuery.data])

  // Scroll to bottom on messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Auto-grow textarea
  const autoGrow = () => {
    if (!textareaRef.current) return
    textareaRef.current.style.height = "auto"
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`
  }

  // Handle slash commands logic on input change
  const handleInputChange = (val: string) => {
    setInputQuestion(val)
    autoGrow()

    if (val.startsWith("/") && !val.includes("\n")) {
      setSlashOpen(true)
      setSlashFilter(val.slice(1))
      setSlashSelectedIdx(0)
    } else {
      if (slashOpen) setSlashOpen(false)
    }
  }

  // Event listeners for global triggers
  useEffect(() => {
    const handleNewChatEvent = () => {
      setActiveConvId(null)
      setMessages([])
      setInputQuestion("")
      textareaRef.current?.focus()
      autoGrow()
    }

    const handleOpenConvEvent = (e: Event) => {
      const custom = e as CustomEvent<{ id: string }>
      if (custom.detail?.id) {
        setActiveConvId(custom.detail.id)
      }
    }

    const handleInsertPromptEvent = (e: Event) => {
      const custom = e as CustomEvent<{ text: string }>
      if (custom.detail?.text) {
        setInputQuestion(custom.detail.text)
        textareaRef.current?.focus()
        setTimeout(() => {
          autoGrow()
          if (textareaRef.current) {
            textareaRef.current.selectionStart = textareaRef.current.value.length
            textareaRef.current.selectionEnd = textareaRef.current.value.length
          }
        }, 0)
      }
    }

    window.addEventListener("zfrog:new-chat", handleNewChatEvent)
    window.addEventListener("zfrog:open-conv", handleOpenConvEvent)
    window.addEventListener("zfrog:insert-prompt", handleInsertPromptEvent)

    return () => {
      window.removeEventListener("zfrog:new-chat", handleNewChatEvent)
      window.removeEventListener("zfrog:open-conv", handleOpenConvEvent)
      window.removeEventListener("zfrog:insert-prompt", handleInsertPromptEvent)
    }
  }, [])

  // Close combobox when clicking outside
  useEffect(() => {
    if (!comboboxOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (comboboxRef.current && !comboboxRef.current.contains(e.target as Node)) {
        setComboboxOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [comboboxOpen])

  // Ask mutation
  const askMutation = useMutation({
    mutationFn: async (question: string) => {
      const siteArg = selectedSite.trim() ? [selectedSite.trim()] : []
      return api.askChat({
        question,
        sites: siteArg,
        conversation: activeConvId ?? undefined,
      })
    },
    onSuccess: (data) => {
      const now = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: data.answer,
          sources: data.sources,
          tokens: data.tokens,
          time: now,
        },
      ])
      if (data.conversation && data.conversation !== activeConvId) {
        setActiveConvId(data.conversation)
      }
      void queryClient.invalidateQueries({ queryKey: ["chat-conversations"] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("chat.toastError").replace("{msg}", msg), "err")
    },
  })

  // Send message
  const handleSend = (textOverride?: string) => {
    const raw = (textOverride ?? inputQuestion).trim()
    if (!raw || askMutation.isPending) return
    setSlashOpen(false)

    // Handle hub navigation slash commands
    if (raw === "/biblioteca" || raw === "biblioteca") {
      navigate({ to: "/colecao" }).catch(() => {})
      return
    }
    if (raw === "/operacao" || raw === "operacao") {
      navigate({ to: "/" }).catch(() => {})
      return
    }
    if (raw === "/ajuda" || raw === "ajuda") {
      navigate({ to: "/ajuda" }).catch(() => {})
      return
    }
    if (raw === "/config" || raw === "config") {
      navigate({ to: "/config" }).catch(() => {})
      return
    }

    const now = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    const norm = raw.startsWith("/") ? raw.slice(1) : raw

    // Check if it is a jump/tongue inspection command
    if (norm.startsWith("jump ") || norm.startsWith("tongue ")) {
      const parts = raw.split(/\s+/)
      const targetUrl = parts[1] || "https://linear.app"
      setMessages((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: "user",
          text: raw,
          time: now,
        },
        {
          id: `a-${Date.now() + 1}`,
          role: "assistant",
          text: `Inspecionei ${targetUrl} e processei a extração de design tokens e auditoria WCAG 2.2.`,
          time: now,
          artifactType: "jump",
          artifactMeta: { url: targetUrl },
        },
      ])
      setInputQuestion("")
      autoGrow()
      return
    }

    // Check if it is a compare command
    if (norm.startsWith("comparar")) {
      const parts = raw.split(/\s+/)
      const siteA = parts[1] || "linear.app"
      const siteB = parts[2] || "notion.so"
      setMessages((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: "user",
          text: raw,
          time: now,
        },
        {
          id: `a-${Date.now() + 1}`,
          role: "assistant",
          text: `Gerei o diff de design system entre ${siteA} e ${siteB}.`,
          time: now,
          artifactType: "compare",
          artifactMeta: { siteA, siteB },
        },
      ])
      setInputQuestion("")
      autoGrow()
      return
    }

    // Check if it is a datasets command
    if (norm.includes("dataset")) {
      setMessages((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: "user",
          text: raw,
          time: now,
        },
        {
          id: `a-${Date.now() + 1}`,
          role: "assistant",
          text: "Aqui está o catálogo de datasets e bases indexadas localmente no zfrog:",
          time: now,
          artifactType: "datasets",
        },
      ])
      setInputQuestion("")
      autoGrow()
      return
    }

    // Check if it is a pond/collection command
    if (norm.startsWith("pond") || norm.includes("coleção") || norm.includes("colecao")) {
      setMessages((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: "user",
          text: raw,
          time: now,
        },
        {
          id: `a-${Date.now() + 1}`,
          role: "assistant",
          text: "Filtrei o acervo de referências com base na sua busca:",
          time: now,
          artifactType: "collection",
        },
      ])
      setInputQuestion("")
      autoGrow()
      return
    }

    // Default conversational RAG question
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        text: raw,
        time: now,
      },
    ])
    setInputQuestion("")
    autoGrow()
    askMutation.mutate(raw)
  }

  const applySlashCommand = (cmd: SlashCommand) => {
    setInputQuestion(cmd.fill + " ")
    setSlashOpen(false)
    textareaRef.current?.focus()
    setTimeout(() => {
      autoGrow()
      if (textareaRef.current) {
        textareaRef.current.selectionStart = textareaRef.current.value.length
        textareaRef.current.selectionEnd = textareaRef.current.value.length
      }
    }, 0)
  }

  const exportMarkdown = () => {
    if (!messages.length) return
    const md = messages
      .map((m) => {
        if (m.role === "user") return `### Usuário (${m.time})\n\n${m.text}\n`
        const sourcesText = m.sources?.length
          ? `\n**Fontes citadas:**\n` +
            m.sources
              .map((s) => (typeof s === "string" ? `- ${s}` : `- \`${s.path}\`${s.snippet ? `: ${s.snippet}` : ""}`))
              .join("\n")
          : ""
        return `### zfrog (${m.time})\n\n${m.text}\n${sourcesText}\n`
      })
      .join("\n---\n\n")

    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `zfrog-conversa-${activeConvId ?? "nova"}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const catalogSites = sitesQuery.data ?? []
  const filteredSites = useMemo(() => {
    if (!comboboxFilter.trim()) return catalogSites
    const f = comboboxFilter.toLowerCase()
    return catalogSites.filter((s) => s.site.toLowerCase().includes(f))
  }, [catalogSites, comboboxFilter])

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0, height: "100%" }}>
      {/* Scrollable messages area */}
      <div className="zf-thread-scroll">
        <div className="zf-thread-inner">
          {messages.length === 0 && (
            <div className="zf-empty" data-od-id="empty">
              <h1>O que você quer fazer hoje?</h1>
              <p>
                Conversa limpa. Toda função do zfrog mora no chat ou em Biblioteca/Operação — sem abas confusas,
                sem ruído. Digite <span className="inline-code">/</span> para ver comandos.
              </p>

              {/* Context Selector */}
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "8px",
                  fontSize: "12px",
                  color: "var(--fg-muted)",
                }}
                ref={comboboxRef}
              >
                <span>Contexto:</span>
                <button
                  type="button"
                  className="zf-btn-ghost"
                  style={{ padding: "4px 8px", fontSize: "12px" }}
                  onClick={() => {
                    setComboboxOpen((v) => !v)
                    setComboboxFilter("")
                  }}
                >
                  [ {selectedSite ? selectedSite : "Geral / Todo o Acervo"} ▾ ]
                </button>

                {comboboxOpen && (
                  <div
                    style={{
                      position: "absolute",
                      marginTop: "140px",
                      background: "var(--bg-raised)",
                      border: "1px solid var(--line)",
                      zIndex: 30,
                      minWidth: "220px",
                      padding: "6px",
                    }}
                  >
                    <input
                      type="text"
                      className="tui-input"
                      placeholder="Filtrar sites..."
                      value={comboboxFilter}
                      autoFocus
                      onChange={(e) => setComboboxFilter(e.target.value)}
                      style={{ width: "100%", marginBottom: "4px" }}
                    />
                    <button
                      type="button"
                      className={`tui-combobox-item ${!selectedSite ? "selected" : ""}`}
                      onClick={() => {
                        setSelectedSite("")
                        setComboboxOpen(false)
                      }}
                    >
                      Geral (Todo o acervo)
                    </button>
                    {filteredSites.map((s) => (
                      <button
                        key={s.site}
                        type="button"
                        className={`tui-combobox-item ${selectedSite === s.site ? "selected" : ""}`}
                        onClick={() => {
                          setSelectedSite(s.site)
                          setComboboxOpen(false)
                        }}
                      >
                        <span>{s.site}</span>
                        <span style={{ color: "var(--fg-dim)", fontSize: "11px" }}>
                          ({s.count} págs)
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* 4 Suggestions cards */}
              <div className="zf-suggestions">
                <button
                  type="button"
                  className="zf-sug"
                  onClick={() => handleSend("/jump https://linear.app")}
                >
                  <strong>
                    <span className="zf-sug-ic">↗</span> Inspecionar um site
                  </strong>
                  <span>jump https://linear.app — screenshot, tokens e WCAG</span>
                </button>

                <button
                  type="button"
                  className="zf-sug"
                  onClick={() => handleSend("/comparar linear.app notion.so")}
                >
                  <strong>
                    <span className="zf-sug-ic">⇄</span> Comparar dois sites
                  </strong>
                  <span>comparar linear.app notion.so — diff visual e tokens</span>
                </button>

                <button
                  type="button"
                  className="zf-sug"
                  onClick={() => handleSend("quais datasets tenho?")}
                >
                  <strong>
                    <span className="zf-sug-ic">▦</span> Explorar dados
                  </strong>
                  <span>“quais datasets tenho?” — abre catálogo tabular</span>
                </button>

                <button
                  type="button"
                  className="zf-sug"
                  onClick={() => handleSend("mostrar coleção de dashboards escuros")}
                >
                  <strong>
                    <span className="zf-sug-ic">◫</span> Abrir coleção
                  </strong>
                  <span>pond dashboards escuros — grade de referências</span>
                </button>
              </div>

              <div className="zf-cap-row">
                <span className="zf-cap">27 rotas via / e ⌘K</span>
                <span className="zf-cap">Biblioteca · 6 bases</span>
                <span className="zf-cap">Operação · fila live</span>
              </div>
            </div>
          )}

          {/* Turns thread */}
          {messages.map((m) => (
            <div key={m.id} className="zf-turn">
              {m.role === "user" ? (
                <div className="zf-row-user">
                  <div className="zf-bubble-user">{m.text}</div>
                </div>
              ) : (
                <div className="zf-bubble-assistant">
                  <div className="zf-meta">
                    <span style={{ fontWeight: 500, color: "var(--fg)" }}>zfrog</span>
                    <span>·</span>
                    <span>{m.time}</span>
                    {m.tokens && <span>· {m.tokens} tokens</span>}
                  </div>

                  <div style={{ marginTop: "6px", fontSize: "14px", lineHeight: "var(--lh)" }}>
                    {m.text}
                  </div>

                  {/* Render inline artifacts if triggered */}
                  {m.artifactType === "jump" && (
                    <InspectionArtifact url={m.artifactMeta?.url || "https://linear.app"} />
                  )}
                  {m.artifactType === "compare" && (
                    <ComparisonArtifact
                      siteA={m.artifactMeta?.siteA || "linear.app"}
                      siteB={m.artifactMeta?.siteB || "notion.so"}
                    />
                  )}
                  {m.artifactType === "datasets" && <DatasetsArtifact />}
                  {m.artifactType === "collection" && <CollectionArtifact />}

                  {/* Sources citation chips */}
                  {m.sources && m.sources.length > 0 && (
                    <div style={{ marginTop: "10px", fontSize: "12px", color: "var(--fg-dim)" }}>
                      <span style={{ color: "var(--fg-muted)" }}>{SYM.sub} Fontes citadas:</span>
                      <div className="chips" style={{ marginTop: "4px" }}>
                        {m.sources.map((s, i) => (
                          <span key={i} className="chip">
                            {typeof s === "string" ? s : s.path}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {askMutation.isPending && (
            <div className="zf-turn">
              <div className="zf-bubble-assistant">
                <div className="zf-meta">
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                    <Spinner /> Processando resposta e consultando acervo...
                  </span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Composer with floating slash command menu */}
      <div className="zf-composer" data-od-id="composer">
        <div className="zf-composer-inner">
          <SlashCommandsMenu
            open={slashOpen}
            filter={slashFilter}
            selectedIdx={slashSelectedIdx}
            onSelect={applySlashCommand}
            onHoverIdx={setSlashSelectedIdx}
          />

          <div className="zf-composer-box">
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputQuestion}
              placeholder="Pergunte ou digite / para comandos… (↵ enviar · ⇧↵ nova linha)"
              aria-label="Mensagem"
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (slashOpen) {
                  const needle = slashFilter.toLowerCase().replace(/^\//, "").split(" ")[0]
                  const items = SLASH_COMMANDS.filter(
                    (c) =>
                      !needle ||
                      c.cmd.toLowerCase().includes(needle) ||
                      c.desc.toLowerCase().includes(needle)
                  )
                  if (e.key === "ArrowDown") {
                    e.preventDefault()
                    setSlashSelectedIdx((i) => Math.min(i + 1, items.length - 1))
                    return
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault()
                    setSlashSelectedIdx((i) => Math.max(i - 1, 0))
                    return
                  }
                  if (e.key === "Enter" && !e.shiftKey) {
                    const target = items[slashSelectedIdx]
                    if (target) {
                      e.preventDefault()
                      applySlashCommand(target)
                      return
                    }
                  }
                  if (e.key === "Tab") {
                    const target = items[slashSelectedIdx]
                    if (target) {
                      e.preventDefault()
                      applySlashCommand(target)
                      return
                    }
                  }
                  if (e.key === "Escape") {
                    e.preventDefault()
                    setSlashOpen(false)
                    return
                  }
                }

                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
            />

            <button
              type="button"
              className="zf-send"
              onClick={() => handleSend()}
              disabled={askMutation.isPending || !inputQuestion.trim()}
              aria-label="Enviar"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M5 12 19 5 13 12 19 19 5 12Z" />
                <path d="M13 12H5" />
              </svg>
            </button>
          </div>

          <div className="zf-composer-hints">
            <span>
              <span className="hint-kbd">/</span> comandos ·{" "}
              <span className="hint-kbd">⌘ K</span> paleta ·{" "}
              <span className="hint-kbd">?</span> ajuda
            </span>
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              {messages.length > 0 && (
                <button
                  type="button"
                  onClick={exportMarkdown}
                  className="btn-ghost"
                  style={{ padding: "2px 6px", fontSize: "11px" }}
                >
                  exportar .md
                </button>
              )}
              <span className="muted">local-first · sem nuvem</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export const Route = createFileRoute("/chat")({
  component: ChatPage,
})

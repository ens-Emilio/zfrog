import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState, useRef, useEffect, useMemo } from "react"
import { api, ChatSource } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { Spinner, SYM, TuiPanel } from "@/components/ui/tui"

interface Message {
  id: string
  role: "user" | "assistant"
  text: string
  sources?: (string | ChatSource)[]
  time: string
  tokens?: number
}

function ChatPage() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [selectedSite, setSelectedSite] = useState<string>("")
  const [customPathMode, setCustomPathMode] = useState(false)
  const [comboboxOpen, setComboboxOpen] = useState(false)
  const [comboboxFilter, setComboboxFilter] = useState("")
  const [focusedSugIdx, setFocusedSugIdx] = useState<number | null>(null)
  const [inputQuestion, setInputQuestion] = useState("")
  const [messages, setMessages] = useState<Message[]>([])
  const [showSessionsDrawer, setShowSessionsDrawer] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const comboboxRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // List of saved conversations
  const convsQuery = useQuery({
    queryKey: ["chat-conversations"],
    queryFn: () => api.getChatConversations(),
  })

  // List of catalog sites for context
  const sitesQuery = useQuery({
    queryKey: ["catalog-sites"],
    queryFn: () => api.getCatalogSites(),
  })

  // Pre-selects the first available site automatically
  useEffect(() => {
    if (!selectedSite && sitesQuery.data && sitesQuery.data.length > 0) {
      setSelectedSite(sitesQuery.data[0].site)
    }
  }, [sitesQuery.data, selectedSite])

  // Closes the combobox when clicking outside
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

  // Initial focus and "/" shortcut to focus the input
  useEffect(() => {
    inputRef.current?.focus()
    const onGlobalKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable) return
      if (e.key === "/") {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener("keydown", onGlobalKey)
    return () => window.removeEventListener("keydown", onGlobalKey)
  }, [])

  // Loads history when a conversation is selected
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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Mutation to send a question
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

  const handleSend = (textToSend?: string) => {
    const q = (textToSend ?? inputQuestion).trim()
    if (!q || askMutation.isPending) return
    if (!selectedSite.trim()) {
      toast(t("chat.selectSiteFirst"), "err")
      return
    }

    const now = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    setMessages((prev) => [
      ...prev,
      {
        id: `u-${Date.now()}`,
        role: "user",
        text: q,
        time: now,
      },
    ])
    setInputQuestion("")
    askMutation.mutate(q)
  }

  const handleNewChat = () => {
    setActiveConvId(null)
    setMessages([])
    setInputQuestion("")
    inputRef.current?.focus()
  }

  const exportMarkdown = () => {
    if (!messages.length) return
    const md = messages
      .map((m) => {
        if (m.role === "user") return `${t("chat.mdUser").replace("{time}", m.time)}\n\n${m.text}\n`
        const sourcesText = m.sources?.length
          ? `\n${t("chat.mdSources")}\n` +
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
    a.download = `zfrog-chat-${activeConvId ?? t("chat.exportSession")}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const conversations = convsQuery.data ?? []
  const catalogSites = sitesQuery.data ?? []

  const activeSiteInfo = useMemo(
    () => catalogSites.find((s) => s.site === selectedSite),
    [catalogSites, selectedSite],
  )

  const filteredSites = useMemo(() => {
    if (!comboboxFilter.trim()) return catalogSites
    const f = comboboxFilter.toLowerCase()
    return catalogSites.filter((s) => s.site.toLowerCase().includes(f))
  }, [catalogSites, comboboxFilter])

  const suggestions = useMemo(() => {
    const s = selectedSite ? selectedSite.replace(/^output\/(snapshots\/)?/, "") : t("chat.thisSite")
    return [
      t("chat.suggestion1").replace("{site}", s),
      t("chat.suggestion2"),
      t("chat.suggestion3"),
    ]
  }, [selectedSite, t])

  const hasSessions = conversations.length > 0

  return (
    <div className="flex flex-col gap-3">
      {/* Main control bar as TuiPanel */}
      <TuiPanel
        title={t("chat.title")}
        action={
          <div className="flex items-baseline gap-2">
            {hasSessions && (
              <button
                type="button"
                className="tui-btn"
                onClick={() => setShowSessionsDrawer((v) => !v)}
              >
                [{showSessionsDrawer
                  ? t("chat.sessionsToggle").replace("{mode}", t("chat.sessionsModeHide")).replace("{count}", String(conversations.length))
                  : t("chat.sessionsToggle").replace("{mode}", t("chat.sessionsModeShow")).replace("{count}", String(conversations.length))}]
              </button>
            )}
            {messages.length > 0 && (
              <button type="button" className="tui-btn" onClick={exportMarkdown}>
                {t("chat.exportMarkdown")}
              </button>
            )}
            <button type="button" className="tui-btn" onClick={handleNewChat}>
              {t("chat.newChat")}
            </button>
          </div>
        }
      >
        {/* Unified context and status row */}
        <div className="flex flex-wrap items-baseline gap-2 border-b border-[var(--line)] pb-2 text-xs">
          <span style={{ color: "var(--fg-dim)" }}>{t("chat.context")}</span>

          {!customPathMode ? (
            <div className="tui-combobox-wrap" ref={comboboxRef}>
              <button
                type="button"
                className="tui-btn"
                onClick={() => {
                  setComboboxOpen((v) => !v)
                  setComboboxFilter("")
                }}
              >
                [ {selectedSite ? selectedSite : t("chat.selectSite")} ▾ ]
              </button>

              {comboboxOpen && (
                <div className="tui-combobox-menu">
                  <div style={{ padding: "0.25lh 1ch", borderBottom: "1px solid var(--line)" }}>
                    <input
                      type="text"
                      className="tui-input"
                      placeholder={t("chat.filterSites")}
                      value={comboboxFilter}
                      autoFocus
                      onChange={(e) => setComboboxFilter(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setComboboxOpen(false)
                        if (e.key === "Enter" && filteredSites[0]) {
                          setSelectedSite(filteredSites[0].site)
                          setComboboxOpen(false)
                        }
                      }}
                    />
                  </div>
                  {filteredSites.length === 0 ? (
                    <div style={{ padding: "0.5lh 1ch", color: "var(--fg-dim)" }}>
                      {t("chat.noSitesFound")}
                    </div>
                  ) : (
                    filteredSites.map((s) => (
                      <button
                        key={s.site}
                        type="button"
                        className={`tui-combobox-item ${selectedSite === s.site ? "selected" : ""}`}
                        onClick={() => {
                          setSelectedSite(s.site)
                          setComboboxOpen(false)
                          inputRef.current?.focus()
                        }}
                      >
                        <span>{s.site}</span>
                        <span style={{ color: "var(--fg-dim)", fontSize: "11px" }}>
                          {t("chat.refCount").replace("{count}", String(s.count))}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-baseline gap-2 flex-1">
              <input
                type="text"
                className="tui-input"
                style={{ width: "35ch" }}
                placeholder="output/snapshots/site.com"
                value={selectedSite}
                onChange={(e) => setSelectedSite(e.target.value)}
              />
            </div>
          )}

          <button
            type="button"
            className="tui-btn"
            style={{ color: "var(--fg-dim)", fontSize: "11px" }}
            onClick={() => setCustomPathMode((v) => !v)}
          >
            [{customPathMode ? t("chat.useCatalog") : t("chat.manualPath")}]
          </button>

          {/* Index status row */}
          <div className="flex items-baseline gap-1 ml-auto text-xs">
            {activeSiteInfo ? (
              <span style={{ color: "var(--fg-muted)" }}>
                <span style={{ color: "var(--ok)" }}>{SYM.ok}</span> {t("chat.indexedPages").replace("{count}", String(activeSiteInfo.count))}
              </span>
            ) : selectedSite ? (
              <span style={{ color: "var(--fg-muted)" }}>
                <span style={{ color: "var(--ok)" }}>{SYM.ok}</span> {t("chat.activePath")} <code>{selectedSite}</code>
              </span>
            ) : (
              <span style={{ color: "var(--warn)" }}>
                {t("chat.selectSiteWarn")}
              </span>
            )}
          </div>
        </div>

        {/* Main layout: when there are no saved sessions, takes 100% of the width */}
        <div className={`grid gap-3 ${hasSessions && showSessionsDrawer ? "grid-cols-1 md:grid-cols-4" : "grid-cols-1"}`}>
          {/* Sessions drawer (only rendered when there is history and the user asked for it) */}
          {hasSessions && showSessionsDrawer && (
            <aside className="tui-panel md:col-span-1 flex flex-col gap-1 p-2 text-xs max-h-[500px] overflow-y-auto" style={{ margin: 0 }}>
              <div className="tui-panel-head" style={{ paddingBottom: "0.25lh", marginBottom: "0.25lh" }}>
                <span className="tui-panel-title">{t("chat.sessionsTitle").replace("{count}", String(conversations.length))}</span>
              </div>
              {conversations.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`w-full text-left p-1 border ${
                    activeConvId === c.id
                      ? "border-[var(--line)] bg-[var(--sel-bg)]"
                      : "border-transparent hover:bg-[var(--sel-bg)]"
                  }`}
                  onClick={() => setActiveConvId(c.id)}
                >
                  <div className="truncate font-mono">{c.id}</div>
                  <div className="flex justify-between text-[11px]" style={{ color: "var(--fg-dim)" }}>
                    <span>{c.sites?.[0] ?? t("chat.global")}</span>
                    <span>{t("chat.turnCount").replace("{count}", String(c.turns))}</span>
                  </div>
                </button>
              ))}
            </aside>
          )}

            {/* Conversation window */}
          <div className={`flex flex-col justify-between ${hasSessions && showSessionsDrawer ? "md:col-span-3" : "w-full"}`}>
            {/* Message stream */}
            <div className="chat-stream">
              {messages.length === 0 && (
                <div className="chat-suggestions">
                  <div className="chat-suggestions-head">
                    {t("chat.suggestionsHead").replace("{site}", selectedSite || t("chat.thisSite"))}
                  </div>
                  {suggestions.map((sug, idx) => (
                    <button
                      key={idx}
                      type="button"
                      className={`suggestion-row ${focusedSugIdx === idx ? "active" : ""}`}
                      onFocus={() => setFocusedSugIdx(idx)}
                      onClick={() => {
                        handleSend(sug)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          handleSend(sug)
                        } else if (e.key === "ArrowDown" || e.key === "j") {
                          e.preventDefault()
                          setFocusedSugIdx(Math.min(idx + 1, suggestions.length - 1))
                        } else if (e.key === "ArrowUp" || e.key === "k") {
                          e.preventDefault()
                          setFocusedSugIdx(Math.max(idx - 1, 0))
                        }
                      }}
                    >
                      <span className="caret">❯</span>
                      <span className="sug-text">“{sug}”</span>
                      <span className="sug-hint">{t("chat.enterToAsk")}</span>
                    </button>
                  ))}
                </div>
              )}

              {messages.map((m) => (
                <div key={m.id} className={`chat-turn ${m.role === "assistant" ? "assistant" : "user"}`}>
                  <div className="chat-turn-meta">
                    <span className="role">{m.role === "user" ? t("chat.you") : t("chat.zfrogRole")}</span>
                    <span>·</span>
                    <span>{m.time}</span>
                    {m.tokens && <span>· {t("chat.tokenCount").replace("{count}", String(m.tokens))}</span>}
                  </div>
                  <div className="chat-turn-body">{m.text}</div>

                  {m.sources && m.sources.length > 0 && (
                    <div className="chat-sources">
                      <span style={{ color: "var(--fg-muted)" }}>{SYM.sub} {t("chat.sources")}</span>
                      <ul style={{ listStyle: "none", paddingLeft: "1ch", marginTop: "0.25lh" }}>
                        {m.sources.map((s, i) => (
                          <li key={i}>
                            {typeof s === "string" ? (
                              <code>{s}</code>
                            ) : (
                              <span>
                                <code>{s.path}</code>
                                {s.snippet && (
                                  <span style={{ color: "var(--fg-dim)" }}> — “{s.snippet.slice(0, 80)}…”</span>
                                )}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}

              {askMutation.isPending && (
                <div className="chat-turn assistant">
                  <div className="chat-turn-meta">
                    <span className="role"><Spinner /> {t("chat.consulting")}</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Terminal-prompt style input bar */}
            <div className="chat-input-bar">
              <span className="caret">❯</span>
              <input
                ref={inputRef}
                type="text"
                placeholder={
                  selectedSite
                    ? t("chat.askPlaceholder").replace("{site}", selectedSite)
                    : t("chat.askPlaceholderNoSite")
                }
                value={inputQuestion}
                onChange={(e) => setInputQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                disabled={askMutation.isPending}
              />
              <button
                type="button"
                className="tui-btn"
                onClick={() => handleSend()}
                disabled={askMutation.isPending || !inputQuestion.trim() || !selectedSite.trim()}
              >
                {askMutation.isPending ? <Spinner /> : t("chat.send")}
              </button>
            </div>
          </div>
        </div>
      </TuiPanel>
    </div>
  )
}

export const Route = createFileRoute("/chat")({
  component: ChatPage,
})

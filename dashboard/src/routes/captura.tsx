import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { api, ExtractPage, ExtractPreview, TotpAccount } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { Spinner, SYM, TuiPanel } from "@/components/ui/tui"

function escapeIdent(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char}`)
}

function cssPath(element: Element): string {
  const segments: string[] = []
  let node: Element | null = element
  while (node !== null && node.nodeType === 1) {
    const self: Element = node
    const tag = self.tagName.toLowerCase()
    if (tag === "html") break

    if (self.id) {
      segments.unshift(`#${escapeIdent(self.id)}`)
      break
    }

    let segment = tag
    const classes: string[] = Array.from(self.classList).slice(0, 2)
    if (classes.length > 0) segment += "." + classes.map(escapeIdent).join(".")

    if (tag !== "body") {
      const parent: Element | null = self.parentElement
      if (parent !== null) {
        const siblings: Element[] = Array.from(parent.children).filter(
          (child) => child.tagName === self.tagName,
        )
        if (siblings.length > 1) segment += `:nth-of-type(${siblings.indexOf(self) + 1})`
      }
    }

    segments.unshift(segment)
    if (tag === "body") break
    node = self.parentElement
  }
  return segments.join(" > ")
}

interface Block {
  id: string
  labelKey: "captura.block.header" | "captura.block.nav" | "captura.block.main" | "captura.block.comments" | "captura.block.footer" | "captura.block.images" | "captura.block.forms" | "captura.block.scripts"
  selectors: string[]
}

const BLOCKS: Block[] = [
  { id: "header", labelKey: "captura.block.header", selectors: ["header", "[role=banner]"] },
  { id: "nav", labelKey: "captura.block.nav", selectors: ["nav", "[role=navigation]"] },
  { id: "main", labelKey: "captura.block.main", selectors: ["main", "[role=main]", "article"] },
  { id: "comments", labelKey: "captura.block.comments", selectors: ["#comments", ".comments", "[data-comments]"] },
  { id: "footer", labelKey: "captura.block.footer", selectors: ["footer", "[role=contentinfo]"] },
  { id: "images", labelKey: "captura.block.images", selectors: ["img", "picture"] },
  { id: "forms", labelKey: "captura.block.forms", selectors: ["form", "input", "textarea", "select"] },
  { id: "scripts", labelKey: "captura.block.scripts", selectors: ["script", "link[rel=stylesheet]"] },
]

interface Preset {
  id: string
  labelKey: "captura.preset.full" | "captura.preset.article" | "captura.preset.products"
  blocks: string[]
}

const PRESETS: Preset[] = [
  { id: "full", labelKey: "captura.preset.full", blocks: BLOCKS.map((b) => b.id) },
  { id: "article", labelKey: "captura.preset.article", blocks: ["main", "images"] },
  { id: "products", labelKey: "captura.preset.products", blocks: ["main", "images", "forms"] },
]

function blocksToSelector(ids: string[]): string {
  const parts: string[] = []
  for (const block of BLOCKS) {
    if (ids.includes(block.id)) parts.push(...block.selectors)
  }
  return parts.join(", ")
}

function CapturaPage() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<"blocos" | "totp">("blocos")

  // ── Block capture state ──
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState<ExtractPage | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [frameReady, setFrameReady] = useState(false)

  const [blocks, setBlocks] = useState<string[]>(BLOCKS.map((b) => b.id))
  const [presetId, setPresetId] = useState("full")

  const [selector, setSelector] = useState(() => blocksToSelector(BLOCKS.map((b) => b.id)))
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<ExtractPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const iframeRef = useRef<HTMLIFrameElement | null>(null)

  // ── TOTP vault & sessions state ──
  const [totpName, setTotpName] = useState("")
  const [totpSecret, setTotpSecret] = useState("")
  const [totpIssuer, setTotpIssuer] = useState("")
  const [selectedTotp, setSelectedTotp] = useState<string | null>(null)

  const totpAccountsQuery = useQuery({
    queryKey: ["totp-accounts"],
    queryFn: () => api.getTotpAccounts(),
    enabled: tab === "totp",
  })

  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api.getSessions(),
    enabled: tab === "totp",
  })

  const totpCodeQuery = useQuery({
    queryKey: ["totp-code", selectedTotp],
    queryFn: () => (selectedTotp ? api.getTotpCode(selectedTotp) : null),
    enabled: Boolean(selectedTotp) && tab === "totp",
    refetchInterval: 5000,
  })

  const addTotpMutation = useMutation({
    mutationFn: () =>
      api.addTotpAccount({
        name: totpName.trim(),
        secret: totpSecret.trim(),
        issuer: totpIssuer.trim() || undefined,
      }),
    onSuccess: (data) => {
      toast(t("captura.totpAddedToast").replace("{name}", data.name), "ok")
      setTotpName("")
      setTotpSecret("")
      setTotpIssuer("")
      void queryClient.invalidateQueries({ queryKey: ["totp-accounts"] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("captura.totpAddError").replace("{error}", msg), "err")
    },
  })

  const deleteTotpMutation = useMutation({
    mutationFn: (name: string) => api.deleteTotpAccount(name),
    onSuccess: (data) => {
      toast(t("captura.totpRemovedToast").replace("{name}", data.removed), "ok")
      if (selectedTotp === data.removed) setSelectedTotp(null)
      void queryClient.invalidateQueries({ queryKey: ["totp-accounts"] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("captura.totpRemoveError").replace("{error}", msg), "err")
    },
  })

  const deleteSessionMutation = useMutation({
    mutationFn: (dom: string) => api.deleteSession(dom),
    onSuccess: (data) => {
      toast(t("captura.sessionRemovedToast").replace("{domain}", data.removed), "ok")
      void queryClient.invalidateQueries({ queryKey: ["sessions"] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("captura.sessionRemoveError").replace("{error}", msg), "err")
    },
  })

  const applyBlocks = (next: string[]) => {
    setBlocks(next)
    setSelector(blocksToSelector(next))
    setPreview(null)
    setPreviewError(null)
  }

  const handlePreset = (id: string) => {
    setPresetId(id)
    const preset = PRESETS.find((p) => p.id === id)
    if (preset) applyBlocks(preset.blocks)
  }

  const handleLoad = async () => {
    const target = url.trim()
    if (!target) return
    setLoading(true)
    setLoadError(null)
    setPage(null)
    setPreview(null)
    setFrameReady(false)
    try {
      const res = await api.extractPage(target)
      setPage(res)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const handleFrameLoad = () => {
    const frame = iframeRef.current
    if (!frame) return
    try {
      const doc = frame.contentDocument
      if (!doc) return

      const style = doc.createElement("style")
      style.textContent = `
        .__zf_hover { outline: 2px dashed #00e5a3 !important; outline-offset: -2px !important; cursor: crosshair !important; }
        .__zf_selected { outline: 2px solid #00e5a3 !important; outline-offset: -2px !important; background: rgba(0, 229, 163, 0.1) !important; }
      `
      doc.head.appendChild(style)

      let currentHover: Element | null = null
      doc.addEventListener(
        "mouseover",
        (e) => {
          const target = e.target as Element | null
          if (!target || target === doc.body || target === doc.documentElement) return
          if (currentHover && currentHover !== target) {
            currentHover.classList.remove("__zf_hover")
          }
          currentHover = target
          target.classList.add("__zf_hover")
        },
        true,
      )

      doc.addEventListener(
        "mouseout",
        (e) => {
          const target = e.target as Element | null
          if (target) target.classList.remove("__zf_hover")
        },
        true,
      )

      doc.addEventListener(
        "click",
        (e) => {
          e.preventDefault()
          e.stopPropagation()
          const target = e.target as Element | null
          if (!target) return
          const path = cssPath(target)
          setSelector(path)
          setPresetId("custom")
          void handlePreview(path)
        },
        true,
      )

      setFrameReady(true)
    } catch {
      // cross-origin frame fallback
    }
  }

  const handlePreview = async (override?: string) => {
    const target = url.trim()
    const value = (override ?? selector).trim()
    if (!target || !value) return
    setPreviewing(true)
    setPreviewError(null)
    setPreview(null)
    try {
      setPreview(await api.previewSelector(target, value))
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e))
    } finally {
      setPreviewing(false)
    }
  }

  const totpAccounts: TotpAccount[] = totpAccountsQuery.data ?? []
  const sessions = sessionsQuery.data ?? []
  const currentCode = totpCodeQuery.data

  return (
    <TuiPanel
      title={t("captura.title")}
      action={
        <div className="toggles text-xs" role="group" aria-label={t("captura.sectionAria")}>
          <button
            type="button"
            className="tgl"
            aria-pressed={tab === "blocos"}
            onClick={() => setTab("blocos")}
          >
            {t("captura.tabBlocks")}
          </button>
          <button
            type="button"
            className="tgl"
            aria-pressed={tab === "totp"}
            onClick={() => setTab("totp")}
          >
            {t("captura.tabTotp")}
          </button>
        </div>
      }
    >
      <div className="text-xs text-[var(--fg-dim)] border-b border-[var(--border)] pb-2 mb-3">
        {tab === "blocos" ? t("captura.blocksHint") : t("captura.totpHint")}
      </div>

      {tab === "blocos" ? (
        <>
          {/* Preset and blocks */}
          <div className="tui-panel" style={{ marginTop: "0.5lh" }}>
            <div className="tui-panel-head">
              <span className="tui-label">{t("captura.blocksToExtract")}</span>
              <div className="flex gap-2">
                {PRESETS.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`tui-btn${presetId === p.id ? " accent" : ""}`}
                    onClick={() => handlePreset(p.id)}
                    style={{ fontSize: 11 }}
                  >
                    {t(p.labelKey)}
                  </button>
                ))}
              </div>
            </div>

            <div className="tui-tags" style={{ marginTop: "0.25lh" }}>
              {BLOCKS.map((b) => {
                const active = blocks.includes(b.id)
                return (
                  <button
                    key={b.id}
                    type="button"
                    className={`tui-tag${active ? " active" : ""}`}
                    onClick={() => {
                      setPresetId("custom")
                      applyBlocks(active ? blocks.filter((id) => id !== b.id) : [...blocks, b.id])
                    }}
                  >
                    {t(b.labelKey)}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Load page for interactive clicking */}
          <div className="tui-field" style={{ marginTop: "0.5lh" }}>
            <label className="tui-label" htmlFor="page-url">
              {t("captura.urlLabel")}
            </label>
            <div className="flex gap-2">
              <input
                id="page-url"
                className="tui-input"
                style={{ flex: 1 }}
                type="url"
                placeholder="https://exemplo.com/pagina"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleLoad()
                }}
              />
              <button
                type="button"
                className="tui-btn accent"
                onClick={() => void handleLoad()}
                disabled={loading || !url.trim()}
              >
                {loading ? <Spinner /> : t("captura.loadPage")}
              </button>
            </div>
          </div>

          {loadError && (
            <p className="empty" style={{ color: "var(--error)" }}>
              {SYM.fail} {t("captura.loadError").replace("{error}", loadError)}
            </p>
          )}

          {/* Editable CSS selector */}
          <div className="tui-field" style={{ marginTop: "0.5lh" }}>
            <label className="tui-label" htmlFor="custom-selector">
              {t("captura.selectorLabel")}
            </label>
            <div className="flex gap-2">
              <input
                id="custom-selector"
                className="tui-input"
                style={{ flex: 1, fontFamily: "inherit" }}
                type="text"
                value={selector}
                onChange={(e) => {
                  setSelector(e.target.value)
                  setPresetId("custom")
                }}
              />
              <button
                type="button"
                className="tui-btn"
                onClick={() => void handlePreview()}
                disabled={previewing || !url.trim() || !selector.trim()}
              >
                {previewing ? <Spinner /> : t("captura.testSelector")}
              </button>
            </div>
          </div>

          {/* Interactive selection frame */}
          {page && (
            <div className="tui-panel" style={{ marginTop: "0.5lh" }}>
              <div className="tui-panel-head">
                <span className="tui-label">{t("captura.interactiveInspection")}</span>
                <span style={{ fontSize: 11, color: "var(--fg-dim)" }}>
                  {frameReady ? t("captura.frameActive") : t("captura.frameLoading")}
                </span>
              </div>
              <iframe
                ref={iframeRef}
                title={t("captura.frameTitle")}
                srcDoc={page.html}
                onLoad={handleFrameLoad}
                style={{
                  width: "100%",
                  height: "460px",
                  border: "1px solid var(--border)",
                  background: "#fff",
                  marginTop: "0.25lh",
                }}
                sandbox="allow-same-origin"
              />
            </div>
          )}

          {/* Preview of selected elements */}
          {previewError && (
            <p className="empty" style={{ color: "var(--error)", marginTop: "0.5lh" }}>
              {SYM.fail} {t("captura.previewError").replace("{error}", previewError)}
            </p>
          )}

          {preview && (
            <div className="tui-panel" style={{ marginTop: "0.5lh" }}>
              <div className="tui-panel-head">
                <span className="tui-label">{t("captura.elementsFound").replace("{count}", String(preview.count))}</span>
                <span style={{ fontSize: 11, color: "var(--ok)" }}>
                  {SYM.ok} {t("captura.selectorValid")}
                </span>
              </div>

              <div style={{ maxHeight: "260px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.25lh" }}>
                {preview.elements.slice(0, 50).map((el) => (
                  <div key={el.index} style={{ borderBottom: "1px solid var(--line)", padding: "0.25lh 0" }}>
                    <span style={{ color: "var(--accent)", fontWeight: 500 }}>&lt;{el.tag}&gt;</span>{" "}
                    <span style={{ color: "var(--fg)" }}>{el.text || t("captura.noVisibleText")}</span>
                    <details style={{ marginTop: "0.125lh" }}>
                      <summary style={{ color: "var(--fg-dim)", cursor: "pointer", fontSize: 11 }}>{t("captura.viewHtml")}</summary>
                      <pre
                        style={{
                          fontFamily: "inherit",
                          fontSize: 11,
                          color: "var(--fg-muted)",
                          background: "var(--sel-bg)",
                          padding: "0.25lh 0.5ch",
                          overflowX: "auto",
                          whiteSpace: "pre-wrap",
                        }}
                      >
                        {el.html}
                      </pre>
                    </details>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        /* TOTP (2FA) vault and saved sessions tab */
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs" style={{ marginTop: "0.5lh" }}>
          {/* Column 1: TOTP management */}
          <div className="tui-panel p-4 flex flex-col gap-4">
            <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between">
              <span>{t("captura.totpVaultTitle")}</span>
              <span className="text-[var(--fg-dim)]">{t("captura.accountsCount").replace("{count}", String(totpAccounts.length))}</span>
            </div>

            {/* New account registration */}
            <div className="border border-[var(--border)] p-3 bg-[var(--bg-panel)] flex flex-col gap-2">
              <span className="font-bold text-[10px] uppercase text-[var(--fg-dim)]">{t("captura.addSecret")}</span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <input
                  type="text"
                  className="tui-input"
                  placeholder={t("captura.namePlaceholder")}
                  value={totpName}
                  onChange={(e) => setTotpName(e.target.value)}
                />
                <input
                  type="text"
                  className="tui-input"
                  placeholder={t("captura.issuerPlaceholder")}
                  value={totpIssuer}
                  onChange={(e) => setTotpIssuer(e.target.value)}
                />
              </div>
              <input
                type="password"
                className="tui-input font-mono"
                placeholder={t("captura.secretPlaceholder")}
                value={totpSecret}
                onChange={(e) => setTotpSecret(e.target.value)}
              />
              <button
                type="button"
                className="tui-btn accent w-full mt-1"
                onClick={() => addTotpMutation.mutate()}
                disabled={addTotpMutation.isPending || !totpName.trim() || !totpSecret.trim()}
              >
                {addTotpMutation.isPending ? <Spinner /> : SYM.ok} {t("captura.saveToVault")}
              </button>
            </div>

            {/* TOTP accounts list and live generator */}
            <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
              {totpAccountsQuery.isLoading && (
                <p className="text-[var(--fg-dim)]"><Spinner /> {t("captura.loadingVault")}</p>
              )}
              {!totpAccountsQuery.isLoading && totpAccounts.length === 0 && (
                <p className="text-[var(--fg-dim)] py-4 text-center">{t("captura.noAccounts")}</p>
              )}
              {totpAccounts.map((acc) => {
                const isSelected = selectedTotp === acc.name
                return (
                  <div
                    key={acc.name}
                    className={`p-2 border flex items-center justify-between ${
                      isSelected
                        ? "border-[var(--accent)] bg-[var(--bg-panel)]"
                        : "border-[var(--border-subtle)] hover:border-[var(--border)]"
                    }`}
                  >
                    <div>
                      <div className="font-bold flex items-center gap-1.5">
                        <span>{acc.name}</span>
                        {acc.issuer && (
                          <span className="text-[10px] text-[var(--fg-dim)] uppercase">({acc.issuer})</span>
                        )}
                      </div>
                      <div className="text-[10px] text-[var(--fg-dim)]">{acc.created_at || "—"}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        className="tui-btn text-[11px]"
                        onClick={() => setSelectedTotp(acc.name)}
                      >
                        {t("captura.generateCode")}
                      </button>
                      <button
                        type="button"
                        className="tui-btn text-[11px] hover:border-[var(--error)]"
                        onClick={() => deleteTotpMutation.mutate(acc.name)}
                        title={t("captura.deleteTitle")}
                      >
                        {SYM.fail}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Active code */}
            {selectedTotp && currentCode && (
              <div className="border border-[var(--accent)] p-3 bg-[var(--bg-panel)] text-center">
                <div className="text-[10px] text-[var(--fg-dim)] uppercase mb-1">
                  {t("captura.currentCode").split("<b>")[0]}
                  <b>{selectedTotp}</b>:
                </div>
                <div className="text-2xl font-mono font-bold tracking-widest text-[var(--accent)]">
                  {currentCode.code}
                </div>
                <div className="text-[10px] text-[var(--fg-dim)] mt-1">
                  {t("captura.renewsIn")
                    .replace("<b>", "")
                    .replace("</b>", "")
                    .replace("{seconds}", String(currentCode.seconds_remaining))}
                </div>
              </div>
            )}
          </div>

          {/* Column 2: saved login sessions */}
          <div className="tui-panel p-4 flex flex-col gap-4">
            <div className="font-bold border-b border-[var(--border)] pb-1 flex justify-between">
              <span>{t("captura.sessionsTitle")}</span>
              <span className="text-[var(--fg-dim)]">{t("captura.domainsCount").replace("{count}", String(sessions.length))}</span>
            </div>

            <p className="text-[var(--fg-dim)]">
              {t("captura.sessionsHint")}
            </p>

            <div className="space-y-1.5 max-h-[380px] overflow-y-auto">
              {sessionsQuery.isLoading && (
                <p className="text-[var(--fg-dim)]"><Spinner /> {t("captura.loadingSessions")}</p>
              )}
              {!sessionsQuery.isLoading && sessions.length === 0 && (
                <p className="text-[var(--fg-dim)] py-6 text-center">
                  {t("captura.noSessions")}
                </p>
              )}
              {sessions.map((s) => (
                <div
                  key={s.domain}
                  className="p-2 border border-[var(--border-subtle)] bg-[var(--bg-panel)] flex items-center justify-between"
                >
                  <div className="truncate mr-2 font-mono">
                    <div className="font-bold">{s.domain}</div>
                    <div className="text-[10px] text-[var(--fg-dim)]">
                      {t("captura.cookieCount").replace("{count}", String(s.cookies)).replace("{savedAt}", s.saved_at)}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="tui-btn text-[11px] hover:border-[var(--error)]"
                    onClick={() => deleteSessionMutation.mutate(s.domain)}
                  >
                    {t("captura.revokeSession")}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </TuiPanel>
  )
}

export const Route = createFileRoute("/captura")({
  component: CapturaPage,
})

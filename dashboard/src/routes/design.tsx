import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"
import { CodeBlock, DetailLine, Spinner, Swatch, Sym } from "@/components/ui/tui"
import { useMotion, useTheme } from "@/lib/prefs"
import { useT, type I18nKey } from "@/lib/i18n"

export const Route = createFileRoute("/design")({
  component: DesignPage,
})

interface ColorToken {
  name: I18nKey
  cssVar: string
  lightOklch: string
  darkOklch: string
  role: I18nKey
  contrastNote: I18nKey
}

const COLOR_TOKENS: ColorToken[] = [
  { name: "design.tokenPaper" as I18nKey, cssVar: "--bg", lightOklch: "oklch(98.7% 0.002 106)", darkOklch: "oklch(16.5% 0.005 106)", role: "design.tokenPaperRole" as I18nKey, contrastNote: "design.noteBase" as I18nKey },
  { name: "design.tokenPaperRaised" as I18nKey, cssVar: "--surface", lightOklch: "oklch(100% 0 0)", darkOklch: "oklch(20.5% 0.006 106)", role: "design.tokenPaperRaisedRole" as I18nKey, contrastNote: "design.noteSurface" as I18nKey },
  { name: "design.tokenSelection" as I18nKey, cssVar: "--sel-bg", lightOklch: "color-mix(in oklch, var(--fg) 4%, var(--surface))", darkOklch: "color-mix(in oklch, var(--fg) 7%, var(--surface))", role: "design.tokenSelectionRole" as I18nKey, contrastNote: "design.noteSurface" as I18nKey },
  { name: "design.tokenHairline" as I18nKey, cssVar: "--border", lightOklch: "oklch(91% 0.004 106)", darkOklch: "oklch(28.5% 0.008 106)", role: "design.tokenHairlineRole" as I18nKey, contrastNote: "design.noteDivider" as I18nKey },
  { name: "design.tokenInk" as I18nKey, cssVar: "--fg", lightOklch: "oklch(19% 0.012 106)", darkOklch: "oklch(93% 0.005 106)", role: "design.tokenInkRole" as I18nKey, contrastNote: "design.ratioAaa" as I18nKey },
  { name: "design.tokenTextSecondary" as I18nKey, cssVar: "--muted", lightOklch: "oklch(48% 0.014 106)", darkOklch: "oklch(70% 0.010 106)", role: "design.tokenTextSecondaryRole" as I18nKey, contrastNote: "design.ratioAa1" as I18nKey },
  { name: "design.tokenTextTertiary" as I18nKey, cssVar: "--accent", lightOklch: "oklch(48% 0.105 145)", darkOklch: "oklch(78% 0.115 145)", role: "design.tokenTextTertiaryRole" as I18nKey, contrastNote: "design.ratioUiAa" as I18nKey },
  { name: "design.tokenAccent" as I18nKey, cssVar: "--accent", lightOklch: "oklch(48% 0.105 145)", darkOklch: "oklch(78% 0.115 145)", role: "design.tokenAccentRole" as I18nKey, contrastNote: "design.ratioAa2" as I18nKey },
  { name: "design.tokenOk" as I18nKey, cssVar: "--ok", lightOklch: "oklch(48% 0.105 145)", darkOklch: "oklch(78% 0.115 145)", role: "design.tokenOkRole" as I18nKey, contrastNote: "design.ratioAa2" as I18nKey },
  { name: "design.tokenError" as I18nKey, cssVar: "--error", lightOklch: "oklch(50% 0.170 27)", darkOklch: "oklch(72% 0.150 27)", role: "design.tokenErrorRole" as I18nKey, contrastNote: "design.ratioAa3" as I18nKey },
  { name: "design.tokenWarn" as I18nKey, cssVar: "--warn", lightOklch: "oklch(50% 0.110 68)", darkOklch: "oklch(80% 0.120 75)", role: "design.tokenWarnRole" as I18nKey, contrastNote: "design.ratioAa4" as I18nKey },
  { name: "design.tokenRun" as I18nKey, cssVar: "--run", lightOklch: "oklch(55% 0.130 235)", darkOklch: "oklch(75% 0.120 235)", role: "design.tokenAccentRole" as I18nKey, contrastNote: "design.ratioAa2" as I18nKey },
]

const SYMBOLS: { sym: string; name: I18nKey; descKey: I18nKey }[] = [
  { sym: "▍", name: "design.symCursor" as I18nKey, descKey: "design.symCursorDesc" as I18nKey },
  { sym: "✓", name: "design.symSuccess" as I18nKey, descKey: "design.symSuccessDesc" as I18nKey },
  { sym: "✗", name: "design.symFailure" as I18nKey, descKey: "design.symFailureDesc" as I18nKey },
  { sym: "·", name: "design.symSeparator" as I18nKey, descKey: "design.symSeparatorDesc" as I18nKey },
  { sym: "…", name: "design.symRunning" as I18nKey, descKey: "design.symRunningDesc" as I18nKey },
  { sym: "⎿", name: "design.symSubordination" as I18nKey, descKey: "design.symSubordinationDesc" as I18nKey },
  { sym: "[x]", name: "design.symToggleOn" as I18nKey, descKey: "design.symToggleOnDesc" as I18nKey },
  { sym: "[ ]", name: "design.symToggleOff" as I18nKey, descKey: "design.symToggleOffDesc" as I18nKey },
  { sym: ">", name: "design.symPrompt" as I18nKey, descKey: "design.symPromptDesc" as I18nKey },
  { sym: "+", name: "design.symDiffAdd" as I18nKey, descKey: "design.symDiffAddDesc" as I18nKey },
  { sym: "-", name: "design.symDiffRemove" as I18nKey, descKey: "design.symDiffRemoveDesc" as I18nKey },
  { sym: "~", name: "design.symDiffChange" as I18nKey, descKey: "design.symDiffChangeDesc" as I18nKey },
]

function DesignPage() {
  const t = useT()
  const [theme, toggleTheme] = useTheme()
  const [motion, setMotion] = useMotion()
  const [activeTab, setActiveTab] = useState<"tokens" | "primitives" | "forms" | "symbols" | "a11y">("tokens")
  const [modalOpen, setModalOpen] = useState(false)
  const [demoInput, setDemoInput] = useState("https://example.com.br")
  const [demoSelect, setDemoSelect] = useState("jump")
  const [demoTags, setDemoTags] = useState(["landing", "saas", "dark-mode"])
  const [newTag, setNewTag] = useState("")

  return (
    <div className="zf-view" style={{ paddingTop: "var(--s6)", paddingBottom: "var(--s8)" }}>
      <div className="zf-head" style={{ marginBottom: "var(--s6)", borderBottom: "1px solid var(--border)", paddingBottom: "var(--s5)" }}>
        <div>
          <h1 className="zf-title">{t("design.headerTitle")}</h1>
          <p className="zf-meta" style={{ marginTop: 4 }}>{t("design.headerSub")}</p>
        </div>
        <span className="zf-spacer" style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: "var(--s2)", alignItems: "center" }}>
          <button type="button" className="zf-btn zf-btn--ghost" onClick={toggleTheme}>
            {theme === "dark" ? t("design.themeDark") : t("design.themeLight")} · {theme}
          </button>
          <button type="button" className="zf-btn zf-btn--ghost" onClick={() => setMotion(motion === "reduced" ? "full" : "reduced")}>
            {motion}
          </button>
        </div>
      </div>

      <div className="zf-tabs" role="tablist">
        {(["tokens", "primitives", "forms", "symbols", "a11y"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            className="zf-tab"
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "tokens" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s6)" }}>
          <div>
            <h2 className="zf-h2" style={{ marginBottom: "var(--s2)" }}>{t("design.tokensHeading")}</h2>
            <p className="zf-meta" style={{ marginBottom: "var(--s4)" }}>{t("design.tokensIntro")}</p>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "var(--s4)", marginBottom: "var(--s5)" }}>
              {COLOR_TOKENS.slice(0, 8).map((c) => (
                <div key={c.cssVar + c.name} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div style={{ height: 44, borderRadius: "var(--radius)", background: `var(${c.cssVar})`, border: "1px solid var(--border)" }} />
                  <span className="zf-micro">{c.cssVar}</span>
                  <span className="zf-meta" style={{ fontSize: 10, overflowWrap: "anywhere" }}>{c.lightOklch}</span>
                  <span style={{ fontSize: 11, color: "var(--fg)" }}>{t(c.name)}</span>
                  <span className="zf-meta" style={{ fontSize: 11 }}>{t(c.role)}</span>
                </div>
              ))}
            </div>

            <div className="zf-panel">
              <div className="zf-panel-hd"><span className="zf-micro">OKLch tokens · zfrog.css</span><span className="zf-spacer" /><span className="zf-meta">light / dark</span></div>
              <div style={{ overflowX: "auto" }}>
                <table className="zf-table">
                  <thead>
                    <tr>
                      <th style={{ width: "5ch" }}></th>
                      <th>{t("design.thVariable")}</th>
                      <th>{t("design.thNameRole")}</th>
                      <th>{t("design.thLight")}</th>
                      <th>{t("design.thDark")}</th>
                      <th>{t("design.thContrast")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {COLOR_TOKENS.map((c) => (
                      <tr key={c.cssVar + c.name}>
                        <td><span style={{ display: "inline-block", width: 14, height: 14, borderRadius: 3, background: `var(${c.cssVar})`, border: "1px solid var(--border)" }} /></td>
                        <td><code className="zf-num">{c.cssVar}</code></td>
                        <td><span style={{ color: "var(--fg)", fontWeight: 500 }}>{t(c.name)}</span><span style={{ display: "block", color: "var(--muted)", fontSize: 11 }}>{t(c.role)}</span></td>
                        <td><code style={{ fontSize: 11, overflowWrap: "anywhere" }}>{c.lightOklch}</code></td>
                        <td><code style={{ fontSize: 11, overflowWrap: "anywhere" }}>{c.darkOklch}</code></td>
                        <td className="zf-meta" style={{ fontSize: 11 }}>{t(c.contrastNote)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap", marginTop: "var(--s4)" }}>
              <span className="zf-chip" style={{ background: "color-mix(in oklch, var(--ok) 14%, transparent)", color: "var(--ok)", borderColor: "color-mix(in oklch, var(--ok) 28%, transparent)" }}>ok</span>
              <span className="zf-chip" style={{ background: "color-mix(in oklch, var(--error) 12%, transparent)", color: "var(--error)", borderColor: "color-mix(in oklch, var(--error) 28%, transparent)" }}>error</span>
              <span className="zf-chip" style={{ background: "color-mix(in oklch, var(--warn) 14%, transparent)", color: "var(--warn)", borderColor: "color-mix(in oklch, var(--warn) 28%, transparent)" }}>warn</span>
              <span className="zf-chip" style={{ background: "color-mix(in oklch, var(--run) 12%, transparent)", color: "var(--run)", borderColor: "color-mix(in oklch, var(--run) 28%, transparent)" }}>run</span>
            </div>

            <pre className="zf-code" style={{ marginTop: "var(--s4)" }}>{`--accent-soft: color-mix(in oklch, var(--accent) 12%, transparent)\n--sel-bg:     color-mix(in oklch, var(--fg) 4%, var(--surface))  /* seleção */\n--font-mono:  ui-monospace, "SF Mono", "JetBrains Mono", Menlo\n--measure:    118ch  /* largura de leitura */\n--rail-w:     236px\n--radius:     7px`}</pre>
          </div>

          <div>
            <h2 className="zf-h2" style={{ marginBottom: "var(--s3)" }}>{t("design.typeHeading")}</h2>
            <div className="zf-panel">
              <div className="zf-panel-bd" style={{ gap: "var(--s4)" }}>
                <div>
                  <p className="zf-micro">{t("design.typeH1Note")}</p>
                  <p className="zf-title" style={{ marginTop: 4 }}>zfrog --engine chromium --output json https://exemplo.com</p>
                </div>
                <div>
                  <p className="zf-micro">{t("design.typeBodyNote")}</p>
                  <p style={{ marginTop: 4 }}>{t("design.typeBodySample")}</p>
                </div>
                <div>
                  <p className="zf-micro">{t("design.typeMetaNote")}</p>
                  <p className="zf-meta" style={{ marginTop: 4 }}>2026-10-06 14:32:01 · dur: 1.2s · mem: 48MB · 142 {t("design.tokensExtracted")}</p>
                </div>
                <div style={{ display: "flex", gap: "var(--s3)", alignItems: "center", paddingTop: "var(--s3)", borderTop: "1px solid var(--border)" }}>
                  <span className="zf-num">0123456789 · tabular-nums</span>
                  <span className="zf-meta"><span className="zf-ok">✓ ok</span> · <span className="zf-error">✗ falha</span> · <span className="zf-warn">◐ aviso</span> · <span style={{ color: "var(--run)" }}>● rodando</span></span>
                </div>
              </div>
            </div>
          </div>

          <div className="zf-panel" data-od-id="ds-controls-preview">
            <div className="zf-panel-hd"><span className="zf-micro">controles · zf-* · live tokens</span><span className="zf-spacer" /><span className="zf-meta">OKLch</span></div>
            <div className="zf-panel-bd">
              <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
                <button className="zf-btn zf-btn--primary">primário</button>
                <button className="zf-btn">secundário</button>
                <button className="zf-btn zf-btn--ghost">ghost</button>
                <button className="zf-btn zf-btn--danger">danger</button>
              </div>
              <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
                <button className="zf-pill is-active">pill ativa</button>
                <button className="zf-pill">pill</button>
                <button className="zf-chip" aria-pressed={true}>chip ativo</button>
                <button className="zf-chip">chip</button>
              </div>
              <div style={{ display: "flex", gap: "var(--s3)", alignItems: "center" }}>
                <span className="zf-label">switch</span>
                <button className="zf-switch" aria-pressed={false} onClick={(e) => e.currentTarget.setAttribute("aria-pressed", String(e.currentTarget.getAttribute("aria-pressed") !== "true"))} aria-label="switch off" />
                <button className="zf-switch" aria-pressed={true} onClick={(e) => e.currentTarget.setAttribute("aria-pressed", String(e.currentTarget.getAttribute("aria-pressed") !== "true"))} aria-label="switch on" />
              </div>
              <div className="zf-field" style={{ maxWidth: "42ch" }}>
                <label className="zf-label">campo</label>
                <input className="zf-input" placeholder="placeholder" defaultValue="https://example.com.br" />
                <span className="zf-hint">hint · validação em aria-invalid</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "primitives" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s6)" }}>
          <div>
            <h2 className="zf-h2" style={{ marginBottom: "var(--s2)" }}>{t("design.primitivesHeading")}</h2>
            <p className="zf-meta" style={{ marginBottom: "var(--s4)" }}>{t("design.primitivesIntro")}</p>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
              <div className="zf-panel">
                <div className="zf-panel-hd"><span className="zf-micro">{t("design.gutCaption")}</span><span className="zf-spacer" /><span className="zf-meta">zf-rows · zf-run · Gut</span></div>
                <div className="zf-panel-bd" style={{ padding: 0 }}>
                  <div className="zf-rows" style={{ border: 0, borderRadius: 0 }}>
                    <button type="button" className="zf-run" aria-selected={true} style={{ cursor: "pointer" }}>
                      <span className="gutter">▍</span>
                      <span className="zf-num">14:02</span>
                      <span><Sym kind="ok" /></span>
                      <span className="cmd">jump</span>
                      <span className="dom">https://stripe.com</span>
                      <span className="zf-num" style={{ textAlign: "right" }}>820ms</span>
                      <span className="zf-meta" style={{ textAlign: "right" }}>200 OK</span>
                    </button>
                    <button type="button" className="zf-run" style={{ cursor: "pointer" }}>
                      <span className="gutter"></span>
                      <span className="zf-num">13:58</span>
                      <span><Sym kind="fail" /></span>
                      <span className="cmd">tongue</span>
                      <span className="dom">https://invalido.local</span>
                      <span className="zf-num" style={{ textAlign: "right" }}>2.1s</span>
                      <span className="zf-meta" style={{ textAlign: "right" }}>503 ERR</span>
                    </button>
                  </div>
                </div>
              </div>

              <div className="zf-panel">
                <div className="zf-panel-hd"><span className="zf-micro">{t("design.detailCaption")}</span></div>
                <div className="zf-panel-bd">
                  <DetailLine><span>{t("design.detailEngine")}</span></DetailLine>
                  <DetailLine><span>{t("design.detailPalette")}</span></DetailLine>
                  <div style={{ marginLeft: "3ch", display: "flex", gap: "var(--s2)", marginTop: 6 }}>
                    <Swatch colors={["#635bff", "#0a2540", "#00d4ff"]} />
                  </div>
                  <DetailLine><span>{t("design.detailTokens")}</span></DetailLine>
                  <CodeBlock code={["--status: 200", "--engine: chromium", "--colors: 12", "--typography: sohne, monospace"]} />
                </div>
              </div>

              <div className="zf-panel">
                <div className="zf-panel-hd"><span className="zf-micro">{t("design.spinnerCaption")}</span></div>
                <div className="zf-panel-bd">
                  <div style={{ display: "flex", gap: "var(--s5)", alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Spinner /> <code>Spinner</code></span>
                    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Sym kind="ok" /> <code>Sym(ok)</code></span>
                    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Sym kind="fail" /> <code>Sym(fail)</code></span>
                    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Sym kind="run" /> <code>Sym(run)</code></span>
                  </div>
                </div>
              </div>

              <div className="zf-panel">
                <div className="zf-panel-hd"><span className="zf-micro">{t("design.modalCaption")}</span></div>
                <div className="zf-panel-bd">
                  <button type="button" className="zf-btn zf-btn--primary" onClick={() => setModalOpen(true)}>{t("design.openModalBtn")}</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "forms" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          <h2 className="zf-h2">{t("design.formsHeading")}</h2>
          <div className="zf-panel">
            <div className="zf-panel-bd" style={{ gap: "var(--s5)" }}>
              <div className="zf-field" style={{ maxWidth: "50ch" }}>
                <label className="zf-label">{t("design.inputLabel")}</label>
                <input type="text" className="zf-input" value={demoInput} onChange={(e) => setDemoInput(e.target.value)} />
              </div>
              <div className="zf-field" style={{ maxWidth: "32ch" }}>
                <label className="zf-label">{t("design.selectLabel")}</label>
                <select className="zf-select" value={demoSelect} onChange={(e) => setDemoSelect(e.target.value)}>
                  <option value="jump">{t("design.optJump")}</option>
                  <option value="tongue">{t("design.optTongue")}</option>
                  <option value="croak">{t("design.optCroak")}</option>
                </select>
              </div>
              <div className="zf-field">
                <label className="zf-label">{t("design.tagsLabel")}</label>
                <div style={{ display: "flex", gap: "var(--s1)", flexWrap: "wrap" }}>
                  {demoTags.map((tag) => (
                    <span key={tag} className="zf-chip">#{tag}
                      <button type="button" style={{ marginLeft: 6, cursor: "pointer", background: "transparent", border: 0, color: "inherit" }} onClick={() => setDemoTags(demoTags.filter((x) => x !== tag))} aria-label={`remover ${tag}`}>×</button>
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: "var(--s2)", alignItems: "center", marginTop: 6 }}>
                  <input type="text" className="zf-input" style={{ flex: 1 }} placeholder={t("design.newTagPlaceholder")} value={newTag} onChange={(e) => setNewTag(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && newTag.trim()) { e.preventDefault(); if (!demoTags.includes(newTag.trim())) setDemoTags([...demoTags, newTag.trim()]); setNewTag("") } }} />
                  <button type="button" className="zf-btn" onClick={() => { if (newTag.trim() && !demoTags.includes(newTag.trim())) { setDemoTags([...demoTags, newTag.trim()]); setNewTag("") } }}>{t("design.addTagBtn")}</button>
                </div>
              </div>
              <div className="zf-field" style={{ maxWidth: "60ch" }}>
                <label className="zf-label">{t("design.textareaLabel")}</label>
                <textarea className="zf-textarea" rows={3} defaultValue={`# Flow config example\nsteps:\n  - extract: "tokens"\n  - snapshot: true`} />
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "symbols" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          <h2 className="zf-h2">{t("design.symbolsHeading")}</h2>
          <p className="zf-meta">{t("design.symbolsIntro")}</p>
          <div className="zf-panel" style={{ overflow: "hidden" }}>
            <table className="zf-table">
              <thead><tr><th style={{ width: "8ch" }}>{t("design.thGlyph")}</th><th>{t("design.thName")}</th><th>{t("design.thPurpose")}</th></tr></thead>
              <tbody>
                {SYMBOLS.map((s) => (
                  <tr key={s.name}>
                    <td style={{ fontSize: 15, color: "var(--accent)", textAlign: "center" }}>{s.sym}</td>
                    <td><code className="zf-num">{t(s.name)}</code></td>
                    <td className="zf-meta">{t(s.descKey)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === "a11y" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          <h2 className="zf-h2">{t("design.a11yHeading")}</h2>
          <div className="zf-panel">
            <div className="zf-panel-bd" style={{ gap: "var(--s4)" }}>
              <div>
                <h3 className="zf-h2" style={{ fontSize: 13 }}>{t("design.a11yContrast")}</h3>
                <p className="zf-meta" style={{ lineHeight: 1.6 }}>{t("design.a11yContrastBody")}</p>
              </div>
              <div>
                <h3 className="zf-h2" style={{ fontSize: 13 }}>{t("design.a11yMotion")}</h3>
                <p className="zf-meta" style={{ lineHeight: 1.6 }}>{t("design.a11yMotionBody")}</p>
              </div>
              <div>
                <h3 className="zf-h2" style={{ fontSize: 13, marginBottom: "var(--s2)" }}>{t("design.a11yShortcuts")}</h3>
                <table className="zf-table">
                  <thead><tr><th style={{ width: "18ch" }}>{t("design.thKey")}</th><th>{t("design.thAction")}</th></tr></thead>
                  <tbody>
                    <tr><td><code>j / k</code> · <code>↑ / ↓</code></td><td className="zf-meta">{t("design.shortcutNav")}</td></tr>
                    <tr><td><code>Enter</code></td><td className="zf-meta">{t("design.shortcutEnter")}</td></tr>
                    <tr><td><code>/</code></td><td className="zf-meta">{t("design.shortcutSlash")}</td></tr>
                    <tr><td><code>Ctrl + K</code></td><td className="zf-meta">{t("design.shortcutCtrlK")}</td></tr>
                    <tr><td><code>Esc</code></td><td className="zf-meta">{t("design.shortcutEsc")}</td></tr>
                    <tr><td><code>?</code></td><td className="zf-meta">{t("design.shortcutHelp")}</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

      {modalOpen && (
        <dialog open className="zf-modal" onClose={() => setModalOpen(false)} aria-label={t("design.modalTitle")} style={{ position: "fixed", inset: 0, margin: "auto" }}>
          <div className="zf-modal-hd"><span style={{ fontWeight: 600 }}>{t("design.modalTitle")}</span><span className="zf-spacer" /><button type="button" className="zf-btn zf-btn--ghost" onClick={() => setModalOpen(false)} aria-label="fechar">✗</button></div>
          <div className="zf-modal-bd">
            <p className="zf-meta" style={{ color: "var(--fg)", lineHeight: 1.6 }}>{t("design.modalBody")}</p>
            <pre className="zf-code" style={{ marginTop: "var(--s3)" }}>{`--tipo: modal zf\n--escape-close: true\n--focus-trapped: false\n--estilo: hairline + OKLch`}</pre>
          </div>
          <div className="zf-modal-ft">
            <button type="button" className="zf-btn" onClick={() => setModalOpen(false)}>{t("design.closeModalBtn")}</button>
          </div>
        </dialog>
      )}
    </div>
  )
}

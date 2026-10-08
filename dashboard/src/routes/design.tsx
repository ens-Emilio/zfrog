import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"
import {
  CodeBlock,
  DetailLine,
  Gut,
  Spinner,
  Swatch,
  Sym,
  TuiModal,
} from "@/components/ui/tui"
import { useMotion, useTheme } from "@/lib/prefs"
import { useT, type I18nKey } from "@/lib/i18n"

export const Route = createFileRoute("/design")({
  component: DesignPage,
})

interface ColorToken {
  name: I18nKey
  cssVar: string
  lightHex: string
  darkHex: string
  role: I18nKey
  contrastNote: I18nKey
}

const COLOR_TOKENS: ColorToken[] = [
  {
    name: "design.tokenPaper",
    cssVar: "--bg",
    lightHex: "#f4f2ec",
    darkHex: "#161512",
    role: "design.tokenPaperRole",
    contrastNote: "design.noteBase",
  },
  {
    name: "design.tokenPaperRaised",
    cssVar: "--bg-raised",
    lightHex: "#ebe8df",
    darkHex: "#1e1c17",
    role: "design.tokenPaperRaisedRole",
    contrastNote: "design.noteSurface",
  },
  {
    name: "design.tokenSelection",
    cssVar: "--sel-bg",
    lightHex: "#e6e3d9",
    darkHex: "#26241d",
    role: "design.tokenSelectionRole",
    contrastNote: "design.noteSurface",
  },
  {
    name: "design.tokenHairline",
    cssVar: "--line",
    lightHex: "#d9d6cc",
    darkHex: "#35332b",
    role: "design.tokenHairlineRole",
    contrastNote: "design.noteDivider",
  },
  {
    name: "design.tokenInk",
    cssVar: "--fg",
    lightHex: "#1d1c1a",
    darkHex: "#e6e3da",
    role: "design.tokenInkRole",
    contrastNote: "design.ratioAaa",
  },
  {
    name: "design.tokenTextSecondary",
    cssVar: "--fg-muted",
    lightHex: "#57544c",
    darkHex: "#aba79c",
    role: "design.tokenTextSecondaryRole",
    contrastNote: "design.ratioAa1",
  },
  {
    name: "design.tokenTextTertiary",
    cssVar: "--fg-dim",
    lightHex: "#6e6b62",
    darkHex: "#949084",
    role: "design.tokenTextTertiaryRole",
    contrastNote: "design.ratioUiAa",
  },
  {
    name: "design.tokenAccent",
    cssVar: "--accent",
    lightHex: "#4f6b3a",
    darkHex: "#93b27b",
    role: "design.tokenAccentRole",
    contrastNote: "design.ratioAa2",
  },
  {
    name: "design.tokenOk",
    cssVar: "--ok",
    lightHex: "#4f6b3a",
    darkHex: "#93b27b",
    role: "design.tokenOkRole",
    contrastNote: "design.ratioAa2",
  },
  {
    name: "design.tokenError",
    cssVar: "--error",
    lightHex: "#a8392f",
    darkHex: "#d0705f",
    role: "design.tokenErrorRole",
    contrastNote: "design.ratioAa3",
  },
  {
    name: "design.tokenWarn",
    cssVar: "--warn",
    lightHex: "#9a6a1c",
    darkHex: "#c99a55",
    role: "design.tokenWarnRole",
    contrastNote: "design.ratioAa4",
  },
]

const SYMBOLS: { sym: string; name: I18nKey; descKey: I18nKey }[] = [
  { sym: "▍", name: "design.symCursor", descKey: "design.symCursorDesc" },
  { sym: "✓", name: "design.symSuccess", descKey: "design.symSuccessDesc" },
  { sym: "✗", name: "design.symFailure", descKey: "design.symFailureDesc" },
  { sym: "·", name: "design.symSeparator", descKey: "design.symSeparatorDesc" },
  { sym: "…", name: "design.symRunning", descKey: "design.symRunningDesc" },
  { sym: "⎿", name: "design.symSubordination", descKey: "design.symSubordinationDesc" },
  { sym: "[x]", name: "design.symToggleOn", descKey: "design.symToggleOnDesc" },
  { sym: "[ ]", name: "design.symToggleOff", descKey: "design.symToggleOffDesc" },
  { sym: ">", name: "design.symPrompt", descKey: "design.symPromptDesc" },
  { sym: "+", name: "design.symDiffAdd", descKey: "design.symDiffAddDesc" },
  { sym: "-", name: "design.symDiffRemove", descKey: "design.symDiffRemoveDesc" },
  { sym: "~", name: "design.symDiffChange", descKey: "design.symDiffChangeDesc" },
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
    <div className="tui-col" style={{ paddingBottom: "3lh" }}>
      {/* Specimen header */}
      <div style={{ borderBottom: "1px solid var(--line)", paddingBottom: "1lh", marginBottom: "1lh" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "1ch" }}>
          <div>
            <h1 style={{ fontSize: "15px", fontWeight: 500, margin: 0 }}>
              {t("design.headerTitle")}
            </h1>
            <p style={{ color: "var(--fg-muted)", fontSize: "12px", marginTop: "0.25lh" }}>
              {t("design.headerSub")}
            </p>
          </div>
          <div style={{ display: "flex", gap: "1.5ch", alignItems: "baseline", fontSize: "12px" }}>
            <button type="button" className="tui-btn" onClick={toggleTheme}>
              [{t("design.themeLabel")}: {theme === "dark" ? t("design.themeDark") : t("design.themeLight")}]
            </button>
            <button
              type="button"
              className="tui-btn"
              onClick={() => setMotion(motion === "reduced" ? "full" : "reduced")}
            >
              [{t("design.motionLabel")}: {motion}]
            </button>
          </div>
        </div>
      </div>

      {/* Specimen internal tabs */}
      <div style={{ display: "flex", gap: "1.5ch", borderBottom: "1px solid var(--line)", paddingBottom: "0.5lh", marginBottom: "1.5lh" }}>
        {(["tokens", "primitives", "forms", "symbols", "a11y"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            className="tui-btn"
            style={{
              fontWeight: activeTab === tab ? 500 : 400,
              color: activeTab === tab ? "var(--accent)" : "var(--fg-muted)",
            }}
            onClick={() => setActiveTab(tab)}
          >
            {activeTab === tab ? `▍ ${tab}` : tab}
          </button>
        ))}
      </div>

      {/* Tab 1: color tokens and rhythm */}
      {activeTab === "tokens" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "2lh" }}>
          <div>
            <h2 style={{ fontSize: "14px", fontWeight: 500, marginBottom: "0.5lh" }}>
              {t("design.tokensHeading")}
            </h2>
            <p style={{ color: "var(--fg-muted)", fontSize: "12px", marginBottom: "1lh" }}>
              {t("design.tokensIntro")}
            </p>
            <table className="tui-table">
              <thead>
                <tr>
                  <th style={{ width: "3ch" }}>{t("design.thColor")}</th>
                  <th>{t("design.thVariable")}</th>
                  <th>{t("design.thNameRole")}</th>
                  <th>{t("design.thLight")}</th>
                  <th>{t("design.thDark")}</th>
                  <th>{t("design.thContrast")}</th>
                </tr>
              </thead>
              <tbody>
                {COLOR_TOKENS.map((c) => (
                  <tr key={c.cssVar}>
                    <td>
                      <span
                        style={{
                          display: "inline-block",
                          width: "12px",
                          height: "12px",
                          background: `var(${c.cssVar})`,
                          border: "1px solid var(--line)",
                        }}
                      />
                    </td>
                    <td>
                      <code>{c.cssVar}</code>
                    </td>
                    <td>
                      <span style={{ color: "var(--fg)" }}>{t(c.name)}</span>
                      <span style={{ display: "block", color: "var(--fg-dim)", fontSize: "11px" }}>{t(c.role)}</span>
                    </td>
                    <td>
                      <code>{c.lightHex}</code>
                    </td>
                    <td>
                      <code>{c.darkHex}</code>
                    </td>
                    <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>
                      {t(c.contrastNote)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <h2 style={{ fontSize: "14px", fontWeight: 500, marginBottom: "0.5lh" }}>
              {t("design.typeHeading")}
            </h2>
            <div className="tui-panel" style={{ display: "flex", flexDirection: "column", gap: "1lh" }}>
              <div>
                <p style={{ color: "var(--fg-dim)", fontSize: "11px" }}>{t("design.typeH1Note")}</p>
                <p style={{ fontSize: "15px", fontWeight: 500 }}>
                  zfrog --engine chromium --output json https://exemplo.com
                </p>
              </div>
              <div>
                <p style={{ color: "var(--fg-dim)", fontSize: "11px" }}>{t("design.typeBodyNote")}</p>
                <p style={{ fontSize: "13px" }}>
                  {t("design.typeBodySample")}
                </p>
              </div>
              <div>
                <p style={{ color: "var(--fg-dim)", fontSize: "11px" }}>{t("design.typeMetaNote")}</p>
                <p style={{ fontSize: "12px", color: "var(--fg-muted)" }}>
                  2026-10-06 14:32:01 · dur: 1.2s · mem: 48MB · 142 {t("design.tokensExtracted")}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: TUI primitives */}
      {activeTab === "primitives" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "2lh" }}>
          <div>
            <h2 style={{ fontSize: "14px", fontWeight: 500, marginBottom: "0.5lh" }}>
              {t("design.primitivesHeading")}
            </h2>
            <p style={{ color: "var(--fg-muted)", fontSize: "12px", marginBottom: "1lh" }}>
              {t("design.primitivesIntro")}
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: "1lh" }}>
              {/* Gut & Runrow */}
              <div className="tui-panel">
                <p style={{ color: "var(--fg-dim)", fontSize: "11px", marginBottom: "0.5lh" }}>
                  {t("design.gutCaption")}
                </p>
                <div className="rows">
                  <div className="runrow sel" style={{ cursor: "pointer" }}>
                    <Gut active />
                    <Sym kind="ok" />
                    <span className="t">14:02</span>
                    <span className="cmd">jump</span>
                    <span className="dom">https://stripe.com</span>
                    <span className="dur">820ms</span>
                    <span className="stat">200 OK</span>
                  </div>
                  <div className="runrow" style={{ cursor: "pointer" }}>
                    <Gut />
                    <Sym kind="fail" />
                    <span className="t">13:58</span>
                    <span className="cmd">tongue</span>
                    <span className="dom">https://invalido.local</span>
                    <span className="dur">2.1s</span>
                    <span className="stat">503 ERR</span>
                  </div>
                </div>
              </div>

              {/* DetailLine & CodeBlock */}
              <div className="tui-panel">
                <p style={{ color: "var(--fg-dim)", fontSize: "11px", marginBottom: "0.5lh" }}>
                  {t("design.detailCaption")}
                </p>
                <div className="detail">
                  <DetailLine>
                    <span>{t("design.detailEngine")}</span>
                  </DetailLine>
                  <DetailLine>
                    <span>{t("design.detailPalette")}</span>
                  </DetailLine>
                  <div style={{ marginLeft: "3ch", display: "flex", gap: "2ch", marginTop: "0.25lh" }}>
                    <Swatch colors={["#635bff", "#0a2540", "#00d4ff"]} />
                  </div>
                  <DetailLine>
                    <span>{t("design.detailTokens")}</span>
                  </DetailLine>
                  <CodeBlock
                    code={[
                      "--status: 200",
                      "--engine: chromium",
                      "--colors: 12",
                      "--typography: sohne, monospace",
                    ]}
                  />
                </div>
              </div>

              {/* Spinner & Sym */}
              <div className="tui-panel">
                <p style={{ color: "var(--fg-dim)", fontSize: "11px", marginBottom: "0.5lh" }}>
                  {t("design.spinnerCaption")}
                </p>
                <div style={{ display: "flex", gap: "3ch", alignItems: "center" }}>
                  <span style={{ display: "inline-flex", gap: "1ch", alignItems: "baseline" }}>
                    <Spinner /> <code>&lt;Spinner /&gt;</code>
                  </span>
                  <span style={{ display: "inline-flex", gap: "1ch", alignItems: "baseline" }}>
                    <Sym kind="ok" /> <code>Sym(ok)</code>
                  </span>
                  <span style={{ display: "inline-flex", gap: "1ch", alignItems: "baseline" }}>
                    <Sym kind="fail" /> <code>Sym(fail)</code>
                  </span>
                  <span style={{ display: "inline-flex", gap: "1ch", alignItems: "baseline" }}>
                    <Sym kind="run" /> <code>Sym(run)</code>
                  </span>
                </div>
              </div>

              {/* TuiModal trigger */}
              <div className="tui-panel">
                <p style={{ color: "var(--fg-dim)", fontSize: "11px", marginBottom: "0.5lh" }}>
                  {t("design.modalCaption")}
                </p>
                <button
                  type="button"
                  className="tui-btn"
                  onClick={() => setModalOpen(true)}
                >
                  {t("design.openModalBtn")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: forms & controls */}
      {activeTab === "forms" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5lh" }}>
          <h2 style={{ fontSize: "14px", fontWeight: 500 }}>
            {t("design.formsHeading")}
          </h2>
          <div className="tui-panel" style={{ display: "flex", flexDirection: "column", gap: "1lh" }}>
            <div>
              <label style={{ display: "block", color: "var(--fg-muted)", fontSize: "12px", marginBottom: "0.25lh" }}>
                {t("design.inputLabel")}
              </label>
              <input
                type="text"
                className="tui-input"
                style={{ width: "100%", maxWidth: "50ch" }}
                value={demoInput}
                onChange={(e) => setDemoInput(e.target.value)}
              />
            </div>

            <div>
              <label style={{ display: "block", color: "var(--fg-muted)", fontSize: "12px", marginBottom: "0.25lh" }}>
                {t("design.selectLabel")}
              </label>
              <select
                className="tui-select"
                value={demoSelect}
                onChange={(e) => setDemoSelect(e.target.value)}
              >
                <option value="jump">{t("design.optJump")}</option>
                <option value="tongue">{t("design.optTongue")}</option>
                <option value="croak">{t("design.optCroak")}</option>
              </select>
            </div>

            <div>
              <label style={{ display: "block", color: "var(--fg-muted)", fontSize: "12px", marginBottom: "0.25lh" }}>
                {t("design.tagsLabel")}
              </label>
              <div className="tui-tags" style={{ marginBottom: "0.5lh" }}>
                {demoTags.map((tag) => (
                  <span key={tag} className="tui-tag">
                    #{tag}
                    <button
                      type="button"
                      style={{ cursor: "pointer" }}
                      onClick={() => setDemoTags(demoTags.filter((t) => t !== tag))}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div style={{ display: "flex", gap: "1ch", alignItems: "baseline" }}>
                <input
                  type="text"
                  className="tui-input"
                  placeholder={t("design.newTagPlaceholder")}
                  value={newTag}
                  onChange={(e) => setNewTag(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newTag.trim()) {
                      e.preventDefault()
                      if (!demoTags.includes(newTag.trim())) {
                        setDemoTags([...demoTags, newTag.trim()])
                      }
                      setNewTag("")
                    }
                  }}
                />
                <button
                  type="button"
                  className="tui-btn"
                  onClick={() => {
                    if (newTag.trim() && !demoTags.includes(newTag.trim())) {
                      setDemoTags([...demoTags, newTag.trim()])
                      setNewTag("")
                    }
                  }}
                >
                  {t("design.addTagBtn")}
                </button>
              </div>
            </div>

            <div>
              <label style={{ display: "block", color: "var(--fg-muted)", fontSize: "12px", marginBottom: "0.25lh" }}>
                {t("design.textareaLabel")}
              </label>
              <textarea
                className="tui-textarea"
                rows={3}
                style={{ width: "100%", maxWidth: "60ch" }}
                defaultValue={`# Flow config example\nsteps:\n  - extract: "tokens"\n  - snapshot: true`}
              />
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: glyph and symbol matrix */}
      {activeTab === "symbols" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5lh" }}>
          <h2 style={{ fontSize: "14px", fontWeight: 500 }}>
            {t("design.symbolsHeading")}
          </h2>
          <p style={{ color: "var(--fg-muted)", fontSize: "12px" }}>
            {t("design.symbolsIntro")}
          </p>

          <table className="tui-table">
            <thead>
              <tr>
                <th style={{ width: "8ch" }}>{t("design.thGlyph")}</th>
                <th>{t("design.thName")}</th>
                <th>{t("design.thPurpose")}</th>
              </tr>
            </thead>
            <tbody>
              {SYMBOLS.map((s) => (
                <tr key={s.name}>
                  <td style={{ fontSize: "15px", color: "var(--accent)", textAlign: "center" }}>
                    {s.sym}
                  </td>
                  <td>
                    <code>{t(s.name)}</code>
                  </td>
                  <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>
                    {t(s.descKey)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 5: a11y & shortcuts */}
      {activeTab === "a11y" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5lh" }}>
          <h2 style={{ fontSize: "14px", fontWeight: 500 }}>
            {t("design.a11yHeading")}
          </h2>

          <div className="tui-panel" style={{ display: "flex", flexDirection: "column", gap: "1lh" }}>
            <div>
              <h3 style={{ fontSize: "13px", fontWeight: 500, marginBottom: "0.25lh" }}>
                {t("design.a11yContrast")}
              </h3>
              <p style={{ color: "var(--fg-muted)", fontSize: "12px", lineHeight: 1.5 }}>
                {t("design.a11yContrastBody")}
              </p>
            </div>

            <div>
              <h3 style={{ fontSize: "13px", fontWeight: 500, marginBottom: "0.25lh" }}>
                {t("design.a11yMotion")}
              </h3>
              <p style={{ color: "var(--fg-muted)", fontSize: "12px", lineHeight: 1.5 }}>
                {t("design.a11yMotionBody")}
              </p>
            </div>

            <div>
              <h3 style={{ fontSize: "13px", fontWeight: 500, marginBottom: "0.5lh" }}>
                {t("design.a11yShortcuts")}
              </h3>
              <table className="tui-table">
                <thead>
                  <tr>
                    <th style={{ width: "14ch" }}>{t("design.thKey")}</th>
                    <th>{t("design.thAction")}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><code>j / k</code> ou <code>↑ / ↓</code></td>
                    <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>{t("design.shortcutNav")}</td>
                  </tr>
                  <tr>
                    <td><code>Enter</code></td>
                    <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>{t("design.shortcutEnter")}</td>
                  </tr>
                  <tr>
                    <td><code>/</code></td>
                    <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>{t("design.shortcutSlash")}</td>
                  </tr>
                  <tr>
                    <td><code>Ctrl + K</code></td>
                    <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>{t("design.shortcutCtrlK")}</td>
                  </tr>
                  <tr>
                    <td><code>Esc</code></td>
                    <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>{t("design.shortcutEsc")}</td>
                  </tr>
                  <tr>
                    <td><code>?</code></td>
                    <td style={{ color: "var(--fg-muted)", fontSize: "12px" }}>{t("design.shortcutHelp")}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Demo modal */}
      <TuiModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={t("design.modalTitle")}
      >
        <p style={{ color: "var(--fg)", fontSize: "13px", lineHeight: 1.5 }}>
          {t("design.modalBody")}
        </p>
        <div style={{ marginTop: "1lh" }}>
          <CodeBlock
            code={[
              "--tipo: modal-tui",
              "--escape-close: true",
              "--focus-trapped: false",
              "--estilo: puro terminal",
            ]}
          />
        </div>
        <div style={{ marginTop: "1lh", display: "flex", justifyContent: "flex-end" }}>
          <button
            type="button"
            className="tui-btn"
            onClick={() => setModalOpen(false)}
          >
            {t("design.closeModalBtn")}
          </button>
        </div>
      </TuiModal>
    </div>
  )
}

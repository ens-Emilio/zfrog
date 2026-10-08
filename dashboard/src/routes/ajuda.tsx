import { createFileRoute } from "@tanstack/react-router"
import { MODES, MODE_ORDER } from "@/lib/labels"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"
import { TuiPanel } from "@/components/ui/tui"

const SHORTCUTS = [
  { key: "j / ↓", desc: "down" },
  { key: "k / ↑", desc: "up" },
  { key: "Enter", desc: "enter" },
  { key: "Esc", desc: "esc" },
  { key: "/", desc: "slash" },
  { key: "ctrl+k", desc: "ctrlK" },
  { key: "?", desc: "question" },
] as const

const CLI = [
  { cmd: "./zfrog dev", desc: "dev" },
  { cmd: "zfrog jump <url>", desc: "jump" },
  { cmd: "zfrog tongue <url> --selector <css>", desc: "tongue" },
  { cmd: "zfrog pond --search '<description>'", desc: "pond" },
  { cmd: "zfrog pond --reindex", desc: "reindex" },
  { cmd: "zfrog ask '<pergunta>'", desc: "ask" },
  { cmd: "zfrog compare-sites --site a --site b", desc: "compare" },
  { cmd: "zfrog dataset <dir>", desc: "dataset" },
  { cmd: "zfrog graph <dir>", desc: "graph" },
  { cmd: "zfrog arweave <dir>", desc: "arweave" },
] as const

function AjudaPage() {
  const t = useT()
  const toast = useToast()

  const copy = async (cmd: string) => {
    try {
      await navigator.clipboard.writeText(cmd)
      toast(t("ajuda.copiedToast"), "ok")
    } catch {
      toast(t("ajuda.copyErrorToast"), "err")
    }
  }

  return (
    <TuiPanel
      title={t("ajuda.title")}
      action={
        <span style={{ color: "var(--fg-dim)", fontSize: 11 }}>
          {t("ajuda.subtitle")}
        </span>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1.5lh", marginTop: "0.5lh" }}>
        {/* Keyboard shortcuts */}
        <div className="tui-panel">
          <div className="tui-panel-head">
            <span className="tui-panel-title">{t("ajuda.shortcutsTitle")}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.25lh", padding: "0.5lh 1ch" }}>
            {SHORTCUTS.map((s) => (
              <div key={s.key} className="flex items-baseline text-[12px]">
                <code style={{ minWidth: "14ch", color: "var(--fg)", fontWeight: 600 }}>{s.key}</code>
                <span style={{ color: "var(--fg-muted)" }}>{t(`ajuda.shortcut.${s.desc}`)}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Command line */}
        <div className="tui-panel">
          <div className="tui-panel-head">
            <span className="tui-panel-title">{t("ajuda.cliTitle")}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5lh", padding: "0.5lh 1ch" }}>
            {CLI.map((c) => (
              <div key={c.cmd} className="flex justify-between items-baseline text-[12px] border-b border-[var(--border-subtle)] pb-2">
                <div>
                  <code style={{ color: "var(--fg)", fontWeight: 600 }}>{c.cmd}</code>
                  <p style={{ color: "var(--fg-dim)", marginTop: "0.125lh" }}>{t(`ajuda.cli.${c.desc}`)}</p>
                </div>
                <button
                  type="button"
                  className="tui-btn"
                  onClick={() => void copy(c.cmd)}
                  style={{ fontSize: 11 }}
                >
                  {t("ajuda.copy")}
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Modes guide */}
        <div className="tui-panel">
          <div className="tui-panel-head">
            <span className="tui-panel-title">{t("ajuda.modesTitle.before")}{MODE_ORDER.length}{t("ajuda.modesTitle.after")}</span>
          </div>
          <div className="overflow-x-auto p-2">
            <table className="tui-table w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border)] text-[var(--fg-dim)] uppercase text-[10px]">
                  <th className="p-1 text-left">{t("ajuda.colMode")}</th>
                  <th className="p-1 text-left">{t("ajuda.colWhen")}</th>
                  <th className="p-1 text-left">{t("ajuda.colOutput")}</th>
                </tr>
              </thead>
              <tbody>
                {MODE_ORDER.map((id) => {
                  const mode = MODES[id]
                  return (
                    <tr key={id} className="border-b border-[var(--border-subtle)]">
                      <td style={{ fontWeight: 600, color: "var(--fg)", whiteSpace: "nowrap" }} className="p-1">
                        {t(mode.label)}
                      </td>
                      <td className="p-1">{t(mode.when)}</td>
                      <td style={{ color: "var(--fg-dim)" }} className="p-1">{t(mode.output)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </TuiPanel>
  )
}

export const Route = createFileRoute("/ajuda")({
  component: AjudaPage,
})

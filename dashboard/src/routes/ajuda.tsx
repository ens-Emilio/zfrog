import { createFileRoute } from "@tanstack/react-router"
import { MODES, MODE_ORDER } from "@/lib/labels"
import { useToast } from "@/components/ToastRegion"
import { useT } from "@/lib/i18n"

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
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("ajuda.title")}</h1>
        <span className="zf-meta">{t("ajuda.subtitle")}</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
        <div className="zf-panel">
          <div className="zf-panel-hd"><span className="zf-micro">{t("ajuda.shortcutsTitle")}</span></div>
          <div className="zf-panel-bd" style={{ padding: 0 }}>
            <div className="zf-list">
              {SHORTCUTS.map((s) => (
                <div key={s.key} style={{ display: "flex", alignItems: "baseline", gap: "var(--s3)" }}>
                  <kbd style={{ minWidth: "14ch" }}>{s.key}</kbd>
                  <span className="zf-meta">{t(`ajuda.shortcut.${s.desc}`)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="zf-panel">
          <div className="zf-panel-hd"><span className="zf-micro">{t("ajuda.cliTitle")}</span></div>
          <div className="zf-panel-bd" style={{ padding: 0 }}>
            <div className="zf-list">
              {CLI.map((c) => (
                <div key={c.cmd} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--s3)" }}>
                  <div style={{ minWidth: 0 }}>
                    <code style={{ color: "var(--fg)", fontWeight: 600 }}>{c.cmd}</code>
                    <div className="zf-meta" style={{ marginTop: 2 }}>{t(`ajuda.cli.${c.desc}`)}</div>
                  </div>
                  <button type="button" className="zf-btn" onClick={() => void copy(c.cmd)}>{t("ajuda.copy")}</button>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="zf-panel">
          <div className="zf-panel-hd"><span className="zf-micro">{t("ajuda.modesTitle.before")}{MODE_ORDER.length}{t("ajuda.modesTitle.after")}</span></div>
          <div style={{ overflowX: "auto" }}>
            <table className="zf-table">
              <thead>
                <tr>
                  <th>{t("ajuda.colMode")}</th>
                  <th>{t("ajuda.colWhen")}</th>
                  <th>{t("ajuda.colOutput")}</th>
                </tr>
              </thead>
              <tbody>
                {MODE_ORDER.map((id) => {
                  const mode = MODES[id]
                  return (
                    <tr key={id}>
                      <td style={{ fontWeight: 600, color: "var(--fg)", whiteSpace: "nowrap" }}>{t(mode.label)}</td>
                      <td>{t(mode.when)}</td>
                      <td className="zf-muted">{t(mode.output)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  )
}

export const Route = createFileRoute("/ajuda")({
  component: AjudaPage,
})

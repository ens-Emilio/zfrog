"use client"
import { useState } from "react"
import { MODES, MODE_ORDER } from "@/lib/labels"
import { Topbar } from "@/components/Navbar"
import { Icon } from "@/lib/icons"
import { useToast } from "@/components/ToastRegion"

/** The terminal equivalents of what the panel does, as the design system lists them. */
const CLI = [
  { cmd: "./zfrog dev", desc: "Sobe a API e o worker em modo de desenvolvimento." },
  { cmd: "./zfrog serve", desc: "Sobe a API e o worker em modo de produção." },
  { cmd: "./zfrog probe https://exemplo.com", desc: "Analisa um site sem baixar, para ver o que ele tem." },
  { cmd: "./zfrog jobs list", desc: "Lista as execuções recentes no terminal." },
]

const TH_STYLE: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid var(--glass-border)",
  fontWeight: 600,
  textAlign: "left",
}

const TD_STYLE: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid var(--glass-border)",
  color: "var(--text-2)",
  verticalAlign: "top",
}

export default function AjudaPage() {
  const toast = useToast()
  const [openFaq, setOpenFaq] = useState<string | null>(null)

  const copy = async (cmd: string) => {
    try {
      await navigator.clipboard.writeText(cmd)
      toast("Comando copiado.")
    } catch {
      toast("Não foi possível copiar o comando.", "err")
    }
  }

  return (
    <div className="view-grid">
      <Topbar
        title="Ajuda"
        description="O que cada modo entrega e como operar o zfrog pelo terminal."
      />

      <div className="card">
        <h2 className="section-title" style={{ marginBottom: "var(--sp-2)" }}>
          Qual modo escolher?
        </h2>
        <p className="card-sub" style={{ marginBottom: "var(--sp-5)" }}>
          Encontre o que você precisa na coluna da esquerda e veja o que cada modo entrega.
        </p>
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "var(--fs-13)",
              minWidth: 520,
            }}
          >
            <caption className="hint" style={{ textAlign: "left", paddingBottom: "var(--sp-3)" }}>
              {MODE_ORDER.length} modos disponíveis.
            </caption>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--text-3)" }}>
                <th scope="col" style={TH_STYLE}>
                  Modo
                </th>
                <th scope="col" style={TH_STYLE}>
                  Escolha quando
                </th>
                <th scope="col" style={TH_STYLE}>
                  Você recebe
                </th>
              </tr>
            </thead>
            <tbody>
              {MODE_ORDER.map((id) => {
                const mode = MODES[id]
                return (
                  <tr key={id}>
                    <th scope="row" style={{ ...TH_STYLE, color: "var(--text-1)", whiteSpace: "nowrap" }}>
                      <span className="od-row" style={{ ["--od-gap" as string]: "8px" }}>
                        <Icon name={mode.icon} size="sm" />
                        {mode.label}
                      </span>
                    </th>
                    <td style={TD_STYLE}>{mode.when}</td>
                    <td style={TD_STYLE}>{mode.output}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="two-col">
        <div className="card">
          <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
            Comandos da linha de comando
          </h3>
          <p className="card-sub" style={{ marginBottom: "var(--sp-4)" }}>
            As mesmas tarefas do painel, no terminal.
          </p>
          <div className="stack-sm">
            {CLI.map((item) => (
              <div key={item.cmd}>
                <div className="od-row" style={{ ["--od-gap" as string]: "12px", alignItems: "flex-start" }}>
                  <code
                    className="od-fill mono"
                    style={{ color: "var(--accent-strong)", overflowWrap: "anywhere" }}
                  >
                    {item.cmd}
                  </code>
                  <button
                    className="btn btn-sm btn-ghost icon-btn"
                    type="button"
                    onClick={() => void copy(item.cmd)}
                    aria-label={`Copiar comando ${item.cmd}`}
                  >
                    <Icon name="i-copy" size="sm" />
                  </button>
                </div>
                <p className="hint" style={{ marginBottom: "var(--sp-3)" }}>
                  {item.desc}
                </p>
              </div>
            ))}
          </div>
        </div>

        <div className="stack-md">
          <div className="accordion">
            <button
              className="acc-trigger"
              type="button"
              aria-expanded={openFaq === "faq-1"}
              aria-controls="faq-1"
              onClick={() => setOpenFaq(openFaq === "faq-1" ? null : "faq-1")}
            >
              <Icon name="i-help" />
              O servidor está fora do ar. O que faço?
              <Icon name="i-chevron" />
            </button>
            <div className="acc-panel" id="faq-1" hidden={openFaq !== "faq-1"}>
              Abra o terminal na pasta do projeto e rode <span className="mono">./zfrog dev</span>. O indicador no
              rodapé da barra lateral fica verde quando a API responde. Se preferir produção, use{" "}
              <span className="mono">./zfrog serve</span>.
            </div>
          </div>

          <div className="accordion">
            <button
              className="acc-trigger"
              type="button"
              aria-expanded={openFaq === "faq-2"}
              aria-controls="faq-2"
              onClick={() => setOpenFaq(openFaq === "faq-2" ? null : "faq-2")}
            >
              <Icon name="i-help" />
              O site veio vazio ou incompleto
              <Icon name="i-chevron" />
            </button>
            <div className="acc-panel" id="faq-2" hidden={openFaq !== "faq-2"}>
              Provavelmente é um site que monta a página com JavaScript. Troque para o modo{" "}
              <strong>Site com JavaScript</strong>, que abre a página em um navegador de verdade antes de salvar.
            </div>
          </div>

          <div className="accordion">
            <button
              className="acc-trigger"
              type="button"
              aria-expanded={openFaq === "faq-3"}
              aria-controls="faq-3"
              onClick={() => setOpenFaq(openFaq === "faq-3" ? null : "faq-3")}
            >
              <Icon name="i-help" />
              Uma execução falhou com erro 403 ou 429
              <Icon name="i-chevron" />
            </button>
            <div className="acc-panel" id="faq-3" hidden={openFaq !== "faq-3"}>
              Erro 403 costuma ser bloqueio do site; erro 429 é excesso de requisições. Reduza a concorrência em
              Configurações ou cadastre um proxy.
            </div>
          </div>

          <div className="accordion">
            <button
              className="acc-trigger"
              type="button"
              aria-expanded={openFaq === "faq-4"}
              aria-controls="faq-4"
              onClick={() => setOpenFaq(openFaq === "faq-4" ? null : "faq-4")}
            >
              <Icon name="i-help" />
              Preciso repetir a captura de um site inteiro
              <Icon name="i-chevron" />
            </button>
            <div className="acc-panel" id="faq-4" hidden={openFaq !== "faq-4"}>
              Use o modo <strong>Só o que mudou</strong>: ele compara com a última cópia e baixa apenas as páginas
              alteradas. O histórico fica em Snapshots, onde também é possível comparar duas versões.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

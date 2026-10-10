import { useEffect, useRef } from "react"

export interface SlashCommand {
  cmd: string
  args: string
  desc: string
  fill: string
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: "/jump", args: "<url>", desc: "Inspecionar site — screenshot, tokens e WCAG", fill: "/jump https://" },
  { cmd: "/tongue", args: "<url>", desc: "Variante do inspector (extração de componente)", fill: "/tongue https://" },
  { cmd: "/comparar", args: "<a> <b>", desc: "Diff visual e de tokens entre dois domínios", fill: "/comparar linear.app notion.so" },
  { cmd: "/pond", args: "[termo]", desc: "Buscar na coleção de referências", fill: "/pond dashboards escuros" },
  { cmd: "/busca", args: "[termo]", desc: "Busca fulltext/semântica no acervo com score", fill: "/busca design tokens" },
  { cmd: "/chat", args: "[pergunta]", desc: "Perguntar ao acervo (RAG local)", fill: "/chat o que é zfrog?" },
  { cmd: "/datasets", args: "", desc: "Listar datasets locais e tabelas", fill: "/datasets" },
  { cmd: "/grafo", args: "[empresa]", desc: "Grafo competitivo — nós e arestas", fill: "/grafo acme" },
  { cmd: "/precos", args: "", desc: "Inteligência e histórico de preços", fill: "/precos" },
  { cmd: "/captura", args: "", desc: "Abrir fluxo de captura e sitemaps", fill: "/captura" },
  { cmd: "/qualidade", args: "", desc: "Checks Arweave / IPFS / validação", fill: "/qualidade" },
  { cmd: "/workers", args: "", desc: "Fila e dispatch de jobs", fill: "/workers" },
  { cmd: "/fluxos", args: "", desc: "Automações e pipelines", fill: "/fluxos" },
  { cmd: "/biblioteca", args: "", desc: "Abrir Biblioteca (hub do acervo)", fill: "/biblioteca" },
  { cmd: "/operacao", args: "", desc: "Abrir Operação (hub de execução)", fill: "/operacao" },
  { cmd: "/ajuda", args: "", desc: "Guia completo de comandos", fill: "/ajuda" },
  { cmd: "/config", args: "", desc: "Tema, idioma e configurações", fill: "/config" },
]

interface SlashCommandsMenuProps {
  open: boolean
  filter: string
  selectedIdx: number
  onSelect: (cmd: SlashCommand) => void
  onHoverIdx: (idx: number) => void
}

export function SlashCommandsMenu({
  open,
  filter,
  selectedIdx,
  onSelect,
  onHoverIdx,
}: SlashCommandsMenuProps) {
  const listRef = useRef<HTMLDivElement>(null)

  const needle = filter.toLowerCase().replace(/^\//, "").split(" ")[0]
  const items = SLASH_COMMANDS.filter(
    (c) =>
      !needle ||
      c.cmd.toLowerCase().includes(needle) ||
      c.desc.toLowerCase().includes(needle)
  )

  useEffect(() => {
    if (listRef.current && listRef.current.children[selectedIdx]) {
      ;(listRef.current.children[selectedIdx] as HTMLElement).scrollIntoView({
        block: "nearest",
      })
    }
  }, [selectedIdx])

  if (!open) return null

  return (
    <div className="zf-slash open" role="listbox" aria-label="Comandos rápidos">
      <div className="zf-slash-head">
        <span>Comandos — {items.length}</span>
        <span style={{ fontSize: "11px", textTransform: "none", letterSpacing: 0 }}>
          ↑↓ · ↵ selecionar · esc fechar
        </span>
      </div>

      <div ref={listRef}>
        {items.map((c, i) => (
          <button
            key={c.cmd}
            type="button"
            className={`zf-cmd ${i === selectedIdx ? "sel" : ""}`}
            role="option"
            aria-selected={i === selectedIdx}
            onMouseDown={(e) => {
              e.preventDefault()
              onSelect(c)
            }}
            onMouseEnter={() => onHoverIdx(i)}
          >
            <span className="zf-cmd-ic">/</span>
            <span className="zf-cmd-main">
              <strong>
                {c.cmd}{" "}
                <span style={{ color: "var(--fg-dim)", fontWeight: 400 }}>
                  {c.args}
                </span>
              </strong>
              <span>{c.desc}</span>
            </span>
            <span className="zf-cmd-k">{c.cmd}</span>
          </button>
        ))}

        {!items.length && (
          <div
            className="small"
            style={{ padding: "12px", color: "var(--fg-dim)" }}
          >
            Nenhum comando correspondente para “{needle}”.
          </div>
        )}
      </div>
    </div>
  )
}

import { useEffect, useRef } from "react"

export interface SlashCommand {
  cmd: string
  args: string
  desc: string
  fill: string
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: "/jump", args: "<url>", desc: "Inspecionar site — captura e análise", fill: "/jump https://" },
  { cmd: "/tongue", args: "<url>", desc: "Inspecionar com extração de componentes", fill: "/tongue https://" },
  { cmd: "/comparar", args: "<url> <url>", desc: "Comparar duas URLs lado a lado", fill: "/comparar " },
  { cmd: "/pond", args: "[busca]", desc: "Buscar na coleção de referências", fill: "/pond " },
  { cmd: "/busca", args: "[termo]", desc: "Busca no acervo com relevância", fill: "/busca " },
  { cmd: "/chat", args: "[pergunta]", desc: "Perguntar ao seu acervo", fill: "/chat " },
  { cmd: "/datasets", args: "", desc: "Listar dados disponíveis", fill: "/datasets" },
  { cmd: "/grafo", args: "[termo]", desc: "Explorar relações e conexões", fill: "/grafo " },
  { cmd: "/precos", args: "", desc: "Ver histórico e variação de preços", fill: "/precos" },
  { cmd: "/captura", args: "", desc: "Abrir captura de sites", fill: "/captura" },
  { cmd: "/qualidade", args: "", desc: "Verificar qualidade do acervo", fill: "/qualidade" },
  { cmd: "/workers", args: "", desc: "Ver fila de processamento", fill: "/workers" },
  { cmd: "/fluxos", args: "", desc: "Ver fluxos e automações", fill: "/fluxos" },
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
                <span style={{ color: "var(--muted)", fontWeight: 400 }}>
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
            style={{ padding: "12px", color: "var(--muted)" }}
          >
            Nenhum comando correspondente para “{needle}”.
          </div>
        )}
      </div>
    </div>
  )
}

import { useEffect, useRef, useState, type ReactNode } from "react"

/* Symbols from DESIGN.md §5.5 — the full set. */
export const SYM = { ok: "✓", fail: "✗", on: "●", off: "○", sub: "⎿" } as const

/** Marker column: invisible until the row is selected (▍). */
export function Gut({ active }: { active?: boolean }) {
  return <span className={`gut${active ? " sel" : ""}`} aria-hidden="true" />
}

/** Status symbol, colored by outcome. Never a filled background. */
export function Sym({ kind, ok }: { kind: "ok" | "fail" | "run"; ok?: boolean }) {
  return <span className={`sym ${kind}${ok ? " ok" : ""}`}>{kind === "ok" ? SYM.ok : kind === "fail" ? SYM.fail : ""}</span>
}

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

/** Braille spinner. Stops out of focus and under reduced-motion (§5.6). */
export function Spinner() {
  const [frame, setFrame] = useState(0)
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return
    let stopped = false
    let timer: number | undefined
    const start = () => {
      if (timer || stopped) return
      timer = window.setInterval(() => setFrame((f) => (f + 1) % FRAMES.length), 80)
    }
    const stop = () => {
      clearInterval(timer)
      timer = undefined
    }
    const onVis = () => (document.hidden ? stop() : start())
    start()
    document.addEventListener("visibilitychange", onVis)
    return () => {
      stopped = true
      stop()
      document.removeEventListener("visibilitychange", onVis)
    }
  }, [])
  return <span className="spin" aria-label="running">{FRAMES[frame]}</span>
}

/** Real extracted colors, inline in text (§4). */
export function Swatch({ colors, n = 5 }: { colors: string[]; n?: number }) {
  if (!colors.length) return null
  return (
    <span className="sw" aria-label={`${Math.min(colors.length, n)} cores`}>
      {colors.slice(0, n).map((c, i) => (
        <i key={i} style={{ background: c }} />
      ))}
    </span>
  )
}

/** Detail subordinate to the line above (⎿). */
export function DetailLine({ kind, children }: { kind?: "err"; children: ReactNode }) {
  return (
    <span className={`dline${kind === "err" ? " err" : ""}`}>
      <span className="mark">{SYM.sub}</span>
      {children}
    </span>
  )
}

/** CSS token block with copy. */
export function CodeBlock({ code }: { code: string[] }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => clearInterval(timer.current), [])
  const copy = () => {
    navigator.clipboard?.writeText(":root {\n  " + code.join("\n  ") + "\n}")
    setCopied(true)
    timer.current = window.setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="codeblock">
      <span
        className="copy"
        role="button"
        tabIndex={0}
        onClick={(e) => { e.stopPropagation(); copy() }}
        onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); copy() } }}
      >
        {copied ? "copiado ✓" : "copiar"}
      </span>
      {"\n"}
      {code.map((line, i) => {
        const idx = line.indexOf(":")
        return (
          <span key={i}>
            <span className="k">{line.slice(0, idx + 1)}</span>
            <span className="v">{line.slice(idx + 1)}</span>
            {"\n"}
          </span>
        )
      })}
    </div>
  )
}

/** Fixed prompt at the base: `❯ comando`. The main action of the interface. */
export function Prompt({
  onRun,
  placeholder,
  autoFocus,
}: {
  onRun: (cmd: string) => void
  placeholder?: string
  autoFocus?: boolean
}) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (autoFocus) ref.current?.focus()
  }, [autoFocus])
  return (
    <span className="tui-prompt">
      <span className="caret">❯</span>
      <input
        ref={ref}
        type="text"
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        aria-label="comando"
        onKeyDown={(e) => {
          if (e.key === "Enter") onRun(e.currentTarget.value)
        }}
      />
    </span>
  )
}

/** TUI modal dialog. Monospace box, sharp borders, no glass or radius. */
export function TuiModal({
  open,
  title,
  children,
  onClose,
}: {
  open: boolean
  title: string
  children: ReactNode
  onClose: () => void
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="tui-modal-scrim"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
    >
      <div className="tui-modal-box">
        <div className="tui-modal-head">
          <h2>{title}</h2>
          <button type="button" className="tui-btn" onClick={onClose} aria-label="fechar">
            [esc / fechar]
          </button>
        </div>
        <div className="tui-modal-body">{children}</div>
      </div>
    </div>
  )
}

/** TUI panel container with 1px border and uppercase header. */
export function TuiPanel({
  title,
  action,
  children,
  className,
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`tui-panel ${className ?? ""}`.trim()}>
      {title && (
        <header className="tui-panel-head">
          <h2 className="tui-panel-title">{title}</h2>
          {action && <div className="tui-panel-action">{action}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export interface ComboboxOption {
  value: string
  label: string
  detail?: string
}

/** TUI Combobox with inline filter and keyboard navigation, replacing native <select>. */
export function TuiCombobox({
  value,
  onChange,
  options,
  placeholder = "select…",
  emptyLabel = "no options found",
  className,
}: {
  value: string
  onChange: (val: string) => void
  options: ComboboxOption[]
  placeholder?: string
  emptyLabel?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState("")
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [])

  const filtered = options.filter(
    (o) =>
      o.label.toLowerCase().includes(filter.toLowerCase()) ||
      (o.detail && o.detail.toLowerCase().includes(filter.toLowerCase())),
  )

  const selectedOpt = options.find((o) => o.value === value)

  return (
    <div className={`tui-combobox-wrap ${className ?? ""}`.trim()} ref={ref}>
      <button
        type="button"
        className="tui-btn"
        onClick={() => {
          setOpen((v) => !v)
          setFilter("")
        }}
        aria-expanded={open}
      >
        [ {selectedOpt ? selectedOpt.label : placeholder} ▾ ]
      </button>

      {open && (
        <div className="tui-combobox-menu">
          <div style={{ padding: "0.25lh 1ch", borderBottom: "1px solid var(--border)" }}>
            <input
              type="text"
              className="tui-input"
              placeholder="filtrar…"
              value={filter}
              autoFocus
              onChange={(e) => setFilter(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setOpen(false)
                if (e.key === "Enter" && filtered[0]) {
                  onChange(filtered[0].value)
                  setOpen(false)
                }
              }}
            />
          </div>
          {filtered.length === 0 ? (
            <div style={{ padding: "0.5lh 1ch", color: "var(--fg-dim)" }}>
              {emptyLabel}
            </div>
          ) : (
            filtered.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`tui-combobox-item ${opt.value === value ? "selected" : ""}`}
                onClick={() => {
                  onChange(opt.value)
                  setOpen(false)
                }}
              >
                <span>{opt.label}</span>
                {opt.detail && (
                  <span style={{ color: "var(--fg-dim)", marginLeft: "1ch", fontSize: "10px" }}>
                    {opt.detail}
                  </span>
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

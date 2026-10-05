"use client"

import * as React from "react"
import { Check, ChevronDown } from "lucide-react"
import { Icon, type IconName } from "@/lib/icons"

export interface SelectOption {
  value: string
  label: string
  /** Ícone opcional à esquerda do rótulo. */
  icon?: IconName
  /** Linha de apoio abaixo do rótulo, para opções que precisam de contexto. */
  hint?: string
  /** Agrupa a opção sob um rótulo. Opções sem grupo ficam no topo, sem cabeçalho. */
  group?: string
}

export interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  label?: string
  hint?: string
  /** Texto do gatilho quando nada está selecionado. */
  placeholder?: string
  id?: string
  disabled?: boolean
  className?: string
  /** Largura mínima do painel; útil quando o gatilho é estreito e os rótulos são longos. */
  panelMinWidth?: number
}

/**
 * Dropdown do painel.
 *
 * Existe porque o `<select>` nativo desenha o popup com a cara do sistema
 * operacional, e o que dá para estilizar nele é fundo, cor e padding — nada de
 * raio, ícone, agrupamento ou animação. Num painel escuro o menu saía claro, com a
 * seleção no azul do sistema. CSS não resolve isso; a única saída é o listbox.
 *
 * O que ele precisa acertar para valer a troca (um controle nativo já vem com
 * tudo isto de graça): teclado, foco e leitura por leitor de tela. Segue o padrão
 * WAI-ARIA de combobox "select-only":
 *
 * - gatilho com `role="combobox"`, `aria-expanded` e `aria-controls`;
 * - painel com `role="listbox"`, opções com `role="option"` e `aria-selected`;
 * - a opção ativa é anunciada por `aria-activedescendant`, então o foco **não**
 *   sai do gatilho enquanto se navega — é o que faz o leitor de tela ler a opção
 *   sob o cursor em vez de perder o contexto;
 * - setas, Home/End, Enter/Espaço, Esc, Tab e busca por digitação;
 * - clicar fora fecha, e o foco volta para o gatilho.
 */
export function Select({
  value,
  onChange,
  options,
  label,
  hint,
  placeholder = "Selecione…",
  id,
  disabled,
  className,
  panelMinWidth,
}: SelectProps) {
  const [open, setOpen] = React.useState(false)
  const [active, setActive] = React.useState(0)
  const rootRef = React.useRef<HTMLDivElement>(null)
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const listRef = React.useRef<HTMLDivElement>(null)
  const typed = React.useRef({ text: "", at: 0 })

  const reactId = React.useId()
  const listId = `${id ?? reactId}-list`
  const optionId = (index: number) => `${listId}-opt-${index}`

  const selectedIndex = options.findIndex((option) => option.value === value)
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined

  // Abre já na opção escolhida: abrir no topo obriga a navegar até o que já está
  // selecionado só para conferir.
  const openPanel = () => {
    if (disabled) return
    setActive(selectedIndex >= 0 ? selectedIndex : 0)
    setOpen(true)
  }

  const close = (refocus = true) => {
    setOpen(false)
    if (refocus) triggerRef.current?.focus()
  }

  const commit = (index: number) => {
    const option = options[index]
    if (!option) return
    onChange(option.value)
    close()
  }

  React.useEffect(() => {
    if (!open) return

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("pointerdown", onPointerDown)
    return () => document.removeEventListener("pointerdown", onPointerDown)
  }, [open])

  // Mantém a opção ativa visível quando a navegação passa da área do painel.
  React.useEffect(() => {
    if (!open) return
    const node = listRef.current?.querySelector<HTMLElement>(`#${CSS.escape(optionId(active))}`)
    node?.scrollIntoView({ block: "nearest" })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a lista muda com `active`; o id já a identifica
  }, [open, active])

  const move = (delta: number) => {
    if (options.length === 0) return
    setActive((current) => (current + delta + options.length) % options.length)
  }

  /** Busca por digitação: a primeira letra salta para a próxima opção que começa com ela. */
  const typeAhead = (key: string, at: number) => {
    const buffer = at - typed.current.at > 800 ? key : typed.current.text + key
    typed.current = { text: buffer, at }

    const needle = buffer.toLowerCase()
    const from = options.findIndex((option, index) => index > active && option.label.toLowerCase().startsWith(needle))
    const index = from >= 0 ? from : options.findIndex((option) => option.label.toLowerCase().startsWith(needle))
    if (index >= 0) setActive(index)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault()
        if (!open) openPanel()
        else move(1)
        return
      case "ArrowUp":
        event.preventDefault()
        if (!open) openPanel()
        else move(-1)
        return
      case "Home":
        if (!open) return
        event.preventDefault()
        setActive(0)
        return
      case "End":
        if (!open) return
        event.preventDefault()
        setActive(options.length - 1)
        return
      case "Enter":
      case " ":
        event.preventDefault()
        if (open) commit(active)
        else openPanel()
        return
      case "Escape":
        if (!open) return
        event.preventDefault()
        close()
        return
      case "Tab":
        if (open) setOpen(false)
        return
      default:
        if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
          if (!open) openPanel()
          typeAhead(event.key, event.timeStamp)
        }
    }
  }

  const renderOption = (option: SelectOption, index: number) => {
    const isActive = index === active
    const isSelected = option.value === value
    return (
      <div
        key={option.value}
        id={optionId(index)}
        role="option"
        aria-selected={isSelected}
        className={`select-item${isActive ? " is-active" : ""}${isSelected ? " is-selected" : ""}`}
        onPointerMove={() => setActive(index)}
        onClick={() => commit(index)}
      >
        {option.icon && <Icon name={option.icon} size="sm" />}
        <span className="select-item-text">
          <span className="select-item-label">{option.label}</span>
          {option.hint && <span className="select-item-hint">{option.hint}</span>}
        </span>
        {isSelected && <Check className="ic ic-sm select-item-check" aria-hidden="true" />}
      </div>
    )
  }

  return (
    <div className={`field${className ? ` ${className}` : ""}`} ref={rootRef}>
      {label && (
        <span className="label" id={`${listId}-label`}>
          {label}
        </span>
      )}

      <button
        type="button"
        ref={triggerRef}
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-haspopup="listbox"
        aria-labelledby={label ? `${listId}-label` : undefined}
        aria-label={label ? undefined : placeholder}
        aria-activedescendant={open && options.length > 0 ? optionId(active) : undefined}
        disabled={disabled}
        className="select-trigger"
        onClick={() => (open ? close(false) : openPanel())}
        onKeyDown={onKeyDown}
      >
        {selected?.icon && <Icon name={selected.icon} size="sm" />}
        <span className={`select-trigger-label${selected ? "" : " is-placeholder"}`}>
          {selected?.label ?? placeholder}
        </span>
        <ChevronDown className={`ic ic-sm select-trigger-chevron${open ? " is-open" : ""}`} aria-hidden="true" />
      </button>

      {open && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-labelledby={label ? `${listId}-label` : undefined}
          aria-label={label ? undefined : placeholder}
          className="select-panel glass"
          style={panelMinWidth ? { minWidth: panelMinWidth } : undefined}
        >
          {/* Na ordem em que as opções foram declaradas: o cabeçalho entra na
              transição de grupo. Reagrupar por chave mudaria a ordem que quem
              escreveu a lista escolheu. */}
          {options.map((option, index) => (
            <React.Fragment key={option.value}>
              {option.group && option.group !== options[index - 1]?.group && (
                <div className="select-group-label">{option.group}</div>
              )}
              {renderOption(option, index)}
            </React.Fragment>
          ))}
        </div>
      )}

      {hint && <span className="hint">{hint}</span>}
    </div>
  )
}

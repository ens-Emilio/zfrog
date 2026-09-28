"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Icon } from "@/lib/icons"
import type { IconName } from "@/lib/icons"
import { NAV_VISIBLE } from "@/lib/nav"

interface Command {
  id: string
  label: string
  sub: string
  icon: IconName
  run: () => void
}

/**
 * The quick-command overlay (Ctrl+K, or `/` outside a field).
 *
 * Opens from anywhere via the `zfrog:palette` event the sidebar button emits, so
 * the sidebar does not need to know about this component.
 */
export function CommandPalette() {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const commands = useMemo<Command[]>(
    () =>
      NAV_VISIBLE.map((item) => ({
        id: item.href,
        label: item.label,
        sub: item.title,
        icon: item.icon,
        run: () => router.push(item.href),
      })),
    [router]
  )

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return commands
    return commands.filter(
      (command) =>
        command.label.toLowerCase().includes(needle) || command.sub.toLowerCase().includes(needle)
    )
  }, [commands, query])

  const close = useCallback(() => {
    setOpen(false)
    setQuery("")
    setCursor(0)
  }, [])

  const openPalette = useCallback(() => {
    setOpen(true)
  }, [])

  useEffect(() => {
    const onEvent = () => openPalette()
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable === true

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        openPalette()
        return
      }
      if (event.key === "/" && !typing) {
        event.preventDefault()
        openPalette()
      }
      if (event.key === "Escape") close()
    }
    window.addEventListener("zfrog:palette", onEvent)
    document.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("zfrog:palette", onEvent)
      document.removeEventListener("keydown", onKey)
    }
  }, [close, openPalette])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  if (!open) return null

  const runAt = (index: number) => {
    const command = matches[index]
    if (!command) return
    close()
    command.run()
  }

  return (
    <div className="palette" onClick={(event) => event.target === event.currentTarget && close()}>
      <div className="palette-box card" role="dialog" aria-modal="true" aria-label="Comandos rápidos">
        <input
          ref={inputRef}
          className="palette-input"
          placeholder="Buscar ou comando…"
          value={query}
          aria-label="Buscar ou comando"
          onChange={(event) => {
            setQuery(event.target.value)
            setCursor(0)
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault()
              setCursor((current) => Math.min(current + 1, matches.length - 1))
            } else if (event.key === "ArrowUp") {
              event.preventDefault()
              setCursor((current) => Math.max(current - 1, 0))
            } else if (event.key === "Enter") {
              event.preventDefault()
              runAt(cursor)
            }
          }}
        />
        <div className="palette-list">
          {matches.length === 0 ? (
            <p className="hint p-3">Nada corresponde a “{query}”.</p>
          ) : (
            matches.map((command, index) => (
              <button
                key={command.id}
                type="button"
                className="palette-item"
                aria-selected={index === cursor}
                onMouseEnter={() => setCursor(index)}
                onClick={() => runAt(index)}
              >
                <Icon name={command.icon} />
                <span>{command.label}</span>
                <span className="sub">{command.sub}</span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

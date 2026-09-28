"use client"

import { useCallback, useEffect, useRef } from "react"
import { Button } from "./button"

/**
 * The `.modal` of the design system, with the behaviour the accessibility rules
 * require: `role="dialog"`, focus moved in and trapped, Escape closes, and focus
 * returns to whatever was focused before.
 *
 * Replaces `window.confirm`, which cannot be styled and blocks the whole page.
 */
export function Modal({
  open,
  title,
  body,
  confirmLabel = "Confirmar",
  cancelLabel = "Cancelar",
  danger,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  body: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const scrimRef = useRef<HTMLDivElement>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)
  const previousFocus = useRef<Element | null>(null)

  useEffect(() => {
    if (!open) return
    previousFocus.current = document.activeElement
    confirmRef.current?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== "Tab") return
      // Keep Tab inside the dialog: the page behind it is inert while it is open.
      const focusables = scrimRef.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea")
      if (!focusables || focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("keydown", onKey)
      if (previousFocus.current instanceof HTMLElement) previousFocus.current.focus()
    }
  }, [open, onClose])

  const handleScrimClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.target === event.currentTarget) onClose()
    },
    [onClose]
  )

  if (!open) return null

  return (
    <div className="modal-scrim" ref={scrimRef} onClick={handleScrimClick}>
      <div className="modal glass" role="dialog" aria-modal="true" aria-labelledby="modal-title" aria-describedby="modal-body">
        <h3 id="modal-title" className="card-title">
          {title}
        </h3>
        <p id="modal-body" className="card-sub">
          {body}
        </p>
        <div className="modal-actions">
          <Button variant="secondary" onClick={onClose}>
            {cancelLabel}
          </Button>
          <Button ref={confirmRef} variant={danger ? "destructive" : "primary"} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

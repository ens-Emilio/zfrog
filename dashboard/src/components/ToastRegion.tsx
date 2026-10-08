
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"

export interface Toast {
  id: number
  message: string
  kind: "ok" | "err"
}

interface ToastContextValue {
  toast: (message: string, kind?: Toast["kind"]) => void
}

const ToastContext = createContext<ToastContextValue>({ toast: () => {} })

/** Toast queue, matching .tui-toast-region / .tui-toast */
export function ToastRegion({ children }: { children?: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((item) => item.id !== id))
  }, [])

  const toast = useCallback((message: string, kind: Toast["kind"] = "ok") => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, message, kind }])
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="tui-toast-region" aria-live="polite" aria-atomic="false">
        {toasts.map((item) => (
          <ToastItem key={item.id} toast={item} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), 4200)
    return () => clearTimeout(timer)
  }, [toast.id, onDismiss])

  return (
    <div className={`tui-toast ${toast.kind}`} role="status">
      <span className="tui-toast-sym">{toast.kind === "err" ? "✗" : "✓"}</span>
      <span className="tui-toast-msg">{toast.message}</span>
      <button
        type="button"
        className="tui-toast-close"
        aria-label="Fechar aviso"
        onClick={() => onDismiss(toast.id)}
      >
        [×]
      </button>
    </div>
  )
}

export function useToast() {
  return useContext(ToastContext).toast
}

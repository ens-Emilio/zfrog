
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

/** Toast queue — zf design */
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
      <div
        aria-live="polite"
        aria-atomic="false"
        style={{
          position: "fixed",
          right: "var(--s5)",
          bottom: "var(--s5)",
          zIndex: 80,
          display: "flex",
          flexDirection: "column",
          gap: "var(--s3)",
          maxWidth: "42ch",
          width: "calc(100vw - var(--s5) * 2)",
          pointerEvents: "none",
        }}
      >
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
    <div
      role="status"
      style={{
        pointerEvents: "auto",
        display: "flex",
        alignItems: "center",
        gap: "var(--s3)",
        padding: "10px var(--s4)",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        boxShadow: "0 8px 24px oklch(0% 0 0 / .14)",
        fontSize: "var(--fs-meta)",
        color: "var(--fg)",
      }}
    >
      <span style={{ color: toast.kind === "err" ? "var(--error)" : "var(--ok)", fontWeight: 600 }}>
        {toast.kind === "err" ? "✗" : "✓"}
      </span>
      <span style={{ flex: 1, wordBreak: "break-word" }}>{toast.message}</span>
      <button
        type="button"
        aria-label="Fechar aviso"
        onClick={() => onDismiss(toast.id)}
        style={{ color: "var(--muted)", cursor: "pointer", background: "none", border: 0, font: "inherit", padding: 0 }}
      >
        [×]
      </button>
    </div>
  )
}
export function useToast() {
  return useContext(ToastContext).toast
}

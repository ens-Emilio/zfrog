import { cn } from "@/lib/utils"

/** One `.kv` row: term on the left, value on the right, hint below. */
export function DetailRow({
  label,
  value,
  hint,
  mono,
  className,
}: {
  label: string
  value: React.ReactNode
  /** Explicação curta mostrada abaixo do valor, para termos técnicos. */
  hint?: string
  mono?: boolean
  className?: string
}) {
  return (
    <div className={cn("grid gap-1 py-3 border-b last:border-0", className)}>
      <div className="row-between items-start">
        <span className="hint">{label}</span>
        <span className={cn("text-[13px] text-right break-all", mono && "mono text-[12.5px]")}>
          {value || <span className="text-[var(--text-3)]">—</span>}
        </span>
      </div>
      {hint && <p className="hint leading-snug">{hint}</p>}
    </div>
  )
}

export function DetailGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid">{children}</div>
}

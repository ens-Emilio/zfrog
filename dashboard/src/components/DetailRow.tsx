"use client"
import { cn } from "@/lib/utils"

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
    <div className={cn("py-3 border-b last:border-0 border-border/60", className)}>
      <div className="flex items-start justify-between gap-4">
        <span className="text-[12px] font-medium uppercase tracking-widest text-muted-foreground shrink-0 pt-0.5">
          {label}
        </span>
        <span className={cn("text-[13.5px] text-right break-all", mono && "font-mono text-[12.5px]")}>
          {value || <span className="text-muted-foreground">—</span>}
        </span>
      </div>
      {hint && <p className="text-[11.5px] text-muted-foreground mt-1 leading-snug">{hint}</p>}
    </div>
  )
}

export function DetailGrid({ children }: { children: React.ReactNode }) {
  return <div className="rounded-[12px] border bg-card/50 divide-y divide-border/60">{children}</div>
}

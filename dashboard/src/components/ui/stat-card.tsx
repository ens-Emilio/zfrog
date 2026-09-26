"use client"
import { cn } from "@/lib/utils"

export function StatCard({
  label,
  value,
  icon,
  trend,
  className,
}: {
  label: string
  value: string | number
  icon?: React.ReactNode
  trend?: string
  className?: string
}) {
  return (
    <div className={cn("rounded-[16px] border bg-card p-4 flex flex-col gap-3", className)}>
      <div className="flex items-start justify-between">
        <span className="text-[11.5px] font-medium uppercase tracking-widest text-muted-foreground">{label}</span>
        {icon && (
          <div className="h-8 w-8 rounded-[10px] bg-secondary flex items-center justify-center text-muted-foreground">
            {icon}
          </div>
        )}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-[28px] font-semibold tracking-tight leading-none">{value}</span>
        {trend && <span className="text-[12px] text-muted-foreground">{trend}</span>}
      </div>
    </div>
  )
}

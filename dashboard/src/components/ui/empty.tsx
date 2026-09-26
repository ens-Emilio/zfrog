"use client"
import { Button } from "./button"

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode
  title: string
  description: string
  action?: { label: string; onClick: () => void }
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center rounded-[16px] border border-dashed bg-card/50">
      {icon && (
        <div className="h-12 w-12 rounded-[14px] bg-secondary flex items-center justify-center mb-4 text-muted-foreground">
          {icon}
        </div>
      )}
      <h3 className="text-[15px] font-semibold">{title}</h3>
      <p className="text-[13.5px] text-muted-foreground mt-1 max-w-sm">{description}</p>
      {action && (
        <Button variant="primary" size="sm" className="mt-5" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  )
}

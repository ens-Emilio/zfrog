import { JobStatus } from "@/lib/api"
import { STATUS_LABELS } from "@/lib/labels"
import { cn } from "@/lib/utils"

/**
 * Job status as a `.badge` of the design system.
 *
 * The palette is deliberately narrow: the accent family marks work in flight, the
 * semantic colours mark outcomes, and neutral marks anything that never started.
 * Status is never carried by colour alone — the badge always shows the label.
 */
const statusMap: Record<JobStatus, string> = {
  pending: "badge-neutral",
  probing: "badge-info",
  processing: "badge-info",
  running: "badge-accent",
  completed: "badge-success",
  failed: "badge-danger",
  cancelled: "badge-neutral",
}

const inFlight: JobStatus[] = ["running", "probing", "processing"]

export function StatusBadge({ status, size = "md" }: { status: JobStatus; size?: "sm" | "md" }) {
  const variant = statusMap[status] ?? "badge-neutral"
  return (
    <span className={cn("badge", variant, size === "sm" && "text-[11px]")}>
      {inFlight.includes(status) && <span className="dot" aria-hidden="true" />}
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

export function Badge({
  variant = "neutral",
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  variant?: "success" | "warning" | "danger" | "info" | "accent" | "neutral"
}) {
  return (
    <span className={cn("badge", `badge-${variant}`, className)} {...props}>
      {children}
    </span>
  )
}

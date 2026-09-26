"use client"
import { cn } from "@/lib/utils"
import { JobStatus } from "@/lib/api"
import { STATUS_LABELS } from "@/lib/labels"

const statusMap: Record<JobStatus, { className: string; dot: string }> = {
  completed: { className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20", dot: "bg-emerald-500" },
  failed: { className: "bg-red-500/10 text-red-600 dark:text-red-400 ring-red-500/20", dot: "bg-red-500" },
  running: { className: "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20", dot: "bg-amber-500" },
  processing: { className: "bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-violet-500/20", dot: "bg-violet-500" },
  probing: { className: "bg-blue-500/10 text-blue-600 dark:text-blue-400 ring-blue-500/20", dot: "bg-blue-500" },
  pending: { className: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 ring-zinc-500/20", dot: "bg-zinc-500" },
  cancelled: { className: "bg-zinc-500/10 text-zinc-500 ring-zinc-500/20", dot: "bg-zinc-400" },
}

const settled: JobStatus[] = ["completed", "failed", "cancelled"]

export function StatusBadge({ status, size = "md" }: { status: JobStatus; size?: "sm" | "md" }) {
  const cfg = statusMap[status] || statusMap.pending
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset whitespace-nowrap",
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-[12px]",
        cfg.className
      )}
    >
      <span
        className={cn("h-1.5 w-1.5 rounded-full", cfg.dot, settled.includes(status) ? "" : "animate-pulse")}
      />
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", className)}
      {...props}
    />
  )
}

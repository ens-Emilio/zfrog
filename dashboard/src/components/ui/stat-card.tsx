/**
 * A `.stat` cell of the design system.
 *
 * Trend lines are informational, never the only carrier of meaning: the label above
 * and the trend text below both read on their own.
 */
export function StatCard({
  label,
  value,
  icon,
  trend,
  trendDirection,
  className,
}: {
  label: string
  value: string | number
  icon?: React.ReactNode
  trend?: string
  trendDirection?: "up" | "down"
  className?: string
}) {
  return (
    <div className={className ? `stat ${className}` : "stat"}>
      <span className="stat-value flex items-center gap-2">
        {value}
        {icon}
      </span>
      <span className="stat-label">{label}</span>
      {trend && <span className={`stat-trend ${trendDirection ?? ""}`}>{trend}</span>}
    </div>
  )
}

/** A row of `.stat` cells; `columns={5}` matches the job detail strip. */
export function StatStrip({ columns = 4, children }: { columns?: 4 | 5; children: React.ReactNode }) {
  return <div className={columns === 5 ? "stat-strip cols-5" : "stat-strip"}>{children}</div>
}

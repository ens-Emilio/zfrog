export function cn(...classes: (string | boolean | undefined | null)[]) {
  return classes.filter(Boolean).join(" ")
}

export function formatBytes(bytes: number) {
  if (bytes == null || isNaN(bytes)) return "—"
  if (bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i]
}

export function formatDuration(seconds: number) {
  if (seconds == null || isNaN(seconds)) return "—"
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

export function timeAgo(dateStr: string) {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = (now.getTime() - d.getTime()) / 1000
  if (diff < 60) return "agora"
  if (diff < 3600) return `${Math.floor(diff / 60)}m atrás`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h atrás`
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })
}

/** Duration as the mm:ss clock the design system shows in the job metrics. */
export function formatClock(seconds: number) {
  if (seconds == null || isNaN(seconds)) return "—"
  const total = Math.max(0, Math.round(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

/** Thousands separator, pt-BR. */
export function formatNumber(value: number) {
  if (value == null || isNaN(value)) return "—"
  return value.toLocaleString("pt-BR")
}

/** Percentage with no decimals, the way the stat cells show it. */
export function formatPercent(value: number) {
  if (value == null || isNaN(value)) return "—"
  return `${Math.round(value)}%`
}

/** `dd/mm/aaaa · hh:mm`, the timestamp format the design system uses. */
export function formatStamp(value: string | number | Date) {
  const d = new Date(value)
  if (isNaN(d.getTime())) return "—"
  return `${d.toLocaleDateString("pt-BR")} · ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`
}

/** The letter shown in a `.job-favicon`, derived from the host. */
export function faviconLetter(host: string) {
  const first = host.replace(/^www\./, "").split(".")[0] || "?"
  return first.charAt(0).toUpperCase()
}

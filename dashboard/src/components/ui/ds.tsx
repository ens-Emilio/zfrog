import { cn } from "@/lib/utils"

/** The `.chip` filter pill; selection is `aria-pressed`, as in the design system. */
export function Chip({
  active,
  children,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button type="button" className={cn("chip", className)} aria-pressed={active} {...props}>
      {children}
    </button>
  )
}

/** The `.mode-card` tile: a square button with an icon and a name. */
export function ModeCard({
  active,
  icon,
  label,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active: boolean; icon: React.ReactNode; label: string }) {
  return (
    <button type="button" className={cn("mode-card", className)} aria-pressed={active} {...props}>
      <span className="mode-ico">{icon}</span>
      <span className="mode-name">{label}</span>
    </button>
  )
}

/** The `.progress` bar; `state` picks the accent, success or error fill. */
export function Progress({
  value,
  state = "running",
  label,
}: {
  value: number
  state?: "running" | "done" | "error"
  label?: string
}) {
  const className = ["progress", state === "done" ? "is-done" : "", state === "error" ? "is-error" : ""]
    .filter(Boolean)
    .join(" ")
  return (
    <div
      className={className}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
      aria-label={label}
    >
      <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  )
}

/** The `.stepper` of pipeline stages. */
export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <div className="stepper">
      {steps.map((step, index) => (
        <div
          key={step}
          className={`step${index < current ? " is-done" : index === current ? " is-current" : ""}`}
        >
          <span className="bar" />
          <span className="lbl">{step}</span>
        </div>
      ))}
    </div>
  )
}

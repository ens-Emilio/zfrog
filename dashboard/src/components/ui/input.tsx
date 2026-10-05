import * as React from "react"
import { AlertTriangle } from "lucide-react"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  hint?: string
  error?: string
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}

/**
 * The `.field` + `.input` pair of the design system, with label, hint and error.
 *
 * The wrapper is a `<label>` rather than a `<div>` when a label is given, so the
 * control is associated implicitly. A `<label>` with `for` would need a generated
 * id, and an id that has to be threaded through every caller is the kind of thing
 * that silently goes missing on one field — implicit association cannot drift.
 */
export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, hint, error, leftIcon, rightIcon, type = "text", ...props }, ref) => {
    const Wrapper = (label ? "label" : "div") as "label"
    return (
      <Wrapper className="field">
        {label && <span className="label">{label}</span>}
        <span className="relative flex items-center">
          {leftIcon && <span className="pointer-events-none absolute left-3 text-[var(--text-3)]">{leftIcon}</span>}
          <input
            type={type}
            ref={ref}
            aria-invalid={error ? true : undefined}
            aria-describedby={hint || error ? `${props.id ?? props.name ?? "field"}-help` : undefined}
            className={[leftIcon ? "pl-10" : "", rightIcon ? "pr-10" : "", "input", className]
              .filter(Boolean)
              .join(" ")}
            {...props}
          />
          {rightIcon && <span className="pointer-events-none absolute right-3 text-[var(--text-3)]">{rightIcon}</span>}
        </span>
        {hint && !error && (
          <span className="hint" id={`${props.id ?? props.name ?? "field"}-help`}>
            {hint}
          </span>
        )}
        {error && (
          <span className="error-text" id={`${props.id ?? props.name ?? "field"}-help`} role="alert">
            <AlertTriangle className="ic ic-sm" aria-hidden="true" />
            {error}
          </span>
        )}
      </Wrapper>
    )
  }
)
Input.displayName = "Input"

/** The `.textarea` (mono, for JSON and lists of proxies). */
export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string; hint?: string }
>(({ className, label, hint, ...props }, ref) => {
  const Wrapper = (label ? "label" : "div") as "label"
  return (
    <Wrapper className="field">
      {label && <span className="label">{label}</span>}
      <textarea ref={ref} className={["textarea", className].filter(Boolean).join(" ")} {...props} />
      {hint && <span className="hint">{hint}</span>}
    </Wrapper>
  )
})
Textarea.displayName = "Textarea"

/**
 * The `.switch` of the design system, for a single boolean.
 *
 * The whole row is the `<label>`, so the visible text names the checkbox.
 */
export function Switch({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: string
  hint?: string
}) {
  return (
    <label className="row-between">
      <span className="field" style={{ ["--od-gap" as string]: "2px" }}>
        <span className="label">{label}</span>
        {hint && <span className="hint">{hint}</span>}
      </span>
      <span className="switch">
        <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
        <span className="track" />
        <span className="thumb" />
      </span>
    </label>
  )
}

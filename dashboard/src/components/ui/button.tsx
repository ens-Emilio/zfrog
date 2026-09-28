"use client"
import * as React from "react"
import { Loader2 } from "lucide-react"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "outline" | "destructive"
  size?: "sm" | "md" | "lg" | "icon"
  loading?: boolean
}

/**
 * The `.btn` of the design system.
 *
 * `outline` and `secondary` both land on the default glass button — the system has
 * one secondary treatment — and `lg` is the 44px touch target the accessibility
 * rules ask for.
 */
const variantStyles: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary: "btn-primary",
  secondary: "",
  outline: "",
  ghost: "btn-ghost",
  destructive: "btn-danger",
}

const sizeStyles: Record<NonNullable<ButtonProps["size"]>, string> = {
  sm: "btn-sm",
  md: "",
  lg: "min-h-[44px] px-6",
  icon: "icon-btn",
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", loading, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={["btn", variantStyles[variant], sizeStyles[size], className].filter(Boolean).join(" ")}
      {...props}
    >
      {loading && <Loader2 className="ic ic-sm animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
)
Button.displayName = "Button"

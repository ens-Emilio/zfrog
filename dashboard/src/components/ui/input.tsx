"use client"
import * as React from "react"
import { cn } from "@/lib/utils"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  hint?: string
  error?: string
  leftIcon?: React.ReactNode
  rightIcon?: React.ReactNode
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, hint, error, leftIcon, rightIcon, type = "text", ...props }, ref) => {
    return (
      <div className="flex flex-col gap-1.5 w-full">
        {label && <label className="text-[12.5px] font-medium text-foreground/80">{label}</label>}
        <div className="relative flex items-center">
          {leftIcon && <span className="absolute left-3 text-muted-foreground">{leftIcon}</span>}
          <input
            type={type}
            ref={ref}
            className={cn(
              "flex h-10 w-full rounded-[12px] border border-input bg-background px-3 py-2 text-[14px] transition-all",
              "placeholder:text-muted-foreground/60",
              "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-0 focus:border-ring",
              "disabled:cursor-not-allowed disabled:opacity-50",
              leftIcon ? "pl-10" : "",
              rightIcon ? "pr-10" : "",
              error ? "border-destructive focus:ring-destructive" : "",
              className || ""
            )}
            {...props}
          />
          {rightIcon && <span className="absolute right-3 text-muted-foreground">{rightIcon}</span>}
        </div>
        {hint && !error && <span className="text-[11.5px] text-muted-foreground">{hint}</span>}
        {error && <span className="text-[11.5px] text-destructive">{error}</span>}
      </div>
    )
  }
)
Input.displayName = "Input"

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement> & { label?: string }
>(({ className, label, children, ...props }, ref) => {
  return (
    <div className="flex flex-col gap-1.5 w-full">
      {label && <label className="text-[12.5px] font-medium text-foreground/80">{label}</label>}
      <select
        ref={ref}
        className={cn(
          "flex h-10 w-full rounded-[12px] border border-input bg-background px-3 py-2 text-[14px]",
          "focus:outline-none focus:ring-2 focus:ring-ring",
          className
        )}
        {...props}
      >
        {children}
      </select>
    </div>
  )
})
Select.displayName = "Select"

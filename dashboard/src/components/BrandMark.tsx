import type { SVGProps } from "react"

/**
 * The zfrog mark: the frog from the design system.
 *
 * The design system ships it as an inline SVG symbol, and no icon library has a
 * frog that matches, so it is kept here verbatim (same path data, same 24×24
 * viewBox) and inherits `currentColor` like every other icon.
 */
export function BrandMark({ className = "ic", ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d="M5.5 3.5a2.5 2.5 0 0 0-1.87 4.16A5.98 5.98 0 0 0 2 11.5V14c0 3.87 3.13 7 7 7h6c3.87 0 7-3.13 7-7v-2.5a5.98 5.98 0 0 0-1.63-3.84A2.5 2.5 0 0 0 18.5 3.5c-1.38 0-2.5 1.12-2.5 2.5 0 .16.02.32.05.48A5.97 5.97 0 0 0 12 7.5h-.05A5.97 5.97 0 0 0 7.95 6.48c.03-.16.05-.32.05-.48 0-1.38-1.12-2.5-2.5-2.5Z" />
      <circle cx="8.5" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="12" r="1" fill="currentColor" stroke="none" />
      <path d="M9 17h6" />
    </svg>
  )
}

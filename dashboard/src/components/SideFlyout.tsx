import { useEffect, useRef } from "react"

export interface FlyoutData {
  label: string
  title: string
  sub?: string
  kbd?: string
  meta?: string
  rect: DOMRect
}

interface SideFlyoutProps {
  data: FlyoutData | null
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function SideFlyout({ data, onMouseEnter, onMouseLeave }: SideFlyoutProps) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!data || !ref.current) return
    const el = ref.current
    const vh = window.innerHeight
    const fh = el.offsetHeight || 120
    let top = data.rect.top - 2
    top = Math.max(52, Math.min(top, vh - fh - 12))
    el.style.top = `${top}px`
    el.style.left = "64px"
  }, [data])

  if (!data) return null

  return (
    <div
      ref={ref}
      className="zf-side-flyout open"
      role="tooltip"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {data.label && <div className="flyout-label">{data.label}</div>}
      <div className="flyout-title">
        <span>{data.title}</span>
        {data.kbd && <span className="flyout-kbd">{data.kbd}</span>}
      </div>
      {data.sub && <div className="flyout-sub">{data.sub}</div>}
      <div className="flyout-rule" />
      {data.meta && (
        <div className="flyout-meta">
          <span>{data.meta}</span>
        </div>
      )}
    </div>
  )
}

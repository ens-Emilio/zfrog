import Link from "next/link"
import { Button } from "./button"

/** The `.empty` block: an icon, a heading, one sentence and a way forward. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  href,
}: {
  icon?: React.ReactNode
  title: string
  description: string
  action?: { label: string; onClick: () => void }
  href?: { label: string; href: string }
}) {
  return (
    <div className="empty glass">
      {icon}
      <h3>{title}</h3>
      <p>{description}</p>
      {action && (
        <Button variant="primary" size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
      {href && (
        <Link href={href.href}>
          <Button variant="primary" size="sm">
            {href.label}
          </Button>
        </Link>
      )}
    </div>
  )
}

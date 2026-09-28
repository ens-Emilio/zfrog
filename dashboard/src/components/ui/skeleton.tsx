import { cn } from "@/lib/utils"

/** The `.skeleton` shimmer of the design system. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton", className)} {...props} />
}

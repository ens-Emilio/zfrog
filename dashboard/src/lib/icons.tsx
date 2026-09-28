import type { LucideIcon } from "lucide-react"
import { BrandMark } from "@/components/BrandMark"
import {
  Accessibility,
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock,
  Code2,
  Command,
  Copy,
  Database,
  Download,
  Eye,
  FileDown,
  FileText,
  Folder,
  Globe,
  HardDrive,
  HelpCircle,
  History,
  Info,
  Keyboard,
  Layers,
  LayoutDashboard,
  Link2,
  ListFilter,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  MousePointerClick,
  Moon,
  Palette,
  Play,
  Plus,
  RefreshCw,
  Repeat,
  RotateCw,
  Ruler,
  Scale,
  Search,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Store,
  Sun,
  Target,
  Terminal,
  Trash2,
  TrendingUp,
  Type,
  Users,
  Webhook,
  X,
  XCircle,
  Zap,
} from "lucide-react"

/**
 * The icon set of the design system, by the name the prototype uses.
 *
 * Names are kept as they appear in the design system documentation so the mapping
 * stays checkable against /design. Sizes come from `.ic` / `.ic-sm` / `.ic-lg`
 * in ds-components.css, which also pins the 1.75 stroke.
 */
export const ICONS = {
  "i-accessibility": Accessibility,
  "i-activity": Activity,
  "i-alert": AlertTriangle,
  "i-arrow-right": ArrowRight,
  "i-book": BookOpen,
  "i-calendar": Calendar,
  "i-check": Check,
  "i-check-circle": CheckCircle2,
  "i-chevron": ChevronDown,
  "i-clock": Clock,
  "i-code": Code2,
  "i-command": Command,
  "i-copy": Copy,
  "i-dashboard": LayoutDashboard,
  "i-database": Database,
  "i-download": Download,
  "i-eye": Eye,
  "i-file": FileText,
  "i-file-down": FileDown,
  "i-filter": ListFilter,
  "i-folder": Folder,
  "i-globe": Globe,
  "i-hard-drive": HardDrive,
  "i-help": HelpCircle,
  "i-history": History,
  "i-info": Info,
  "i-keyboard": Keyboard,
  "i-layers": Layers,
  "i-link": Link2,
  "i-loader": Loader2,
  "i-message": MessageSquare,
  "i-moon": Moon,
  "i-more": MoreHorizontal,
  "i-mouse": MousePointerClick,
  "i-palette": Palette,
  "i-play": Play,
  "i-plus": Plus,
  "i-refresh": RefreshCw,
  "i-repeat": Repeat,
  "i-rotate": RotateCw,
  "i-ruler": Ruler,
  "i-scale": Scale,
  "i-search": Search,
  "i-server": Server,
  "i-settings": Settings,
  "i-shield": ShieldCheck,
  "i-sliders": SlidersHorizontal,
  "i-sparkles": Sparkles,
  "i-stats": BarChart3,
  "i-store": Store,
  "i-sun": Sun,
  "i-target": Target,
  "i-terminal": Terminal,
  "i-trash": Trash2,
  "i-trending": TrendingUp,
  "i-type": Type,
  "i-users": Users,
  "i-webhook": Webhook,
  "i-x": X,
  "i-x-circle": XCircle,
  "i-zap": Zap,
} satisfies Record<string, LucideIcon>

export type IconName = keyof typeof ICONS | "i-frog"

/** Icon sizes the design system defines. */
export type IconSize = "sm" | "md" | "lg"

const sizeClass: Record<IconSize, string> = { sm: "ic ic-sm", md: "ic", lg: "ic ic-lg" }

export function Icon({
  name,
  size = "md",
  className,
}: {
  name: IconName
  size?: IconSize
  className?: string
}) {
  // The frog is the brand mark, not a library icon: no package ships one that
  // matches, so it lives in its own component.
  if (name === "i-frog") {
    return <BrandMark className={className ? `${sizeClass[size]} ${className}` : sizeClass[size]} />
  }
  const Cmp = ICONS[name]
  return <Cmp className={className ? `${sizeClass[size]} ${className}` : sizeClass[size]} aria-hidden="true" />
}

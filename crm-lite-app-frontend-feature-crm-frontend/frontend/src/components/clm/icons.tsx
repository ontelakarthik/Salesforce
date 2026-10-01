import {
  ArrowDown,
  ArrowUp,
  ArrowsDownUp,
  Bell,
  Buildings,
  Calendar,
  CaretDoubleLeft,
  CaretDoubleRight,
  CaretDown,
  CaretLeft,
  CaretRight,
  CheckCircle,
  Clock,
  ClipboardText,
  CurrencyDollar,
  DotsNine,
  File,
  FileText,
  Layout,
  MagnifyingGlass,
  Plus,
  Question,
  Shield,
  SquaresFour,
  Stack,
  Star,
  Target,
  TrendUp,
  UserCircle,
  Users,
  Warning,
  X,
} from "@phosphor-icons/react";

export type IconName =
  | "grid"
  | "building"
  | "document"
  | "documentCheck"
  | "documentList"
  | "clock"
  | "layers"
  | "help"
  | "userCircle"
  | "trendingUp"
  | "checkCircle"
  | "layout"
  | "bell"
  | "users"
  | "star"
  | "search"
  | "chevronDown"
  | "plus"
  | "alertTriangle"
  | "dollar"
  | "calendar"
  | "chevronLeft"
  | "chevronRight"
  | "chevronsLeft"
  | "chevronsRight"
  | "arrowUp"
  | "arrowDown"
  | "arrowUpDown"
  | "close"
  | "waffle"
  | "shield"
  | "target";

/** Sizing/color for every icon is driven entirely by CSS (see globals.css's
 * per-context `svg{width/height/color}` rules) — Phosphor's SVGs use
 * currentColor internally, same contract the old hand-drawn set had. */
const ICONS: Record<IconName, React.ComponentType<{ className?: string }>> = {
  grid: SquaresFour,
  building: Buildings,
  document: File,
  documentCheck: ClipboardText,
  documentList: FileText,
  clock: Clock,
  layers: Stack,
  help: Question,
  userCircle: UserCircle,
  trendingUp: TrendUp,
  checkCircle: CheckCircle,
  layout: Layout,
  bell: Bell,
  users: Users,
  star: Star,
  search: MagnifyingGlass,
  chevronDown: CaretDown,
  plus: Plus,
  alertTriangle: Warning,
  dollar: CurrencyDollar,
  calendar: Calendar,
  chevronLeft: CaretLeft,
  chevronRight: CaretRight,
  chevronsLeft: CaretDoubleLeft,
  chevronsRight: CaretDoubleRight,
  arrowUp: ArrowUp,
  arrowDown: ArrowDown,
  arrowUpDown: ArrowsDownUp,
  close: X,
  waffle: DotsNine,
  shield: Shield,
  target: Target,
};

export function Icon({ name }: { name: IconName }) {
  const Component = ICONS[name];
  return <Component />;
}

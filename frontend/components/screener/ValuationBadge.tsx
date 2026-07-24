import { VERDICT_STYLES } from "@/components/ticker/FairValuePill";
import { cn } from "@/lib/utils";

// Screener-card-specific labels -- deliberately category-only (no price or
// discount/premium %, which stay on the ticker page's Valuation tab). Same
// underlying verdict and colors as the ticker header's FairValuePill, just
// worded for a list view rather than a single-ticker detail view.
const VALUATION_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fair Valued",
};

interface Props {
  verdict: string | null;
}

export function ValuationBadge({ verdict }: Props) {
  if (!verdict) return null;
  const cls = VERDICT_STYLES[verdict] ?? VERDICT_STYLES.fair;
  const label = VALUATION_LABELS[verdict] ?? verdict;

  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold", cls)}>{label}</span>
  );
}

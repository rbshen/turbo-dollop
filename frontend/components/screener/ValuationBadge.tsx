import { FLAT_VERDICT_STYLES, VERDICT_STYLES } from "@/components/ticker/FairValuePill";
import { cn } from "@/lib/utils";

// Screener-card-specific labels -- deliberately category-only (no price or
// discount/premium %, which stay on the ticker page's Valuation tab). Same
// underlying verdict and colors as the ticker header's FairValuePill, just
// worded for a list view rather than a single-ticker detail view.
export const VALUATION_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fair Valued",
};

interface Props {
  verdict: string | null;
  // "chip" (default): bordered pill. "flat": borderless, same height as
  // ScreenerCard's other pills (company type, MoatPill's "flat" variant).
  variant?: "chip" | "flat";
}

export function ValuationBadge({ verdict, variant = "chip" }: Props) {
  if (!verdict) return null;
  const cls = variant === "chip" ? (VERDICT_STYLES[verdict] ?? VERDICT_STYLES.fair) : (FLAT_VERDICT_STYLES[verdict] ?? FLAT_VERDICT_STYLES.fair);
  const label = VALUATION_LABELS[verdict] ?? verdict;

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        cls
      )}
    >
      {label}
    </span>
  );
}

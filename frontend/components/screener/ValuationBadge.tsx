import { VALUATION_TONE } from "@/components/ticker/FairValuePill";
import { Status } from "@/components/ui/status";
import type { ValuationSource } from "@/lib/api/types";
import { pillLabel } from "@/lib/tierColor";

// Screener-card-specific labels -- deliberately category-only (no price or
// discount/premium %, which stay on the ticker page's Valuation tab). Same
// underlying verdict and colors as the ticker header's FairValuePill, just
// worded for a list view rather than a single-ticker detail view.
export const VALUATION_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fairvalued",
};

// Screener card: state is conveyed by color alone (same pattern as the
// vs-SPY pill's own "screener" tier) -- every verdict renders the same
// literal text here.
const VALUATION_LABELS_SCREENER: Record<string, string> = {
  undervalued: "Valuation",
  overvalued: "Valuation",
  fair: "Valuation",
};

const LABEL_SETS: Record<"full" | "screener", Record<string, string>> = {
  full: VALUATION_LABELS,
  screener: VALUATION_LABELS_SCREENER,
};

interface Props {
  verdict: string | null;
  /** "custom" marks that this ticker's verdict came from an active,
   * user-saved custom valuation rather than Auto Calculation -- shown so a
   * Screener/Watchlist comparison across tickers doesn't silently mix an
   * Auto-derived verdict with a user's own override (see CLAUDE.md's Fork
   * B scope decision). Undefined/"auto"/null all render nothing extra. */
  source?: ValuationSource | null;
  // Which label wording tier to use -- see LABEL_SETS above. Defaults to
  // the full "Overvalued"/"Fairvalued"/"Undervalued" wording.
  labelSet?: "full" | "screener";
}

export function ValuationBadge({ verdict, source, labelSet = "full" }: Props) {
  if (!verdict) return null;
  const tone = VALUATION_TONE[verdict] ?? VALUATION_TONE.fair;
  const label = LABEL_SETS[labelSet][verdict] ?? verdict;

  return (
    <Status tone={tone}>
      {pillLabel(label)}
      {source === "custom" && <span className="font-normal opacity-70">· Custom</span>}
    </Status>
  );
}

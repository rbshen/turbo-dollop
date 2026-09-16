import { PriceTargetRangeSlider } from "@/components/analystRatings/PriceTargetRangeSlider";
import type { PriceTargetSummary } from "@/lib/api/types";

interface Props {
  data: PriceTargetSummary;
  currency?: string;
}

// Content-only -- no outer card wrapper. Embedded as the right column of
// AtAGlanceCard, which owns the outer border/background/padding. Renders
// the low/average/high range as a PriceTargetRangeSlider instead of three
// separate stat blocks.
export function PriceTargetsCard({ data, currency = "USD" }: Props) {
  return (
    <PriceTargetRangeSlider
      low={data.target_low}
      avg={data.target_consensus}
      high={data.target_high}
      currentPrice={data.current_price}
      upsidePct={data.upside_pct}
      currency={currency}
    />
  );
}

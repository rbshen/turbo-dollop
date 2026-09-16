import { ConsensusBanner } from "@/components/analystRatings/ConsensusBanner";
import { PriceTargetsCard } from "@/components/analystRatings/PriceTargetsCard";
import type { ConsensusBanner as ConsensusBannerData, PriceTargetSummary } from "@/lib/api/types";

interface Props {
  banner: ConsensusBannerData;
  priceTarget: PriceTargetSummary;
  currency?: string;
}

// Merges the old separate ConsensusBanner + PriceTargetsCard cards into one
// two-column card -- consensus rating on the left, price-target range on
// the right, divided by a single border (no precedent for this exact
// divider elsewhere in the app; built from existing border/spacing tokens
// only).
export function AtAGlanceCard({ banner, priceTarget, currency = "USD" }: Props) {
  return (
    <div className="rounded-lg border border-border-card bg-surface p-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 md:gap-0 md:divide-x md:divide-border-card">
        <div className="md:pr-6">
          <ConsensusBanner data={banner} />
        </div>
        <div className="md:pl-6">
          <PriceTargetsCard data={priceTarget} currency={currency} />
        </div>
      </div>
    </div>
  );
}

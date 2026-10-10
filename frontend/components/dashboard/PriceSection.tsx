"use client";

import { PriceRangeBar } from "@/components/charts/PriceRangeBar";
import { StageTimeline } from "@/components/charts/StageTimeline";
import { VisualRow } from "@/components/charts/VisualRow";
import { fmtSwingDate } from "@/components/technical/ChecklistCard";
import { RowSkeleton } from "@/components/dashboard/Skeleton";
import { SectionHeading } from "@/components/dashboard/SectionHeading";
import { Section } from "@/components/ui/section";
import type { DashboardOut } from "@/lib/api/types";
import { fairValueUnavailableText } from "@/lib/dashboard";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";
import { useTrendAnalysis } from "@/lib/hooks/useTrendAnalysis";
import { formatWeinsteinSince, WEINSTEIN_LOWER_BOUND_CAVEAT } from "@/lib/weinsteinStage";

/** Section C. The price and the fair value are the HEADER's (the summary), so the bar agrees with the valuation pill above it; the band and
 * the reasons come from /dashboard, the stage weeks from the production engine on the cached bars. */
export function PriceSection({ ticker, data, error, loading }: { ticker: string; data: DashboardOut | undefined; error: Error | undefined; loading: boolean }) {
  const { data: summary } = useTickerSummary(ticker);
  const { data: trend } = useTrendAnalysis(ticker);

  const fv = data?.fair_value;
  // The summary's fair value is the header pill's; the endpoint's is the same value from the cache (the fallback when the summary has none).
  const fairValue = summary?.fair_value_price ?? fv?.fair_value_price ?? null;
  const price = summary?.price ?? null;
  const currency = summary?.quote_currency ?? fv?.currency ?? "USD";

  const sinceDate = trend?.weinstein_stage_since_date ?? data?.weinstein.since_date ?? null;
  const lowerBound = trend?.weinstein_stage_since_is_lower_bound ?? data?.weinstein.since_is_lower_bound ?? false;
  const sinceText = sinceDate ? formatWeinsteinSince(sinceDate, lowerBound, fmtSwingDate) : null;

  return (
    <Section title={<SectionHeading title="Price and valuation" tag="Not part of the score" />} data-testid="dashboard-price">
      {error ? (
        <p className="text-sm text-negative">Couldn&apos;t load price and valuation — {error.message}</p>
      ) : loading || !data || !summary ? (
        <RowSkeleton rows={2} />
      ) : (
        <div>
          <div className="py-4" data-testid="price-range-row">
            <VisualRow label="Price against fair value">
              <PriceRangeBar
                price={price}
                fairValue={fairValue}
                bandLow={fv?.band_low}
                bandHigh={fv?.band_high}
                currency={currency}
                unavailableReason={fairValue == null && fv ? fairValueUnavailableText(fv) : null}
              />
            </VisualRow>
          </div>
          <div className="border-t border-border-subtle py-4" data-testid="stage-row">
            <VisualRow label="Weinstein stage, last 12 months">
              {data.weinstein.available ? (
                <StageTimeline weeks={data.weinstein.weeks} since={sinceDate} sinceIsLowerBound={lowerBound} />
              ) : (
                <div className="flex flex-col gap-1">
                  <p className="text-xs text-text-tertiary">{data.weinstein.unavailable_reason ?? "No stage history yet"}</p>
                  {sinceText && (
                    <p className="text-xs text-text-secondary">
                      {sinceText}
                      {lowerBound && <span className="text-text-tertiary"> — {WEINSTEIN_LOWER_BOUND_CAVEAT}</span>}
                    </p>
                  )}
                </div>
              )}
            </VisualRow>
          </div>
        </div>
      )}
    </Section>
  );
}

"use client";

import { useState } from "react";

import { CurrentDistributionList } from "@/components/analystRatings/CurrentDistributionList";
import { RatingDistributionTrendChart } from "@/components/analystRatings/RatingDistributionTrendChart";
import { RecommendationDetailsTable } from "@/components/analystRatings/RecommendationDetailsTable";
import { SegmentedControl } from "@/components/shared/SegmentedControl";
import { buildVerdict } from "@/lib/analystRatingsVerdict";
import type { PriceTargetSummary, RatingHistoryPoint, RecommendationDetailsColumn } from "@/lib/api/types";

interface Props {
  history: RatingHistoryPoint[];
  columns: RecommendationDetailsColumn[];
  priceTarget: PriceTargetSummary;
  currency?: string;
  /** ISO timestamp of the cached grades_consensus row Current Distribution
   * is built from -- see analyst_ratings_data.py's own comment on why this
   * is a live, independently-refreshed FMP snapshot, not expected to
   * reconcile with Recommendation Trend's grades_historical-sourced bars. */
  currentAsOf?: string | null;
}

type SentimentView = "summary" | "details";

// Mirrors ValuationGauge.tsx's own inline toLocaleDateString convention
// (this app has no shared fmtDate helper).
function fmtAsOfDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// Merges the old separate Analyst Distribution, Recommendation Trend, and
// Recommendation Details cards into one. Row 1: the recommendation-trend
// chart, full row width. Row 2: the current distribution as label/value
// rows (~20% width) alongside a toggle between a one-line summary and the
// full details table (~80% width) -- a 1/5-4/5 split via the same
// `grid-cols-1 lg:grid-cols-5` pattern this card already used for its
// former side-by-side layout, so it still stacks to one column below `lg`.
export function SentimentOverTimeCard({ history, columns, priceTarget, currency = "USD", currentAsOf }: Props) {
  const [view, setView] = useState<SentimentView>("summary");
  const currentColumn = columns[0];

  return (
    <div className="space-y-6 rounded-lg border border-border-card bg-surface p-6">
      <div className="space-y-3">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Recommendation Trend</h2>
        <RatingDistributionTrendChart history={history} />
      </div>

      <div className="grid grid-cols-1 gap-6 border-t border-border-card pt-6 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-1">
          <h2 className="font-heading text-sm font-semibold text-text-primary">Current Distribution</h2>
          {currentColumn ? (
            <>
              <CurrentDistributionList column={currentColumn} />
              <p className="text-xs text-text-tertiary">
                Live consensus{currentAsOf ? `, as of ${fmtAsOfDate(currentAsOf)}` : ""} — independently refreshed
                from the Recommendation Trend chart, so totals may not match.
              </p>
            </>
          ) : (
            <p className="text-sm text-text-tertiary">No current distribution available.</p>
          )}
        </div>

        <div className="space-y-3 lg:col-span-4">
          {currentColumn && (
            <>
              <h2 className="font-heading text-sm font-semibold text-text-primary">Recommendation Details</h2>
              <SegmentedControl
                value={view}
                onChange={setView}
                options={[
                  { value: "summary", label: "Summary" },
                  { value: "details", label: "vs 2M · 6M · 1Y ago" },
                ]}
              />

              {view === "summary" ? (
                <p className="text-xs leading-relaxed text-text-tertiary">{buildVerdict(columns, priceTarget, currency)}</p>
              ) : (
                <RecommendationDetailsTable columns={columns} currency={currency} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

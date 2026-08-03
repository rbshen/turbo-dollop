"use client";

import { AnalystDistributionBar } from "@/components/analystRatings/AnalystDistributionBar";
import { AvgRatingTrendChart } from "@/components/analystRatings/AvgRatingTrendChart";
import { ConsensusBanner } from "@/components/analystRatings/ConsensusBanner";
import { PriceTargetsCard } from "@/components/analystRatings/PriceTargetsCard";
import { PriceTargetTrendChart } from "@/components/analystRatings/PriceTargetTrendChart";
import { RatingDistributionTrendChart } from "@/components/analystRatings/RatingDistributionTrendChart";
import { RecommendationDetailsTable } from "@/components/analystRatings/RecommendationDetailsTable";
import { useAnalystRatings } from "@/lib/hooks/useAnalystRatings";

interface Props {
  ticker: string;
}

export function AnalystRatingsTab({ ticker }: Props) {
  const { data, error } = useAnalystRatings(ticker);

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-negative">
          Couldn&apos;t load {ticker} — {error.message}
        </span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-text-tertiary animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  const currentColumn = data.recommendation_details[0];

  return (
    <div className="space-y-6 py-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <ConsensusBanner data={data.banner} />
        <PriceTargetsCard data={data.price_target} />
      </div>

      {currentColumn && (
        <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
          <h2 className="font-heading text-sm font-semibold text-text-primary">Analyst Distribution</h2>
          <AnalystDistributionBar column={currentColumn} />
        </div>
      )}

      <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Recommendation Trend</h2>
        <RatingDistributionTrendChart history={data.history} />
      </div>

      <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Average Rating Trend</h2>
        <AvgRatingTrendChart history={data.history} />
      </div>

      <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Average Price Target Trend</h2>
        <PriceTargetTrendChart history={data.history} />
      </div>

      <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Recommendation Details</h2>
        <RecommendationDetailsTable columns={data.recommendation_details} />
      </div>
    </div>
  );
}

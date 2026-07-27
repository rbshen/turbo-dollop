"use client";

import { AvgTargetCard } from "@/components/analystRatings/AvgTargetCard";
import { ConsensusBanner } from "@/components/analystRatings/ConsensusBanner";
import { PriceTargetRangeCard } from "@/components/analystRatings/PriceTargetRangeCard";
import { RatingHistoryChart } from "@/components/analystRatings/RatingHistoryChart";
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
        <span className="text-sm text-red-400">
          Couldn&apos;t load {ticker} — {error.message}
        </span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-zinc-600 animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <ConsensusBanner data={data.banner} />
        <AvgTargetCard data={data.price_target} />
        <PriceTargetRangeCard data={data.price_target} />
      </div>

      <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Rating History</h2>
        <RatingHistoryChart history={data.history} />
      </div>

      <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Recommendation Details</h2>
        <div className="overflow-x-auto">
          <RecommendationDetailsTable columns={data.recommendation_details} />
        </div>
      </div>
    </div>
  );
}

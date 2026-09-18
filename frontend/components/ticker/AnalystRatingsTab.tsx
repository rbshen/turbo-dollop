"use client";

import { AtAGlanceCard } from "@/components/analystRatings/AtAGlanceCard";
import { PriceTargetTrendCard } from "@/components/analystRatings/PriceTargetTrendCard";
import { SentimentOverTimeCard } from "@/components/analystRatings/SentimentOverTimeCard";
import { useAnalystRatings } from "@/lib/hooks/useAnalystRatings";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";

interface Props {
  ticker: string;
}

export function AnalystRatingsTab({ ticker }: Props) {
  const { data, error } = useAnalystRatings(ticker);
  // Same SWR key TickerTabsContainer's own header fetch already uses -- a
  // cache hit, not a new request. Price targets are quote-domain (the
  // ticker's actual traded market currency), same as the header's own
  // price -- must never disagree with it.
  const { data: summary } = useTickerSummary(ticker);
  const quoteCurrency = summary?.quote_currency ?? "USD";

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

  return (
    <div className="space-y-6 py-6">
      <div className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">At a Glance</h2>
        <AtAGlanceCard banner={data.banner} priceTarget={data.price_target} currency={quoteCurrency} />
      </div>
      <div className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Price Targets Over Time</h2>
        <PriceTargetTrendCard history={data.history} recency={data.price_target_by_recency} currency={quoteCurrency} />
      </div>
      <div className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Analyst Sentiment Over Time</h2>
        <SentimentOverTimeCard
          history={data.history}
          columns={data.recommendation_details}
          currency={quoteCurrency}
          currentAsOf={data.grades_consensus_as_of}
        />
      </div>
    </div>
  );
}

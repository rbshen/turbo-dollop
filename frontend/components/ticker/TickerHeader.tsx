"use client";

import { ExchangeBadge } from "@/components/ticker/ExchangeBadge";
import { FairValuePill } from "@/components/ticker/FairValuePill";
import { PriceChange } from "@/components/ticker/PriceChange";
import { RefreshButton } from "@/components/ticker/RefreshButton";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";

interface Props {
  symbol: string;
}

export function TickerHeader({ symbol }: Props) {
  const { data, error } = useTickerSummary(symbol);

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-red-400">Couldn&apos;t load {symbol} — {error.message}</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-zinc-600 animate-pulse">Loading {symbol}…</span>
      </div>
    );
  }

  return (
    <div className="space-y-4 py-6">
      {(data.sector || data.industry) && (
        <p className="text-xs text-zinc-500">
          {data.sector}
          {data.sector && data.industry && " • "}
          {data.industry}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">{data.company_name ?? data.ticker}</h1>
        <span className="font-mono text-sm text-zinc-500">{data.ticker}</span>
        {data.exchange && <ExchangeBadge exchange={data.exchange} />}
        <span className="ml-auto">
          <RefreshButton ticker={data.ticker} />
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {data.price != null && (
          <span className="font-mono text-xl font-bold tabular-nums text-zinc-100">${data.price.toFixed(2)}</span>
        )}
        <PriceChange change={data.change} changePercent={data.change_percent} />
        <FairValuePill verdict={data.fair_value_verdict} price={data.fair_value_price} method={data.fair_value_method} />
      </div>

      {data.next_earnings_date && (
        <p className="text-xs text-zinc-500">Next earnings: {data.next_earnings_date}</p>
      )}
    </div>
  );
}

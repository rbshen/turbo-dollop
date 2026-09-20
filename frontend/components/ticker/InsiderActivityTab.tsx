"use client";

import { useState } from "react";

import { InsiderNotableTrades } from "@/components/insiderActivity/InsiderNotableTrades";
import { InsiderQuarterlyChart } from "@/components/insiderActivity/InsiderQuarterlyChart";
import { InsiderSummaryCard } from "@/components/insiderActivity/InsiderSummaryCard";
import { InsiderTransactionsTable } from "@/components/insiderActivity/InsiderTransactionsTable";
import { SegmentedControl } from "@/components/shared/SegmentedControl";
import { useInsiderActivity } from "@/lib/hooks/useInsiderActivity";
import {
  INSIDER_VIEW_CAPTIONS,
  INSIDER_VIEW_OPTIONS,
  type InsiderView,
  fmtAsOf,
  insiderViewState,
} from "@/lib/insiderActivity";

interface Props {
  ticker: string;
}

const EMPTY_MESSAGE = "No insider trading data available for this ticker";
const NOT_CACHED_MESSAGE =
  "Insider activity hasn't been cached for this ticker yet. FMP may be paused, or the fetch hasn't succeeded yet — check back after the next successful refresh.";

function SectionHeading({ children }: { children: string }) {
  return <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">{children}</h2>;
}

export function InsiderActivityTab({ ticker }: Props) {
  const { data, error } = useInsiderActivity(ticker);
  // One state for the chart and the transactions table -- a control on either
  // one switches both.
  const [insiderView, setInsiderView] = useState<InsiderView>("open_market");

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

  const view = insiderViewState(data);

  // Two distinct empty states, deliberately not merged: "empty" means FMP
  // answered and there is genuinely nothing to show (HK/France-listed or
  // quiet tickers); "not_cached" means we have never successfully fetched
  // it, so an absence of data says nothing about the ticker. Same card
  // shape as LiquidityZonesCard's empty state.
  if (view !== "content") {
    const isEmpty = view === "empty";
    return (
      <div className="py-6">
        <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h2 className="font-heading text-sm font-semibold text-text-primary">Insider Activity</h2>
              <p className="text-sm text-text-secondary">Form 4 insider buys and sales.</p>
            </div>
            <span className="shrink-0 rounded-full border border-border-card bg-surface-2 px-3 py-1 text-xs font-semibold text-text-tertiary">
              {isEmpty ? "No data" : "Not cached yet"}
            </span>
          </div>
          {isEmpty ? (
            <p className="rounded-md border border-border-card bg-surface-2 p-3 text-xs text-text-secondary">
              {EMPTY_MESSAGE}
              {data.as_of ? ` (checked ${fmtAsOf(data.as_of)})` : ""}.
            </p>
          ) : (
            <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs text-warn">{NOT_CACHED_MESSAGE}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      {data.as_of && <p className="text-xs text-text-tertiary">Data as of {fmtAsOf(data.as_of)}</p>}

      <div className="space-y-3">
        <SectionHeading>At a Glance</SectionHeading>
        <InsiderSummaryCard summary={data.summary} />
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionHeading>Shares Acquired vs. Disposed by Quarter</SectionHeading>
          <SegmentedControl value={insiderView} onChange={setInsiderView} options={INSIDER_VIEW_OPTIONS} />
        </div>
        <div className="space-y-3 rounded-lg border border-border-card bg-surface p-6">
          <p className="text-xs text-text-tertiary">{INSIDER_VIEW_CAPTIONS[insiderView]}</p>
          <InsiderQuarterlyChart activity={data.quarterly_activity} view={insiderView} />
          {data.history_truncated && (
            <p className="text-xs text-text-tertiary">
              Earlier quarters are left out — this ticker files too often for the fetched history to reach back the full
              12 quarters, and a partly-covered quarter would read as a smaller real total.
            </p>
          )}
        </div>
      </div>

      <div className="space-y-3">
        <SectionHeading>Notable Trades</SectionHeading>
        <InsiderNotableTrades buy={data.summary.notable_buy} sale={data.summary.notable_sale} />
      </div>

      <InsiderTransactionsTable transactions={data.transactions} view={insiderView} onViewChange={setInsiderView} />
    </div>
  );
}

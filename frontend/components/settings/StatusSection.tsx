"use client";

import { DataSourceCard } from "@/components/settings/DataSourceCard";
import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";
import { useDataSourceHealth } from "@/lib/hooks/useDataSourceHealth";

// "Quote / Price" is deliberately split across the FMP/Massive/Yahoo
// cards, not one tag on FMP -- when FMP is paused,
// data/ticker_summary.py::get_summary() overrides only the `price` field
// with a live Massive snapshot (falling back to Yahoo for a non-US
// ticker or a Massive error -- _fetch_massive_latest_price/
// _fetch_yahoo_latest_close); every other quote field (change, market
// cap, year high/low) has no Massive/Yahoo equivalent and stays pinned to
// the last cached FMP value, going stale like everything else on this
// card.
//
// Massive/Polygon (2026-09-23 migration) is now the primary daily-bar
// source for every US-listed ticker across the technical-analysis
// features below; Yahoo Finance stays wired in as an automatic fallback
// for those features (any US ticker Massive can't serve) plus the two
// ranges/features that need more history than Massive's Starter plan
// covers (Chart's W_4Y view, the Analyst Ratings 10y price overlay) and
// every non-US-listed ticker outright.
const FMP_POWERS = ["Fundamentals", "Ratios & Scoring", "Quote (change/cap/range)", "Analyst Ratings"];
const MASSIVE_POWERS = [
  "Chart (OHLC, ≤2y)",
  "Price (fallback)",
  "Weinstein Stage",
  "Liquidity Zones",
  "Trend Signals",
  "Sector Heatmap",
  "Momentum",
];
const YAHOO_POWERS = ["Chart (OHLC, 4y)", "Price (fallback, non-US)", "Non-US tickers"];

/** Settings "Status" tab content -- Data Sources (FMP + Yahoo Finance
 * health cards) then Scheduled Jobs, replacing the old site-wide
 * FmpPausedBanner/CronHealthBanner entirely (see app/layout.tsx, both
 * deleted). No own section title here -- the sidebar nav label already
 * says "Status" -- unlike every sibling section, which renders its own
 * `<h2>` matching its nav label (e.g. MoatSettingsForm's own "Economic
 * Moat Point Values" heading). */
export function StatusSection() {
  const { data } = useDataSourceHealth();
  const fmp = data?.sources.find((s) => s.source === "fmp");
  const massive = data?.sources.find((s) => s.source === "massive");
  const yahoo = data?.sources.find((s) => s.source === "yahoo");

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-4 lg:flex-row">
        <DataSourceCard title="FMP" flagLabel="FMP_ENABLED" status={fmp} powers={FMP_POWERS} />
        <DataSourceCard title="Massive" flagLabel="MASSIVE_ENABLED" status={massive} powers={MASSIVE_POWERS} />
        <DataSourceCard title="Yahoo Finance" status={yahoo} powers={YAHOO_POWERS} />
      </div>

      <ScheduledJobsSection />
    </section>
  );
}

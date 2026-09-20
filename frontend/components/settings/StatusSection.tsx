"use client";

import { DataSourceCard } from "@/components/settings/DataSourceCard";
import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";
import { useDataSourceHealth } from "@/lib/hooks/useDataSourceHealth";

// "Quote / Price" is deliberately split across both cards, not one tag on
// FMP -- when FMP is paused, data/ticker_summary.py::get_summary()
// overrides only the `price` field with a live Yahoo close
// (_fetch_yahoo_latest_close); every other quote field (change, market
// cap, year high/low) has no Yahoo equivalent and stays pinned to the
// last cached FMP value, going stale like everything else on this card.
const FMP_POWERS = ["Fundamentals", "Ratios & Scoring", "Quote (change/cap/range)", "Analyst Ratings"];
const YAHOO_POWERS = ["Chart (OHLC)", "Price (fallback)", "Weinstein Stage", "Liquidity Zones", "Trend Signals", "Sector Heatmap"];

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
  const yahoo = data?.sources.find((s) => s.source === "yahoo");

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-4 lg:flex-row">
        <DataSourceCard title="FMP" flagLabel="FMP_ENABLED" status={fmp} powers={FMP_POWERS} />
        <DataSourceCard title="Yahoo Finance" status={yahoo} powers={YAHOO_POWERS} />
      </div>

      <ScheduledJobsSection />
    </section>
  );
}

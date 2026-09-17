"use client";

import { DataSourceCard } from "@/components/settings/DataSourceCard";
import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";
import { useDataSourceHealth } from "@/lib/hooks/useDataSourceHealth";

const FMP_POWERS = ["Fundamentals", "Ratios & Scoring", "Quote / Price", "Analyst Ratings"];
const YAHOO_POWERS = ["Chart (OHLC)", "Weinstein Stage", "Liquidity Zones", "Trend Signals"];

/** Settings "Status" tab content -- Data Sources (FMP + Yahoo Finance
 * health cards) then Scheduled Jobs, replacing the old site-wide
 * FmpPausedBanner/CronHealthBanner entirely (see app/layout.tsx, both
 * deleted). No own section title -- the sidebar nav label already says
 * "Status", matching every sibling section's own content component
 * (e.g. WatchlistSettingsForm renders no "Watchlists" heading either). */
export function StatusSection() {
  const { data } = useDataSourceHealth();
  const fmp = data?.sources.find((s) => s.source === "fmp");
  const yahoo = data?.sources.find((s) => s.source === "yahoo");

  return (
    <section className="space-y-4">
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Data Sources</h3>
        <div className="flex flex-col gap-4 lg:flex-row">
          <DataSourceCard title="FMP" flagLabel="FMP_ENABLED" status={fmp} powers={FMP_POWERS} />
          <DataSourceCard title="Yahoo Finance" status={yahoo} powers={YAHOO_POWERS} />
        </div>
      </div>

      <ScheduledJobsSection />
    </section>
  );
}

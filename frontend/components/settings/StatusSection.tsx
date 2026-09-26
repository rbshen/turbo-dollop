"use client";

import { DataGroupsSection } from "@/components/settings/DataGroupsSection";
import { DataSourceCard } from "@/components/settings/DataSourceCard";
import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";
import { useDataSourceHealth } from "@/lib/hooks/useDataSourceHealth";

// Yahoo Finance is now only the automatic fallback behind FMP for the daily/intraday
// price features (and the Chart tab's fall-through). The ticker header's price no longer
// touches it: a live FMP quote, then the last close cached nightly from FMP.
const YAHOO_POWERS = ["Chart (fallback)", "Price bars (fallback)", "Non-US tickers"];

/** Settings "Status" tab content -- FMP data-group table, the Yahoo
 * health card (until P6b removes it), then Scheduled Jobs, replacing the old site-wide
 * FmpPausedBanner/CronHealthBanner entirely (see app/layout.tsx, both
 * deleted). No own section title here -- the sidebar nav label already
 * says "Status" -- unlike every sibling section, which renders its own
 * `<h2>` matching its nav label (e.g. MoatSettingsForm's own "Economic
 * Moat Point Values" heading). */
export function StatusSection() {
  const { data } = useDataSourceHealth();
  const yahoo = data?.sources.find((s) => s.source === "yahoo");

  return (
    <section className="space-y-4">
      <DataGroupsSection />

      <div className="flex flex-col gap-4 lg:flex-row">
        <DataSourceCard title="Yahoo Finance" status={yahoo} powers={YAHOO_POWERS} />
      </div>

      <ScheduledJobsSection />
    </section>
  );
}

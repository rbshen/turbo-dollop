"use client";

import { DataGroupsSection } from "@/components/settings/DataGroupsSection";
import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";

/** Settings "Status" tab content -- the FMP data-group table, then Scheduled Jobs, replacing the
 * old site-wide FmpPausedBanner/CronHealthBanner entirely (see app/layout.tsx, both deleted).
 * FMP is the only external data source (Yahoo was removed in Phase 6b), so there is no separate
 * per-source health card. No own section title here -- the sidebar nav label already
 * says "Status" -- unlike every sibling section, which renders its own
 * `<h2>` matching its nav label (e.g. MoatSettingsForm's own "Economic
 * Moat Point Values" heading). */
export function StatusSection() {
  return (
    <section className="space-y-4">
      <DataGroupsSection />

      <ScheduledJobsSection />
    </section>
  );
}

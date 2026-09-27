"use client";

import { FmpHealthSummaryCard } from "@/components/settings/FmpHealthSummaryCard";
import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";

/** Settings "Scheduled Jobs" tab content (renamed from "Status" 2026-09-27) --
 * the FMP plan/master-switch/key-problem summary card, then the cron jobs
 * table, replacing the old site-wide FmpPausedBanner/CronHealthBanner
 * entirely (see app/layout.tsx, both deleted). The per-group FMP toggle
 * table that used to live here moved out to its own "FMP Data Groups"
 * section (FmpDataGroupsSection) the same day. FMP is the only external
 * data source, so there is no separate per-source health card. No own
 * section title here -- the sidebar nav label already says "Scheduled
 * Jobs" -- unlike every sibling section, which renders its own `<h2>`
 * matching its nav label (e.g. MoatSettingsForm's own "Economic Moat
 * Point Values" heading). */
export function StatusSection() {
  return (
    <section className="space-y-4">
      <FmpHealthSummaryCard />

      <ScheduledJobsSection />
    </section>
  );
}

"use client";

import { ScheduledJobsSection } from "@/components/settings/ScheduledJobsSection";

/** Settings "Scheduled jobs" tab content (renamed from "Status" 2026-09-27) --
 * just the cron jobs table, replacing the old site-wide FmpPausedBanner/
 * CronHealthBanner entirely (see app/layout.tsx, both deleted). The per-group
 * FMP toggle table moved out to "FMP data groups" (FmpDataGroupsSection) on
 * 2026-09-27, and the FMP plan/master-switch/key-problem card followed it
 * there on 2026-09-30. FMP is the only external data source, so there is no
 * separate per-source health card. */
export function StatusSection() {
  return (
    <section className="space-y-4">
      <ScheduledJobsSection />
    </section>
  );
}

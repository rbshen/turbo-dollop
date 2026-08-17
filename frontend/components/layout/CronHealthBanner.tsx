"use client";

import { WarningOctagon } from "@phosphor-icons/react";

import { useCronHealth } from "@/lib/hooks/useCronHealth";

// Same bare-div, no-dismiss-state pattern as FmpPausedBanner (rare,
// actionable signal, not routine noise -- reappearing on every
// load/navigation is the point). Deliberately NOT visually identical to
// that banner, since the two mean different things: red (text-negative),
// not amber (text-warn), plus an icon FmpPausedBanner doesn't have.
export function CronHealthBanner() {
  const { data } = useCronHealth();

  // data.enabled is an explicit skip (CRON_HEALTH_ENABLED=false), distinct
  // from "checked and every job came back ok" -- both render nothing, but
  // only one of them means the backend actually looked.
  if (!data || !data.enabled) return null;

  const problemJobs = data.jobs.filter((job) => job.health_status !== "ok");
  if (problemJobs.length === 0) return null;

  return (
    <div className="border-b border-negative/40 bg-negative/10 px-4 py-2 text-sm text-negative">
      <div className="mx-auto flex max-w-5xl items-start gap-2">
        <WarningOctagon className="mt-0.5 size-4 shrink-0" weight="fill" />
        <div>
          <span className="font-medium">
            {problemJobs.length === 1 ? "A cron job needs attention:" : `${problemJobs.length} cron jobs need attention:`}
          </span>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {problemJobs.map((job) => (
              <li key={job.job_name}>
                <span className="font-mono">{job.job_name}</span> — {job.health_status}
                {job.message ? `: ${job.message}` : ""}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

"use client";

import { Fragment } from "react";

import { useCronHealth } from "@/lib/hooks/useCronHealth";
import { useFmpStatus } from "@/lib/hooks/useFmpStatus";
import type { CronJobHealthOut } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const GROUP_ORDER: CronJobHealthOut["cadence_group"][] = ["daily", "weekly", "monthly"];
const GROUP_LABELS: Record<CronJobHealthOut["cadence_group"], string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

const STATUS_DOT: Record<CronJobHealthOut["health_status"], string> = {
  ok: "bg-positive",
  failed: "bg-negative",
  overdue: "bg-warn",
  unknown: "bg-zinc-600",
};

// Jobs with their own explicit `if not settings.fmp_enabled: skip` early
// return (see CLAUDE.md's "Cron job heartbeat" section) -- these still
// report a normal "success" heartbeat while skipped, so a genuinely
// missing run for one of these two specifically is far more likely an
// FMP-disabled skip than a real gap. This is a frontend-only, best-effort
// text distinction (per the task's own "otherwise both gray is fine"
// allowance) -- health_status itself stays "unknown" either way.
const FMP_GATED_JOB_NAMES = new Set(["pipeline.nightly_fundamentals_fetch", "pipeline.monthly_price_target_snapshot"]);

function messageFor(job: CronJobHealthOut, fmpEnabled: boolean | undefined): string {
  if (job.health_status === "unknown" && fmpEnabled === false && FMP_GATED_JOB_NAMES.has(job.job_name)) {
    return "Skipped — FMP disabled";
  }
  return job.message ?? "—";
}

/** Settings "Status" section's Scheduled Jobs table -- one row per cron
 * job, grouped by cadence (Daily/Weekly/Monthly, in that order) and sorted
 * by time-of-day within each group, reading live status off the existing
 * useCronHealth() (core/cron_health.py::get_cron_health -- no second
 * health-tracking system, this is purely a display layer over it). */
export function ScheduledJobsSection() {
  const { data: cronHealth } = useCronHealth();
  const { data: fmpStatus } = useFmpStatus();

  return (
    <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-900/40 p-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-100">Scheduled Jobs</h3>
        <div className="flex items-center gap-4 text-xs text-zinc-500">
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-positive" /> Success
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-negative" /> Failed
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-warn" /> Overdue
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-zinc-600" /> Unknown
          </span>
        </div>
      </div>

      {!cronHealth ? (
        <p className="text-sm text-zinc-600">Loading…</p>
      ) : !cronHealth.enabled ? (
        <p className="text-sm text-zinc-400">Scheduled job monitoring is currently disabled (CRON_HEALTH_ENABLED=false).</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-zinc-500">
              <th className="py-1.5 pr-3 font-medium">Job</th>
              <th className="py-1.5 pr-3 font-medium">Description</th>
              <th className="py-1.5 pr-3 font-medium">Time</th>
              <th className="py-1.5 pr-3 font-medium">Status</th>
              <th className="py-1.5 font-medium">Message</th>
            </tr>
          </thead>
          <tbody>
            {GROUP_ORDER.map((group) => {
              const jobs = cronHealth.jobs
                .filter((job) => job.cadence_group === group)
                .sort((a, b) => a.sort_minutes - b.sort_minutes);
              if (jobs.length === 0) return null;
              return (
                <Fragment key={group}>
                  <tr>
                    <td colSpan={5} className="pt-3 pb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                      {GROUP_LABELS[group]}
                    </td>
                  </tr>
                  {jobs.map((job) => (
                    <tr key={job.job_name} className="border-t border-zinc-800/60">
                      <td className="py-2 pr-3 font-mono text-xs text-zinc-200">{job.job_name}</td>
                      <td className="py-2 pr-3 text-zinc-400">{job.description}</td>
                      <td className="py-2 pr-3 font-mono text-xs text-zinc-400">{job.time_label}</td>
                      <td className="py-2 pr-3">
                        <span className={cn("inline-block size-2 rounded-full", STATUS_DOT[job.health_status])} />
                      </td>
                      <td
                        className={cn(
                          "py-2 text-xs",
                          job.health_status === "failed"
                            ? "text-negative"
                            : job.health_status === "overdue"
                              ? "text-warn"
                              : "text-zinc-500"
                        )}
                      >
                        {messageFor(job, fmpStatus?.enabled)}
                      </td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

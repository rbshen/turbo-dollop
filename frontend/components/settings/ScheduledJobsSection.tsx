"use client";

import { useState } from "react";

import { useCronHealth } from "@/lib/hooks/useCronHealth";
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
  skipped: "bg-sky-500",
};

/** Settings "Status" section's Scheduled Jobs table -- one row per cron
 * job, switchable by cadence via a Daily/Weekly/Monthly tab bar (defaults
 * to Daily) and sorted by time-of-day within the active tab, reading live
 * status off the existing useCronHealth() (core/cron_health.py::
 * get_cron_health -- no second health-tracking system, this is purely a
 * display layer over it). */
export function ScheduledJobsSection() {
  const { data: cronHealth } = useCronHealth();
  const [activeGroup, setActiveGroup] = useState<CronJobHealthOut["cadence_group"]>("daily");

  const jobs = (cronHealth?.jobs ?? [])
    .filter((job) => job.cadence_group === activeGroup)
    .sort((a, b) => a.sort_minutes - b.sort_minutes);

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
            <span className="size-2 rounded-full bg-sky-500" /> Skipped
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
        <>
          <div className="flex gap-1 border-b border-zinc-800">
            {GROUP_ORDER.map((group) => {
              const count = cronHealth.jobs.filter((job) => job.cadence_group === group).length;
              const isActive = group === activeGroup;
              return (
                <button
                  key={group}
                  type="button"
                  onClick={() => setActiveGroup(group)}
                  className={cn(
                    "border-b-2 px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive
                      ? "border-brand text-brand"
                      : "border-transparent text-zinc-500 hover:text-zinc-300"
                  )}
                >
                  {GROUP_LABELS[group]} <span className="text-xs text-zinc-600">({count})</span>
                </button>
              );
            })}
          </div>

          <table className="w-full table-fixed text-left text-sm">
            <colgroup>
              <col className="w-[45%]" />
              <col className="w-28" />
              <col className="w-24" />
              <col />
            </colgroup>
            <thead>
              <tr className="text-xs uppercase tracking-wide text-zinc-500">
                <th className="py-1.5 pr-3 font-medium">Description</th>
                <th className="py-1.5 pr-3 font-medium">Time</th>
                <th className="py-1.5 pr-3 font-medium">Status</th>
                <th className="py-1.5 font-medium">Message</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-4 text-sm text-zinc-600">
                    No {GROUP_LABELS[activeGroup].toLowerCase()} jobs.
                  </td>
                </tr>
              ) : (
                jobs.map((job) => (
                  <tr key={job.job_name} className="border-t border-zinc-800/60">
                    <td className="py-2 pr-3">
                      <div className="text-zinc-200">{job.description}</div>
                      <div className="font-mono text-[11px] text-zinc-500">{job.job_name}</div>
                    </td>
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
                            : job.health_status === "skipped"
                              ? "text-sky-400"
                              : "text-zinc-500"
                      )}
                    >
                      {job.message ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

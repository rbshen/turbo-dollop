"use client";

import { useState } from "react";

import { useCronHealth } from "@/lib/hooks/useCronHealth";
import type { CronJobHealthOut } from "@/lib/api/types";
import { Section } from "@/components/ui/section";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const GROUP_ORDER: CronJobHealthOut["cadence_group"][] = ["daily", "weekly", "monthly"];
const GROUP_LABELS: Record<CronJobHealthOut["cadence_group"], string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

// unknown and skipped share the same neutral read (nothing is wrong, there's
// just no live/attempted run to report) -- same treatment Badge/Status use
// elsewhere in the app for a value that isn't a Pass/Fail-style read. This
// retires the raw sky-blue "skipped" dot: blue is reserved for brand actions
// only, everywhere else in the app.
const STATUS_DOT: Record<CronJobHealthOut["health_status"], string> = {
  ok: "bg-positive",
  failed: "bg-negative",
  overdue: "bg-warn",
  unknown: "bg-text-tertiary",
  skipped: "bg-text-tertiary",
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
    <Section>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">Scheduled Jobs</h3>
        <div className="flex items-center gap-4 text-xs text-text-tertiary">
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
            <span className="size-2 rounded-full bg-text-tertiary" /> Skipped
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-text-tertiary" /> Unknown
          </span>
        </div>
      </div>

      {!cronHealth ? (
        <p className="mt-3 text-sm text-text-tertiary animate-pulse">Loading…</p>
      ) : !cronHealth.enabled ? (
        <p className="mt-3 text-sm text-text-secondary">Scheduled job monitoring is currently disabled (CRON_HEALTH_ENABLED=false).</p>
      ) : (
        <>
          <div className="mt-3 flex gap-1 border-b border-border-subtle">
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
                      : "border-transparent text-text-tertiary hover:text-text-primary"
                  )}
                >
                  {GROUP_LABELS[group]} <span className="text-xs text-text-tertiary">({count})</span>
                </button>
              );
            })}
          </div>

          <Table className="table-fixed">
            <colgroup>
              <col className="w-[45%]" />
              <col className="w-28" />
              <col className="w-24" />
              <col />
            </colgroup>
            <TableHeader>
              <TableRow className="h-9">
                <TableHead>Description</TableHead>
                <TableHead>Time</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Message</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-4 text-sm text-text-tertiary">
                    No {GROUP_LABELS[activeGroup].toLowerCase()} jobs.
                  </TableCell>
                </TableRow>
              ) : (
                jobs.map((job) => (
                  <TableRow key={job.job_name}>
                    <TableCell className="whitespace-normal">
                      <div className="text-text-primary">{job.description}</div>
                      <div className="font-mono text-[11px] text-text-tertiary">{job.job_name}</div>
                    </TableCell>
                    <TableCell className="font-mono text-xs tabular-nums text-text-secondary">{job.time_label}</TableCell>
                    <TableCell>
                      <span className={cn("inline-block size-2 rounded-full", STATUS_DOT[job.health_status])} />
                    </TableCell>
                    <TableCell
                      className={cn(
                        "whitespace-normal text-xs",
                        job.health_status === "failed"
                          ? "text-negative"
                          : job.health_status === "overdue"
                            ? "text-warn"
                            : "text-text-tertiary"
                      )}
                    >
                      {job.message ?? "—"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </>
      )}
    </Section>
  );
}

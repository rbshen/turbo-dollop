"use client";

import { useState } from "react";

import { useCronHealth } from "@/lib/hooks/useCronHealth";
import type { CronJobHealthOut } from "@/lib/api/types";
import { Section } from "@/components/ui/section";
import { Status, type StatusTone } from "@/components/ui/status";
import { Tabs } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const GROUP_ORDER: CronJobHealthOut["cadence_group"][] = ["daily", "weekly", "monthly"];
const GROUP_LABELS: Record<CronJobHealthOut["cadence_group"], string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

// unknown and skipped share the same neutral pill (nothing is wrong, there's
// just no live/attempted run to report) -- same treatment Status/Badge use
// elsewhere in the app for a value that isn't a Pass/Fail-style read, told
// apart by their words. This retires the raw sky-blue "skipped" treatment:
// blue is reserved for brand actions only, everywhere else in the app.
const STATUS_PILL: Record<CronJobHealthOut["health_status"], { tone: StatusTone; label: string }> = {
  ok: { tone: "positive", label: "Success" },
  failed: { tone: "negative", label: "Failed" },
  overdue: { tone: "warn", label: "Overdue" },
  unknown: { tone: "neutral", label: "Unknown" },
  skipped: { tone: "neutral", label: "Skipped" },
};

/** One job's health pill -- exported so /styleguide shows the real thing. */
export function JobStatusPill({ status }: { status: CronJobHealthOut["health_status"] }) {
  const { tone, label } = STATUS_PILL[status];
  return <Status tone={tone}>{label}</Status>;
}

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
      <h3 className="text-sm font-semibold text-text-primary">Scheduled jobs</h3>

      {!cronHealth ? (
        <p className="mt-3 text-sm text-text-tertiary animate-pulse">Loading…</p>
      ) : !cronHealth.enabled ? (
        <p className="mt-3 text-sm text-text-secondary">Scheduled job monitoring is currently disabled (CRON_HEALTH_ENABLED=false).</p>
      ) : (
        <>
          <Tabs
            aria-label="Job cadence"
            className="mt-3"
            value={activeGroup}
            onValueChange={(next) => setActiveGroup(next as CronJobHealthOut["cadence_group"])}
            items={GROUP_ORDER.map((group) => ({
              value: group,
              label: GROUP_LABELS[group],
              count: cronHealth.jobs.filter((job) => job.cadence_group === group).length,
            }))}
          />

          <Table className="table-fixed">
            <colgroup>
              <col className="w-[45%]" />
              <col className="w-28" />
              <col className="w-28" />
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
                    <TableCell className="whitespace-normal font-mono text-xs tabular-nums text-text-secondary">{job.time_label}</TableCell>
                    <TableCell>
                      <JobStatusPill status={job.health_status} />
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

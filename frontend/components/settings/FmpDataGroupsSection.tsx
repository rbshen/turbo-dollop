"use client";

import { useState } from "react";

import { updateGroup, useDataGroups } from "@/lib/hooks/useDataGroups";
import { STATE_LABEL, disableWarning, reasonText } from "@/lib/dataGroups";
import { errorDetail } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/relativeTime";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Section } from "@/components/ui/section";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DataGroupOut, DataGroupState } from "@/lib/api/types";
import { cn } from "@/lib/utils";

// cached_only has no real tone of its own (nothing is wrong, it's simply not
// refreshing) -- same neutral Badge tone the rest of the app uses for a
// value that isn't a Pass/Fail-style read (see e.g. MomentumTable's
// overall_score cell, or Badge's own "Not scored" styleguide example).
const STATE_TONE: Record<DataGroupState, BadgeTone> = {
  live: "positive",
  cached_only: "neutral",
  not_on_plan: "warn",
  restricted: "negative",
  failing: "negative",
};

/** Settings > FMP Data Groups: one row per FMP data group (core/data_groups.py)
 * -- the endpoint group/tier/enabled table, split out of the old combined
 * DataGroupsSection (2026-09-27) so it could live in its own nav section,
 * separate from the plan/master-switch/key-problem summary (now
 * FmpHealthSummaryCard, under Settings > Scheduled Jobs). The "verified" tick
 * (2026-09-27) was removed outright, not just hidden here -- confirmed to
 * have zero downstream effect anywhere. Toggles and the required-tier editor
 * write to the DB and take effect live (no restart). */
export function FmpDataGroupsSection() {
  const { data, error } = useDataGroups();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
    } catch (e) {
      setMessage(errorDetail(e) ?? "Update failed");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="text-sm text-negative">Couldn&apos;t load data groups — {error.message}</p>;
  if (!data) return <p className="text-sm text-text-tertiary animate-pulse">Loading data groups…</p>;

  const onToggle = (group: DataGroupOut, enabled: boolean) => {
    if (!enabled && !window.confirm(disableWarning(group))) return;
    void run(() => updateGroup(group.key, { enabled }));
  };

  return (
    <Section title="FMP Data Groups">
      {message && <p className="mb-3 text-xs text-negative">{message}</p>}

      <Table>
        <TableHeader>
          <TableRow className="h-9">
            <TableHead className="w-10">On</TableHead>
            <TableHead>Group</TableHead>
            <TableHead>State</TableHead>
            <TableHead>Last success</TableHead>
            <TableHead>Required tier</TableHead>
            <TableHead>Feeds</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.groups.map((g) => (
            <TableRow key={g.key} className={cn("align-top", !g.can_toggle && "opacity-60")}>
              <TableCell>
                <input
                  type="checkbox"
                  aria-label={`Enable ${g.label}`}
                  checked={g.enabled}
                  disabled={busy || !g.can_toggle}
                  title={!g.can_toggle ? reasonText(g) : undefined}
                  className="size-3.5 rounded border-border-input bg-surface-2 accent-brand"
                  onChange={(e) => onToggle(g, e.target.checked)}
                />
              </TableCell>
              <TableCell className="whitespace-normal">
                <div className="text-text-primary">{g.label}</div>
                <div className="font-mono text-[11px] text-text-tertiary">
                  {g.key}
                  {!g.wired && " · not wired yet"}
                </div>
              </TableCell>
              <TableCell>
                <Badge tone={STATE_TONE[g.state]} title={g.state === "failing" ? (g.last_error ?? undefined) : reasonText(g) || undefined}>
                  {STATE_LABEL[g.state]}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-xs text-text-secondary">
                {g.last_success_at ? formatRelativeTime(g.last_success_at) : "—"}
              </TableCell>
              <TableCell>
                <select
                  aria-label={`Required tier for ${g.label}`}
                  className="rounded border border-border-input bg-surface-2 px-2 py-1 text-xs text-text-primary focus:border-brand focus:outline-none"
                  value={g.required_tier}
                  disabled={busy}
                  onChange={(e) => void run(() => updateGroup(g.key, { required_tier: e.target.value }))}
                >
                  {data.tiers.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </TableCell>
              <TableCell className="whitespace-normal text-xs text-text-secondary">{g.feeds.join(", ")}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

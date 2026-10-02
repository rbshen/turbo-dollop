"use client";

import { useState } from "react";

import { retestGroupVariants, updateGroup, useDataGroups } from "@/lib/hooks/useDataGroups";
import { FmpHealthSummaryCard } from "@/components/settings/FmpHealthSummaryCard";
import { STATE_LABEL, disableWarning, reasonText, unavailableNote } from "@/lib/dataGroups";
import { errorDetail } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/relativeTime";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/ui/section";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/switch";
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

/** The per-group table, presentational: every value comes in as a prop and every
 * change goes out through `onToggle` / `onTier`, so it renders identically in
 * the live section and in /styleguide's mock. */
export function FmpGroupsTable({
  groups,
  tiers,
  busy,
  failure,
  onToggle,
  onTier,
  onRetest,
}: {
  groups: DataGroupOut[];
  tiers: string[];
  /** A request is in flight: every control is disabled. */
  busy: boolean;
  /** A failed request's message, shown in the row of the group it was for. */
  failure: { key: string; message: string } | null;
  onToggle: (group: DataGroupOut, enabled: boolean) => void;
  onTier: (group: DataGroupOut, tier: string) => void;
  /** Re-test the group's refused request variants (shown only when it has some). */
  onRetest?: (group: DataGroupOut) => void;
}) {
  return (
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
        {groups.map((g) => (
          <TableRow key={g.key} className={cn("align-top", !g.can_toggle && "opacity-60")}>
            <TableCell>
              <Switch
                aria-label={`Enable ${g.label}`}
                checked={g.enabled}
                disabled={busy || !g.can_toggle}
                title={!g.can_toggle ? reasonText(g) : undefined}
                onChange={(e) => onToggle(g, e.target.checked)}
              />
            </TableCell>
            <TableCell className="whitespace-normal">
              <div className="text-text-primary">{g.label}</div>
              <div className="font-mono text-[11px] text-text-tertiary">
                {g.key}
                {!g.wired && " · not wired yet"}
              </div>
              {unavailableNote(g) && (
                <div className="mt-1 flex items-center gap-2 text-xs text-text-secondary">
                  <span title={(g.unavailable_variants ?? []).map((v) => v.label).join("\n")}>{unavailableNote(g)}</span>
                  {onRetest && (
                    <Button variant="ghost" size="sm" disabled={busy} onClick={() => onRetest(g)}>
                      Re-test
                    </Button>
                  )}
                </div>
              )}
              {failure?.key === g.key && (
                <p role="alert" className="mt-1 text-xs text-negative">
                  {failure.message}
                </p>
              )}
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
              <Select
                size="medium"
                aria-label={`Required tier for ${g.label}`}
                value={g.required_tier}
                disabled={busy}
                onChange={(e) => onTier(g, e.target.value)}
              >
                {tiers.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
            </TableCell>
            <TableCell className="whitespace-normal text-xs text-text-secondary">{g.feeds.join(", ")}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Settings > FMP Data Groups: one row per FMP data group (core/data_groups.py)
 * -- the endpoint group/tier/enabled table, split out of the old combined
 * DataGroupsSection (2026-09-27) so it could live in its own nav section --
 * with the plan/master-switch/key-problem summary (FmpHealthSummaryCard)
 * below it (moved here from Settings > Scheduled Jobs, 2026-09-30). The
 * table and the card are independent components that share one SWR key
 * (useDataGroups), so a plan or master change made in the card updates the
 * table's rows with no wiring between them. The "verified" tick
 * (2026-09-27) was removed outright, not just hidden here -- confirmed to
 * have zero downstream effect anywhere. Toggles and the required-tier editor
 * write to the DB and take effect live (no restart). */
export function FmpDataGroupsSection() {
  const { data, error } = useDataGroups();
  const [busy, setBusy] = useState(false);
  // A failed request's message, shown in the row of the group it was for (near
  // the control that caused it). The controls themselves stay on the fetched
  // data, so they keep showing the real current state.
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);

  async function run(groupKey: string, action: () => Promise<unknown>) {
    setBusy(true);
    setFailure(null);
    try {
      await action();
    } catch (e) {
      setFailure({ key: groupKey, message: errorDetail(e) ?? "Update failed" });
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="text-sm text-negative">Couldn&apos;t load data groups — {error.message}</p>;
  if (!data) return <p className="text-sm text-text-tertiary animate-pulse">Loading data groups…</p>;

  const onToggle = (group: DataGroupOut, enabled: boolean) => {
    if (!enabled && !window.confirm(disableWarning(group))) return;
    void run(group.key, () => updateGroup(group.key, { enabled }));
  };

  return (
    <Section title="FMP data groups">
      <FmpGroupsTable
        groups={data.groups}
        tiers={data.tiers}
        busy={busy}
        failure={failure}
        onToggle={onToggle}
        onTier={(group, tier) => void run(group.key, () => updateGroup(group.key, { required_tier: tier }))}
        onRetest={(group) => void run(group.key, () => retestGroupVariants(group.key))}
      />

      <FmpHealthSummaryCard />
    </Section>
  );
}

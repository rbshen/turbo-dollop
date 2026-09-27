"use client";

import { useState } from "react";

import { updateGroup, useDataGroups } from "@/lib/hooks/useDataGroups";
import { STATE_LABEL, disableWarning, reasonText } from "@/lib/dataGroups";
import { errorDetail } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/relativeTime";
import type { DataGroupOut, DataGroupState } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const CHIP: Record<DataGroupState, string> = {
  live: "bg-positive/16 text-positive border-positive/40",
  cached_only: "bg-zinc-700/30 text-zinc-300 border-zinc-600",
  not_on_plan: "bg-warn/16 text-warn border-warn/40",
  restricted: "bg-negative/16 text-negative border-negative/40",
  failing: "bg-negative/16 text-negative border-negative/40",
};

/** Settings > FMP Data Groups: one row per FMP data group (core/data_groups.py)
 * -- the endpoint group/tier/verified-tick/enabled table, split out of the old
 * combined DataGroupsSection (2026-09-27) so it could live in its own nav
 * section, separate from the plan/master-switch/key-problem summary (now
 * FmpHealthSummaryCard, under Settings > Scheduled Jobs). Toggles, the
 * required-tier editor and its "verified" tick all write to the DB and take
 * effect live (no restart). */
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
  if (!data) return <p className="text-sm text-zinc-600 animate-pulse">Loading data groups…</p>;

  const onToggle = (group: DataGroupOut, enabled: boolean) => {
    if (!enabled && !window.confirm(disableWarning(group))) return;
    void run(() => updateGroup(group.key, { enabled }));
  };

  return (
    <section className="space-y-4">
      <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">FMP Data Groups</h2>

      {message && <p className="text-xs text-negative">{message}</p>}

      <div className="overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-900/40 p-5">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-widest text-zinc-500">
              <th className="py-2 pr-3 font-medium">On</th>
              <th className="py-2 pr-3 font-medium">Group</th>
              <th className="py-2 pr-3 font-medium">State</th>
              <th className="py-2 pr-3 font-medium">Last success</th>
              <th className="py-2 pr-3 font-medium">Required tier</th>
              <th className="py-2 font-medium">Feeds</th>
            </tr>
          </thead>
          <tbody>
            {data.groups.map((g) => (
              <tr key={g.key} className={cn("border-t border-zinc-800/60 align-top", !g.can_toggle && "opacity-60")}>
                <td className="py-2 pr-3">
                  <input
                    type="checkbox"
                    aria-label={`Enable ${g.label}`}
                    checked={g.enabled}
                    disabled={busy || !g.can_toggle}
                    title={!g.can_toggle ? reasonText(g) : undefined}
                    onChange={(e) => onToggle(g, e.target.checked)}
                  />
                </td>
                <td className="py-2 pr-3">
                  <div className="text-zinc-200">{g.label}</div>
                  <div className="font-mono text-[11px] text-zinc-500">
                    {g.key}
                    {!g.wired && " · not wired yet"}
                  </div>
                </td>
                <td className="py-2 pr-3">
                  <span
                    title={g.state === "failing" ? (g.last_error ?? undefined) : reasonText(g) || undefined}
                    className={cn("inline-block rounded-full border px-2.5 py-0.5 text-xs font-semibold", CHIP[g.state])}
                  >
                    {STATE_LABEL[g.state]}
                  </span>
                </td>
                <td className="py-2 pr-3 text-xs text-zinc-400">
                  {g.last_success_at ? formatRelativeTime(g.last_success_at) : "—"}
                </td>
                <td className="py-2 pr-3">
                  <div className="flex items-center gap-2">
                    <select
                      aria-label={`Required tier for ${g.label}`}
                      className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200"
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
                    <label className="flex items-center gap-1 text-[11px] text-zinc-500" title="Tick after checking FMP's pricing page yourself">
                      <input
                        type="checkbox"
                        aria-label={`Tier verified for ${g.label}`}
                        checked={g.tier_verified}
                        disabled={busy}
                        onChange={(e) => void run(() => updateGroup(g.key, { tier_verified: e.target.checked }))}
                      />
                      verified
                    </label>
                  </div>
                </td>
                <td className="py-2 text-xs text-zinc-500">{g.feeds.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

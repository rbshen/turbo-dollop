"use client";

import { useState } from "react";

import { setFmpPlan, setMaster, useDataGroups } from "@/lib/hooks/useDataGroups";
import { errorDetail } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Section } from "@/components/ui/section";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/switch";

/** Settings > FMP Data Groups, below the per-group table: the FMP plan /
 * master-switch / key-problem summary card. Split out of the old combined
 * DataGroupsSection (2026-09-27), first kept under Scheduled Jobs, and moved
 * under the group table on 2026-09-30. Shares the same useDataGroups() SWR
 * data as the table -- each keeps its own busy/error state, since they're
 * independent action surfaces (plan/master here, per-group toggles above).
 * It renders no section title of its own: it sits inside FmpDataGroupsSection. */
export function FmpHealthSummaryCard() {
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

  if (error) return <p className="text-sm text-negative">Couldn&apos;t load FMP status — {error.message}</p>;
  if (!data) return <p className="text-sm text-text-tertiary animate-pulse">Loading FMP status…</p>;

  return (
    <Section>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">FMP status</h3>
          <p className="mt-1 max-w-xl text-xs text-text-tertiary">
            A group that is off (or above your plan, or restricted by FMP) makes no live FMP calls and serves cached data
            only — nothing is ever wiped. Changes apply immediately. Per-group toggles are in the table above.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-xs text-text-secondary">
          {/* Both controls apply the moment they change (no Save) and are driven by
              the fetched data, not local state: a cancelled confirmation or a
              failed request leaves them showing the real current value. */}
          <div className="flex items-center gap-2">
            <label htmlFor="fmp-plan">My FMP plan</label>
            <Select
              id="fmp-plan"
              size="medium"
              value={data.fmp_plan}
              disabled={busy}
              onChange={(e) => void run(() => setFmpPlan(e.target.value))}
            >
              {data.tiers.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="fmp-master"
              label="FMP master switch"
              checked={data.master_on}
              disabled={busy}
              onChange={(e) => {
                if (!e.target.checked && !window.confirm("Disable ALL FMP calls? Every group goes cache-only (nothing is wiped).")) return;
                void run(() => setMaster(e.target.checked));
              }}
            />
            <Badge tone={data.master_on ? "positive" : "warn"}>{data.master_on ? "On" : "Off — cache only"}</Badge>
          </div>
        </div>
      </div>

      {data.key_problem_at && (
        <p className="mt-3 rounded border border-negative/40 bg-negative/10 px-3 py-2 text-xs text-negative">
          FMP rejected the API key ({data.key_problem_detail}) — check FMP_API_KEY in backend/.env and your subscription. No
          data group is blamed.
        </p>
      )}
      {message && (
        <p role="alert" className="mt-3 text-xs text-negative">
          {message}
        </p>
      )}
    </Section>
  );
}

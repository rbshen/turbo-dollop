"use client";

// Mock of the immediate-apply FMP sections for /styleguide: the real
// presentational views (FmpGroupsTable, FmpStatusCardView) fed with mock data
// and local state, so it makes no API calls and the confirmation dialog is
// skipped. Every control is live so it can be tabbed into and flipped.
import { useState } from "react";

import { FmpStatusCardView } from "@/components/settings/FmpHealthSummaryCard";
import { FmpGroupsTable } from "@/components/settings/FmpDataGroupsSection";
import { Section } from "@/components/ui/section";
import type { DataGroupOut, DataGroupsOut } from "@/lib/api/types";

const TIERS = ["Starter", "Premium", "Ultimate"];

function group(overrides: Partial<DataGroupOut>): DataGroupOut {
  return {
    key: "fundamentals",
    label: "Fundamentals",
    wired: true,
    enabled: true,
    state: "live",
    reason: "live",
    required_tier: "Starter",
    restricted_since: null,
    last_success_at: "2026-09-28T03:10:00Z",
    last_error: null,
    feeds: ["Financials", "Ratios", "Growth Rate"],
    can_toggle: true,
    ...overrides,
  };
}

const GROUPS: DataGroupOut[] = [
  group({}),
  group({ key: "news", label: "News", enabled: false, state: "cached_only", reason: "user_off", feeds: ["News tab"], last_success_at: null }),
  group({
    key: "analyst_ratings",
    label: "Analyst ratings",
    required_tier: "Premium",
    state: "not_on_plan",
    reason: "above_plan",
    can_toggle: false,
    feeds: ["Analyst Ratings tab", "Price-target snapshot"],
  }),
  group({
    key: "institutional_ownership",
    label: "Institutional ownership",
    enabled: false,
    wired: false,
    state: "cached_only",
    reason: "user_off",
    required_tier: "Ultimate",
    feeds: ["Institutional Ownership (shelved)"],
    last_success_at: null,
  }),
];

function status(overrides: Partial<DataGroupsOut> = {}): DataGroupsOut {
  return {
    master_on: true,
    fmp_plan: "Starter",
    tiers: TIERS,
    key_problem_at: null,
    key_problem_detail: null,
    groups: GROUPS,
    ...overrides,
  };
}

function Caption({ children }: { children: React.ReactNode }) {
  return <p className="mb-3 max-w-xl text-xs text-text-tertiary">{children}</p>;
}

// The live section's shape: the table, then the status card below it.
function Panel({
  groups,
  data,
  busy = false,
  failure = null,
  message = null,
  onToggle,
  onTier,
  onPlan,
  onMaster,
  idPrefix,
}: {
  groups: DataGroupOut[];
  data: DataGroupsOut;
  busy?: boolean;
  failure?: { key: string; message: string } | null;
  message?: string | null;
  onToggle?: (g: DataGroupOut, enabled: boolean) => void;
  onTier?: (g: DataGroupOut, tier: string) => void;
  onPlan?: (plan: string) => void;
  onMaster?: (on: boolean) => void;
  idPrefix: string;
}) {
  return (
    <Section title="FMP data groups">
      <FmpGroupsTable
        groups={groups}
        tiers={data.tiers}
        busy={busy}
        failure={failure}
        onToggle={onToggle ?? (() => {})}
        onTier={onTier ?? (() => {})}
      />
      <FmpStatusCardView data={data} busy={busy} message={message} onPlan={onPlan ?? (() => {})} onMaster={onMaster ?? (() => {})} idPrefix={idPrefix} />
    </Section>
  );
}

export function FmpSettingsMock() {
  const [groups, setGroups] = useState(GROUPS);
  const [plan, setPlan] = useState("Starter");
  const [masterOn, setMasterOn] = useState(true);
  const patch = (key: string, change: Partial<DataGroupOut>) =>
    setGroups((prev) => prev.map((g) => (g.key === key ? { ...g, ...change } : g)));

  return (
    <div className="flex flex-col gap-14">
      <div>
        <Caption>
          Interactive: on (Fundamentals), off (News), not toggleable because it is above the plan (Analyst ratings,
          dimmed, with its reason as a tooltip), and not wired yet (Institutional ownership). The Switch and the tier
          Select apply the moment they change: there is no Save. The state badges are static in this mock.
        </Caption>
        <Panel
          idPrefix="sg-fmp-live"
          groups={groups}
          data={status({ groups, fmp_plan: plan, master_on: masterOn })}
          onToggle={(g, enabled) => patch(g.key, { enabled })}
          onTier={(g, tier) => patch(g.key, { required_tier: tier })}
          onPlan={setPlan}
          onMaster={setMasterOn}
        />
      </div>

      <div>
        <Caption>
          While a request is in flight (busy) every control in the table and the card is disabled, and the row keeps
          showing its real state.
        </Caption>
        <Panel idPrefix="sg-fmp-busy" groups={GROUPS} data={status()} busy />
      </div>

      <div>
        <Caption>
          A failed request shows the server&apos;s message next to the control that caused it (in the row, or under the card),
          leaves the control on the real current state, and the key-problem line shows when FMP rejects the API key.
        </Caption>
        <Panel
          idPrefix="sg-fmp-error"
          groups={GROUPS}
          data={status({ master_on: false, key_problem_at: "2026-09-29T10:00:00Z", key_problem_detail: "HTTP 401" })}
          failure={{ key: "news", message: "enabled: Input should be a valid boolean" }}
          message="fmp_plan: Input should be 'Starter', 'Premium' or 'Ultimate'"
        />
      </div>
    </div>
  );
}

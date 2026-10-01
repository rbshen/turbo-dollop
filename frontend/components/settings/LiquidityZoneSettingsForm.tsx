"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { LiquidityZoneConfigOut } from "@/lib/api/types";
import { useLiquidityZoneConfig } from "@/lib/hooks/useLiquidityZoneConfig";
import { Checkbox } from "@/components/ui/checkbox";
import { Select } from "@/components/ui/Select";
import { NumberSettingRow } from "@/components/settings/NumberSettingRow";
import {
  SettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSection,
} from "@/components/settings/SettingsLayout";
import { useSettingsSave, type SettingsSaver } from "@/components/settings/useSettingsSave";
import { checkNumber, type NumberRules } from "@/lib/numberInput";
import { MONITORED_WATCHLISTS_PHRASE } from "@/lib/monitoredWatchlists";

// The bounds are the server's own (LiquidityZoneConfigIn in backend/core/
// schemas.py). A value outside a bound, or a non-integer in an integer field,
// shows an inline error and blocks Save; nothing is clamped, snapped, rounded
// or reverted for the user.
const RULES = {
  swingBars: { integer: true, min: 1, max: 3 },
  cluster: { min: 0, max: 3 },
  maxZones: { integer: true, min: 1, max: 10 },
  recency: { integer: true, min: 1, max: 52 },
} satisfies Record<string, NumberRules>;

export function LiquidityZoneSettingsForm() {
  const { data, error, isLoading } = useLiquidityZoneConfig();
  // Held here, above the keyed form below, so "Saved ✓" survives the remount.
  const saver = useSettingsSave();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load Liquidity Zone settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save remounts this with fresh initial state.
  return <LiquidityZoneForm key={data.updated_at} data={data} saver={saver} />;
}

// A single config object. The three groups below are sub-headings within one
// save action, not independently-saved panels.
function LiquidityZoneForm({ data, saver }: { data: LiquidityZoneConfigOut; saver: SettingsSaver }) {
  // Every number is held as the raw text, like the other Settings forms.
  const [swingBars, setSwingBars] = useState(String(data.swing_bars_each_side));
  const [clusterPct, setClusterPct] = useState(String(data.cluster_pct));
  const [maxLps, setMaxLps] = useState(String(data.max_lps_per_side));
  const [priority, setPriority] = useState<LiquidityZoneConfigOut["over_cap_priority"]>(data.over_cap_priority);
  const [keepSupport, setKeepSupport] = useState(data.keep_last_breached_support);
  const [keepResistance, setKeepResistance] = useState(data.keep_last_breached_resistance);
  const [onlyRecent, setOnlyRecent] = useState(data.only_keep_if_breached_recently);
  const [recencyBars, setRecencyBars] = useState(String(data.breach_recency_bars));

  const swingCheck = checkNumber(swingBars, RULES.swingBars);
  const clusterCheck = checkNumber(clusterPct, RULES.cluster);
  const maxLpsCheck = checkNumber(maxLps, RULES.maxZones);
  const recencyCheck = checkNumber(recencyBars, RULES.recency);

  // Breach recency only applies while "only keep if breached recently" is
  // ticked. While it is not, the field is disabled, never validated, never
  // blocks Save, and the STORED value is sent unchanged.
  const recencyApplies = onlyRecent;
  const invalid =
    swingCheck.error !== null ||
    clusterCheck.error !== null ||
    maxLpsCheck.error !== null ||
    (recencyApplies && recencyCheck.error !== null);

  // Edited = differs from the stored value. An unparsable entry is not the
  // stored value, so it counts as edited (and blocks Save through `invalid`).
  const unchanged =
    swingCheck.value === data.swing_bars_each_side &&
    clusterCheck.value === data.cluster_pct &&
    maxLpsCheck.value === data.max_lps_per_side &&
    priority === data.over_cap_priority &&
    keepSupport === data.keep_last_breached_support &&
    keepResistance === data.keep_last_breached_resistance &&
    onlyRecent === data.only_keep_if_breached_recently &&
    (!recencyApplies || recencyCheck.value === data.breach_recency_bars);

  // Identifies the field values, so a failed save's message stays until they change.
  const signature = JSON.stringify([swingBars, clusterPct, maxLps, priority, keepSupport, keepResistance, onlyRecent, recencyBars]);
  const shown = saver.view(signature);

  function handleSave() {
    if (invalid || swingCheck.value === null || clusterCheck.value === null || maxLpsCheck.value === null) return;
    const recency = recencyApplies ? recencyCheck.value : data.breach_recency_bars;
    if (recency === null) return;
    const body = {
      swing_bars_each_side: swingCheck.value,
      cluster_pct: clusterCheck.value,
      max_lps_per_side: maxLpsCheck.value,
      breach_recency_bars: recency,
      over_cap_priority: priority,
      keep_last_breached_support: keepSupport,
      keep_last_breached_resistance: keepResistance,
      only_keep_if_breached_recently: onlyRecent,
    };
    void saver.run(async () => {
      await apiPut<LiquidityZoneConfigOut>("/config/liquidity-zones", body);
      await mutate("/config/liquidity-zones");
    }, signature);
  }

  return (
    <SettingsSection
      title="Liquidity zones"
      intro={`Support and resistance levels found from swings in price, computed nightly for tickers on ${MONITORED_WATCHLISTS_PHRASE} only. One set of settings is shared by the Daily and Weekly computations. A change applies on the next nightly run, not retroactively.`}
    >
      <SettingsGroup title="Detection">
        <NumberSettingRow
          id="lz-swing-bars"
          label="Swing bars each side"
          hint="How many bars on each side of a pivot it takes to confirm a swing. 2 means a 5-bar window."
          rules={RULES.swingBars}
          value={swingBars}
          onChange={setSwingBars}
        />
        <NumberSettingRow
          id="lz-cluster-pct"
          label="Cluster"
          unit="%"
          step={0.1}
          hint="Zones within this percentage of each other merge into one. 0 turns merging off."
          rules={RULES.cluster}
          value={clusterPct}
          onChange={setClusterPct}
        />
      </SettingsGroup>

      <SettingsGroup title="Display">
        <NumberSettingRow
          id="lz-max-lps"
          label="Max zones per side"
          hint="The most zones shown above and below price. The last-breached zone is extra and does not count."
          rules={RULES.maxZones}
          value={maxLps}
          onChange={setMaxLps}
        />
        <SettingsRow
          label="When over the cap, keep"
          htmlFor="lz-priority"
          hint="Nearest to price keeps the zones closest to today's price; most recent keeps the newest."
        >
          <Select
            size="medium"
            value={priority}
            onChange={(e) => setPriority(e.target.value as LiquidityZoneConfigOut["over_cap_priority"])}
          >
            <option value="nearest_price">Nearest to price</option>
            <option value="most_recent">Most recent</option>
          </Select>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="Last breached liquidity">
        {/* The row's own <label for> is each checkbox's only accessible name. */}
        <SettingsRow
          label="Keep last breached support"
          htmlFor="lz-keep-support"
          hint="Also draw one support level that price has already broken below: the broken one closest to the supports still holding."
        >
          <Checkbox variant="neutral" checked={keepSupport} onChange={(e) => setKeepSupport(e.target.checked)} />
        </SettingsRow>
        <SettingsRow
          label="Keep last breached resistance"
          htmlFor="lz-keep-resistance"
          hint="Also draw one resistance level that price has already broken above: the broken one closest to the resistances still holding."
        >
          <Checkbox variant="neutral" checked={keepResistance} onChange={(e) => setKeepResistance(e.target.checked)} />
        </SettingsRow>
        <SettingsRow
          label="Only keep if breached recently"
          htmlFor="lz-only-recent"
          hint="Show a kept level only when the break happened within the window below."
        >
          <Checkbox variant="neutral" checked={onlyRecent} onChange={(e) => setOnlyRecent(e.target.checked)} />
        </SettingsRow>
        <NumberSettingRow
          id="lz-recency"
          label="Breach recency"
          unit="bars"
          hint="How many bars back from the latest bar a break can be and still be kept. Only used when the option above is ticked."
          rules={RULES.recency}
          value={recencyBars}
          onChange={setRecencyBars}
          disabled={!onlyRecent}
        />
      </SettingsGroup>

      <SettingsFooter
        onSave={handleSave}
        status={shown.status}
        invalid={invalid}
        unchanged={unchanged}
        message={shown.detail}
        updatedAt={data.updated_at}
      />
    </SettingsSection>
  );
}

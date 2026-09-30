"use client";

// Mock Settings sections built with the Settings layout kit, for review in
// /styleguide. Mock data only, no API: they show the real labels (sentence
// case, units as a suffix), draft hints, and the validation and conditional-row
// behaviour the migrated forms will have. Every field is live.
import { useState } from "react";

import {
  SettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSection,
  type SaveStatus,
} from "@/components/settings/SettingsLayout";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NumberField } from "@/components/ui/number-field";
import { Select } from "@/components/ui/Select";
import type { FieldSize } from "@/lib/formControl";
import { checkNumber, type NumberRules } from "@/lib/numberInput";

const MOCK_UPDATED_AT = "2026-09-26T09:14:00";

// A mock save: "saving" briefly, then "saved", then back to idle.
function useMockSave() {
  const [status, setStatus] = useState<SaveStatus>("idle");
  function save() {
    setStatus("saving");
    setTimeout(() => setStatus("saved"), 500);
    setTimeout(() => setStatus("idle"), 3000);
  }
  return { status, save };
}

// One numeric row: the rules are declared once and used for both the field
// and the row's error, exactly as a migrated form would.
function NumberRow({
  id,
  label,
  hint,
  unit,
  size = "short",
  rules,
  step,
  value,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  hint: string;
  unit?: string;
  size?: FieldSize;
  rules: NumberRules;
  step?: number;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const error = disabled ? null : checkNumber(value, rules).error;
  return (
    <SettingsRow label={label} hint={hint} htmlFor={id} error={error} disabled={disabled}>
      <NumberField value={value} onChange={onChange} size={size} unit={unit} step={step} {...rules} />
    </SettingsRow>
  );
}

// Mirrors WeinsteinConfigIn's server bounds (backend/core/schemas.py).
const WEINSTEIN_RULES = {
  maLength: { integer: true, min: 2, max: 200 },
  withinRange: { min: 0, max: 50 },
  slopeLookback: { integer: true, min: 1, max: 52 },
  breakoutVolume: { min: 0.1, max: 20 },
  volumeAvg: { integer: true, min: 2, max: 200 },
  rsSmoothing: { integer: true, min: 2, max: 200 },
} satisfies Record<string, NumberRules>;

export function WeinsteinMock() {
  const [v, setV] = useState({
    maLength: "30",
    withinRange: "5",
    slopeLookback: "5",
    breakoutVolume: "2",
    // One field in an invalid state (below the server's minimum of 2).
    volumeAvg: "1",
    rsSmoothing: "52",
  });
  const [maType, setMaType] = useState("EMA");
  const [benchmark, setBenchmark] = useState("SPY");
  const { status, save } = useMockSave();
  const set = (key: keyof typeof v) => (value: string) => setV((prev) => ({ ...prev, [key]: value }));
  const invalid =
    (Object.keys(WEINSTEIN_RULES) as (keyof typeof WEINSTEIN_RULES)[]).some(
      (key) => checkNumber(v[key], WEINSTEIN_RULES[key]).error !== null,
    ) || benchmark.trim() === "";

  return (
    <SettingsSection
      title="Weinstein stage"
      intro="Sets how the weekly stage is worked out: Base, Advance, Top or Decline. It feeds the stage pill in the ticker header, the Technical tab card and the Screener filter. A change applies the next time a ticker is recomputed, by the nightly trend job or when you open the ticker. It always runs on weekly bars."
    >
      <SettingsGroup title="Stage">
        <NumberRow
          id="sg-ws-ma-length"
          label="MA length"
          unit="weeks"
          hint="How many weeks the moving average looks back. A longer average reacts more slowly."
          rules={WEINSTEIN_RULES.maLength}
          value={v.maLength}
          onChange={set("maLength")}
        />
        <SettingsRow
          label="MA type"
          htmlFor="sg-ws-ma-type"
          hint="EMA gives recent weeks more weight; SMA weighs every week equally."
        >
          <Select size="short" value={maType} onChange={(e) => setMaType(e.target.value)}>
            <option value="EMA">EMA</option>
            <option value="SMA">SMA</option>
          </Select>
        </SettingsRow>
        <NumberRow
          id="sg-ws-within-range"
          label="Within range"
          unit="%"
          step={0.5}
          hint="How far price must be above or below the average, with its slope agreeing, before the stage moves to Advance or Decline."
          rules={WEINSTEIN_RULES.withinRange}
          value={v.withinRange}
          onChange={set("withinRange")}
        />
        <NumberRow
          id="sg-ws-slope-lookback"
          label="Slope lookback"
          unit="weeks"
          hint="How many weeks back the average is compared with to tell whether it is rising or falling."
          rules={WEINSTEIN_RULES.slopeLookback}
          value={v.slopeLookback}
          onChange={set("slopeLookback")}
        />
      </SettingsGroup>

      <SettingsGroup title="Breakout and relative strength">
        <NumberRow
          id="sg-ws-vol-mult"
          label="Breakout volume"
          unit="× average"
          step={0.1}
          hint="A move into Advance only counts as a confirmed breakout when the week's volume is at least this many times its average."
          rules={WEINSTEIN_RULES.breakoutVolume}
          value={v.breakoutVolume}
          onChange={set("breakoutVolume")}
        />
        <NumberRow
          id="sg-ws-vol-avg"
          label="Volume average length"
          unit="weeks"
          hint="How many weeks of volume are averaged to judge whether this week's volume is unusually high."
          rules={WEINSTEIN_RULES.volumeAvg}
          value={v.volumeAvg}
          onChange={set("volumeAvg")}
        />
        <SettingsRow
          label="RS benchmark"
          htmlFor="sg-ws-benchmark"
          hint="The ticker each stock's relative strength is measured against. SPY by default."
          error={benchmark.trim() === "" ? "Enter a ticker symbol." : undefined}
        >
          <Input variant="boxed" size="medium" value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
        </SettingsRow>
        <NumberRow
          id="sg-ws-rs-smoothing"
          label="RS smoothing length"
          unit="weeks"
          hint="How many weeks the stock-to-benchmark price ratio is averaged over before today's ratio is compared with it."
          rules={WEINSTEIN_RULES.rsSmoothing}
          value={v.rsSmoothing}
          onChange={set("rsSmoothing")}
        />
      </SettingsGroup>

      <SettingsFooter onSave={save} status={status} invalid={invalid} updatedAt={MOCK_UPDATED_AT} />
    </SettingsSection>
  );
}

// Mirrors LiquidityZoneConfigIn's server bounds.
const LIQUIDITY_RULES = {
  swing: { integer: true, min: 1, max: 3 },
  cluster: { min: 0, max: 3 },
  maxZones: { integer: true, min: 1, max: 10 },
  recency: { integer: true, min: 1, max: 52 },
} satisfies Record<string, NumberRules>;

export function LiquidityMock() {
  const [swing, setSwing] = useState("2");
  const [cluster, setCluster] = useState("0");
  const [maxZones, setMaxZones] = useState("3");
  const [priority, setPriority] = useState("nearest_price");
  const [keepSupport, setKeepSupport] = useState(true);
  const [keepResistance, setKeepResistance] = useState(true);
  const [onlyRecent, setOnlyRecent] = useState(false);
  const [recency, setRecency] = useState("5");
  const { status, save } = useMockSave();
  const invalid =
    checkNumber(swing, LIQUIDITY_RULES.swing).error !== null ||
    checkNumber(cluster, LIQUIDITY_RULES.cluster).error !== null ||
    checkNumber(maxZones, LIQUIDITY_RULES.maxZones).error !== null ||
    (onlyRecent && checkNumber(recency, LIQUIDITY_RULES.recency).error !== null);

  return (
    <SettingsSection
      title="Liquidity zones"
      intro="Support and resistance levels found from swings in price, computed nightly for watchlists named W1 through W5 only. One set of settings is shared by the Daily and Weekly computations. A change applies on the next nightly run, not retroactively."
    >
      <SettingsGroup title="Detection">
        <NumberRow
          id="sg-lz-swing"
          label="Swing bars each side"
          hint="How many bars on each side of a pivot it takes to confirm a swing. 2 means a 5-bar window."
          rules={LIQUIDITY_RULES.swing}
          value={swing}
          onChange={setSwing}
        />
        <NumberRow
          id="sg-lz-cluster"
          label="Cluster"
          unit="%"
          step={0.1}
          hint="Zones within this percentage of each other merge into one. 0 turns merging off."
          rules={LIQUIDITY_RULES.cluster}
          value={cluster}
          onChange={setCluster}
        />
      </SettingsGroup>

      <SettingsGroup title="Display">
        <NumberRow
          id="sg-lz-max"
          label="Max zones per side"
          hint="The most zones shown above and below price. The last-breached zone is extra and does not count."
          rules={LIQUIDITY_RULES.maxZones}
          value={maxZones}
          onChange={setMaxZones}
        />
        <SettingsRow
          label="When over the cap, keep"
          htmlFor="sg-lz-priority"
          hint="Nearest to price keeps the zones closest to today's price; most recent keeps the newest."
        >
          <Select size="medium" value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="nearest_price">Nearest to price</option>
            <option value="most_recent">Most recent</option>
          </Select>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="Last breached liquidity">
        <SettingsRow
          label="Keep last breached support"
          htmlFor="sg-lz-keep-support"
          hint="Also draw the one support level that price most recently broke below."
        >
          <Checkbox variant="neutral" checked={keepSupport} onChange={(e) => setKeepSupport(e.target.checked)} />
        </SettingsRow>
        <SettingsRow
          label="Keep last breached resistance"
          htmlFor="sg-lz-keep-resistance"
          hint="Also draw the one resistance level that price most recently broke above."
        >
          <Checkbox variant="neutral" checked={keepResistance} onChange={(e) => setKeepResistance(e.target.checked)} />
        </SettingsRow>
        <SettingsRow
          label="Only keep if breached recently"
          htmlFor="sg-lz-only-recent"
          hint="Show a kept level only when the break happened within the window below."
        >
          <Checkbox variant="neutral" checked={onlyRecent} onChange={(e) => setOnlyRecent(e.target.checked)} />
        </SettingsRow>
        <NumberRow
          id="sg-lz-recency"
          label="Breach recency"
          unit="bars"
          hint="How many bars back from the latest bar a break can be and still be kept. Only used when the option above is ticked."
          rules={LIQUIDITY_RULES.recency}
          value={recency}
          onChange={setRecency}
          disabled={!onlyRecent}
        />
      </SettingsGroup>

      <SettingsFooter onSave={save} status={status} invalid={invalid} updatedAt={MOCK_UPDATED_AT} />
    </SettingsSection>
  );
}

// No server bounds exist for the discount-rate fields, so none are set here.
export function DiscountRateMock() {
  const [rf, setRf] = useState("3.608");
  const [mrp, setMrp] = useState("2.728");
  const { status, save } = useMockSave();
  const invalid = checkNumber(rf).error !== null || checkNumber(mrp).error !== null;

  return (
    <SettingsSection
      title="Discount rate by country"
      intro="The rates used to work out each ticker's discount rate for the Valuation tab: risk-free rate plus beta times market risk premium. Both are 5-year trailing averages from market-risk-premia.com that you update by hand; nothing refreshes them, so they go stale until you do. Beta comes live from FMP for each ticker. Only the United States has its own rate; a ticker from any other country, such as an ADR, uses the US rate."
    >
      <SettingsGroup title="United States (US)">
        <NumberRow
          id="sg-dr-rf"
          label="Risk-free rate"
          unit="%"
          step={0.001}
          hint="A 5-year trailing average of the risk-free rate, and the starting point of the discount rate."
          rules={{}}
          value={rf}
          onChange={setRf}
        />
        <NumberRow
          id="sg-dr-mrp"
          label="Market risk premium"
          unit="%"
          step={0.001}
          hint="The extra return investors expect from stocks over the risk-free rate, as a 5-year trailing average."
          rules={{}}
          value={mrp}
          onChange={setMrp}
        />
        <SettingsFooter onSave={save} status={status} invalid={invalid} updatedAt={MOCK_UPDATED_AT} className="mt-4 pb-1" />
      </SettingsGroup>
    </SettingsSection>
  );
}

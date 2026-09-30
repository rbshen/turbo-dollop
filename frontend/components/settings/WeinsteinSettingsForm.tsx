"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { WeinsteinConfigOut } from "@/lib/api/types";
import { useWeinsteinConfig } from "@/lib/hooks/useWeinsteinConfig";
import { Input } from "@/components/ui/input";
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

// The bounds are the server's own (WeinsteinConfigIn in backend/core/
// schemas.py), with ONE deliberate exception: breakout volume's floor is 0.1
// (the old client hint) where the server accepts anything above 0. The error
// text says so. A value outside a bound, or a non-integer in an integer field,
// shows an inline error and blocks Save; nothing is truncated or corrected.
const RULES = {
  maLength: { integer: true, min: 2, max: 200 },
  withinRange: { min: 0, max: 50 },
  slopeLookback: { integer: true, min: 1, max: 52 },
  breakoutVolume: { min: 0.1, max: 20 },
  volumeAvg: { integer: true, min: 2, max: 200 },
  rsSmoothing: { integer: true, min: 2, max: 200 },
} satisfies Record<string, NumberRules>;

const BENCHMARK_MAX_LENGTH = 20;

// 1 to 20 characters after trimming; case is not enforced.
function benchmarkError(text: string): string | null {
  const length = text.trim().length;
  if (length === 0) return "Enter a ticker symbol.";
  if (length > BENCHMARK_MAX_LENGTH) return `Enter ${BENCHMARK_MAX_LENGTH} characters or fewer.`;
  return null;
}

export function WeinsteinSettingsForm() {
  const { data, error, isLoading } = useWeinsteinConfig();
  // Held here, above the keyed form below, so "Saved ✓" survives the remount.
  const saver = useSettingsSave();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load Weinstein settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save remounts this with fresh initial text.
  return <WeinsteinForm key={data.updated_at} data={data} saver={saver} />;
}

// A single config object. The two groups below are sub-headings within one
// save action, not independently-saved panels.
function WeinsteinForm({ data, saver }: { data: WeinsteinConfigOut; saver: SettingsSaver }) {
  const [maLength, setMaLength] = useState(String(data.ma_length));
  const [maType, setMaType] = useState<WeinsteinConfigOut["ma_type"]>(data.ma_type);
  const [rangePct, setRangePct] = useState(String(data.within_range_pct));
  const [slopeLookback, setSlopeLookback] = useState(String(data.slope_lookback));
  const [volMult, setVolMult] = useState(String(data.breakout_volume_mult));
  const [volAvgLength, setVolAvgLength] = useState(String(data.volume_avg_length));
  const [benchmark, setBenchmark] = useState(data.rs_benchmark);
  const [rsSmoothing, setRsSmoothing] = useState(String(data.rs_smoothing_length));

  const maLengthCheck = checkNumber(maLength, RULES.maLength);
  const rangeCheck = checkNumber(rangePct, RULES.withinRange);
  const slopeCheck = checkNumber(slopeLookback, RULES.slopeLookback);
  const volMultCheck = checkNumber(volMult, RULES.breakoutVolume);
  const volAvgCheck = checkNumber(volAvgLength, RULES.volumeAvg);
  const rsSmoothingCheck = checkNumber(rsSmoothing, RULES.rsSmoothing);
  const benchmarkMessage = benchmarkError(benchmark);

  const invalid =
    [maLengthCheck, rangeCheck, slopeCheck, volMultCheck, volAvgCheck, rsSmoothingCheck].some(
      (c) => c.error !== null,
    ) || benchmarkMessage !== null;

  // Edited = differs from the stored value. An unparsable entry is not the
  // stored value, so it counts as edited (and blocks Save through `invalid`).
  const unchanged =
    maLengthCheck.value === data.ma_length &&
    maType === data.ma_type &&
    rangeCheck.value === data.within_range_pct &&
    slopeCheck.value === data.slope_lookback &&
    volMultCheck.value === data.breakout_volume_mult &&
    volAvgCheck.value === data.volume_avg_length &&
    benchmark.trim() === data.rs_benchmark &&
    rsSmoothingCheck.value === data.rs_smoothing_length;

  // Identifies the field values, so a failed save's message stays until they change.
  const signature = JSON.stringify([maLength, maType, rangePct, slopeLookback, volMult, volAvgLength, benchmark, rsSmoothing]);
  const shown = saver.view(signature);

  function handleSave() {
    const numbers = [maLengthCheck, rangeCheck, slopeCheck, volMultCheck, volAvgCheck, rsSmoothingCheck].map(
      (c) => c.value,
    );
    if (invalid || numbers.some((n) => n === null)) return;
    const [ma_length, within_range_pct, slope_lookback, breakout_volume_mult, volume_avg_length, rs_smoothing_length] =
      numbers as number[];
    const body = {
      ma_length,
      ma_type: maType,
      within_range_pct,
      slope_lookback,
      breakout_volume_mult,
      volume_avg_length,
      rs_benchmark: benchmark.trim(),
      rs_smoothing_length,
    };
    void saver.run(async () => {
      await apiPut<WeinsteinConfigOut>("/config/weinstein", body);
      await mutate("/config/weinstein");
    }, signature);
  }

  return (
    <SettingsSection
      title="Weinstein stage"
      intro="Sets how the weekly stage is worked out: Base, Advance, Top or Decline. It feeds the stage pill in the ticker header, the Technical tab card and the Screener filter. A change applies the next time a ticker is recomputed, by the nightly trend job or when you open the ticker. It always runs on weekly bars."
    >
      <SettingsGroup title="Stage">
        <NumberSettingRow
          id="ws-ma-length"
          label="MA length"
          unit="weeks"
          hint="How many weeks the moving average looks back. A longer average reacts more slowly."
          rules={RULES.maLength}
          value={maLength}
          onChange={setMaLength}
        />
        <SettingsRow
          label="MA type"
          htmlFor="ws-ma-type"
          hint="EMA gives recent weeks more weight; SMA weighs every week equally."
        >
          <Select size="short" value={maType} onChange={(e) => setMaType(e.target.value as WeinsteinConfigOut["ma_type"])}>
            <option value="EMA">EMA</option>
            <option value="SMA">SMA</option>
          </Select>
        </SettingsRow>
        <NumberSettingRow
          id="ws-range-pct"
          label="Within range"
          unit="%"
          step={0.5}
          hint="How far price must be above or below the average, with its slope agreeing, before the stage moves to Advance or Decline."
          rules={RULES.withinRange}
          value={rangePct}
          onChange={setRangePct}
        />
        <NumberSettingRow
          id="ws-slope-lookback"
          label="Slope lookback"
          unit="weeks"
          hint="How many weeks back the average is compared with to tell whether it is rising or falling."
          rules={RULES.slopeLookback}
          value={slopeLookback}
          onChange={setSlopeLookback}
        />
      </SettingsGroup>

      <SettingsGroup title="Breakout and relative strength">
        <NumberSettingRow
          id="ws-vol-mult"
          label="Breakout volume"
          unit="× average"
          step={0.1}
          hint="A move into Advance only counts as a confirmed breakout when the week's volume is at least this many times its average."
          rules={RULES.breakoutVolume}
          value={volMult}
          onChange={setVolMult}
        />
        <NumberSettingRow
          id="ws-vol-avg"
          label="Volume average length"
          unit="weeks"
          hint="How many weeks of volume are averaged to judge whether this week's volume is unusually high."
          rules={RULES.volumeAvg}
          value={volAvgLength}
          onChange={setVolAvgLength}
        />
        <SettingsRow
          label="RS benchmark"
          htmlFor="ws-benchmark"
          hint="The ticker each stock's relative strength is measured against. SPY by default."
          error={benchmarkMessage}
        >
          <Input size="medium" className="font-mono" value={benchmark} onChange={(e) => setBenchmark(e.target.value)} />
        </SettingsRow>
        <NumberSettingRow
          id="ws-rs-smoothing"
          label="RS smoothing length"
          unit="weeks"
          hint="How many weeks the stock-to-benchmark price ratio is averaged over before today's ratio is compared with it."
          rules={RULES.rsSmoothing}
          value={rsSmoothing}
          onChange={setRsSmoothing}
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

"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { WeinsteinConfigOut } from "@/lib/api/types";
import { useWeinsteinConfig } from "@/lib/hooks/useWeinsteinConfig";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Section } from "@/components/ui/section";
import { Select } from "@/components/ui/Select";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function WeinsteinSettingsForm() {
  const { data, error, isLoading } = useWeinsteinConfig();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load Weinstein settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save remounts this with fresh initial text --
  // same convention as LiquidityZoneSettingsForm.
  return <WeinsteinForm key={data.updated_at} data={data} />;
}

// A single config object -- content sits directly in the Section, no Card
// wrapper (same reasoning as MoatSettingsForm). The two field groups below
// (Stage / Breakout & relative strength) are plain subheadings, not nested
// Sections -- they're an organizational split within one save action, not
// independently-saved panels.
function WeinsteinForm({ data }: { data: WeinsteinConfigOut }) {
  const [maLength, setMaLength] = useState(String(data.ma_length));
  const [maType, setMaType] = useState<WeinsteinConfigOut["ma_type"]>(data.ma_type);
  const [rangePct, setRangePct] = useState(String(data.within_range_pct));
  const [slopeLookback, setSlopeLookback] = useState(String(data.slope_lookback));
  const [volMult, setVolMult] = useState(String(data.breakout_volume_mult));
  const [volAvgLength, setVolAvgLength] = useState(String(data.volume_avg_length));
  const [benchmark, setBenchmark] = useState(data.rs_benchmark);
  const [rsSmoothing, setRsSmoothing] = useState(String(data.rs_smoothing_length));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const numbers = {
      ma_length: parseInt(maLength, 10),
      within_range_pct: parseFloat(rangePct),
      slope_lookback: parseInt(slopeLookback, 10),
      breakout_volume_mult: parseFloat(volMult),
      volume_avg_length: parseInt(volAvgLength, 10),
      rs_smoothing_length: parseInt(rsSmoothing, 10),
    };
    if (Object.values(numbers).some((v) => Number.isNaN(v)) || benchmark.trim() === "") {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
      return;
    }
    setStatus("saving");
    try {
      await apiPut<WeinsteinConfigOut>("/config/weinstein", {
        ...numbers,
        ma_type: maType,
        rs_benchmark: benchmark.trim(),
      });
      await mutate("/config/weinstein");
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <Section title="Weinstein Stage">
      <p className="text-xs text-text-tertiary">
        Parameters for the weekly Stage 1-4 engine (Base / Advance / Top / Decline) behind the ticker-header pill, the
        Technical tab card and the Screener filter. Changes apply the next time a ticker is recomputed (the nightly
        trend job, or an on-demand ticker view) — no restart needed. The engine always runs on weekly bars.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-2">
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-text-secondary">Stage</h3>
          <Field label="MA length (weeks)" htmlFor="ws-ma-length">
            <Input
              id="ws-ma-length"
              variant="boxed"
              type="number"
              step="1"
              min="2"
              className="mt-1 w-full font-mono"
              value={maLength}
              onChange={(e) => setMaLength(e.target.value)}
            />
          </Field>
          <Field label="MA type" htmlFor="ws-ma-type">
            <Select
              id="ws-ma-type"
              className="mt-1"
              value={maType}
              onChange={(e) => setMaType(e.target.value as WeinsteinConfigOut["ma_type"])}
            >
              <option value="EMA">EMA</option>
              <option value="SMA">SMA</option>
            </Select>
          </Field>
          <Field label="Within range (%)" htmlFor="ws-range-pct">
            <Input
              id="ws-range-pct"
              variant="boxed"
              type="number"
              step="0.5"
              min="0"
              className="mt-1 w-full font-mono"
              value={rangePct}
              onChange={(e) => setRangePct(e.target.value)}
            />
          </Field>
          <Field label="Slope lookback (bars)" htmlFor="ws-slope-lookback">
            <Input
              id="ws-slope-lookback"
              variant="boxed"
              type="number"
              step="1"
              min="1"
              className="mt-1 w-full font-mono"
              value={slopeLookback}
              onChange={(e) => setSlopeLookback(e.target.value)}
            />
          </Field>
        </div>

        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-text-secondary">Breakout &amp; relative strength</h3>
          <Field label="Breakout volume (x average)" htmlFor="ws-vol-mult">
            <Input
              id="ws-vol-mult"
              variant="boxed"
              type="number"
              step="0.1"
              min="0.1"
              className="mt-1 w-full font-mono"
              value={volMult}
              onChange={(e) => setVolMult(e.target.value)}
            />
          </Field>
          <Field label="Volume average length (weeks)" htmlFor="ws-vol-avg">
            <Input
              id="ws-vol-avg"
              variant="boxed"
              type="number"
              step="1"
              min="2"
              className="mt-1 w-full font-mono"
              value={volAvgLength}
              onChange={(e) => setVolAvgLength(e.target.value)}
            />
          </Field>
          <Field label="RS benchmark" htmlFor="ws-benchmark">
            <Input
              id="ws-benchmark"
              variant="boxed"
              type="text"
              className="mt-1 w-full font-mono"
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
            />
          </Field>
          <Field label="RS smoothing length (weeks)" htmlFor="ws-rs-smoothing">
            <Input
              id="ws-rs-smoothing"
              variant="boxed"
              type="number"
              step="1"
              min="2"
              className="mt-1 w-full font-mono"
              value={rsSmoothing}
              onChange={(e) => setRsSmoothing(e.target.value)}
            />
          </Field>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3">
        <Button variant="primary" onClick={handleSave} disabled={status === "saving"}>
          {STATUS_LABELS[status]}
        </Button>
        <p className="text-xs text-text-tertiary">Last updated {new Date(data.updated_at).toLocaleString()}</p>
      </div>
    </Section>
  );
}

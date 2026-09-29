"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { LiquidityZoneConfigOut } from "@/lib/api/types";
import { useLiquidityZoneConfig } from "@/lib/hooks/useLiquidityZoneConfig";
import { InfoTooltip } from "@/components/ui/InfoTooltip";
import { NumberStepper } from "@/components/ui/NumberStepper";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/input";
import { Section } from "@/components/ui/section";
import { cn } from "@/lib/utils";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function LiquidityZoneSettingsForm() {
  const { data, error, isLoading } = useLiquidityZoneConfig();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load Liquidity Zone settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save remounts this with fresh initial state --
  // same convention as DiscountRateSettingsForm.
  return <LiquidityZoneForm key={data.updated_at} data={data} />;
}

// A single config object -- content sits directly in the Section, no Card
// wrapper (same reasoning as MoatSettingsForm/WeinsteinSettingsForm). The
// three field groups below are plain subheadings, not nested Sections, for
// the same reason WeinsteinSettingsForm's two groups are.
function LiquidityZoneForm({ data }: { data: LiquidityZoneConfigOut }) {
  const [swingBars, setSwingBars] = useState(data.swing_bars_each_side);
  const [clusterPct, setClusterPct] = useState(data.cluster_pct);
  const [maxLps, setMaxLps] = useState(data.max_lps_per_side);
  const [priority, setPriority] = useState<LiquidityZoneConfigOut["over_cap_priority"]>(data.over_cap_priority);
  const [keepSupport, setKeepSupport] = useState(data.keep_last_breached_support);
  const [keepResistance, setKeepResistance] = useState(data.keep_last_breached_resistance);
  const [onlyRecent, setOnlyRecent] = useState(data.only_keep_if_breached_recently);
  const [recencyBars, setRecencyBars] = useState(data.breach_recency_bars);
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    setStatus("saving");
    try {
      await apiPut<LiquidityZoneConfigOut>("/config/liquidity-zones", {
        swing_bars_each_side: swingBars,
        cluster_pct: clusterPct,
        max_lps_per_side: maxLps,
        breach_recency_bars: recencyBars,
        over_cap_priority: priority,
        keep_last_breached_support: keepSupport,
        keep_last_breached_resistance: keepResistance,
        only_keep_if_breached_recently: onlyRecent,
      });
      await mutate("/config/liquidity-zones");
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  const fieldLabel = (text: string, tooltip: { label: string; text: string }) => (
    <span className="inline-flex items-center gap-1.5">
      {text}
      <InfoTooltip label={tooltip.label} text={tooltip.text} />
    </span>
  );

  return (
    <Section title="Liquidity Zones">
      <p className="text-xs text-text-tertiary">
        Swing-based support/resistance detection, computed nightly for watchlists named W1 through W5 only. One set of
        settings is shared by the Daily and Weekly computations. Changes here apply on the next nightly run, not
        retroactively.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-3">
        <div className="space-y-4">
          <h3 className="text-xs font-semibold text-text-secondary">Detection</h3>
          <Field
            label={fieldLabel("Swing bars (each side)", {
              label: "About swing bars",
              text: "Bars on EACH side of the pivot. 2 = a 5-bar window (2 left + pivot + 2 right). A swing needs this many bars to its right before it is confirmed.",
            })}
            htmlFor="lz-swing-bars"
          >
            <NumberStepper id="lz-swing-bars" value={swingBars} onChange={setSwingBars} min={1} max={3} step={1} />
          </Field>
          <Field
            label={fieldLabel("Cluster % (0 disables)", {
              label: "About cluster %",
              text: "Merge consecutive valid liquidity zones within this % of each other into one zone. Support zones are represented by their LOWEST price; resistance zones by their HIGHEST price. 0 = clustering off.",
            })}
            htmlFor="lz-cluster-pct"
          >
            <NumberStepper id="lz-cluster-pct" value={clusterPct} onChange={setClusterPct} min={0} max={3} step={0.1} />
          </Field>
        </div>

        <div className="space-y-4">
          <h3 className="text-xs font-semibold text-text-secondary">Display</h3>
          <Field
            label={fieldLabel("Max zones per side", {
              label: "About max zones per side",
              text: "Cap on how many valid zones to show per side. The last-breached zone (if enabled below) is shown separately and does not count toward this cap.",
            })}
            htmlFor="lz-max-lps"
          >
            <NumberStepper id="lz-max-lps" value={maxLps} onChange={setMaxLps} min={1} max={10} step={1} />
          </Field>
          <Field
            label={fieldLabel("When over the cap, keep", {
              label: "About over-cap priority",
              text: "When there are more valid zones than the cap allows, choose which to keep: 'Nearest price' keeps the zones closest to the current price; 'Most recent' keeps the newest ones instead, regardless of price distance.",
            })}
            htmlFor="lz-priority"
          >
            <Select
              id="lz-priority"
              className="mt-1"
              value={priority}
              onChange={(e) => setPriority(e.target.value as LiquidityZoneConfigOut["over_cap_priority"])}
            >
              <option value="nearest_price">Nearest to price</option>
              <option value="most_recent">Most recent</option>
            </Select>
          </Field>
        </div>

        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-text-secondary">Last breached Liquidity</h3>
          <Checkbox
            id="lz-keep-support"
            checked={keepSupport}
            onChange={(e) => setKeepSupport(e.target.checked)}
            label="Keep last breached support"
          />
          <Checkbox
            id="lz-keep-resistance"
            checked={keepResistance}
            onChange={(e) => setKeepResistance(e.target.checked)}
            label="Keep last breached resistance"
          />
          <Checkbox
            id="lz-only-recent"
            checked={onlyRecent}
            onChange={(e) => setOnlyRecent(e.target.checked)}
            label="Only keep if breached recently"
          />
          <div className={cn("ml-3 border-l border-border-subtle pl-3 transition-opacity", !onlyRecent && "opacity-40")}>
            <Field
              label={fieldLabel("Breach recency (bars)", {
                label: "About breach recency",
                text: "A breached zone is only eligible to be kept and shown if its breach happened within this many bars of the most recent bar.",
              })}
              htmlFor="lz-recency"
            >
              <NumberStepper
                id="lz-recency"
                value={recencyBars}
                onChange={setRecencyBars}
                min={1}
                max={52}
                step={1}
                disabled={!onlyRecent}
              />
            </Field>
          </div>
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

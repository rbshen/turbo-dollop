"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { ReitDividendYieldConfigOut } from "@/lib/api/types";
import { useReitDividendYieldConfig } from "@/lib/hooks/useReitDividendYieldConfig";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Section } from "@/components/ui/section";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

export function ReitDividendYieldSettingsForm() {
  const { data, error, isLoading } = useReitDividendYieldConfig();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load REIT dividend yield settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (which changes updated_at) remounts this
  // with fresh initial text -- same pattern as DiscountRateSettingsForm/
  // MoatSettingsForm.
  return <ReitDividendYieldForm key={data.updated_at} data={data} />;
}

// A single config object, one field -- content sits directly in the
// Section, no Card wrapper (same reasoning as MoatSettingsForm).
function ReitDividendYieldForm({ data }: { data: ReitDividendYieldConfigOut }) {
  const [thresholdText, setThresholdText] = useState(String(data.threshold_pct));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const thresholdPct = parseFloat(thresholdText);
    if (Number.isNaN(thresholdPct)) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<ReitDividendYieldConfigOut>("/config/reit-dividend-yield", { threshold_pct: thresholdPct });
      await mutate("/config/reit-dividend-yield");
      // This threshold feeds Step3Out.dividend_yield_meets_reit_threshold
      // for every REIT ticker -- invalidate every cached Step 3 fetch (and
      // the ticker header, which also reads Step 3's result) so the next
      // view reflects the new threshold without a manual page reload.
      await mutate((key) => typeof key === "string" && (key.includes("/step3") || key.includes("/summary")));
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <Section title="REIT Dividend Yield Threshold">
      <p className="text-xs text-text-tertiary">
        Informational bargain-reference check shown on REIT/Property Developer tickers&apos; Valuation tab
        (valuation.md §3.3) — flags whether trailing dividend yield is at or above this threshold. Never affects
        the Price-to-Book calculation or verdict itself.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Threshold (%)" htmlFor="reit-dividend-yield-threshold">
          <Input
            id="reit-dividend-yield-threshold"
            variant="boxed"
            type="number"
            step="0.1"
            min="0"
            className="mt-1 w-full font-mono"
            value={thresholdText}
            onChange={(e) => setThresholdText(e.target.value)}
          />
        </Field>
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

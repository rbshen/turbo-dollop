"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { MoatScoreConfigOut } from "@/lib/api/types";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";
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

export function MoatSettingsForm() {
  const { data, error, isLoading } = useMoatConfig();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load Economic Moat settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (which changes updated_at) remounts this
  // with fresh initial text -- same pattern as DiscountRateSettingsForm.
  return <MoatScoreForm key={data.updated_at} data={data} />;
}

// A single config object, no per-region/per-item repetition -- content sits
// directly in the Section, not wrapped in its own Card, matching
// ScheduledJobsSection/FmpDataGroupsSection's precedent for a panel that is
// the sole content of its nav tab.
function MoatScoreForm({ data }: { data: MoatScoreConfigOut }) {
  const [wideText, setWideText] = useState(String(data.wide_moat_score));
  const [narrowText, setNarrowText] = useState(String(data.narrow_moat_score));
  const [noMoatText, setNoMoatText] = useState(String(data.no_moat_score));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const wideMoatScore = parseFloat(wideText);
    const narrowMoatScore = parseFloat(narrowText);
    const noMoatScore = parseFloat(noMoatText);
    if (Number.isNaN(wideMoatScore) || Number.isNaN(narrowMoatScore) || Number.isNaN(noMoatScore)) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<MoatScoreConfigOut>("/config/moat", {
        wide_moat_score: wideMoatScore,
        narrow_moat_score: narrowMoatScore,
        no_moat_score: noMoatScore,
      });
      // Every mounted OverallAssessmentCard reads this same global SWR key
      // -- one revalidation reflows every open ticker's blended score
      // without a manual page reload.
      await mutate("/config/moat");
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <Section title="Economic Moat Point Values">
      <p className="text-xs text-text-tertiary">
        Point values (0-100 scale) each Economic Moat state contributes to Overall Assessment once a ticker has a
        moat set. Applied as: <span className="font-mono text-text-secondary">0.69 × Financials/Growth Rate/Profitability/Debt blend + 0.31 × moat score</span>.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label="Wide Moat" htmlFor="wide-moat-score">
          <Input
            id="wide-moat-score"
            variant="boxed"
            type="number"
            step="0.1"
            min="0"
            max="100"
            className="mt-1 w-full font-mono"
            value={wideText}
            onChange={(e) => setWideText(e.target.value)}
          />
        </Field>
        <Field label="Narrow Moat" htmlFor="narrow-moat-score">
          <Input
            id="narrow-moat-score"
            variant="boxed"
            type="number"
            step="0.1"
            min="0"
            max="100"
            className="mt-1 w-full font-mono"
            value={narrowText}
            onChange={(e) => setNarrowText(e.target.value)}
          />
        </Field>
        <Field label="No Moat" htmlFor="no-moat-score">
          <Input
            id="no-moat-score"
            variant="boxed"
            type="number"
            step="0.1"
            min="0"
            max="100"
            className="mt-1 w-full font-mono"
            value={noMoatText}
            onChange={(e) => setNoMoatText(e.target.value)}
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

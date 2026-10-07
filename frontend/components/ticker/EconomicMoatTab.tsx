"use client";

import Link from "next/link";
import { useState } from "react";
import { mutate } from "swr";

import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { apiPut } from "@/lib/api/client";
import type { TickerMoatOut } from "@/lib/api/types";
import { useTickerMoat } from "@/lib/hooks/useTickerMoat";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";
import {
  DEFAULT_NARROW_MOAT_MULTIPLIER,
  MOAT_LABELS,
  NO_MOAT_MULTIPLIER,
  WIDE_MOAT_MULTIPLIER,
  type MoatValue,
} from "@/lib/overallScore";
import { pillLabel } from "@/lib/tierColor";

interface Props {
  ticker: string;
}

const MOAT_OPTIONS: MoatValue[] = ["no_moat", "narrow_moat", "wide_moat"];

const MOAT_DESCRIPTIONS: Record<MoatValue, string> = {
  no_moat: "No durable competitive advantage protecting this business from competitors.",
  narrow_moat: "Some durable advantage, but not strong or broad enough to fend off competition indefinitely.",
  wide_moat: "A strong, durable competitive advantage expected to persist for a decade or more.",
};

export function EconomicMoatTab({ ticker }: Props) {
  const { data, error, isLoading } = useTickerMoat(ticker);

  if (error) {
    return <p className="py-6 text-sm text-negative">Couldn&apos;t load Economic Moat — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="py-6 text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  return <MoatControls key={data.updated_at ?? "unset"} ticker={ticker} data={data} />;
}

function MoatControls({ ticker, data }: { ticker: string; data: TickerMoatOut }) {
  const [pending, setPending] = useState<MoatValue | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function handleConfirm() {
    if (!pending) return;
    setSaving(true);
    setSaveError(null);
    try {
      await apiPut<TickerMoatOut>(`/tickers/${ticker}/moat`, { moat: pending });
      // Every hook on this page keys off "/tickers/{ticker}/..." -- refreshes
      // this tab, the header pill, and Overall Assessment together. The
      // Screener's own row was already updated server-side (see
      // main.py::update_ticker_moat), so revalidate its list too, in case
      // the user navigates there next.
      await mutate((key) => typeof key === "string" && key.startsWith(`/tickers/${ticker}`));
      await mutate("/screener");
      setPending(null);
    } catch {
      setSaveError("Failed to save — please try again.");
    } finally {
      setSaving(false);
    }
  }

  // Segmented control shows the pending selection immediately (a live
  // preview), but nothing actually saves until Confirm -- this app changes
  // Overall Assessment's scoring on save, unlike the design handoff's own
  // prototype which has no such consequence to guard against.
  const displayed = pending ?? data.moat;
  const { data: moatConfig } = useMoatConfig();
  const narrow = moatConfig?.narrow_moat_multiplier ?? DEFAULT_NARROW_MOAT_MULTIPLIER;
  const multiplierSentence = `Wide moat × ${WIDE_MOAT_MULTIPLIER.toFixed(1)}, Narrow moat × ${narrow.toFixed(2)}, No moat × ${NO_MOAT_MULTIPLIER.toFixed(2)}.`;

  return (
    <div className="space-y-6 py-6">
      <div>
        <h2 className="font-heading text-sm font-semibold text-text-primary">Economic moat</h2>
        <p className="mt-1 text-sm text-text-secondary">
          A manually-set classification, not computed from data. It is not a part of the score: it multiplies the Steps score
          (the weighted blend of Financials / Growth Rate / Profitability / Debt) to give the Overall score. {multiplierSentence}{" "}
          A ticker with no moat rated is scored as No moat. The weights are adjustable in{" "}
          <Link href="/settings?section=score-weighting" className="underline underline-offset-2 hover:text-text-primary">
            Score weighting
          </Link>{" "}
          and the Narrow multiplier in{" "}
          <Link href="/settings?section=economic-moat" className="underline underline-offset-2 hover:text-text-primary">
            Economic moat
          </Link>{" "}
          — see the Overall Assessment card for how this ticker is currently scored.
        </p>
      </div>

      <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
        <div className="space-y-3">
          <p className="text-xs text-text-tertiary">Current rating</p>
          <SegmentedControl
            aria-label="Economic moat rating"
            className="flex flex-wrap"
            value={displayed ?? "no_moat"}
            onValueChange={(next) => {
              if (next !== data.moat) setPending(next as MoatValue);
            }}
            options={MOAT_OPTIONS.map((option) => ({ value: option, label: pillLabel(MOAT_LABELS[option]) }))}
          />
          <p className="text-sm text-text-secondary">
            {displayed ? MOAT_DESCRIPTIONS[displayed] : "Not set — scored as No moat until you pick a rating above."}
          </p>
        </div>

        {pending && (
          <div className="space-y-3 rounded-md border border-warn/40 bg-warn/10 p-4">
            <p className="text-sm text-warn">
              Set economic moat to <span className="font-semibold">{pillLabel(MOAT_LABELS[pending])}</span>? This changes how
              Overall Assessment is scored for {ticker}.
            </p>
            <div className="flex items-center gap-3">
              {/* The one primary of the panel, in the warn fill: confirming changes how Overall Assessment is scored. */}
              <Button variant="primary" className="bg-warn hover:bg-warn/80" onClick={handleConfirm} disabled={saving}>
                {saving ? "Saving…" : "Confirm"}
              </Button>
              <Button variant="outline" onClick={() => setPending(null)} disabled={saving}>
                Cancel
              </Button>
            </div>
            {saveError && <p className="text-sm text-negative">{saveError}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

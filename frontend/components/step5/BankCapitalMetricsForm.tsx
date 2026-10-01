"use client";

import { useState } from "react";
import { mutate } from "swr";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { NumberField } from "@/components/ui/number-field";
import { apiPut, errorDetail } from "@/lib/api/client";
import type { Step5Out, TickerBankCapitalMetricsIn, TickerBankCapitalMetricsOut } from "@/lib/api/types";
import { useTickerBankCapitalMetrics } from "@/lib/hooks/useTickerBankCapitalMetrics";
import { fmtPct } from "@/lib/format";
import { checkNumber } from "@/lib/numberInput";

interface Props {
  ticker: string;
  step5: Step5Out;
}

export function BankCapitalMetricsForm({ ticker, step5 }: Props) {
  const { data, error, isLoading } = useTickerBankCapitalMetrics(ticker);

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load CET1/NPL inputs — {error.message}</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }
  return <BankCapitalMetricsControls key={data.updated_at ?? "unset"} ticker={ticker} data={data} step5={step5} />;
}

interface PendingState {
  cet1: string;
  cet1AsOf: string;
  npl: string;
  nplAsOf: string;
}

function BankCapitalMetricsControls({ ticker, data, step5 }: { ticker: string; data: TickerBankCapitalMetricsOut; step5: Step5Out }) {
  const [pending, setPending] = useState<PendingState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const initial: PendingState = {
    cet1: data.cet1_ratio_pct != null ? String(data.cet1_ratio_pct) : "",
    cet1AsOf: data.cet1_as_of ?? "",
    npl: data.npl_ratio_pct != null ? String(data.npl_ratio_pct) : "",
    nplAsOf: data.npl_as_of ?? "",
  };
  const displayed = pending ?? initial;
  const dirty =
    pending !== null &&
    (pending.cet1 !== initial.cet1 ||
      pending.cet1AsOf !== initial.cet1AsOf ||
      pending.npl !== initial.npl ||
      pending.nplAsOf !== initial.nplAsOf);

  // Both ratios are optional floats on the backend (no bounds), so a box is
  // either empty, a number, or invalid text -- never corrected or clamped.
  const cet1Check = checkNumber(displayed.cet1, { optional: true });
  const nplCheck = checkNumber(displayed.npl, { optional: true });
  const invalid = cet1Check.error !== null || nplCheck.error !== null;

  function update(field: keyof PendingState, value: string) {
    setSaveError(null);
    setPending({ ...displayed, [field]: value });
  }

  function handleCancel() {
    setSaveError(null);
    setPending(null);
  }

  async function handleConfirm() {
    if (!pending || invalid) return;
    setSaving(true);
    setSaveError(null);
    try {
      const cet1 = cet1Check.value;
      const npl = nplCheck.value;
      const body: TickerBankCapitalMetricsIn = {
        cet1_ratio_pct: cet1,
        cet1_as_of: pending.cet1AsOf.trim() === "" ? null : pending.cet1AsOf,
        npl_ratio_pct: npl,
        npl_as_of: pending.nplAsOf.trim() === "" ? null : pending.nplAsOf,
      };
      await apiPut<TickerBankCapitalMetricsOut>(`/tickers/${ticker}/bank-capital-metrics`, body);
      // Same mutate pattern as EconomicMoatTab -- refreshes this form, the
      // Step 5 card, and Overall Assessment together; also revalidate the
      // Screener since its TickerScore row was updated server-side too.
      await mutate((key) => typeof key === "string" && key.startsWith(`/tickers/${ticker}`));
      await mutate("/screener");
      setPending(null);
    } catch (e) {
      const detail = errorDetail(e);
      setSaveError(detail ? `Failed to save — ${detail}` : "Failed to save — please try again.");
    } finally {
      setSaving(false);
    }
  }

  // Only shown while npl_source is "auto" -- once a manual override is
  // active, Step5Out only carries the resolved (overridden) value, not the
  // live auto-computed one, so the helper text degrades to a generic note
  // rather than showing a stale/unavailable auto number.
  const autoNpl = step5.npl_source === "auto" ? step5.ratios.npl_ratio?.value ?? null : null;

  return (
    <Card className="space-y-4">
      <div>
        <h3 className="text-sm font-medium text-text-primary">CET1 &amp; NPL ratios</h3>
        <p className="mt-1 text-sm text-text-secondary">
          CET1 has no automated source (manual entry only). NPL is auto-computed where available; entering a value here
          overrides it.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-4">
          <FormField label="CET1 ratio" htmlFor={`${ticker}-cet1`} error={cet1Check.error}>
            <NumberField
              value={displayed.cet1}
              onChange={(value) => update("cet1", value)}
              size="medium"
              optional
              unit="%"
              placeholder="Not yet entered"
            />
          </FormField>
          <FormField label="CET1 as of" htmlFor={`${ticker}-cet1-as-of`}>
            <Input
              type="text"
              size="medium"
              value={displayed.cet1AsOf}
              onChange={(e) => update("cet1AsOf", e.target.value)}
              placeholder="e.g. Q2 2026"
            />
          </FormField>
        </div>

        <div className="space-y-4">
          <FormField label="NPL ratio override" htmlFor={`${ticker}-npl`} error={nplCheck.error}>
            <NumberField
              value={displayed.npl}
              onChange={(value) => update("npl", value)}
              size="medium"
              optional
              unit="%"
              placeholder={autoNpl != null ? `auto: ${fmtPct(autoNpl, 1)}` : "Not available"}
            />
          </FormField>
          <FormField label="NPL as of" htmlFor={`${ticker}-npl-as-of`} hint="Leave blank to keep auto.">
            <Input
              type="text"
              size="medium"
              value={displayed.nplAsOf}
              onChange={(e) => update("nplAsOf", e.target.value)}
              placeholder="e.g. Q1 2026"
            />
          </FormField>
          {autoNpl != null && (
            <p className="text-xs text-text-tertiary">
              Auto-computed: {fmtPct(autoNpl, 1)} (as of {step5.npl_as_of}) — editable above.
            </p>
          )}
        </div>
      </div>

      {dirty && (
        <div className="space-y-3 rounded-md border border-warn/40 bg-warn/10 p-4">
          <p className="text-sm text-warn">
            Save these CET1/NPL values? This recomputes Debt and Overall Assessment for {ticker}.
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleConfirm}
              disabled={saving || invalid}
              className="rounded-md border border-warn/60 bg-warn/15 px-4 py-1.5 text-sm font-medium text-warn transition-colors hover:border-warn disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Saving…" : "Confirm"}
            </button>
            <Button variant="outline" onClick={handleCancel} disabled={saving}>
              Cancel
            </Button>
          </div>
          {invalid && <p className="text-sm text-text-secondary">Fix the highlighted fields to save.</p>}
          {saveError && <p className="text-sm text-negative">{saveError}</p>}
        </div>
      )}
    </Card>
  );
}

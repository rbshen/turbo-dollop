"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { DiscountRateConfigOut } from "@/lib/api/types";
import { useDiscountRateConfigs } from "@/lib/hooks/useDiscountRateConfig";
import { fmtNumber } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Section } from "@/components/ui/section";

type Status = "idle" | "saving" | "saved" | "error";

const STATUS_LABELS: Record<Status, string> = {
  idle: "Save",
  saving: "Saving…",
  saved: "Saved ✓",
  error: "Save failed",
};

// A region's own display name, where it differs from its bare code. Only
// US is supported today (backend helpers/discount_rate_config.py::
// SUPPORTED_REGIONS); a ticker from any other country (an ADR's domicile)
// uses the US rate directly and never gets its own row.
const REGION_LABELS: Record<string, string> = {
  US: "United States",
};

function regionLabel(region: string): string {
  return REGION_LABELS[region] ?? region;
}

export function DiscountRateSettingsForm() {
  const { data, error, isLoading } = useDiscountRateConfigs();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load discount rate settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  return (
    <Section title="Discount Rate by Country">
      <p className="text-xs text-text-tertiary">
        Risk-Free Rate and Market Risk Premium are 5-year trailing averages from market-risk-premia.com — manually
        maintained here, not auto-fetched (see CLAUDE.md). Beta stays sourced live per-ticker from FMP. Feeds a
        ticker&apos;s own country&apos;s Valuation discount rate: <span className="font-mono text-text-secondary">Rf + β × MRP</span>. Only
        the United States has its own rate; a ticker from any other country (e.g. an ADR) uses the US rate directly.
      </p>

      <div className="mt-4 space-y-4">
        {data.map((row) => (
          // Keyed on region + updated_at so a save (which changes updated_at)
          // remounts just that region's form with fresh initial text --
          // avoids setState-in-effect just to resync local edit state.
          <DiscountRateForm key={`${row.region}-${row.updated_at}`} data={row} />
        ))}
      </div>
    </Section>
  );
}

// Each region is a genuinely distinct, independently-saved panel -- a Card,
// not folded into the Section's own flow -- so a future second region (the
// backend already supports more than one) reads as its own bounded card
// rather than blurring into the one above it.
function DiscountRateForm({ data }: { data: DiscountRateConfigOut }) {
  const [rfText, setRfText] = useState(fmtNumber(data.risk_free_rate * 100, 3));
  const [mrpText, setMrpText] = useState(fmtNumber(data.market_risk_premium * 100, 3));
  const [status, setStatus] = useState<Status>("idle");

  async function handleSave() {
    const riskFreeRate = parseFloat(rfText);
    const marketRiskPremium = parseFloat(mrpText);
    if (Number.isNaN(riskFreeRate) || Number.isNaN(marketRiskPremium)) {
      setStatus("error");
      return;
    }
    setStatus("saving");
    try {
      await apiPut<DiscountRateConfigOut>("/config/discount-rate", {
        region: data.region,
        risk_free_rate: riskFreeRate / 100,
        market_risk_premium: marketRiskPremium / 100,
      });
      await mutate("/config/discount-rate");
      await mutate("/config/discount-rates");
      // Every ticker's Step 3 discount rate is derived from this config --
      // invalidate every cached Step 3 fetch (and the ticker header, which
      // also reads Step 3's result) so the next view reflects the new rate
      // without a manual page reload. Invalidates every region's cache at
      // once (not just this row's) since there's no cheap way to know from
      // here which cached /step3 responses belong to this region's
      // tickers -- an over-invalidation, not a correctness issue.
      await mutate((key) => typeof key === "string" && (key.includes("/step3") || key.includes("/summary")));
      setStatus("saved");
    } catch {
      setStatus("error");
    } finally {
      setTimeout(() => setStatus("idle"), 3000);
    }
  }

  return (
    <Card className="space-y-4">
      <h3 className="text-sm font-semibold text-text-primary">
        {regionLabel(data.region)} <span className="font-mono text-xs text-text-tertiary">({data.region})</span>
      </h3>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Risk-Free Rate (%)" htmlFor={`risk-free-rate-${data.region}`}>
          <Input
            id={`risk-free-rate-${data.region}`}
            variant="boxed"
            type="number"
            step="0.001"
            className="mt-1 w-full font-mono"
            value={rfText}
            onChange={(e) => setRfText(e.target.value)}
          />
        </Field>
        <Field label="Market Risk Premium (%)" htmlFor={`market-risk-premium-${data.region}`}>
          <Input
            id={`market-risk-premium-${data.region}`}
            variant="boxed"
            type="number"
            step="0.001"
            className="mt-1 w-full font-mono"
            value={mrpText}
            onChange={(e) => setMrpText(e.target.value)}
          />
        </Field>
      </div>

      <div className="flex items-center gap-3">
        <Button variant="primary" onClick={handleSave} disabled={status === "saving"}>
          {STATUS_LABELS[status]}
        </Button>
        <p className="text-xs text-text-tertiary">Last updated {new Date(data.updated_at).toLocaleString()}</p>
      </div>
    </Card>
  );
}

"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { DiscountRateConfigOut } from "@/lib/api/types";
import { useDiscountRateConfigs } from "@/lib/hooks/useDiscountRateConfig";
import { NumberField } from "@/components/ui/number-field";
import {
  SettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSection,
} from "@/components/settings/SettingsLayout";
import { useSettingsSave, type SettingsSaver } from "@/components/settings/useSettingsSave";
import { checkNumber } from "@/lib/numberInput";
import { fractionToPercentText, percentToFraction } from "@/lib/percentFraction";

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
    <SettingsSection
      title="Discount rate by country"
      intro="The rates used to work out each ticker's discount rate for the Valuation tab: risk-free rate plus beta times market risk premium. Both are 5-year trailing averages from market-risk-premia.com that you update by hand; nothing refreshes them, so they go stale until you do. Beta comes live from FMP for each ticker. Only the United States has its own rate; a ticker from any other country, such as an ADR, uses the US rate."
    >
      <div className="space-y-10">
        {data.map((row) => (
          <DiscountRateRegion key={row.region} data={row} />
        ))}
      </div>
    </SettingsSection>
  );
}

// One region saves on its own, so each holds its own save status here, ABOVE
// the form's key={updated_at} remount, so "Saved ✓" survives it.
function DiscountRateRegion({ data }: { data: DiscountRateConfigOut }) {
  const saver = useSettingsSave();
  // Keyed on updated_at so a save (which changes updated_at) remounts just
  // this region's form with fresh initial text.
  return <DiscountRateForm key={data.updated_at} data={data} saver={saver} />;
}

// The stored rates are fractions (0.03608); the fields show and take percent
// (3.608). The stored value is shown at full precision (never rounded to 3
// decimals), and a field the user did not edit is sent back as its ORIGINAL
// stored value -- so pressing Save can never rewrite a rate the user did not
// touch, and editing one field never rewrites the other. No bounds: the
// server has none, so the only check is "is it a number".
function DiscountRateForm({ data, saver }: { data: DiscountRateConfigOut; saver: SettingsSaver }) {
  const shownRf = fractionToPercentText(data.risk_free_rate);
  const shownMrp = fractionToPercentText(data.market_risk_premium);
  const [rfText, setRfText] = useState(shownRf);
  const [mrpText, setMrpText] = useState(shownMrp);

  const rf = checkNumber(rfText);
  const mrp = checkNumber(mrpText);
  const invalid = rf.error !== null || mrp.error !== null;
  // Edited = differs from what the stored value shows. An unparsable entry
  // counts as edited (it is not the stored value) but blocks Save via `invalid`.
  const rfEdited = rf.value === null || rf.value !== Number(shownRf);
  const mrpEdited = mrp.value === null || mrp.value !== Number(shownMrp);
  const unchanged = !rfEdited && !mrpEdited;

  function handleSave() {
    if (invalid || rf.value === null || mrp.value === null) return;
    const body = {
      region: data.region,
      risk_free_rate: rfEdited ? percentToFraction(rf.value) : data.risk_free_rate,
      market_risk_premium: mrpEdited ? percentToFraction(mrp.value) : data.market_risk_premium,
    };
    void saver.run(async () => {
      await apiPut<DiscountRateConfigOut>("/config/discount-rate", body);
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
    });
  }

  return (
    <div>
      <SettingsGroup title={`${regionLabel(data.region)} (${data.region})`}>
        <SettingsRow
          label="Risk-free rate"
          hint="A 5-year trailing average of the risk-free rate, and the starting point of the discount rate."
          htmlFor={`risk-free-rate-${data.region}`}
          error={rf.error}
        >
          <NumberField value={rfText} onChange={setRfText} size="short" unit="%" step={0.001} />
        </SettingsRow>
        <SettingsRow
          label="Market risk premium"
          hint="The extra return investors expect from stocks over the risk-free rate, as a 5-year trailing average."
          htmlFor={`market-risk-premium-${data.region}`}
          error={mrp.error}
        >
          <NumberField value={mrpText} onChange={setMrpText} size="short" unit="%" step={0.001} />
        </SettingsRow>
      </SettingsGroup>

      <SettingsFooter
        onSave={handleSave}
        status={saver.status}
        invalid={invalid}
        unchanged={unchanged}
        updatedAt={data.updated_at}
      />
    </div>
  );
}

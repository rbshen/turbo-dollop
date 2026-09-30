"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { ReitDividendYieldConfigOut } from "@/lib/api/types";
import { useReitDividendYieldConfig } from "@/lib/hooks/useReitDividendYieldConfig";
import { NumberField } from "@/components/ui/number-field";
import {
  SettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSection,
} from "@/components/settings/SettingsLayout";
import { useSettingsSave, type SettingsSaver } from "@/components/settings/useSettingsSave";
import { checkNumber } from "@/lib/numberInput";

export function ReitDividendYieldSettingsForm() {
  const { data, error, isLoading } = useReitDividendYieldConfig();
  // Held here, above the keyed form below, so "Saved ✓" survives the remount.
  const saver = useSettingsSave();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load REIT dividend yield settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (which changes updated_at) remounts this
  // with fresh initial text -- same pattern as the other settings forms.
  return <ReitDividendYieldForm key={data.updated_at} data={data} saver={saver} />;
}

// A single config object, one field. No bounds: the server has none, so the
// only check is "is it a number" -- a value is never clamped or corrected.
function ReitDividendYieldForm({ data, saver }: { data: ReitDividendYieldConfigOut; saver: SettingsSaver }) {
  const [thresholdText, setThresholdText] = useState(String(data.threshold_pct));

  const check = checkNumber(thresholdText);
  const invalid = check.error !== null;
  // An unparsable entry counts as edited (it is not the stored value) but
  // blocks Save through `invalid`.
  const unchanged = check.value !== null && check.value === data.threshold_pct;

  // Identifies the field values, so a failed save's message stays until they change.
  const signature = JSON.stringify([thresholdText]);
  const shown = saver.view(signature);

  function handleSave() {
    if (check.value === null || invalid) return;
    const thresholdPct = check.value;
    void saver.run(async () => {
      await apiPut<ReitDividendYieldConfigOut>("/config/reit-dividend-yield", { threshold_pct: thresholdPct });
      await mutate("/config/reit-dividend-yield");
      // This threshold feeds Step3Out.dividend_yield_meets_reit_threshold
      // for every REIT ticker -- invalidate every cached Step 3 fetch (and
      // the ticker header, which also reads Step 3's result) so the next
      // view reflects the new threshold without a manual page reload.
      await mutate((key) => typeof key === "string" && (key.includes("/step3") || key.includes("/summary")));
    }, signature);
  }

  return (
    <SettingsSection
      title="REIT dividend yield threshold"
      intro="Sets the dividend yield at or above which a REIT or property developer is flagged as a possible bargain on its Valuation tab. This is an informational check only; it never changes the Price-to-Book calculation or verdict."
    >
      <SettingsGroup>
        <SettingsRow
          label="Threshold"
          hint="A REIT or property developer is flagged when its trailing dividend yield is at or above this. A reference check only; it never changes the Price-to-Book result."
          htmlFor="reit-dividend-yield-threshold"
          error={check.error}
        >
          <NumberField value={thresholdText} onChange={setThresholdText} size="short" unit="%" step={0.1} />
        </SettingsRow>
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

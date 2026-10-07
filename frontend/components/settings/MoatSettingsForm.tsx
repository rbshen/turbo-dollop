"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { MoatScoreConfigOut } from "@/lib/api/types";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";
import { refreshScoreWeights, revalidateScores, useRecomputeStatus } from "@/lib/hooks/useScoreWeights";
import { RecomputeStatusLine } from "@/components/settings/RecomputeStatusLine";
import { NumberField } from "@/components/ui/number-field";
import { Select } from "@/components/ui/Select";
import {
  SettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSection,
} from "@/components/settings/SettingsLayout";
import { useSettingsSave, type SettingsSaver } from "@/components/settings/useSettingsSave";

export function MoatSettingsForm() {
  const { data, error, isLoading } = useMoatConfig();
  // Held here, above the keyed form below, so "Saved ✓" survives the remount.
  const saver = useSettingsSave();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load Economic Moat settings — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (which changes updated_at) remounts this
  // with fresh initial text.
  return <MoatScoreForm key={data.updated_at} data={data} saver={saver} />;
}

// Wide and No moat / not rated are fixed (the backend enforces them: only the Narrow value is an input), shown read-only. Narrow is
// one of the server's allowed values (`narrow_moat_multiplier_options`: 0.80, 0.82, 0.85, 0.87, 0.90), so there is nothing to type
// and nothing to validate in the form: a select cannot hold a value outside its options.
const fmt = (value: number) => value.toFixed(2);

function MoatScoreForm({ data, saver }: { data: MoatScoreConfigOut; saver: SettingsSaver }) {
  const [narrow, setNarrow] = useState(fmt(data.narrow_moat_multiplier));
  const unchanged = Number(narrow) === data.narrow_moat_multiplier;

  // Identifies the field value, so a failed save's message stays until it changes.
  const signature = narrow;
  const shown = saver.view(signature);
  const { running } = useRecomputeStatus();

  function handleSave() {
    const body = { narrow_moat_multiplier: Number(narrow) };
    void saver.run(async () => {
      await apiPut<MoatScoreConfigOut>("/config/moat", body);
      // Every mounted OverallAssessmentCard reads this same global SWR key
      // -- one revalidation reflows every open ticker's score
      // without a manual page reload.
      await mutate("/config/moat");
      // Saving the multiplier starts a full score recompute: read its status now so the polling begins, and refresh the scores shown.
      await refreshScoreWeights();
      await revalidateScores();
    }, signature);
  }

  return (
    <SettingsSection
      title="Economic moat multipliers"
      intro="A ticker's Overall score is its Steps score (the weighted blend of the four checks, set under Score weighting) times a multiplier for its moat rating. Wide moat keeps the Steps score as it is, Narrow moat scales it down by the factor you choose, and No moat scales it to 70%. A ticker with no moat rated is scored as No moat. Saving the Narrow multiplier recomputes all scores."
    >
      <RecomputeStatusLine />
      <SettingsGroup>
        <SettingsRow
          label="Wide moat"
          hint="Fixed at 1.0: a Wide moat leaves the Steps score unchanged."
          htmlFor="wide-moat-multiplier"
        >
          <NumberField id="wide-moat-multiplier" value="1.0" onChange={() => {}} size="short" readOnly disabled />
        </SettingsRow>
        <SettingsRow
          label="Narrow moat"
          hint="Multiplies the Steps score of a Narrow moat ticker. The default is 0.85."
          htmlFor="narrow-moat-multiplier"
        >
          <Select size="short" value={narrow} onChange={(e) => setNarrow(e.target.value)}>
            {data.narrow_moat_multiplier_options.map((option) => (
              <option key={option} value={fmt(option)}>
                {fmt(option)}
              </option>
            ))}
          </Select>
        </SettingsRow>
        <SettingsRow
          label="No moat / not rated"
          hint="Fixed at 0.70: a No moat rating, or a ticker with no moat rated, scales the Steps score to 70%. It cannot be changed."
          htmlFor="no-moat-multiplier"
        >
          <NumberField id="no-moat-multiplier" value={fmt(data.no_moat_multiplier)} onChange={() => {}} size="short" readOnly disabled />
        </SettingsRow>
      </SettingsGroup>

      <SettingsFooter
        onSave={handleSave}
        status={shown.status}
        invalid={false}
        unchanged={unchanged || running}
        message={shown.detail}
        updatedAt={data.updated_at}
      />
    </SettingsSection>
  );
}

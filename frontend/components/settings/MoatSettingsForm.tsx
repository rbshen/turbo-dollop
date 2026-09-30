"use client";

import { useState } from "react";
import { mutate } from "swr";

import { apiPut } from "@/lib/api/client";
import type { MoatScoreConfigOut } from "@/lib/api/types";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";
import { NumberField } from "@/components/ui/number-field";
import {
  SettingsFooter,
  SettingsGroup,
  SettingsRow,
  SettingsSection,
} from "@/components/settings/SettingsLayout";
import { useSettingsSave, type SettingsSaver } from "@/components/settings/useSettingsSave";
import { checkNumber } from "@/lib/numberInput";

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

// The three scores are points on a 0-100 scale. The backend has no bound and
// the API is unchanged, so this is a FORM-LEVEL check only: a value outside
// 0-100 shows an inline error and blocks Save; it is never clamped or corrected.
const MOAT_SCORE_RULES = { min: 0, max: 100 };

// A single config object, three fields.
function MoatScoreForm({ data, saver }: { data: MoatScoreConfigOut; saver: SettingsSaver }) {
  const [wideText, setWideText] = useState(String(data.wide_moat_score));
  const [narrowText, setNarrowText] = useState(String(data.narrow_moat_score));
  const [noMoatText, setNoMoatText] = useState(String(data.no_moat_score));

  const wide = checkNumber(wideText, MOAT_SCORE_RULES);
  const narrow = checkNumber(narrowText, MOAT_SCORE_RULES);
  const noMoat = checkNumber(noMoatText, MOAT_SCORE_RULES);
  const invalid = wide.error !== null || narrow.error !== null || noMoat.error !== null;
  const unchanged =
    wide.value === data.wide_moat_score &&
    narrow.value === data.narrow_moat_score &&
    noMoat.value === data.no_moat_score;

  function handleSave() {
    if (invalid || wide.value === null || narrow.value === null || noMoat.value === null) return;
    const body = {
      wide_moat_score: wide.value,
      narrow_moat_score: narrow.value,
      no_moat_score: noMoat.value,
    };
    void saver.run(async () => {
      await apiPut<MoatScoreConfigOut>("/config/moat", body);
      // Every mounted OverallAssessmentCard reads this same global SWR key
      // -- one revalidation reflows every open ticker's blended score
      // without a manual page reload.
      await mutate("/config/moat");
    });
  }

  return (
    <SettingsSection
      title="Economic moat point values"
      intro="Sets the points each moat rating counts for in a ticker's Overall Assessment. Once you have set a moat for a ticker, it makes up 31% of that ticker's overall score and the four automated checks make up the other 69%. A ticker with no moat set is scored on the four checks alone."
    >
      <SettingsGroup>
        <SettingsRow
          label="Wide moat"
          hint="The points, out of 100, that a Wide moat rating counts for in the Overall Assessment. The default is 100."
          htmlFor="wide-moat-score"
          error={wide.error}
        >
          <NumberField value={wideText} onChange={setWideText} size="short" step={0.1} {...MOAT_SCORE_RULES} />
        </SettingsRow>
        <SettingsRow
          label="Narrow moat"
          hint="The points, out of 100, that a Narrow moat rating counts for in the Overall Assessment. The default is 65."
          htmlFor="narrow-moat-score"
          error={narrow.error}
        >
          <NumberField value={narrowText} onChange={setNarrowText} size="short" step={0.1} {...MOAT_SCORE_RULES} />
        </SettingsRow>
        <SettingsRow
          label="No moat"
          hint="The points, out of 100, that a No moat rating counts for in the Overall Assessment. At the default of 0 it can hold the overall score below 70 whatever the four checks say."
          htmlFor="no-moat-score"
          error={noMoat.error}
        >
          <NumberField value={noMoatText} onChange={setNoMoatText} size="short" step={0.1} {...MOAT_SCORE_RULES} />
        </SettingsRow>
      </SettingsGroup>

      <SettingsFooter
        onSave={handleSave}
        status={saver.status}
        invalid={invalid}
        unchanged={unchanged}
        message={saver.detail}
        updatedAt={data.updated_at}
      />
    </SettingsSection>
  );
}

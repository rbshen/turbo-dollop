"use client";

import { useState } from "react";
import { mutate } from "swr";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NumberSettingRow } from "@/components/settings/NumberSettingRow";
import { SettingsFooter, SettingsGroup, SettingsSection } from "@/components/settings/SettingsLayout";
import { useSettingsSave, type SettingsSaver } from "@/components/settings/useSettingsSave";
import { apiPost, apiPut } from "@/lib/api/client";
import type { StuckCheckSettingsOut, StuckCheckSettingsValues } from "@/lib/api/types";
import { STUCK_CHECK_SETTINGS_URL, useStuckCheckSettings } from "@/lib/hooks/useStuckCheckSettings";
import { checkNumber, type NumberRules } from "@/lib/numberInput";

type NumericKey = Exclude<keyof StuckCheckSettingsValues, "exemptions">;

// The wording of each threshold; the bounds, defaults and the exemptable rows all come from the endpoint.
const FIELDS: Record<NumericKey, { label: string; hint: string; unit: string; step?: number; integer?: boolean }> = {
  sbc_revenue_pct: {
    label: "SBC limit, % of revenue",
    hint: "Flag the stock-based compensation row when five years of it come to more than this share of revenue.",
    unit: "%",
  },
  sbc_fcf_pct: {
    label: "SBC limit, % of free cash flow",
    hint: "Flag it when five years of it come to more than this share of free cash flow. A share that cannot be measured counts as over.",
    unit: "%",
  },
  cash_conversion_line: {
    label: "Cash conversion line",
    hint: "Free cash flow divided by net income. Flagged only when both the last 3 and the last 10 fiscal years are below it.",
    unit: "×",
    step: 0.05,
  },
  share_growth_pct: {
    label: "Share count growth per year",
    hint: "Flag diluted shares growing faster than this a year, unless one year carries most of it.",
    unit: "%",
    step: 0.5,
  },
  one_off_pct: {
    label: "One-off exception",
    hint: "When a single year carries at least this share of the dilution, it reads as a one-off issuance and is not flagged.",
    unit: "%",
  },
  sector_band_pp: {
    label: "In-line band",
    hint: "A return within this many percentage points of its sector ETF reads as in line, beyond it as leads or trails.",
    unit: "pp",
    step: 0.5,
  },
  smoothing_days: {
    label: "Time-stop smoothing",
    hint: "Trading days a ticker must stay out of Pass and Undervalued before its since-date resets. Used by the daily log; nothing shows it yet.",
    unit: "days",
    integer: true,
  },
};

const GROUPS: { title: string; keys: NumericKey[] }[] = [
  { title: "Stock-based compensation", keys: ["sbc_revenue_pct", "sbc_fcf_pct"] },
  { title: "Cash conversion and share count", keys: ["cash_conversion_line", "share_growth_pct", "one_off_pct"] },
  { title: "Relative strength", keys: ["sector_band_pp"] },
  { title: "Since-date", keys: ["smoothing_days"] },
];

const TICKER_TEXT = /^[A-Z0-9][A-Z0-9.-]{0,9}$/;

interface ExemptionDraft {
  id: number; // local key only
  ticker: string;
  reason: string;
  rows: string[];
}

export function StuckCheckSettingsForm() {
  const { data, error, isLoading } = useStuckCheckSettings();
  // Held here, above the keyed form below, so "Saved ✓" survives the remount.
  const saver = useSettingsSave();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load these settings — {error.message}</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }
  return <StuckForm key={data.updated_at} data={data} saver={saver} />;
}

function draftsFrom(exemptions: StuckCheckSettingsValues["exemptions"]): ExemptionDraft[] {
  return exemptions.map((e, id) => ({ id, ticker: e.ticker, reason: e.reason, rows: [...e.rows] }));
}

function StuckForm({ data, saver }: { data: StuckCheckSettingsOut; saver: SettingsSaver }) {
  const [texts, setTexts] = useState<Record<NumericKey, string>>(
    () => Object.fromEntries(Object.keys(FIELDS).map((k) => [k, String(data[k as NumericKey])])) as Record<NumericKey, string>,
  );
  const [drafts, setDrafts] = useState<ExemptionDraft[]>(() => draftsFrom(data.exemptions));
  const [nextId, setNextId] = useState(data.exemptions.length);

  const rulesFor = (key: NumericKey): NumberRules => ({
    integer: FIELDS[key].integer,
    min: data.bounds[key].min,
    max: data.bounds[key].max,
  });
  const checks = Object.fromEntries(
    (Object.keys(FIELDS) as NumericKey[]).map((key) => [key, checkNumber(texts[key], rulesFor(key))]),
  ) as Record<NumericKey, ReturnType<typeof checkNumber>>;

  const seen = new Set<string>();
  const entryErrors = drafts.map((d) => {
    const ticker = d.ticker.trim().toUpperCase();
    const errors: string[] = [];
    if (!TICKER_TEXT.test(ticker)) errors.push("Enter a ticker such as IBKR or BRK.B.");
    else if (seen.has(ticker)) errors.push("This ticker is already in the list.");
    seen.add(ticker);
    if (d.reason.trim() === "") errors.push("Give a reason.");
    if (d.rows.length === 0) errors.push("Tick at least one row.");
    return errors;
  });

  const invalid = Object.values(checks).some((c) => c.error !== null) || entryErrors.some((e) => e.length > 0);
  const bodyExemptions = drafts.map((d) => ({ ticker: d.ticker.trim().toUpperCase(), reason: d.reason.trim(), rows: data.row_options.map((o) => o.key).filter((k) => d.rows.includes(k)) }));
  const unchanged =
    (Object.keys(FIELDS) as NumericKey[]).every((key) => checks[key].value === data[key]) &&
    JSON.stringify(bodyExemptions) === JSON.stringify(data.exemptions);
  const atDefaults =
    (Object.keys(FIELDS) as NumericKey[]).every((key) => data[key] === data.defaults[key]) &&
    JSON.stringify(data.exemptions) === JSON.stringify(data.defaults.exemptions);

  const signature = JSON.stringify([texts, drafts]);
  const shown = saver.view(signature);

  function handleSave() {
    if (invalid) return;
    const body = { exemptions: bodyExemptions } as Record<string, unknown>;
    for (const key of Object.keys(FIELDS) as NumericKey[]) body[key] = checks[key].value;
    void saver.run(async () => {
      await apiPut<StuckCheckSettingsOut>(STUCK_CHECK_SETTINGS_URL, body);
      await mutate(STUCK_CHECK_SETTINGS_URL);
    }, signature);
  }

  function handleReset() {
    void saver.run(async () => {
      await apiPost<StuckCheckSettingsOut>(`${STUCK_CHECK_SETTINGS_URL}/reset`);
      await mutate(STUCK_CHECK_SETTINGS_URL);
    }, signature);
  }

  const patch = (id: number, change: Partial<ExemptionDraft>) =>
    setDrafts((prev) => prev.map((d) => (d.id === id ? { ...d, ...change } : d)));

  return (
    <SettingsSection
      title="Why might it be stuck?"
      intro="Thresholds for the Why might it be stuck? section at the bottom of a ticker's Dashboard tab. The section is context only: it never changes a score, a verdict or the Screener. A change applies the next time a ticker page loads, with no recompute."
    >
      {GROUPS.map((group) => (
        <SettingsGroup key={group.title} title={group.title}>
          {group.keys.map((key) => (
            <NumberSettingRow
              key={key}
              id={`stuck-${key}`}
              label={FIELDS[key].label}
              hint={FIELDS[key].hint}
              unit={FIELDS[key].unit}
              step={FIELDS[key].step}
              rules={rulesFor(key)}
              value={texts[key]}
              onChange={(value) => setTexts((prev) => ({ ...prev, [key]: value }))}
            />
          ))}
        </SettingsGroup>
      ))}

      <SettingsGroup title="Exempt tickers">
        <p className="pb-3 text-xs text-text-tertiary">
          A ticker listed here shows Not applicable, with its reason, on the rows ticked. Use it where a business model distorts a
          row, such as a broker or a captive finance arm.
        </p>
        {drafts.map((draft, index) => (
          <fieldset key={draft.id} className="space-y-3 py-4" aria-label={`Exemption ${index + 1}`}>
            <div className="flex flex-wrap items-start gap-3">
              <Input
                aria-label={`Exemption ${index + 1} ticker`}
                placeholder="Ticker"
                size="short"
                className="font-mono uppercase"
                value={draft.ticker}
                invalid={entryErrors[index].length > 0 && !TICKER_TEXT.test(draft.ticker.trim().toUpperCase())}
                onChange={(e) => patch(draft.id, { ticker: e.target.value })}
              />
              <Input
                aria-label={`Exemption ${index + 1} reason`}
                placeholder="Reason, shown on the card"
                size="full"
                className="min-w-0 flex-1 basis-64"
                maxLength={300}
                value={draft.reason}
                onChange={(e) => patch(draft.id, { reason: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
              {data.row_options.map((option) => (
                <Checkbox
                  key={option.key}
                  variant="neutral"
                  label={option.label}
                  checked={draft.rows.includes(option.key)}
                  onChange={(e) =>
                    patch(draft.id, { rows: e.target.checked ? [...draft.rows, option.key] : draft.rows.filter((k) => k !== option.key) })
                  }
                />
              ))}
            </div>
            {entryErrors[index].length > 0 && (
              <p role="alert" className="text-xs text-negative">
                {entryErrors[index].join(" ")}
              </p>
            )}
            <Button variant="ghost" size="sm" onClick={() => setDrafts((prev) => prev.filter((d) => d.id !== draft.id))}>
              Remove {draft.ticker.trim().toUpperCase() || "entry"}
            </Button>
          </fieldset>
        ))}
        <div className="py-3">
          <Button
            variant="outline"
            onClick={() => {
              setDrafts((prev) => [...prev, { id: nextId, ticker: "", reason: "", rows: [] }]);
              setNextId(nextId + 1);
            }}
          >
            Add exempt ticker
          </Button>
        </div>
      </SettingsGroup>

      <SettingsFooter
        onSave={handleSave}
        status={shown.status}
        invalid={invalid}
        unchanged={unchanged}
        message={shown.detail}
        updatedAt={data.updated_at}
        secondary={
          <Button variant="outline" onClick={handleReset} disabled={atDefaults || saver.status === "saving"}>
            Reset to defaults
          </Button>
        }
      />
    </SettingsSection>
  );
}

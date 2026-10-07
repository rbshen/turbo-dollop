"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { NumberSettingRow } from "@/components/settings/NumberSettingRow";
import { RecomputeStatusLine } from "@/components/settings/RecomputeStatusLine";
import {
  SettingsFooter,
  SettingsGroup,
  SettingsSection,
} from "@/components/settings/SettingsLayout";
import { useSettingsSave, type SettingsSaver } from "@/components/settings/useSettingsSave";
import { apiPost, apiPut } from "@/lib/api/client";
import type { ScoreWeightGroupKey, ScoreWeightGroups, ScoreWeightsOut } from "@/lib/api/types";
import { refreshScoreWeights, revalidateScores, useRecomputeStatus, useScoreWeights } from "@/lib/hooks/useScoreWeights";
import { checkNumber } from "@/lib/numberInput";

// What each group and component is called and what it measures (plain English, one short sentence). The groups, their components, the
// bounds and the sums all come from the endpoint; only the wording lives here.
interface FieldSpec {
  key: string;
  label: string;
  hint: string;
}
interface GroupSpec {
  key: ScoreWeightGroupKey;
  title: string;
  fields: FieldSpec[];
}

const GROUPS: GroupSpec[] = [
  {
    key: "overall",
    title: "Overall weights",
    fields: [
      { key: "financials", label: "Financials", hint: "Revenue, net income and cash flow." },
      { key: "growth", label: "Growth Rate", hint: "Forward analyst growth expectations." },
      { key: "profitability", label: "Profitability", hint: "Returns on equity and capital, receivables and cash conversion." },
      { key: "debt", label: "Debt", hint: "Short-term liquidity, leverage and the burden of servicing debt." },
    ],
  },
  {
    key: "step1",
    title: "Financials",
    fields: [
      { key: "revenue", label: "Revenue", hint: "Is the business growing? The foundation of the check." },
      { key: "net_income", label: "Net Income", hint: "Reported profit trend (with an operating-income backup for one-off dips)." },
      { key: "cfo", label: "Cash flow from operations", hint: "The cash the business actually generates." },
      { key: "margins", label: "Margins", hint: "Gross and net margin direction." },
      { key: "fcf", label: "Free cash flow", hint: "Whether cash burn is sustained." },
    ],
  },
  {
    key: "step2",
    title: "Growth Rate",
    fields: [
      { key: "magnitude", label: "Growth magnitude", hint: "How fast analysts expect the company to grow." },
      { key: "agreement", label: "Estimate agreement", hint: "How closely the analysts' estimates agree." },
    ],
  },
  {
    key: "step4",
    title: "Profitability",
    fields: [
      { key: "roe", label: "Return on equity", hint: "Profit for each dollar shareholders have invested." },
      { key: "roic", label: "Return on invested capital", hint: "Profit against all the capital in the business." },
      { key: "ar", label: "Revenue vs accounts receivable", hint: "Whether receivables are outgrowing revenue." },
      { key: "ccc", label: "Cash conversion cycle", hint: "How fast spending turns back into cash." },
    ],
  },
  {
    key: "step5",
    title: "Debt",
    fields: [
      { key: "current_ratio", label: "Current ratio", hint: "Short-term assets against short-term obligations." },
      { key: "debt_to_ebitda", label: "Debt / EBITDA", hint: "Debt against operating earnings." },
      { key: "debt_servicing", label: "Debt servicing ratio", hint: "Interest as a share of operating cash flow." },
    ],
  },
];

const fieldId = (group: string, field: string) => `weight-${group}-${field}`;
const textKey = (group: string, field: string) => `${group}.${field}`;
type Texts = Record<string, string>;

function textsFrom(weights: ScoreWeightGroups): Texts {
  const texts: Texts = {};
  for (const group of GROUPS) {
    for (const field of group.fields) {
      texts[textKey(group.key, field.key)] = String((weights[group.key] as Record<string, number>)[field.key]);
    }
  }
  return texts;
}

export function ScoreWeightingForm() {
  const { data, error, isLoading } = useScoreWeights();
  // Held here, above the keyed form below, so "Saved ✓" survives the remount.
  const saver = useSettingsSave();

  if (error) {
    return <p className="text-sm text-negative">Couldn&apos;t load score weighting — {error.message}</p>;
  }

  if (isLoading || !data) {
    return <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>;
  }

  // Keyed on updated_at so a save (or a reset) remounts this with fresh initial text.
  return <WeightsForm key={data.updated_at} data={data} saver={saver} />;
}

type Confirming = "save" | "reset" | null;

function WeightsForm({ data, saver }: { data: ScoreWeightsOut; saver: SettingsSaver }) {
  const [texts, setTexts] = useState<Texts>(() => textsFrom(data.weights));
  const [confirming, setConfirming] = useState<Confirming>(null);
  const { running, run } = useRecomputeStatus();

  const checks: Record<string, ReturnType<typeof checkNumber>> = {};
  const rulesFor = (group: ScoreWeightGroupKey, field: string) => {
    const bounds = (data.bounds[group] as Record<string, { min: number; max: number }>)[field];
    return { integer: true, min: bounds.min, max: bounds.max };
  };
  for (const group of GROUPS) {
    for (const field of group.fields) {
      const key = textKey(group.key, field.key);
      checks[key] = checkNumber(texts[key], rulesFor(group.key, field.key));
    }
  }

  // Per set: the sum of what is typed (when every entry is a number) against what the set must add up to.
  const sums = GROUPS.map((group) => {
    const values = group.fields.map((field) => checks[textKey(group.key, field.key)].value);
    const sum = values.every((v) => v !== null) ? (values as number[]).reduce((a, b) => a + b, 0) : null;
    return { group: group.key, sum, needs: data.sums[group.key], ok: sum === data.sums[group.key] };
  });

  // Strict orderings (the endpoint's `orderings`: Debt/EBITDA > Debt Servicing > Current ratio), checked on what is typed once every
  // entry of the group is a number. One message per group that breaks its order.
  const orderMessages: Partial<Record<ScoreWeightGroupKey, string>> = {};
  for (const group of GROUPS) {
    const order = data.orderings?.[group.key];
    if (!order) continue;
    const typed = order.map((field) => checks[textKey(group.key, field)].value);
    if (typed.some((v) => v === null)) continue;
    if (typed.some((v, i) => i > 0 && (typed[i - 1] as number) <= (v as number))) {
      const names = order.map((field) => group.fields.find((f) => f.key === field)?.label ?? field).join(" > ");
      orderMessages[group.key] = `${group.title} weights must keep this order, each strictly larger than the next: ${names}.`;
    }
  }

  const fieldsInvalid = Object.values(checks).some((c) => c.error !== null);
  const invalid = fieldsInvalid || sums.some((s) => !s.ok) || Object.keys(orderMessages).length > 0;
  const unchanged = GROUPS.every((group) =>
    group.fields.every(
      (field) => checks[textKey(group.key, field.key)].value === (data.weights[group.key] as Record<string, number>)[field.key],
    ),
  );
  const atDefaults = GROUPS.every((group) =>
    group.fields.every(
      (field) => (data.weights[group.key] as Record<string, number>)[field.key] === (data.defaults[group.key] as Record<string, number>)[field.key],
    ),
  );

  // Identifies the field values, so a failed save's message stays until they change.
  const signature = JSON.stringify(texts);
  const shown = saver.view(signature);

  function buildBody(): ScoreWeightGroups {
    const body: Record<string, Record<string, number>> = {};
    for (const group of GROUPS) {
      body[group.key] = {};
      for (const field of group.fields) body[group.key][field.key] = checks[textKey(group.key, field.key)].value as number;
    }
    return body as unknown as ScoreWeightGroups;
  }

  function confirm() {
    const action = confirming;
    if (action === null || (action === "save" && invalid)) return;
    setConfirming(null);
    void saver.run(async () => {
      if (action === "save") await apiPut<ScoreWeightsOut>("/config/score-weights", buildBody());
      else await apiPost<ScoreWeightsOut>("/config/score-weights/reset");
      // The step endpoints already answer with the new weights, and the recompute has started: pick up both now.
      await refreshScoreWeights();
      await revalidateScores();
    }, signature);
  }

  const locked = running; // one recompute at a time: nothing here can be saved while one runs

  return (
    <SettingsSection
      title="Score weighting"
      intro="Sets how much each check counts in a ticker's Overall Assessment, and how much each part counts inside each check. The weights are whole numbers and apply to all tickers. The four automated checks add up to 100% and give the Fundamentals score; the Economic moat multiplier (Settings > Economic moat) is then applied to it."
    >
      <RecomputeStatusLine />

      <SettingsGroup title="Overall weights">
        {GROUPS[0].fields.map((field) => (
          <NumberSettingRow
            key={field.key}
            id={fieldId("overall", field.key)}
            label={field.label}
            hint={field.hint}
            unit="%"
            rules={rulesFor("overall", field.key)}
            value={texts[textKey("overall", field.key)]}
            onChange={(value) => setTexts((prev) => ({ ...prev, [textKey("overall", field.key)]: value }))}
            disabled={locked}
          />
        ))}
        <SumCaption sum={sums[0]} />
      </SettingsGroup>

      {GROUPS.slice(1).map((group, index) => (
        <SettingsGroup key={group.key} title={group.title}>
          {group.fields.map((field) => (
            <NumberSettingRow
              key={field.key}
              id={fieldId(group.key, field.key)}
              label={field.label}
              hint={field.hint}
              unit="%"
              rules={rulesFor(group.key, field.key)}
              value={texts[textKey(group.key, field.key)]}
              onChange={(value) => setTexts((prev) => ({ ...prev, [textKey(group.key, field.key)]: value }))}
              disabled={locked}
            />
          ))}
          <SumCaption sum={sums[index + 1]} />
          {orderMessages[group.key] && (
            <p role="alert" data-testid="weight-order" className="pb-2 text-xs text-negative">
              {orderMessages[group.key]}
            </p>
          )}
        </SettingsGroup>
      ))}

      <div className="mt-6 max-w-xl space-y-1 text-xs text-text-tertiary">
        <p>A weight of 0 means the part is not counted in the score, but missing data can still affect the check.</p>
        <p>
          Banks, Insurance, Utilities and REITs use fewer parts, so the Financials and Profitability weights apply only to the
          checks that exist for them; the rest share the weight in proportion.
        </p>
        <p>
          Debt has no hard fail: a ratio in breach scores 0 (or close to it) and the weights decide the rest. Debt/EBITDA must be the
          largest Debt weight and Current ratio the smallest, so a breach cannot be averaged away. Banks and REITs keep their hard
          limits.
        </p>
        <p>Applies to all tickers. Saving recomputes all scores (about a minute).</p>
      </div>

      {confirming && (
        <div className="mt-6 max-w-xl space-y-3 rounded-md border border-warn/40 bg-warn/10 p-4" role="alertdialog" aria-label="Confirm score weighting change">
          <p className="text-sm text-warn">
            {confirming === "save"
              ? "Save these weights? This recomputes the scores of all tracked tickers (about a minute) and changes their Overall scores."
              : "Reset every weight to its default? This recomputes the scores of all tracked tickers (about a minute) and changes their Overall scores."}
          </p>
          <div className="flex items-center gap-3">
            {/* The one primary of the panel, in the warn fill: confirming changes every ticker's score. */}
            <Button variant="primary" className="bg-warn hover:bg-warn/80" onClick={confirm}>
              Confirm
            </Button>
            <Button variant="outline" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      <SettingsFooter
        onSave={() => setConfirming("save")}
        status={locked ? "idle" : shown.status}
        invalid={invalid}
        unchanged={unchanged || locked}
        message={shown.detail}
        updatedAt={data.updated_at}
        secondary={
          <Button variant="outline" onClick={() => setConfirming("reset")} disabled={locked || atDefaults || saver.status === "saving"}>
            Reset to defaults
          </Button>
        }
      />
      {run?.state === "running" && <p className="sr-only">A recompute is running; the weights cannot be changed until it finishes.</p>}
    </SettingsSection>
  );
}

function SumCaption({ sum }: { sum: { sum: number | null; needs: number; ok: boolean } }) {
  const text = sum.ok
    ? `Sum ${sum.needs} of ${sum.needs}`
    : sum.sum === null
      ? `Sum unknown, needs ${sum.needs}`
      : `Sum ${sum.sum}, needs ${sum.needs}`;
  return (
    <p aria-live="polite" data-testid="weight-sum" className={sum.ok ? "py-2 text-xs text-text-tertiary" : "py-2 text-xs text-negative"}>
      {text}
    </p>
  );
}

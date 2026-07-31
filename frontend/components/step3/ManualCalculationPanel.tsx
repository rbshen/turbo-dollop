"use client";

import { CaretDown } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import useSWRMutation from "swr/mutation";

import {
  FIELD_LABEL_CELL_CLASS,
  FIELD_ROW_CLASS,
  FIELD_VALUE_CELL_CLASS,
  METHOD_LABELS,
  PBBandsTable,
  SECTION_HEADING_CLASS,
  pctText,
} from "@/components/step3/Step3Card";
import { ValuationGauge } from "@/components/step3/ValuationGauge";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { apiPost } from "@/lib/api/client";
import { fmtMoney, fmtNumber, fmtPct } from "@/lib/format";
import type { Step3CurrentValueCandidates, Step3ManualOut, Step3ManualRequest, Step3Method, Step3Out } from "@/lib/api/types";

interface Props {
  ticker: string;
  autoData: Step3Out;
}

const METHOD_OPTIONS: Exclude<Step3Method, "PASS">[] = ["DCF", "DFCF", "DNI", "DNI_NORMALIZED", "PRICE_TO_BOOK", "PSG"];

// Presentation-only mirror of step3_data.py's own current_value_labels dict
// -- Manual Calculation picks its "Current Value" label/default purely from
// the method the user selects here, independent of whichever method Auto
// picked for this ticker.
const CURRENT_VALUE_LABELS: Record<string, string> = {
  DCF: "Operating Cash Flow (Current)",
  DFCF: "Free Cash Flow (Current)",
  DNI: "Net Income (Current)",
  DNI_NORMALIZED: "Net Income (Smoothed, 5yr avg)",
};

// Generous, not data-derived -- growth/discount rate sliders must never
// clamp a real ticker's auto-derived starting value out of reach. 0.1-point
// steps match the 1-decimal precision the value readout already shows.
const GROWTH_SLIDER = { min: -50, max: 100, step: 0.1 };
const DISCOUNT_RATE_SLIDER = { min: 0, max: 30, step: 0.1 };

function candidateForMethod(method: Step3Method, candidates: Step3CurrentValueCandidates): number | null {
  switch (method) {
    case "DCF":
      return candidates.cfo_ttm;
    case "DFCF":
      return candidates.fcf_ttm;
    case "DNI":
      return candidates.net_income_ttm;
    case "DNI_NORMALIZED":
      return candidates.net_income_smoothed;
    default:
      return null;
  }
}

interface FormState {
  currentValue: string;
  growthYr15: string;
  growthYr610: string;
  growthYr1120: string;
  discountRate: string;
  sharesOutstanding: string;
  totalDebt: string;
  cashAndSt: string;
  bookValuePerShare: string;
  pbMeanRatio: string;
  pbSdRatio: string;
  salesPerShare: string;
  projectedGrowthRate: string;
  fairPsgRatio: string;
}

function toPlainText(n: number | null): string {
  return n == null ? "" : String(n);
}

function toPctText(n: number | null): string {
  return n == null ? "" : String(n * 100);
}

function toMillionsText(n: number | null): string {
  return n == null ? "" : String(n / 1_000_000);
}

function parseNum(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const n = parseFloat(trimmed);
  return Number.isNaN(n) ? null : n;
}

function parsePct(text: string): number | null {
  const n = parseNum(text);
  return n == null ? null : n / 100;
}

function parseMillions(text: string): number | null {
  const n = parseNum(text);
  return n == null ? null : n * 1_000_000;
}

// Pre-fills every field from the ticker's live Auto Calculation data --
// switching methods re-derives from this same static snapshot rather than
// refetching, and discards whatever was typed for the previously-selected
// method (simplest mental model: each method switch starts from a fresh,
// real baseline for that method).
function defaultsForMethod(method: Step3Method, autoData: Step3Out): FormState {
  return {
    currentValue: toMillionsText(candidateForMethod(method, autoData.inputs.current_value_candidates)),
    growthYr15: toPctText(autoData.inputs.growth_yr_1_5),
    growthYr610: toPctText(autoData.inputs.growth_yr_6_10),
    growthYr1120: toPctText(autoData.inputs.growth_yr_11_20),
    discountRate: toPctText(autoData.inputs.discount_rate),
    // Shares Outstanding is entered in millions here (like Total Debt/Cash),
    // not a raw share count -- see FieldKind "sharesMillions" below.
    sharesOutstanding: toMillionsText(autoData.inputs.shares_outstanding),
    totalDebt: toMillionsText(autoData.inputs.total_debt),
    cashAndSt: toMillionsText(autoData.inputs.cash_and_st_investments),
    bookValuePerShare: toPlainText(autoData.inputs.book_value_per_share),
    pbMeanRatio: toPlainText(autoData.inputs.pb_mean_ratio),
    pbSdRatio: toPlainText(autoData.inputs.pb_sd_ratio),
    salesPerShare: toPlainText(autoData.inputs.sales_per_share),
    projectedGrowthRate: toPctText(autoData.inputs.projected_growth_rate),
    fairPsgRatio: toPlainText(autoData.inputs.fair_psg_ratio),
  };
}

function buildRequest(method: Step3Method, form: FormState, lastClose: number | null): Step3ManualRequest {
  return {
    method,
    current_value: parseMillions(form.currentValue),
    growth_yr_1_5: parsePct(form.growthYr15),
    growth_yr_6_10: parsePct(form.growthYr610),
    growth_yr_11_20: parsePct(form.growthYr1120),
    discount_rate: parsePct(form.discountRate),
    shares_outstanding: parseMillions(form.sharesOutstanding),
    total_debt: parseMillions(form.totalDebt),
    cash_and_st_investments: parseMillions(form.cashAndSt),
    book_value_per_share: parseNum(form.bookValuePerShare),
    pb_mean_ratio: parseNum(form.pbMeanRatio),
    pb_sd_ratio: parseNum(form.pbSdRatio),
    sales_per_share: parseNum(form.salesPerShare),
    projected_growth_rate: parsePct(form.projectedGrowthRate),
    fair_psg_ratio: parseNum(form.fairPsgRatio),
    last_close: lastClose,
  };
}

// swr/mutation, not a raw useEffect+setState -- the mount-time "recompute
// on initial method" call below goes through this hook's own `trigger`
// (opaque to our component), not a same-component setState call, which
// keeps effect-triggered async state updates inside the same async-state
// abstraction (useSWR) already used everywhere else in this app (see
// useStep3) instead of a bespoke loading/error/result useState trio.
async function manualCalcFetcher(path: string, { arg }: { arg: Step3ManualRequest }): Promise<Step3ManualOut> {
  return apiPost<Step3ManualOut>(path, arg);
}

// What each field's *stored* string already represents, so it can be shown
// the same way Auto Calculation's read-only rows show the equivalent value
// -- "pct"/"millions" strings are already scaled (percentage points /
// millions) by toPctText/toMillionsText above, so formatting is just a
// straight fmtPct/fmtMoney call, no further scaling.
type FieldKind = "plain" | "pct" | "millions" | "currency" | "sharesMillions" | "ratio";

function formatDisplay(kind: FieldKind, raw: string): string {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  const n = parseFloat(trimmed);
  if (Number.isNaN(n)) return raw;
  switch (kind) {
    case "pct":
      return fmtPct(n, 1);
    case "millions":
    case "currency":
      return fmtMoney(n);
    case "sharesMillions":
      return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    case "ratio":
      return fmtNumber(n, 2);
    default:
      return raw;
  }
}

// Native type="number" inputs can't render "$48,253.00"/"+14.6%"-style
// formatting at all (browsers reject non-numeric-parseable content), so
// this is a plain text input that shows the formatted string while
// unfocused and the raw editable number while focused/being typed --
// standard "format on blur" pattern. The raw string in parent form state
// is unchanged either way; only this row's own render output differs.
function ManualInputRow({
  label,
  sublabel,
  value,
  onChange,
  kind = "plain",
}: {
  label: string;
  sublabel?: string;
  value: string;
  onChange: (v: string) => void;
  kind?: FieldKind;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <TableRow className={FIELD_ROW_CLASS}>
      <TableCell className={FIELD_LABEL_CELL_CLASS}>
        <div className="text-sm">{label}</div>
        {/* Always rendered, matching InputRow -- a blank placeholder line
            keeps every row's label cell (and therefore the row) identically
            tall, whether or not this particular field has a real sub-note. */}
        <div className="truncate text-[10px] text-text-tertiary">{sublabel || " "}</div>
      </TableCell>
      {/* Reuses InputRow's exact FIELD_VALUE_CELL_CLASS (not a local
          align-top/padding copy) so this row's vertical alignment can never
          drift from Auto Calculation's read-only rows again -- one shared
          template for both "value is plain text" and "value is an input
          box". */}
      <TableCell className={FIELD_VALUE_CELL_CLASS}>
        <input
          type="text"
          inputMode="decimal"
          value={focused ? value : formatDisplay(kind, value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-border-input bg-page px-2 py-1 text-right font-mono text-sm text-text-primary focus:border-brand focus:outline-none"
        />
      </TableCell>
    </TableRow>
  );
}

// Live slider for Growth Yr 1-5/6-10/11-20 and Discount Rate -- percentage
// value + label on one row, sublabel below, full-width native range input
// below that (updates live on every drag tick via onChange, matching the
// design handoff's interaction spec).
function SliderField({
  label,
  sublabel,
  value,
  onChange,
  min,
  max,
  step,
}: {
  label: string;
  sublabel?: string;
  value: string;
  onChange: (v: string) => void;
  min: number;
  max: number;
  step: number;
}) {
  const n = parseFloat(value);
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-text-secondary">{label}</span>
        <span className="font-mono text-sm font-semibold text-text-primary">{Number.isNaN(n) ? "—" : fmtPct(n, 1)}</span>
      </div>
      {sublabel && <div className="text-[10px] text-text-tertiary">{sublabel}</div>}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={Number.isNaN(n) ? 0 : n}
        onChange={(e) => onChange(e.target.value)}
        className="range-slider"
      />
    </div>
  );
}

export function ManualCalculationPanel({ ticker, autoData }: Props) {
  const initialMethod: Step3Method = autoData.selected_method === "PASS" ? "DCF" : autoData.selected_method;
  const [method, setMethod] = useState<Step3Method>(initialMethod);
  const [form, setForm] = useState<FormState>(() => defaultsForMethod(initialMethod, autoData));

  const { trigger, reset, data: result, error: mutationError, isMutating: loading } = useSWRMutation(`/tickers/${ticker}/step3/manual`, manualCalcFetcher, { throwOnError: false });

  function runCalculate(runMethod: Step3Method, values: FormState) {
    void trigger(buildRequest(runMethod, values, autoData.inputs.last_close));
  }

  useEffect(() => {
    runCalculate(initialMethod, form);
    // Run once on mount, using the initial method/defaults -- `trigger` is
    // swr/mutation's own stable function reference, not component state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleMethodChange(next: Step3Method) {
    const defaults = defaultsForMethod(next, autoData);
    setMethod(next);
    setForm(defaults);
    // Clear the previous method's result immediately -- otherwise
    // useSWRMutation keeps showing its last resolved `data` (the old
    // method's numbers) under the new method's label/rows until the new
    // POST resolves.
    reset();
    runCalculate(next, defaults);
  }

  // Every field recomputes live -- on every slider drag tick and every
  // text-field keystroke, per the design handoff's interaction spec. The
  // Calculate button below is no longer required for this; it's kept for
  // a future "override the valuation" use, not today's recompute.
  function updateField(key: keyof FormState, value: string) {
    const next = { ...form, [key]: value };
    setForm(next);
    runCalculate(method, next);
  }

  function field(key: keyof FormState) {
    return (v: string) => updateField(key, v);
  }

  const isTwentyYearMethod = method === "DCF" || method === "DFCF" || method === "DNI" || method === "DNI_NORMALIZED";
  const isPB = method === "PRICE_TO_BOOK";
  const isPSG = method === "PSG";

  return (
    <div className="space-y-6 rounded-lg border border-border-card bg-surface p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className={SECTION_HEADING_CLASS}>Custom Valuation</h2>
        {/* appearance-none strips the browser's native <select> chrome --
            CaretDown restores the dropdown affordance manually. Compact and
            right-aligned inline with the title, not a full-width field
            below it with its own "Method" label. */}
        <div className="relative">
          <select
            id="manual-method"
            value={method}
            onChange={(e) => handleMethodChange(e.target.value as Step3Method)}
            className="h-8 max-w-[220px] appearance-none truncate rounded-md border border-border-input bg-surface-2 py-1 pl-2.5 pr-7 text-xs text-text-primary focus:border-brand focus:outline-none"
          >
            {METHOD_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {METHOD_LABELS[m]}
              </option>
            ))}
          </select>
          <CaretDown size={12} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary" />
        </div>
      </div>

      <ValuationGauge
        discountPremiumPct={result?.discount_premium_pct ?? null}
        intrinsicValuePerShare={result?.intrinsic_value_per_share ?? null}
        lastClose={autoData.inputs.last_close}
      />

      <div className="flex items-center justify-between text-sm">
        <span className="text-text-tertiary">Discount/Premium</span>
        <span className="font-mono text-text-primary">{pctText(result?.discount_premium_pct ?? null)}</span>
      </div>

      {isTwentyYearMethod && (
        <div className="space-y-5">
          <SliderField
            label="Growth Yr 1-5"
            sublabel={autoData.inputs.growth_yr_1_5_source ?? "% per year"}
            value={form.growthYr15}
            onChange={field("growthYr15")}
            {...GROWTH_SLIDER}
          />
          <SliderField label="Growth Yr 6-10" value={form.growthYr610} onChange={field("growthYr610")} {...GROWTH_SLIDER} />
          <SliderField label="Growth Yr 11-20 (terminal)" value={form.growthYr1120} onChange={field("growthYr1120")} {...GROWTH_SLIDER} />
          <SliderField label="Discount Rate (CAPM)" value={form.discountRate} onChange={field("discountRate")} {...DISCOUNT_RATE_SLIDER} />
        </div>
      )}

      <Table className="text-sm">
        <TableBody>
          {isTwentyYearMethod && (
            <>
              <ManualInputRow label={CURRENT_VALUE_LABELS[method]} sublabel="(in millions)" value={form.currentValue} onChange={field("currentValue")} kind="millions" />
              <ManualInputRow
                label="Shares Outstanding"
                sublabel="(in millions)"
                value={form.sharesOutstanding}
                onChange={field("sharesOutstanding")}
                kind="sharesMillions"
              />
              <ManualInputRow label="Total Debt" sublabel="(in millions)" value={form.totalDebt} onChange={field("totalDebt")} kind="millions" />
              <ManualInputRow
                label={`Cash${autoData.inputs.cash_and_st_investments_includes_short_term_investments ? " + ST Investments" : ""}`}
                sublabel="(in millions)"
                value={form.cashAndSt}
                onChange={field("cashAndSt")}
                kind="millions"
              />
            </>
          )}

          {isPB && (
            <>
              <ManualInputRow label="Book Value Per Share" value={form.bookValuePerShare} onChange={field("bookValuePerShare")} kind="currency" />
              <ManualInputRow label="Mean P/B" value={form.pbMeanRatio} onChange={field("pbMeanRatio")} kind="ratio" />
              <ManualInputRow label="SD P/B" value={form.pbSdRatio} onChange={field("pbSdRatio")} kind="ratio" />
            </>
          )}

          {isPSG && (
            <>
              <ManualInputRow label="Sales Per Share" value={form.salesPerShare} onChange={field("salesPerShare")} kind="currency" />
              <ManualInputRow label="Projected Growth Rate" value={form.projectedGrowthRate} onChange={field("projectedGrowthRate")} kind="pct" />
              <ManualInputRow label="Fair PSG Ratio" value={form.fairPsgRatio} onChange={field("fairPsgRatio")} kind="ratio" />
            </>
          )}
        </TableBody>
      </Table>

      {isPB && result?.pb_bands && <PBBandsTable bands={result.pb_bands} lastClose={autoData.inputs.last_close} />}

      <button
        type="button"
        onClick={() => runCalculate(method, form)}
        disabled={loading}
        className="rounded-md border border-border-input bg-surface-2 px-4 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:border-brand hover:text-text-primary disabled:opacity-50"
      >
        {loading ? "Calculating…" : "Calculate"}
      </button>

      {mutationError && <p className="text-sm text-negative">{mutationError instanceof Error ? mutationError.message : "Calculation failed"}</p>}
      {result?.error && <p className="text-sm text-warn">{result.error}</p>}
    </div>
  );
}

"use client";

import { CaretDown } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import useSWRMutation from "swr/mutation";

import {
  FIELD_LABEL_CELL_CLASS,
  FIELD_ROW_CLASS,
  FIELD_VALUE_CELL_CLASS,
  InputRow,
  METHOD_FIELD_CLASS,
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
    sharesOutstanding: toPlainText(autoData.inputs.shares_outstanding),
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
    shares_outstanding: parseNum(form.sharesOutstanding),
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
type FieldKind = "plain" | "pct" | "millions" | "currency" | "shares" | "ratio";

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
    case "shares":
      return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
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
        <div className="truncate text-[10px] text-zinc-600">{sublabel || " "}</div>
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
          className="w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-right font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
        />
      </TableCell>
    </TableRow>
  );
}

export function ManualCalculationPanel({ ticker, autoData }: Props) {
  const initialMethod: Step3Method = autoData.selected_method === "PASS" ? "DCF" : autoData.selected_method;
  const [method, setMethod] = useState<Step3Method>(initialMethod);
  const [form, setForm] = useState<FormState>(() => defaultsForMethod(initialMethod, autoData));

  const { trigger, data: result, error: mutationError, isMutating: loading } = useSWRMutation(`/tickers/${ticker}/step3/manual`, manualCalcFetcher, { throwOnError: false });

  // Intrinsic Value/Gauge/Discount-Premium are not live on every keystroke
  // -- they only refresh when the method changes or "Calculate" is clicked.
  // Selecting a method still recomputes immediately (using that method's
  // freshly-derived defaults) so the panel reads as a live parallel to Auto
  // Calculation until the user starts overriding fields themselves.
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
    runCalculate(next, defaults);
  }

  function field(key: keyof FormState) {
    return (v: string) => setForm((prev) => ({ ...prev, [key]: v }));
  }

  const isTwentyYearMethod = method === "DCF" || method === "DFCF" || method === "DNI" || method === "DNI_NORMALIZED";
  const isPB = method === "PRICE_TO_BOOK";
  const isPSG = method === "PSG";

  return (
    <div className="space-y-6">
      <h2 className={SECTION_HEADING_CLASS}>Manual Calculation</h2>

      <div>
        <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="manual-method">
          Method
        </label>
        {/* appearance-none strips the browser's native <select> chrome --
            without it, a <select> renders at a slightly different height
            than a <p> even with identical padding/border classes, which is
            what threw off row alignment against Auto Calculation's Method
            box. CaretDown restores the dropdown affordance manually. */}
        <div className="relative mt-1">
          <select
            id="manual-method"
            value={method}
            onChange={(e) => handleMethodChange(e.target.value as Step3Method)}
            className={`${METHOD_FIELD_CLASS} appearance-none pr-7 focus:border-zinc-500 focus:outline-none`}
          >
            {METHOD_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {METHOD_LABELS[m]}
              </option>
            ))}
          </select>
          <CaretDown size={14} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500" />
        </div>
      </div>

      <div className="space-y-1">
        <p className="text-xs uppercase tracking-widest text-zinc-500">Intrinsic Value {isPB && "(Mean)"}</p>
        <p className="font-mono text-3xl font-bold tabular-nums text-zinc-100">
          {result?.intrinsic_value_per_share != null ? fmtMoney(result.intrinsic_value_per_share) : "—"}
        </p>
      </div>

      <div className="space-y-1">
        <p className="text-xs uppercase tracking-widest text-zinc-500">Last Close</p>
        <p className="font-mono text-lg text-zinc-200">{autoData.inputs.last_close != null ? fmtMoney(autoData.inputs.last_close) : "—"}</p>
      </div>

      <ValuationGauge
        discountPremiumPct={result?.discount_premium_pct ?? null}
        intrinsicValuePerShare={result?.intrinsic_value_per_share ?? null}
        lastClose={autoData.inputs.last_close}
      />

      {/* Discount/Premium shares this table with the growth rows -- not a
          separate <Table> -- so it doesn't pick up the parent's space-y-6
          gap that a second Table would introduce here. That extra 24px
          gap (present only in Manual, only above Growth Yr 1-5, since Auto
          groups Discount/Premium + growth rows in one table too) was the
          actual cause of the row misalignment cascading downward -- not a
          vertical-align issue within any single row. */}
      <Table className="text-sm">
        <TableBody>
          {/* pr-2 -- not present on Auto's copy of this same row -- offsets
              this value to match the ~8px inset every ManualInputRow's
              bordered input has from its own px-2 padding. Without it, this
              one plain-text value (no input box) sits flush at the cell's
              right edge, visibly right of every input-box value below it. */}
          <InputRow label="Discount/Premium" value={<span className="pr-2">{pctText(result?.discount_premium_pct ?? null)}</span>} />
          {isTwentyYearMethod && (
            <>
              <ManualInputRow label="Growth Yr 1-5" sublabel="% per year" value={form.growthYr15} onChange={field("growthYr15")} kind="pct" />
              <ManualInputRow label="Growth Yr 6-10" value={form.growthYr610} onChange={field("growthYr610")} kind="pct" />
              <ManualInputRow label="Growth Yr 11-20 (terminal)" value={form.growthYr1120} onChange={field("growthYr1120")} kind="pct" />
              <ManualInputRow label={CURRENT_VALUE_LABELS[method]} sublabel="(in millions)" value={form.currentValue} onChange={field("currentValue")} kind="millions" />
              <ManualInputRow label="Discount Rate (CAPM)" value={form.discountRate} onChange={field("discountRate")} kind="pct" />
              <ManualInputRow label="Shares Outstanding" value={form.sharesOutstanding} onChange={field("sharesOutstanding")} kind="shares" />
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
        className="rounded-md border border-zinc-700 bg-zinc-800/60 px-4 py-1.5 text-sm font-medium text-zinc-200 transition-colors hover:border-zinc-500 hover:text-zinc-100 disabled:opacity-50"
      >
        {loading ? "Calculating…" : "Calculate"}
      </button>

      {mutationError && <p className="text-sm text-red-400">{mutationError instanceof Error ? mutationError.message : "Calculation failed"}</p>}
      {result?.error && <p className="text-sm text-amber-400">{result.error}</p>}
    </div>
  );
}

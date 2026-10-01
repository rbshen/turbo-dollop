"use client";

import { useEffect, useId, useState, type CSSProperties } from "react";
import { mutate } from "swr";
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
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FIELD_ERROR_CLASS, FieldProvider, useFieldContextValue } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/Select";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { apiDelete, apiPost, apiPut, errorDetail } from "@/lib/api/client";
import { fmtMoney, fmtNumber, fmtPct } from "@/lib/format";
import { useTickerCustomValuation } from "@/lib/hooks/useTickerCustomValuation";
import { isIncompleteNumberPrefix } from "@/lib/numberInput";
import { cn } from "@/lib/utils";
import type {
  Step3CurrentValueCandidates,
  Step3ManualOut,
  Step3ManualParams,
  Step3ManualRequest,
  Step3Method,
  Step3Out,
  TickerCustomValuationIn,
  TickerCustomValuationOut,
} from "@/lib/api/types";

interface Props {
  ticker: string;
  autoData: Step3Out;
}

const METHOD_OPTIONS: Exclude<Step3Method, "PASS">[] = [
  "DCF",
  "DFCF",
  "DNI",
  "DNI_NORMALIZED",
  "CF_NORMALIZED",
  "FCF_NORMALIZED",
  "PRICE_TO_BOOK_STANDARD",
  "PRICE_TO_BOOK",
  "PSG",
];

// The dropdown's own selectable values: the 6 plain methods (always live,
// editable-from-Auto-defaults, as before) plus one extra entry --
// "SAVED_CUSTOM" -- that only exists once a custom valuation has been
// saved, labeled after whichever method it was saved under (e.g.
// "Discounted Free Cash Flow · Custom"). There's exactly one saved row per
// ticker (no versioning), so there's exactly one such entry, never more.
type MethodSelection = Step3Method | "SAVED_CUSTOM";

// "SAVED_CUSTOM" is only ever a reachable selection when saved.saved is
// true (the option itself isn't rendered otherwise), so savedMethod is
// never actually null when this branch runs -- the DCF fallback is
// unreachable in practice, just satisfying the type.
function realMethodFor(selection: MethodSelection, savedMethod: Step3Method | null): Step3Method {
  return selection === "SAVED_CUSTOM" ? (savedMethod ?? "DCF") : selection;
}

// Display-only sentence case for a METHOD_LABELS entry ("Discounted Cash Flow
// (Operating CF)" -> "Discounted cash flow (operating CF)"): later Title-case
// words drop to lower case, acronyms ("CF") and the first word are left alone.
// METHOD_LABELS itself (Step3Card's, also used by the Model Valuation title) is
// not edited here, and the option values never change.
function methodOptionLabel(method: string): string {
  return (METHOD_LABELS[method] ?? method)
    .split(" ")
    .map((word, i) => (i > 0 && /^\(?[A-Z][a-z]+\)?$/.test(word) ? word.toLowerCase() : word))
    .join(" ");
}

// Presentation-only mirror of step3_data.py's own current_value_labels dict
// -- Manual Calculation picks its "Current Value" label/default purely from
// the method the user selects here, independent of whichever method Auto
// picked for this ticker.
const CURRENT_VALUE_LABELS: Record<string, string> = {
  DCF: "Operating cash flow (current)",
  DFCF: "Free cash flow (current)",
  DNI: "Net income (current)",
  DNI_NORMALIZED: "Net income (smoothed, 5yr avg)",
  CF_NORMALIZED: "Operating cash flow (smoothed, 5yr avg)",
  FCF_NORMALIZED: "Free cash flow (smoothed, 5yr avg)",
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
    case "CF_NORMALIZED":
      return candidates.cfo_smoothed;
    case "FCF_NORMALIZED":
      return candidates.fcf_smoothed;
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
  bookValuePerShareStandard: string;
  pbMeanRatioStandard: string;
  pbSdRatioStandard: string;
  salesPerShare: string;
  projectedGrowthRate: string;
  fairPsgRatio: string;
}

function toPlainText(n: number | null | undefined): string {
  return n == null ? "" : String(n);
}

function toPctText(n: number | null | undefined): string {
  return n == null ? "" : String(n * 100);
}

function toMillionsText(n: number | null | undefined): string {
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
    bookValuePerShareStandard: toPlainText(autoData.inputs.book_value_per_share_standard),
    pbMeanRatioStandard: toPlainText(autoData.inputs.pb_mean_ratio_standard),
    pbSdRatioStandard: toPlainText(autoData.inputs.pb_sd_ratio_standard),
    salesPerShare: toPlainText(autoData.inputs.sales_per_share),
    projectedGrowthRate: toPctText(autoData.inputs.projected_growth_rate),
    fairPsgRatio: toPlainText(autoData.inputs.fair_psg_ratio),
  };
}

// Pre-fills every field from a previously-saved custom valuation instead of
// Auto's own numbers -- used on first mount whenever one exists, active or
// not (a saved-but-inactive valuation's inputs are still what the user last
// typed, and should still greet them on return).
function defaultsFromSaved(saved: TickerCustomValuationOut): FormState {
  return {
    currentValue: toMillionsText(saved.current_value),
    growthYr15: toPctText(saved.growth_yr_1_5),
    growthYr610: toPctText(saved.growth_yr_6_10),
    growthYr1120: toPctText(saved.growth_yr_11_20),
    discountRate: toPctText(saved.discount_rate),
    sharesOutstanding: toMillionsText(saved.shares_outstanding),
    totalDebt: toMillionsText(saved.total_debt),
    cashAndSt: toMillionsText(saved.cash_and_st_investments),
    bookValuePerShare: toPlainText(saved.book_value_per_share),
    pbMeanRatio: toPlainText(saved.pb_mean_ratio),
    pbSdRatio: toPlainText(saved.pb_sd_ratio),
    bookValuePerShareStandard: toPlainText(saved.book_value_per_share_standard),
    pbMeanRatioStandard: toPlainText(saved.pb_mean_ratio_standard),
    pbSdRatioStandard: toPlainText(saved.pb_sd_ratio_standard),
    salesPerShare: toPlainText(saved.sales_per_share),
    projectedGrowthRate: toPctText(saved.projected_growth_rate),
    fairPsgRatio: toPlainText(saved.fair_psg_ratio),
  };
}

function buildParams(form: FormState): Step3ManualParams {
  return {
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
    book_value_per_share_standard: parseNum(form.bookValuePerShareStandard),
    pb_mean_ratio_standard: parseNum(form.pbMeanRatioStandard),
    pb_sd_ratio_standard: parseNum(form.pbSdRatioStandard),
    sales_per_share: parseNum(form.salesPerShare),
    projected_growth_rate: parsePct(form.projectedGrowthRate),
    fair_psg_ratio: parseNum(form.fairPsgRatio),
  };
}

function buildRequest(method: Step3Method, form: FormState, lastClose: number | null): Step3ManualRequest {
  return { method, ...buildParams(form), last_close: lastClose };
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

function formatDisplay(kind: FieldKind, raw: string, currency: string = "USD"): string {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  const n = parseFloat(trimmed);
  if (Number.isNaN(n)) return raw;
  switch (kind) {
    case "pct":
      return fmtPct(n, 1);
    case "millions":
    case "currency":
      return fmtMoney(n, currency);
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
//
// Not a NumberField: that holds the raw text only (no format-on-blur) and
// rejects what parseFloat reads ("12abc", "1e3", "+4"), so converting would
// change what the row shows or what it sends. The kit Input is wired the way a
// FormField wires a control (a real <label for>, the sublabel as its linked
// hint, an inline error) -- the table row keeps the label and the box in
// their two cells, which FormField's stacked layout cannot do.
//
// The error is for text the parse above reads as nothing at all (parseNum ->
// null, which is also what gets sent): it never blocks, clamps or corrects.
// "-", "." and "-." are the start of a number, so they show no error while the
// box is still focused.
const UNREADABLE_NUMBER_MESSAGE = "Enter a number.";

function ManualInputRow({
  label,
  sublabel,
  value,
  onChange,
  kind = "plain",
  currency = "USD",
}: {
  label: string;
  sublabel?: string;
  value: string;
  onChange: (v: string) => void;
  kind?: FieldKind;
  currency?: string;
}) {
  const [focused, setFocused] = useState(false);
  const id = useId();
  const unreadable = value.trim() !== "" && parseNum(value) === null && !(focused && isIncompleteNumberPrefix(value));
  const field = useFieldContextValue(id, { hint: sublabel, error: unreadable ? UNREADABLE_NUMBER_MESSAGE : undefined });
  return (
    <FieldProvider value={field}>
      <TableRow className={FIELD_ROW_CLASS}>
        <TableCell className={FIELD_LABEL_CELL_CLASS}>
          <label htmlFor={id} className="block text-sm">
            {label}
          </label>
          {/* Always rendered, matching InputRow -- a blank placeholder line
              keeps every row's label cell (and therefore the row) identically
              tall, whether or not this particular field has a real sub-note. */}
          <div id={field.hintId} className="truncate text-[10px] text-text-tertiary">
            {sublabel || " "}
          </div>
        </TableCell>
        {/* Reuses InputRow's exact FIELD_VALUE_CELL_CLASS (not a local
            align-top/padding copy) so this row's vertical alignment can never
            drift from Auto Calculation's read-only rows again -- one shared
            template for both "value is plain text" and "value is an input
            box". The kit Input is 36px, so pt-3 + the box fills the row's
            h-12 exactly; only an error line makes a row taller. */}
        <TableCell className={FIELD_VALUE_CELL_CLASS}>
          <Input
            type="text"
            inputMode="decimal"
            size="full"
            value={focused ? value : formatDisplay(kind, value, currency)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onChange={(e) => onChange(e.target.value)}
            className="text-right font-mono tabular-nums"
          />
          {unreadable && (
            <p id={field.errorId} role="alert" className={cn(FIELD_ERROR_CLASS, "text-left font-sans")}>
              {UNREADABLE_NUMBER_MESSAGE}
            </p>
          )}
        </TableCell>
      </TableRow>
    </FieldProvider>
  );
}

// Live slider for growth yr 1-5/6-10/11-20 and discount rate -- percentage
// value + label on one row, sublabel below, full-width native range input
// below that (updates live on every drag tick via onChange, matching the
// design handoff's interaction spec).
//
// The label is a real <label for>, the sublabel is the input's description,
// and aria-valuetext carries the same text as the readout ("+14.6%") because
// the input's own value is the bare number (14.6). .range-slider:focus in
// globals.css removes the outline (and the global CSS is not edited here), so
// the focus ring is restored with utility classes -- they sit in a later
// cascade layer than that rule. Arrow/Home/End/Page keys are the browser's own:
// nothing here handles a key.
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
  const id = useId();
  const n = parseFloat(value);
  const clamped = Number.isNaN(n) ? min : Math.min(max, Math.max(min, n));
  const fillPct = ((clamped - min) / (max - min)) * 100;
  const sublabelId = `${id}-note`;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm text-text-secondary">
          {label}
        </label>
        <span className="font-mono text-sm font-semibold text-text-primary">{Number.isNaN(n) ? "—" : fmtPct(n, 1)}</span>
      </div>
      {sublabel && (
        <div id={sublabelId} className="text-[10px] text-text-tertiary">
          {sublabel}
        </div>
      )}
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={Number.isNaN(n) ? 0 : n}
        onChange={(e) => onChange(e.target.value)}
        aria-valuetext={Number.isNaN(n) ? "No value" : fmtPct(n, 1)}
        aria-describedby={sublabel ? sublabelId : undefined}
        className="range-slider focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        style={{ "--range-fill": `${fillPct}%` } as CSSProperties}
      />
    </div>
  );
}

// Every hook on the ticker page keys off "/tickers/{ticker}/..." -- one
// sweep refreshes this panel, the Model Valuation section, and the header
// pill together. Watchlist rows are keyed by watchlist id, not by ticker
// ("/watchlists/{id}/rows"), so they need their own separate sweep; the
// Screener list is a third, independent key. Same pattern as
// BankCapitalMetricsForm.tsx/EconomicMoatTab.tsx, extended to cover
// Watchlist since an activated custom valuation can now change what a
// Watchlist row shows too (see CLAUDE.md's Fork B scope decision).
async function revalidateEverywhere(ticker: string) {
  await mutate((key) => typeof key === "string" && key.startsWith(`/tickers/${ticker}`));
  await mutate((key) => typeof key === "string" && key.startsWith("/watchlists"));
  await mutate("/screener");
}

// client.ts's request() embeds the backend's own HTTPException detail after
// " - " (e.g. "PUT ... failed: 400 - Missing required inputs for PSG") --
// surface just that part when present, since it's genuinely actionable
// ("which field is missing"), not just "it failed".
function errorMessage(err: unknown, fallback: string): string {
  return errorDetail(err) ?? fallback;
}

export function ManualCalculationPanel({ ticker, autoData }: Props) {
  const { data: saved, error, isLoading } = useTickerCustomValuation(ticker);

  if (error) {
    return (
      <Card>
        <p className="text-sm text-negative">Couldn&apos;t load custom valuation — {error.message}</p>
      </Card>
    );
  }
  if (isLoading || !saved) {
    return (
      <Card>
        <p className="text-sm text-text-tertiary animate-pulse">Loading…</p>
      </Card>
    );
  }
  // Keyed on ticker + saved_at -- saved_at only changes on a real Save (not
  // activate/deactivate/delete, which don't touch the stored parameters),
  // so the form only resets to the freshly-saved values exactly when they
  // actually changed. Including ticker guards against two different
  // tickers coincidentally sharing the same saved_at (or both "unset").
  return (
    <ManualCalculationControls
      key={`${ticker}-${saved.saved_at ?? "unset"}`}
      ticker={ticker}
      autoData={autoData}
      saved={saved}
    />
  );
}

function ManualCalculationControls({
  ticker,
  autoData,
  saved,
}: {
  ticker: string;
  autoData: Step3Out;
  saved: TickerCustomValuationOut;
}) {
  const initialSelection: MethodSelection =
    saved.saved && saved.method ? "SAVED_CUSTOM" : autoData.selected_method === "PASS" ? "DCF" : autoData.selected_method;
  const [selection, setSelection] = useState<MethodSelection>(initialSelection);
  // The real method behind whatever's selected -- "SAVED_CUSTOM" isn't
  // itself a Step3Method, it's this panel's own dropdown entry for "the one
  // saved row" (see MethodSelection's own comment), so every place that
  // needs an actual method (isTwentyYearMethod/isPB/isPSG below, the
  // preview POST, the Save request body) reads this instead of `selection`
  // directly.
  const method: Step3Method = realMethodFor(selection, saved.method);
  const [form, setForm] = useState<FormState>(() => (saved.saved ? defaultsFromSaved(saved) : defaultsForMethod(method, autoData)));
  const quoteCurrency = autoData.inputs.quote_currency ?? "USD";

  const { trigger, reset, data: result, error: mutationError } = useSWRMutation(`/tickers/${ticker}/step3/manual`, manualCalcFetcher, { throwOnError: false });

  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  function runCalculate(runMethod: Step3Method, values: FormState) {
    void trigger(buildRequest(runMethod, values, autoData.inputs.last_close));
  }

  useEffect(() => {
    runCalculate(method, form);
    // Run once on mount, using the initial selection/defaults -- `trigger`
    // is swr/mutation's own stable function reference, not component state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSelectionChange(next: MethodSelection) {
    setSelection(next);
    const defaults = next === "SAVED_CUSTOM" ? defaultsFromSaved(saved) : defaultsForMethod(next, autoData);
    setForm(defaults);
    // Clear the previous selection's result immediately -- otherwise
    // useSWRMutation keeps showing its last resolved `data` (the old
    // selection's numbers) under the new selection's label/rows until the
    // new POST resolves.
    reset();
    runCalculate(realMethodFor(next, saved.method), defaults);
  }

  // Every field recomputes live -- on every slider drag tick and every
  // text-field keystroke, per the design handoff's interaction spec.
  function updateField(key: keyof FormState, value: string) {
    const next = { ...form, [key]: value };
    setForm(next);
    runCalculate(method, next);
  }

  function field(key: keyof FormState) {
    return (v: string) => updateField(key, v);
  }

  async function runAction(action: () => Promise<unknown>, fallback: string) {
    setActionPending(true);
    setActionError(null);
    try {
      await action();
      await revalidateEverywhere(ticker);
      setConfirmingDelete(false);
    } catch (err) {
      setActionError(errorMessage(err, fallback));
    } finally {
      setActionPending(false);
    }
  }

  function handleSave() {
    const body: TickerCustomValuationIn = { method, ...buildParams(form) };
    void runAction(() => apiPut<TickerCustomValuationOut>(`/tickers/${ticker}/custom-valuation`, body), "Failed to save — please try again.");
  }

  function handleActivate() {
    void runAction(() => apiPost(`/tickers/${ticker}/custom-valuation/activate`), "Failed to activate — please try again.");
  }

  function handleDeactivate() {
    void runAction(() => apiPost(`/tickers/${ticker}/custom-valuation/deactivate`), "Failed to revert to auto — please try again.");
  }

  function handleDelete() {
    void runAction(() => apiDelete(`/tickers/${ticker}/custom-valuation`), "Failed to delete — please try again.");
  }

  const isTwentyYearMethod =
    method === "DCF" ||
    method === "DFCF" ||
    method === "DNI" ||
    method === "DNI_NORMALIZED" ||
    method === "CF_NORMALIZED" ||
    method === "FCF_NORMALIZED";
  const isPB = method === "PRICE_TO_BOOK" || method === "PRICE_TO_BOOK_STANDARD";
  const isPBStandard = method === "PRICE_TO_BOOK_STANDARD";
  const isPSG = method === "PSG";

  return (
    <Card className="space-y-6">
      <div className="flex min-h-8 flex-wrap items-center justify-between gap-3">
        <h2 className={SECTION_HEADING_CLASS}>Custom valuation</h2>
        {/* The kit native Select, with a visible "Method" label to its left.
            The kit field is 36px, taller than this title row's 32px (the
            Model Valuation card's title row is min-h-8 so the two columns
            align row for row), so the group takes -my-0.5 and the row keeps
            its height. wide (320px) fits the nine method labels; the saved
            entry ("<method> · custom") can be longer and clips when closed.
            Below the width where label and select fit together the label
            wraps above the select instead of overflowing. */}
        <div className="-my-0.5 flex max-w-full flex-wrap items-center gap-x-2">
          <label htmlFor="manual-method" className="text-xs text-text-secondary">
            Method
          </label>
          <Select id="manual-method" size="wide" value={selection} onChange={(e) => handleSelectionChange(e.target.value as MethodSelection)}>
            {/* Only rendered once a custom valuation is saved -- there's
                exactly one (no versioning), so at most one such entry. */}
            {saved.saved && saved.method && <option value="SAVED_CUSTOM">{methodOptionLabel(saved.method)} · custom</option>}
            {METHOD_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {methodOptionLabel(m)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <ValuationGauge
        discountPremiumPct={result?.discount_premium_pct ?? null}
        intrinsicValuePerShare={result?.intrinsic_value_per_share ?? null}
        lastClose={autoData.inputs.last_close}
        quoteCurrency={quoteCurrency}
        reportedCurrency={autoData.inputs.reported_currency}
        fxRate={autoData.inputs.fx_rate}
        fxRateAsOf={autoData.inputs.fx_rate_as_of}
      />

      <div className="flex items-center justify-between text-sm">
        <span className="text-text-tertiary">Discount/premium</span>
        <span className="font-mono text-text-primary">{pctText(result?.discount_premium_pct ?? null)}</span>
      </div>

      {isTwentyYearMethod && (
        <div className="space-y-5">
          <SliderField
            label="Growth yr 1-5"
            sublabel={autoData.inputs.growth_yr_1_5_source ?? "% per year"}
            value={form.growthYr15}
            onChange={field("growthYr15")}
            {...GROWTH_SLIDER}
          />
          <SliderField label="Growth yr 6-10" value={form.growthYr610} onChange={field("growthYr610")} {...GROWTH_SLIDER} />
          <SliderField label="Growth yr 11-20 (terminal)" value={form.growthYr1120} onChange={field("growthYr1120")} {...GROWTH_SLIDER} />
          <SliderField label="Discount rate (CAPM)" value={form.discountRate} onChange={field("discountRate")} {...DISCOUNT_RATE_SLIDER} />
        </div>
      )}

      <Table className="text-sm">
        <TableBody>
          {isTwentyYearMethod && (
            <>
              <ManualInputRow label={CURRENT_VALUE_LABELS[method]} sublabel="(in millions)" value={form.currentValue} onChange={field("currentValue")} kind="millions" currency={quoteCurrency} />
              <ManualInputRow
                label="Shares outstanding"
                sublabel="(in millions)"
                value={form.sharesOutstanding}
                onChange={field("sharesOutstanding")}
                kind="sharesMillions"
              />
              <ManualInputRow label="Total debt" sublabel="(in millions)" value={form.totalDebt} onChange={field("totalDebt")} kind="millions" currency={quoteCurrency} />
              <ManualInputRow
                label={`Cash${autoData.inputs.cash_and_st_investments_includes_short_term_investments ? " + ST investments" : ""}`}
                sublabel="(in millions)"
                value={form.cashAndSt}
                onChange={field("cashAndSt")}
                kind="millions"
                currency={quoteCurrency}
              />
            </>
          )}

          {isPB && (
            <>
              <ManualInputRow
                label={isPBStandard ? "Book value per share (standard)" : "Book value per share (custom)"}
                value={isPBStandard ? form.bookValuePerShareStandard : form.bookValuePerShare}
                onChange={field(isPBStandard ? "bookValuePerShareStandard" : "bookValuePerShare")}
                kind="currency"
                currency={quoteCurrency}
              />
              <ManualInputRow
                label="Mean P/B"
                value={isPBStandard ? form.pbMeanRatioStandard : form.pbMeanRatio}
                onChange={field(isPBStandard ? "pbMeanRatioStandard" : "pbMeanRatio")}
                kind="ratio"
              />
              <ManualInputRow
                label="SD P/B"
                value={isPBStandard ? form.pbSdRatioStandard : form.pbSdRatio}
                onChange={field(isPBStandard ? "pbSdRatioStandard" : "pbSdRatio")}
                kind="ratio"
              />
            </>
          )}

          {isPSG && (
            <>
              <ManualInputRow label="Sales per share" value={form.salesPerShare} onChange={field("salesPerShare")} kind="currency" currency={quoteCurrency} />
              <ManualInputRow label="Projected growth rate" value={form.projectedGrowthRate} onChange={field("projectedGrowthRate")} kind="pct" />
              <ManualInputRow label="Fair PSG ratio" value={form.fairPsgRatio} onChange={field("fairPsgRatio")} kind="ratio" />
            </>
          )}
        </TableBody>
      </Table>

      {isPB && result?.pb_bands && (
        <PBBandsTable bands={result.pb_bands} lastClose={autoData.inputs.last_close} currency={quoteCurrency} />
      )}

      {mutationError && <p className="text-sm text-negative">{mutationError instanceof Error ? mutationError.message : "Calculation failed"}</p>}
      {result?.error && <p className="text-sm text-warn">{result.error}</p>}

      {/* Status/action bar lives at the BOTTOM of this column, below every
          parameter row -- placing it under the title (as a first pass did)
          pushed this column's numbers down relative to Model Valuation's,
          breaking row-for-row alignment between the two cards. The left
          column has no equivalent bar interrupting its own flow, so this
          one shouldn't either. */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border-card bg-surface-2 px-3 py-2 text-xs">
        <span className="text-text-tertiary">
          Active:{" "}
          <span className="font-semibold text-text-primary">{saved.is_active ? "Custom" : "Auto"}</span>
          {saved.saved && saved.saved_at && <> — saved {new Date(saved.saved_at).toLocaleString()}</>}
        </span>
        {/* sm outline is 32px, like the RefreshButton/ExportMenu in a dense row;
            Save is the one primary (primary at sm is 28px, so h-8 matches
            the outline buttons beside it, as on AddToWatchlistButton).
            Activate and Delete keep their positive and negative tone as
            colour classes on the outline button. */}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" size="sm" className="h-8" onClick={handleSave} disabled={actionPending}>
            {actionPending ? "Working…" : "Save"}
          </Button>
          {saved.saved && !saved.is_active && (
            <Button
              variant="outline"
              size="sm"
              className="border-positive/40 bg-positive/10 text-positive hover:border-positive hover:bg-positive/10 hover:text-positive"
              onClick={handleActivate}
              disabled={actionPending}
            >
              Activate
            </Button>
          )}
          {saved.saved && saved.is_active && (
            <Button variant="outline" size="sm" onClick={handleDeactivate} disabled={actionPending}>
              Revert to auto
            </Button>
          )}
          {saved.saved && !confirmingDelete && (
            <Button
              variant="outline"
              size="sm"
              className="border-negative/40 bg-negative/10 text-negative hover:border-negative hover:bg-negative/10 hover:text-negative"
              onClick={() => setConfirmingDelete(true)}
              disabled={actionPending}
            >
              Delete
            </Button>
          )}
        </div>
      </div>

      {confirmingDelete && (
        <div className="space-y-3 rounded-md border border-negative/40 bg-negative/10 p-4">
          <p className="text-sm text-negative">
            Delete this saved custom valuation for {ticker}?
            {saved.is_active && " This will also revert the ticker to auto calculation everywhere it's shown."}
          </p>
          <div className="flex items-center gap-3">
            <Button variant="danger" onClick={handleDelete} disabled={actionPending}>
              {actionPending ? "Deleting…" : "Confirm delete"}
            </Button>
            <Button variant="outline" onClick={() => setConfirmingDelete(false)} disabled={actionPending}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {actionError && <p className="text-sm text-negative">{actionError}</p>}
    </Card>
  );
}

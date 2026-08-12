"use client";

import { ManualCalculationPanel } from "@/components/step3/ManualCalculationPanel";
import { ValuationGauge } from "@/components/step3/ValuationGauge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useStep3 } from "@/lib/hooks/useStep3";
import { fmtMoney, fmtNumber, fmtPct } from "@/lib/format";
import type { Step3Out, Step3PBBands } from "@/lib/api/types";

interface Props {
  ticker: string;
}

// CF_NORMALIZED/FCF_NORMALIZED never appear in the left "Model Valuation"
// column (Auto Calculation's own selected_method) -- they're Manual
// Calculation/Custom Valuation-only method choices, so these two entries
// are only ever looked up from ManualCalculationPanel's method dropdown.
export const METHOD_LABELS: Record<string, string> = {
  DCF: "Discounted Cash Flow (Operating CF)",
  DFCF: "Discounted Free Cash Flow",
  DNI: "Discounted Net Income",
  DNI_NORMALIZED: "Discounted Net Income (Normalized)",
  CF_NORMALIZED: "Discounted Cash Flow (Normalized)",
  FCF_NORMALIZED: "Discounted Free Cash Flow (Normalized)",
  PRICE_TO_BOOK: "Price to Book",
  PSG: "Price to Sales Growth",
  PASS: "No method applies",
};

const PB_BAND_LABELS: Record<keyof Step3PBBands, string> = {
  minus_2sd: "Mean − 2 SD",
  minus_1sd: "Mean − 1 SD",
  mean: "Mean",
  plus_1sd: "Mean + 1 SD",
  plus_2sd: "Mean + 2 SD",
};

// Card-title weight -- same class this app uses for every other card's own
// title, shared by "Model Valuation" and "Custom Valuation".
export const SECTION_HEADING_CLASS = "font-heading text-sm font-semibold text-text-primary";

export function pctText(fraction: number | null): string {
  return fraction == null ? "—" : fmtPct(fraction * 100, 1);
}

/** Company-level dollar figures are shown in millions (label carries the
 * "(in millions)" tag) rather than raw dollars -- per-share figures like
 * Intrinsic Value / Last Close are left as plain per-share dollars. */
export function millionsText(n: number | null): string {
  return n == null ? "—" : fmtMoney(n / 1_000_000);
}

// Round 8 tried top-aligning the value cell to the row instead of centering
// it -- didn't hold up: a row's rendered height is the max of its cells'
// heights, so "Growth Yr 1-5" (label cell has a real sub-note, 2 lines) is
// a taller row than "Growth Yr 6-10" (no sub-note, 1 line) regardless of
// which vertical-align the value cell uses, and something about how that
// extra row height interacted with the input box's own rendering still
// pushed it down specifically on the 2-line row.
//
// Root-caused here: the actual bug is that row height ISN'T constant in
// the first place. Fix is at the source, not the alignment rule -- every
// label cell now *always* renders 2 lines (a blank placeholder line when
// there's no real sub-note, not a conditionally-omitted one), so every
// row from Discount/Premium downward is identically tall by construction.
// With no row-height variance left, top-aligning the value cell can no
// longer drift row-to-row regardless of whether a given row has a real
// sub-note or a blank one.
export const FIELD_ROW_CLASS = "h-12 border-border-subtle hover:bg-transparent";
// whitespace-normal overrides TableCell's own default nowrap -- a long
// label (e.g. "Free Cash Flow (Normalized, 5yr avg CapEx)") needs to still
// be able to wrap to 2 lines within the fixed row height rather than
// overflowing horizontally past the column.
export const FIELD_LABEL_CELL_CLASS = "whitespace-normal p-0 pt-3 pr-4 align-top text-text-tertiary";
export const FIELD_VALUE_CELL_CLASS = "p-0 pt-3 text-right align-top font-mono text-sm text-text-primary";

export function InputRow({ label, sublabel, value }: { label: string; sublabel?: string; value: React.ReactNode }) {
  return (
    <TableRow className={FIELD_ROW_CLASS}>
      <TableCell className={FIELD_LABEL_CELL_CLASS}>
        <div className="text-sm">{label}</div>
        {/* Always rendered (never conditional) -- a blank placeholder line
            still occupies the same height as a real one, which is what
            keeps every row's label cell (and therefore the row itself)
            identically tall. truncate/nowrap so a long real sub-note (e.g.
            the analyst-source string on Growth Yr 1-5) still can't wrap to
            a 3rd line and grow that one row past the others. */}
        <div className="truncate text-[10px] text-text-tertiary">{sublabel || " "}</div>
      </TableCell>
      <TableCell className={FIELD_VALUE_CELL_CLASS}>{value}</TableCell>
    </TableRow>
  );
}

export function PBBandsTable({ bands, lastClose }: { bands: Step3PBBands; lastClose: number | null }) {
  const order: (keyof Step3PBBands)[] = ["minus_2sd", "minus_1sd", "mean", "plus_1sd", "plus_2sd"];
  return (
    <Table className="w-full border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="border-b border-border-card py-2 pr-4 font-medium">Band</TableHead>
          <TableHead className="border-b border-border-card py-2 text-right font-medium">Intrinsic Value</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {order.map((key) => (
          <TableRow key={key} className="hover:bg-transparent">
            <TableCell className="border-b border-border-subtle py-1.5 pr-4 text-text-secondary">{PB_BAND_LABELS[key]}</TableCell>
            <TableCell
              className={`border-b border-border-subtle py-1.5 text-right font-mono ${key === "mean" ? "font-semibold text-text-primary" : "text-text-secondary"}`}
            >
              {fmtMoney(bands[key])}
            </TableCell>
          </TableRow>
        ))}
        {lastClose != null && (
          <TableRow className="hover:bg-transparent">
            <TableCell className="py-1.5 pr-4 text-text-tertiary">Last Close</TableCell>
            <TableCell className="py-1.5 text-right font-mono text-text-secondary">{fmtMoney(lastClose)}</TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}

// Additive, informational-only context alongside the ticker-specific P/B
// bands above -- never changes intrinsic_value_per_share/discount_premium_pct/
// verdict, which keep their existing mean+-10% logic untouched. Framework
// context: the -1SD buy signal, the fixed sanity-range benchmark (Bank
// 1.2-1.4, REIT <=1.2/up to 1.5 with high DPU growth), REIT's Dividend/DPU
// Yield + DPU-growth notes, and (PASS-only) the loss-making Standard
// company PB liquidation reference.
export function ValuationContextNotes({ data }: { data: Step3Out }) {
  const hasBenchmark = data.benchmark_pb_low != null || data.benchmark_pb_high != null;
  const hasDividendInfo = data.dividend_yield_pct != null || data.dpu_growth_note != null;

  if (
    data.historical_pb_buy_signal == null &&
    !hasBenchmark &&
    !hasDividendInfo &&
    data.loss_making_pb_note == null
  ) {
    return null;
  }

  return (
    <div className="space-y-1.5 text-xs text-text-tertiary">
      {data.historical_pb_buy_signal != null && (
        <p>
          Historical P/B buy signal (price at/below −1 SD):{" "}
          <span className={data.historical_pb_buy_signal ? "text-positive" : "text-text-secondary"}>
            {data.historical_pb_buy_signal ? "Yes" : "No"}
          </span>
        </p>
      )}
      {hasBenchmark && (
        <p>
          Benchmark P/B range: {data.benchmark_pb_low != null ? fmtNumber(data.benchmark_pb_low) : "—"}
          {" – "}
          {data.benchmark_pb_high != null ? fmtNumber(data.benchmark_pb_high) : "—"}
          {data.benchmark_pb_note && <> ({data.benchmark_pb_note})</>}
        </p>
      )}
      {data.dividend_yield_pct != null && (
        <p>
          Dividend Yield: {fmtPct(data.dividend_yield_pct, 1)}
          {/* The exact configured threshold isn't on this payload (only
              whether it was met) -- see /settings for the live value,
              editable there since Piece 4. */}
          {data.dividend_yield_meets_reit_threshold != null && (
            <> ({data.dividend_yield_meets_reit_threshold ? "meets" : "below"} the configured REIT threshold)</>
          )}
        </p>
      )}
      {data.dpu_growth_note && <p>{data.dpu_growth_note}</p>}
      {data.loss_making_pb_note && <p>{data.loss_making_pb_note}</p>}
    </div>
  );
}

export function Step3Card({ ticker }: Props) {
  const { data, error } = useStep3(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-negative">Couldn&apos;t load Valuation data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Valuation…</p>
      </div>
    );
  }

  const isTwentyYearMethod = data.selected_method === "DCF" || data.selected_method === "DFCF" || data.selected_method === "DNI" || data.selected_method === "DNI_NORMALIZED";
  const isPB = data.selected_method === "PRICE_TO_BOOK";
  const isPSG = data.selected_method === "PSG";
  const isPass = data.selected_method === "PASS";

  // `data` is always Auto Calculation (the /step3 endpoint deliberately
  // never routes through get_active_valuation) -- this whole card is a
  // fixed reference point to compare a custom valuation against, and must
  // never itself switch to showing custom figures. "Active: Custom" is
  // communicated entirely from the Custom Valuation panel's own status bar
  // on the right, sourced from its own saved-row fetch, not from here.
  return (
    <div className="space-y-6">
      <details className="text-sm">
        <summary className="cursor-pointer text-xs uppercase tracking-widest text-text-tertiary">Method selection reasoning</summary>
        <ul className="mt-2 space-y-1 text-xs text-text-tertiary">
          {data.method_reasoning.map((step, i) => (
            <li key={i}>
              <span className={step.passed === true ? "text-positive" : step.passed === false ? "text-text-tertiary" : "text-warn"}>
                [{step.step}] {step.check} → {step.passed === null ? "unknown" : String(step.passed)}
              </span>{" "}
              — {step.detail}
            </li>
          ))}
        </ul>
      </details>

      {/* The Custom Valuation panel must always render, even when Auto's
          own tree landed on PASS -- a PASS ticker (Auto genuinely can't
          value it) is the single most valuable case for a saved manual
          override, and there'd otherwise be no way to even open the panel
          to create one. Only the left "Model Valuation" column's content
          is conditional on isPass. */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="space-y-6 rounded-lg border border-border-card bg-surface p-6">
          {/* min-h-8 matches Custom Valuation's title row, whose height is
              set by its h-8 method <select> -- without it this row (a bare
              h2, ~20px) renders shorter than the other column's, shifting
              everything below (price, gauge, slider) up relative to it. */}
          <div className="flex min-h-8 items-center">
            <h2 className={SECTION_HEADING_CLASS}>Model Valuation · {METHOD_LABELS[data.selected_method] ?? data.selected_method}</h2>
          </div>

          {isPass ? (
            <div className="space-y-3">
              <p className="text-sm text-text-secondary">
                {data.insufficient_data
                  ? `Insufficient data was available to select a valuation method for ${ticker}.`
                  : data.pass_reason}
              </p>
              <ValuationContextNotes data={data} />
            </div>
          ) : (
            <>
              <ValuationGauge
                discountPremiumPct={data.discount_premium_pct}
                intrinsicValuePerShare={data.intrinsic_value_per_share}
                lastClose={data.inputs.last_close}
                reportedCurrency={data.inputs.reported_currency}
                fxRate={data.inputs.fx_rate}
                fxRateAsOf={data.inputs.fx_rate_as_of}
              />

              {/* Discount/Premium, growth rows, Current Value/Discount
                  Rate/Shares/Total Debt/Cash, and the PSG fields all share
                  ONE <Table> -- not split across several sibling <Table>s
                  -- so none of them pick up the parent's space-y-6 gap
                  partway through the row sequence. Mirrors
                  ManualCalculationPanel's merged table (see round-10 fix
                  there): that gap, when it existed only on one side, is
                  what caused "Operating Cash Flow" (nee "Current Value")
                  to land at different heights between the two columns. */}
              <Table className="text-sm">
                <TableBody>
                  <InputRow label="Discount/Premium" value={pctText(data.discount_premium_pct)} />
                  {isTwentyYearMethod && (
                    <>
                      <InputRow label="Growth Yr 1-5" value={pctText(data.inputs.growth_yr_1_5)} sublabel={data.inputs.growth_yr_1_5_source ?? "Unavailable"} />
                      <InputRow label="Growth Yr 6-10" value={pctText(data.inputs.growth_yr_6_10)} />
                      <InputRow label="Growth Yr 11-20 (terminal)" value={pctText(data.inputs.growth_yr_11_20)} />
                      <InputRow label={data.inputs.current_value_label ?? "Current Value"} sublabel="(in millions)" value={millionsText(data.inputs.current_value)} />
                      <InputRow
                        label="Discount Rate (CAPM)"
                        value={
                          data.inputs.discount_rate != null ? (
                            <span>
                              {pctText(data.inputs.discount_rate)}
                              {data.inputs.capm?.beta_outside_reference_range && <span className="ml-1 text-warn">†</span>}
                            </span>
                          ) : (
                            "—"
                          )
                        }
                      />
                      <InputRow
                        label="Shares Outstanding"
                        value={data.inputs.shares_outstanding != null ? data.inputs.shares_outstanding.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—"}
                      />
                      <InputRow label="Total Debt" sublabel="(in millions)" value={millionsText(data.inputs.total_debt)} />
                      <InputRow
                        label={`Cash${data.inputs.cash_and_st_investments_includes_short_term_investments ? " + ST Investments" : ""}`}
                        sublabel="(in millions)"
                        value={millionsText(data.inputs.cash_and_st_investments)}
                      />
                    </>
                  )}
                  {isPSG && (
                    <>
                      <InputRow label="Sales Per Share" value={data.inputs.sales_per_share != null ? fmtMoney(data.inputs.sales_per_share) : "—"} />
                      <InputRow label="Projected Growth Rate" value={pctText(data.inputs.projected_growth_rate)} />
                      <InputRow label="Fair PSG Ratio" value={data.inputs.fair_psg_ratio != null ? fmtNumber(data.inputs.fair_psg_ratio) : "—"} />
                    </>
                  )}
                </TableBody>
              </Table>

              {isPB && data.pb_bands && <PBBandsTable bands={data.pb_bands} lastClose={data.inputs.last_close} />}

              {isPB && <ValuationContextNotes data={data} />}

              {isTwentyYearMethod && data.inputs.capm?.beta_outside_reference_range && (
                <p className="text-xs text-warn">† Beta is below 0.8, outside the workbook&apos;s manual reference table range — CAPM is still applied directly.</p>
              )}
            </>
          )}
        </div>

        <ManualCalculationPanel ticker={ticker} autoData={data} />
      </div>
    </div>
  );
}

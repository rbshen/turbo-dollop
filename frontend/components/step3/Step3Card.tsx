"use client";

import { ManualCalculationPanel } from "@/components/step3/ManualCalculationPanel";
import { ValuationGauge } from "@/components/step3/ValuationGauge";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { useStep3 } from "@/lib/hooks/useStep3";
import { fmtMoney, fmtNumber, fmtPct } from "@/lib/format";
import type { Step3PBBands } from "@/lib/api/types";

interface Props {
  ticker: string;
}

export const METHOD_LABELS: Record<string, string> = {
  DCF: "Discounted Cash Flow (Operating CF)",
  DFCF: "Discounted Free Cash Flow",
  DNI: "Discounted Net Income",
  DNI_NORMALIZED: "Discounted Net Income (Normalized)",
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
// title (Step1Card/Step4Card), now shared by "Auto Calculation" and "Manual
// Calculation" since the page-level "VALUATION" title above them was
// removed.
export const SECTION_HEADING_CLASS = "text-sm font-semibold uppercase tracking-widest text-zinc-400";

// Shared by Auto Calculation's (read-only) Method box and Manual
// Calculation's (interactive) Method <select> -- a fixed height rather than
// one derived from padding/line-height, since a <select> and a <p> render
// their "same" padding at slightly different heights across browsers, which
// was throwing off row alignment between the two columns even when their
// padding/border classes matched.
export const METHOD_FIELD_CLASS = "flex h-9 w-full items-center rounded-md border border-zinc-700 bg-zinc-900 px-2 text-sm text-zinc-200";

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
export const FIELD_ROW_CLASS = "h-12 border-zinc-900 hover:bg-transparent";
// whitespace-normal overrides TableCell's own default nowrap -- a long
// label (e.g. "Free Cash Flow (Normalized, 5yr avg CapEx)") needs to still
// be able to wrap to 2 lines within the fixed row height rather than
// overflowing horizontally past the column.
export const FIELD_LABEL_CELL_CLASS = "whitespace-normal p-0 pt-3 pr-4 align-top text-zinc-500";
export const FIELD_VALUE_CELL_CLASS = "p-0 pt-3 text-right align-top font-mono text-sm text-zinc-200";

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
        <div className="truncate text-[10px] text-zinc-600">{sublabel || " "}</div>
      </TableCell>
      <TableCell className={FIELD_VALUE_CELL_CLASS}>{value}</TableCell>
    </TableRow>
  );
}

export function PBBandsTable({ bands, lastClose }: { bands: Step3PBBands; lastClose: number | null }) {
  const order: (keyof Step3PBBands)[] = ["minus_2sd", "minus_1sd", "mean", "plus_1sd", "plus_2sd"];
  return (
    <table className="w-full border-separate border-spacing-0 text-sm">
      <thead>
        <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
          <th className="border-b border-zinc-800 py-2 pr-4 font-medium">Band</th>
          <th className="border-b border-zinc-800 py-2 text-right font-medium">Intrinsic Value</th>
        </tr>
      </thead>
      <tbody>
        {order.map((key) => (
          <tr key={key}>
            <td className="border-b border-zinc-900 py-1.5 pr-4 text-zinc-400">{PB_BAND_LABELS[key]}</td>
            <td className={`border-b border-zinc-900 py-1.5 text-right font-mono ${key === "mean" ? "font-semibold text-zinc-100" : "text-zinc-300"}`}>
              {fmtMoney(bands[key])}
            </td>
          </tr>
        ))}
        {lastClose != null && (
          <tr>
            <td className="py-1.5 pr-4 text-zinc-500">Last Close</td>
            <td className="py-1.5 text-right font-mono text-zinc-300">{fmtMoney(lastClose)}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

export function Step3Card({ ticker }: Props) {
  const { data, error } = useStep3(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-red-400">Couldn&apos;t load Valuation data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Valuation…</p>
      </div>
    );
  }

  const isTwentyYearMethod = data.selected_method === "DCF" || data.selected_method === "DFCF" || data.selected_method === "DNI" || data.selected_method === "DNI_NORMALIZED";
  const isPB = data.selected_method === "PRICE_TO_BOOK";
  const isPSG = data.selected_method === "PSG";
  const isPass = data.selected_method === "PASS";

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <details className="text-sm">
        <summary className="cursor-pointer text-xs uppercase tracking-widest text-zinc-500">Method selection reasoning</summary>
        <ul className="mt-2 space-y-1 text-xs text-zinc-500">
          {data.method_reasoning.map((step, i) => (
            <li key={i}>
              <span className={step.passed === true ? "text-emerald-400" : step.passed === false ? "text-zinc-500" : "text-amber-400"}>
                [{step.step}] {step.check} → {step.passed === null ? "unknown" : String(step.passed)}
              </span>{" "}
              — {step.detail}
            </li>
          ))}
        </ul>
      </details>

      {isPass ? (
        <p className="text-sm text-zinc-400">
          {data.insufficient_data
            ? `Insufficient data was available to select a valuation method for ${ticker}.`
            : data.pass_reason}
        </p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div className="space-y-6">
              <h2 className={SECTION_HEADING_CLASS}>Auto Calculation</h2>

              <div>
                <p className="text-xs uppercase tracking-widest text-zinc-500">Method</p>
                {/* Not an interactive control -- METHOD_FIELD_CLASS visually
                    matches Manual Calculation's <select> exactly (same fixed
                    height, padding, font size) so the Intrinsic Value row
                    below starts at the same vertical position in both
                    columns. */}
                <p className={`mt-1 ${METHOD_FIELD_CLASS}`}>{METHOD_LABELS[data.selected_method] ?? data.selected_method}</p>
              </div>

              <div className="space-y-1">
                <p className="text-xs uppercase tracking-widest text-zinc-500">Intrinsic Value {isPB && "(Mean)"}</p>
                <p className="font-mono text-3xl font-bold tabular-nums text-zinc-100">
                  {data.intrinsic_value_per_share != null ? fmtMoney(data.intrinsic_value_per_share) : "—"}
                </p>
              </div>

              <div className="space-y-1">
                <p className="text-xs uppercase tracking-widest text-zinc-500">Last Close</p>
                <p className="font-mono text-lg text-zinc-200">{data.inputs.last_close != null ? fmtMoney(data.inputs.last_close) : "—"}</p>
              </div>

              <ValuationGauge discountPremiumPct={data.discount_premium_pct} intrinsicValuePerShare={data.intrinsic_value_per_share} lastClose={data.inputs.last_close} />

              {/* Discount/Premium, growth rows, Current Value/Discount Rate/
                  Shares/Total Debt/Cash, and the PSG fields all share ONE
                  <Table> -- not split across several sibling <Table>s -- so
                  none of them pick up the parent's space-y-6 gap partway
                  through the row sequence. Mirrors ManualCalculationPanel's
                  merged table (see round-10 fix there): that gap, when it
                  existed only on one side, is what caused "Operating Cash
                  Flow" (nee "Current Value") to land at different heights
                  between the two columns. */}
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
                              {data.inputs.capm?.beta_outside_reference_range && <span className="ml-1 text-amber-400">†</span>}
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

              {isTwentyYearMethod && data.inputs.capm?.beta_outside_reference_range && (
                <p className="text-xs text-amber-400">† Beta is below 0.8, outside the workbook&apos;s manual reference table range — CAPM is still applied directly.</p>
              )}
            </div>

            <ManualCalculationPanel ticker={ticker} autoData={data} />
          </div>
        </>
      )}
    </div>
  );
}

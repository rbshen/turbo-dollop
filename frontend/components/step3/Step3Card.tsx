"use client";

import { useState } from "react";

import { ValuationGauge } from "@/components/step3/ValuationGauge";
import { useStep3, type Step3GrowthOverrides } from "@/lib/hooks/useStep3";
import { fmtMoney, fmtNumber, fmtPct } from "@/lib/format";
import type { Step3Out, Step3PBBands } from "@/lib/api/types";

interface Props {
  ticker: string;
}

const METHOD_LABELS: Record<string, string> = {
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

function pctText(fraction: number | null): string {
  return fraction == null ? "—" : fmtPct(fraction * 100, 1);
}

function InputRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <tr>
      <td className="border-b border-zinc-900 py-1.5 pr-4 text-zinc-500">{label}</td>
      <td className="border-b border-zinc-900 py-1.5 text-right font-mono text-zinc-200">{value}</td>
    </tr>
  );
}

function GrowthRateEditor({ data, overrides, onChange }: { data: Step3Out; overrides: Step3GrowthOverrides; onChange: (o: Step3GrowthOverrides) => void }) {
  const [yr610Text, setYr610Text] = useState(() => (data.inputs.growth_yr_6_10 != null ? (data.inputs.growth_yr_6_10 * 100).toFixed(1) : ""));
  const [yr1120Text, setYr1120Text] = useState(() => (data.inputs.growth_yr_11_20 * 100).toFixed(1));

  function commit(field: "growth_yr_6_10" | "growth_yr_11_20", text: string) {
    const parsed = parseFloat(text);
    if (Number.isNaN(parsed)) return;
    onChange({ ...overrides, [field]: parsed / 100 });
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div>
        <label className="block text-xs uppercase tracking-widest text-zinc-500">Growth Yr 1-5</label>
        <p className="mt-1 font-mono text-sm text-zinc-300">{pctText(data.inputs.growth_yr_1_5)}</p>
        <p className="text-xs text-zinc-600">{data.inputs.growth_yr_1_5_source ?? "Unavailable"}</p>
      </div>
      <div>
        <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="growth-yr-6-10">
          Growth Yr 6-10
        </label>
        <input
          id="growth-yr-6-10"
          type="number"
          step="0.1"
          className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
          value={yr610Text}
          onChange={(e) => setYr610Text(e.target.value)}
          onBlur={() => commit("growth_yr_6_10", yr610Text)}
        />
        <p className="text-xs text-zinc-600">% per year, defaults to Yr 1-5</p>
      </div>
      <div>
        <label className="block text-xs uppercase tracking-widest text-zinc-500" htmlFor="growth-yr-11-20">
          Growth Yr 11-20 (terminal)
        </label>
        <input
          id="growth-yr-11-20"
          type="number"
          step="0.1"
          className="mt-1 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-sm text-zinc-200 focus:border-zinc-600 focus:outline-none"
          value={yr1120Text}
          onChange={(e) => setYr1120Text(e.target.value)}
          onBlur={() => commit("growth_yr_11_20", yr1120Text)}
        />
        <p className="text-xs text-zinc-600">% per year, defaults to 4%</p>
      </div>
    </div>
  );
}

function PBBandsTable({ bands, lastClose }: { bands: Step3PBBands; lastClose: number | null }) {
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
  const [overrides, setOverrides] = useState<Step3GrowthOverrides>({});
  const { data, error } = useStep3(ticker, overrides);

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-red-400">Couldn&apos;t load Step 3 data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Step 3…</p>
      </div>
    );
  }

  const isTwentyYearMethod = data.selected_method === "DCF" || data.selected_method === "DFCF" || data.selected_method === "DNI" || data.selected_method === "DNI_NORMALIZED";
  const isPB = data.selected_method === "PRICE_TO_BOOK";
  const isPSG = data.selected_method === "PSG";
  const isPass = data.selected_method === "PASS";

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Step 3 · Valuation</h2>
        <span className="rounded-md border border-zinc-700 bg-zinc-800/60 px-3 py-1 text-sm font-medium text-zinc-200">
          {METHOD_LABELS[data.selected_method] ?? data.selected_method}
        </span>
      </div>

      <div className="space-y-1">
        <p className="text-sm text-zinc-300">
          Classified as <span className="font-medium text-zinc-100">{data.company_type}</span>
        </p>
        <p className="text-xs text-zinc-600">{data.classification_note}</p>
      </div>

      {isPass ? (
        <p className="text-sm text-zinc-400">{data.pass_reason}</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-widest text-zinc-500">Intrinsic Value {isPB && "(Mean)"}</p>
            <p className="font-mono text-3xl font-bold tabular-nums text-zinc-100">
              {data.intrinsic_value_per_share != null ? fmtMoney(data.intrinsic_value_per_share) : "—"}
            </p>
            <p className="text-sm text-zinc-500">
              Last close {data.inputs.last_close != null ? fmtMoney(data.inputs.last_close) : "—"}
              {data.discount_premium_pct != null && <> · {pctText(data.discount_premium_pct)} vs intrinsic value</>}
            </p>
          </div>
          <ValuationGauge discountPremiumPct={data.discount_premium_pct} />
        </div>
      )}

      {isPB && data.pb_bands && <PBBandsTable bands={data.pb_bands} lastClose={data.inputs.last_close} />}

      {isTwentyYearMethod && (
        <>
          <GrowthRateEditor data={data} overrides={overrides} onChange={setOverrides} />
          <table className="w-full border-separate border-spacing-0 text-sm">
            <tbody>
              <InputRow label={data.inputs.current_value_label ?? "Current Value"} value={data.inputs.current_value != null ? fmtMoney(data.inputs.current_value) : "—"} />
              <InputRow label="Total Debt" value={data.inputs.total_debt != null ? fmtMoney(data.inputs.total_debt) : "—"} />
              <InputRow
                label={`Cash${data.inputs.cash_and_st_investments_includes_short_term_investments ? " + ST Investments" : ""}`}
                value={data.inputs.cash_and_st_investments != null ? fmtMoney(data.inputs.cash_and_st_investments) : "—"}
              />
              <InputRow label="Shares Outstanding" value={data.inputs.shares_outstanding != null ? data.inputs.shares_outstanding.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—"} />
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
              {data.inputs.capm && (
                <InputRow
                  label="  Rf + β × MRP"
                  value={`${pctText(data.inputs.capm.risk_free_rate)} + ${fmtNumber(data.inputs.capm.beta)} × ${pctText(data.inputs.capm.market_risk_premium)}`}
                />
              )}
              <InputRow label="Current Fiscal Year" value={data.inputs.current_fiscal_year ?? "—"} />
            </tbody>
          </table>
          {data.inputs.capm?.beta_outside_reference_range && (
            <p className="text-xs text-amber-400">† Beta is below 0.8, outside the workbook&apos;s manual reference table range — CAPM is still applied directly.</p>
          )}
        </>
      )}

      {isPSG && (
        <table className="w-full border-separate border-spacing-0 text-sm">
          <tbody>
            <InputRow label="Sales Per Share" value={data.inputs.sales_per_share != null ? fmtMoney(data.inputs.sales_per_share) : "—"} />
            <InputRow label="Projected Growth Rate" value={pctText(data.inputs.projected_growth_rate)} />
            <InputRow label="Fair PSG Ratio" value={data.inputs.fair_psg_ratio != null ? fmtNumber(data.inputs.fair_psg_ratio) : "—"} />
          </tbody>
        </table>
      )}

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
    </div>
  );
}

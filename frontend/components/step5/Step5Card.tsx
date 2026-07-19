"use client";

import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import { useStep5 } from "@/lib/hooks/useStep5";
import { fmtNumber, fmtPct, fmtTableMoney } from "@/lib/format";
import type { Step5RatioResult } from "@/lib/api/types";

interface Props {
  ticker: string;
}

const OUTLIER_METRIC_LABELS: Record<string, string> = {
  ebitda_ttm: "EBITDA (TTM)",
  interest_expense_ttm: "Interest Expense (TTM)",
  interest_income_ttm: "Interest Income (TTM)",
  net_interest_expense_ttm: "Net Interest Expense (TTM)",
  cfo_ttm: "Cash Flow from Operations (TTM)",
};

const RATIO_LABELS: Record<string, string> = {
  current_ratio: "Current Ratio",
  debt_to_ebitda: "Debt / EBITDA",
  debt_servicing_ratio: "Debt Servicing Ratio",
  gearing_ratio: "Gearing Ratio",
};

const TIER_LABELS: Record<string, string> = {
  excellent: "Excellent",
  good: "Good",
  acceptable: "Acceptable",
  approaching_limit: "Approaching limit",
  fail: "Fail",
};

const PERCENT_RATIOS = new Set(["debt_servicing_ratio", "gearing_ratio"]);

function formatRatioValue(key: string, value: number): string {
  return PERCENT_RATIOS.has(key) ? fmtPct(value, 1) : `${fmtNumber(value, 2)}x`;
}

function tierClass(label: string): string {
  if (label === "fail") return "text-red-400";
  if (label === "approaching_limit") return "text-amber-300";
  return "text-zinc-100";
}

function ratioRows(ratios: Record<string, Step5RatioResult>) {
  return Object.entries(ratios).map(([key, r]) => (
    <tr key={key}>
      <td className="border-b border-zinc-900 py-2 pr-4 text-zinc-400">{RATIO_LABELS[key] ?? key}</td>
      <td className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
        {formatRatioValue(key, r.value)}
      </td>
      <td className={`border-b border-zinc-900 py-2 text-right font-medium ${tierClass(r.label)}`}>
        {TIER_LABELS[r.label] ?? r.label}
      </td>
    </tr>
  ));
}

export function Step5Card({ ticker }: Props) {
  const { data, error } = useStep5(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-red-400">Couldn&apos;t load Step 5 data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Step 5…</p>
      </div>
    );
  }

  const isBank = data.company_type === "Bank";

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Step 5 · Conservative debt</h2>
        {data.score != null && <ScoreBadge score={data.score} verdict={data.verdict} />}
      </div>

      <div className="space-y-1">
        <p className="text-sm text-zinc-300">
          Classified as <span className="font-medium text-zinc-100">{data.company_type}</span>
        </p>
        <p className="text-xs text-zinc-600">{data.classification_note}</p>
      </div>

      <OutlierWarningNote warnings={data.outlier_warnings} labels={OUTLIER_METRIC_LABELS} />

      {isBank ? (
        <p className="text-sm text-zinc-500">Not yet supported — CET1 data unavailable from FMP.</p>
      ) : data.verdict === "insufficient_data" ? (
        <p className="text-sm text-zinc-500">Required balance sheet/income statement figures were unavailable for {ticker}.</p>
      ) : (
        <>
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
                <th className="border-b border-zinc-800 py-2 pr-4 font-medium">Ratio</th>
                <th className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">Value</th>
                <th className="border-b border-zinc-800 py-2 text-right font-medium">Tier</th>
              </tr>
            </thead>
            <tbody>{ratioRows(data.ratios)}</tbody>
          </table>

          {data.deferred_revenue_current != null && data.deferred_revenue_current > 0 && (
            <p className="text-xs text-zinc-600">
              Deferred revenue (current): {fmtTableMoney(data.deferred_revenue_current)} — informational only. A low
              Current Ratio driven mainly by deferred revenue (cash already collected, not yet delivered) isn&apos;t
              necessarily a red flag; this isn&apos;t auto-applied to the ratio above.
            </p>
          )}

          <p className="text-sm text-zinc-400">
            {data.hard_fail
              ? "At least one ratio breached its hard limit, so this fails regardless of the blended score shown above."
              : "No ratio breached its hard limit."}
          </p>
        </>
      )}
    </div>
  );
}

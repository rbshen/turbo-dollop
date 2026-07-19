"use client";

import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { useStep2 } from "@/lib/hooks/useStep2";
import { fmtPct } from "@/lib/format";

interface Props {
  ticker: string;
}

function agreementLabel(spread: number | null | undefined): string {
  if (spread == null) return "Unknown";
  if (spread < 10) return "Tight";
  if (spread <= 20) return "Moderate";
  return "Wide";
}

function rationale(data: NonNullable<ReturnType<typeof useStep2>["data"]>): string {
  if (data.components.insufficient_data) {
    return "Not enough forward-looking analyst estimate data was available to project a growth rate.";
  }
  const basisLabel = data.basis === "eps" ? "EPS" : "revenue";
  const spreadLabel = agreementLabel(data.estimate_spread).toLowerCase();
  return (
    `Projected ${basisLabel} growth of ${fmtPct(data.growth_rate ?? 0, 1)} from FY${data.base_fiscal_year} to ` +
    `FY${data.target_fiscal_year}, with ${spreadLabel} agreement across analyst estimates (±${fmtPct(
      (data.estimate_spread ?? 0) / 2,
      1
    )} around the average).`
  );
}

export function Step2Card({ ticker }: Props) {
  const { data, error } = useStep2(ticker);

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-red-400">Couldn&apos;t load Step 2 data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Step 2…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">
          Step 2 · Positive growth rate
        </h2>
        <ScoreBadge score={data.score} verdict={data.verdict} />
      </div>

      {data.components.insufficient_data ? (
        <p className="text-sm text-zinc-500">No forward analyst estimates were available for {ticker}.</p>
      ) : (
        <>
          <div className="space-y-2">
            <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">
              Analyst estimates ({data.basis === "eps" ? "EPS" : "revenue"}) — cumulative growth from FY
              {data.base_fiscal_year}
            </h3>
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
                  <th className="border-b border-zinc-800 py-2 pr-4 font-medium">Fiscal year</th>
                  <th className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">Avg growth</th>
                  <th className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">High</th>
                  <th className="border-b border-zinc-800 py-2 text-right font-medium">Low</th>
                </tr>
              </thead>
              <tbody>
                {data.estimates.map((row) => (
                  <tr key={row.fiscal_year}>
                    <td className="border-b border-zinc-900 py-2 pr-4 text-zinc-400">FY{row.fiscal_year}</td>
                    <td className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                      {fmtPct(row.growth_avg, 1)}
                    </td>
                    <td className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                      {fmtPct(row.growth_high, 1)}
                    </td>
                    <td className="border-b border-zinc-900 py-2 text-right font-mono tabular-nums text-zinc-100">
                      {fmtPct(row.growth_low, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="space-y-1">
            <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">
              Estimate agreement <span className="normal-case text-zinc-600">(analyst estimate range, not source consensus)</span>
            </h3>
            <p className="text-sm text-zinc-300">
              {agreementLabel(data.estimate_spread)}
              {data.estimate_spread != null && (
                <span className="text-zinc-500"> — spread of {fmtPct(data.estimate_spread, 1)} around the average</span>
              )}
            </p>
          </div>

          <div className="space-y-1">
            <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Growth catalysts</h3>
            {data.growth_catalysts ? (
              <p className="text-sm text-zinc-300">{data.growth_catalysts}</p>
            ) : (
              <p className="text-sm text-zinc-600">No catalysts recorded yet.</p>
            )}
          </div>

          <p className="text-sm text-zinc-400">{rationale(data)}</p>
        </>
      )}
    </div>
  );
}

"use client";

import { CaretDown } from "@phosphor-icons/react";

import { ReasoningTable } from "@/components/shared/ReasoningTable";
import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useStep2 } from "@/lib/hooks/useStep2";
import { fmtPct } from "@/lib/format";

interface Props {
  ticker: string;
}

// Order mirrors scoring/step2.py::score_step2's components dict.
const COMPONENT_ORDER = ["magnitude", "agreement"] as const;

const METRIC_LABELS: Record<string, string> = {
  magnitude: "Growth Magnitude",
  agreement: "Estimate Agreement",
};

const TIER_LABELS: Record<string, string> = {
  // magnitude (scoring/step2.py::_score_magnitude)
  strong: "Strong (>15%)",
  solid: "Solid (10–15%)",
  modest: "Modest (5–10%)",
  weak: "Weak (0–5%)",
  negative: "Negative (<0%)",
  // agreement (scoring/step2.py::_score_agreement)
  tight: "Tight (<10% spread)",
  moderate: "Moderate (10–20% spread)",
  wide: "Wide (>20% spread)",
};

function tierClass(score: number): string {
  if (score === 0) return "text-red-400";
  if (score < 70) return "text-amber-300";
  return "text-zinc-100";
}

function agreementLabel(spread: number | null | undefined): string {
  if (spread == null) return "Unknown";
  if (spread < 10) return "Tight";
  if (spread <= 20) return "Moderate";
  return "Wide";
}

function rationale(data: NonNullable<ReturnType<typeof useStep2>["data"]>): string {
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
        <p className="text-sm text-red-400">Couldn&apos;t load Growth Rate data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Growth Rate…</p>
      </div>
    );
  }

  // No usable growth projection in either basis -- a data gap, not a scored
  // Fail (see CLAUDE.md's Step 2 deviations). Same early-return convention
  // Step4Card uses for its own insufficient_data state: score is never
  // rendered as a badge, and `components` isn't read (it's {} here).
  if (data.verdict === "insufficient_data" || data.score == null) {
    return (
      <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">
          Growth Rate
        </h2>
        <p className="text-sm text-zinc-500">No forward analyst estimates were available for {ticker}.</p>
      </div>
    );
  }

  const componentRows = COMPONENT_ORDER.map((key) => {
    const component = data.components[key];
    const weight = data.weights[key] ?? 0;
    return {
      key,
      label: METRIC_LABELS[key],
      tierLabel: TIER_LABELS[component.tier ?? ""] ?? component.tier,
      score: component.score,
      weight,
      contribution: Math.round(weight * component.score),
    };
  });

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">
          Growth Rate
        </h2>
        <ScoreBadge score={data.score} verdict={data.verdict} />
      </div>

      <Collapsible>
        <CollapsibleTrigger className="group flex items-center gap-1.5 text-xs uppercase tracking-widest text-zinc-500 hover:text-zinc-300">
          <CaretDown size={12} className="transition-transform duration-200 group-data-[panel-open]:rotate-180" />
          Reasoning
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-3">
            <ReasoningTable
              rows={componentRows.map((row) => ({ ...row, tierClassName: tierClass(row.score) }))}
            />
          </div>
        </CollapsibleContent>
      </Collapsible>

      <div className="space-y-2">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">
          Analyst estimates ({data.basis === "eps" ? "EPS" : "revenue"}) — cumulative growth from FY
          {data.base_fiscal_year}
        </h3>
        <Table className="w-full border-separate border-spacing-0 text-sm">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="border-b border-zinc-800 py-2 pr-4 font-medium">Fiscal year</TableHead>
              <TableHead className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">Avg growth</TableHead>
              <TableHead className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">High</TableHead>
              <TableHead className="border-b border-zinc-800 py-2 text-right font-medium">Low</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.estimates.map((row) => (
              <TableRow key={row.fiscal_year} className="hover:bg-transparent">
                <TableCell className="border-b border-zinc-900 py-2 pr-4 text-zinc-400">FY{row.fiscal_year}</TableCell>
                <TableCell className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                  {fmtPct(row.growth_avg, 1)}
                </TableCell>
                <TableCell className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                  {fmtPct(row.growth_high, 1)}
                </TableCell>
                <TableCell className="border-b border-zinc-900 py-2 text-right font-mono tabular-nums text-zinc-100">
                  {fmtPct(row.growth_low, 1)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="space-y-1">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">
          Estimate agreement <span className="normal-case text-zinc-600">(analyst estimate range, not source consensus)</span>
        </h3>
        <p className="text-sm text-zinc-300">
          {agreementLabel(data.estimate_spread)}
          {data.estimate_spread != null && (
            <span className="text-zinc-500">
              {" "}
              — spread of {fmtPct(data.estimate_spread, 1)} around the average
              {data.target_analyst_count != null && ` (based on ${data.target_analyst_count} analysts)`}
            </span>
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
    </div>
  );
}

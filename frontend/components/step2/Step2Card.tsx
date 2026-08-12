"use client";

import { AnalysisSectionCard, type ReasoningBullet } from "@/components/shared/AnalysisSectionCard";
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
  if (score === 0) return "text-negative";
  if (score < 70) return "text-warn";
  return "text-text-primary";
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
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-negative">Couldn&apos;t load Growth Rate data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Growth Rate…</p>
      </div>
    );
  }

  // No usable growth projection in either basis -- a data gap, not a scored
  // Fail (see CLAUDE.md's Step 2 deviations). Same early-return convention
  // Step4Card uses for its own insufficient_data state: score is never
  // rendered as a badge, and `components` isn't read (it's {} here).
  if (data.verdict === "insufficient_data" || data.score == null) {
    return (
      <div className="space-y-2 rounded-lg border border-border-card bg-surface p-6">
        <h2 className="font-heading text-sm font-semibold text-text-primary">Growth Rate</h2>
        <p className="text-sm text-text-tertiary">No forward analyst estimates were available for {ticker}.</p>
      </div>
    );
  }

  const bullets: ReasoningBullet[] = COMPONENT_ORDER.map((key) => {
    const component = data.components[key];
    return {
      key,
      text: `${METRIC_LABELS[key]}: ${TIER_LABELS[component.tier ?? ""] ?? component.tier}`,
      tierClassName: tierClass(component.score),
    };
  });

  // REIT-only notes (basis explanation + historical DPU trend) -- purely
  // informational, never affect score/verdict/bullets above. Null for every
  // other company type.
  const notes = (
    <>
      {data.growth_basis_note && <p className="text-xs text-text-tertiary">{data.growth_basis_note}</p>}
      {data.dpu_growth_note && <p className="text-xs text-text-tertiary">{data.dpu_growth_note}</p>}
    </>
  );

  return (
    <AnalysisSectionCard
      title="Growth Rate"
      score={data.score}
      verdict={data.verdict}
      blurb={rationale(data)}
      notes={notes}
      bullets={bullets}
    />
  );
}

"use client";

import { useStep5 } from "@/lib/hooks/useStep5";
import { flatChipClassFor } from "@/lib/tierColor";

// Debt-only verdict chip for TickerHeader, alongside the blended Assessment
// chip. Motivation (see CLAUDE.md's "Overall Assessment's step weighting"
// section): Debt is a hard pass/fail bankruptcy filter, but its own Fail
// can still blend into an Overall "Pass"/"Strong Pass" (confirmed real
// cases: MA, FICO) -- a user reading only the header's Assessment chip has
// no way to see that. This chip surfaces Debt specifically, not the other
// 3 steps, since Debt's own hard-fail design is what the blend can mask;
// Growth Rate/Profitability/Financials don't have this same documented
// masking pattern.
//
// Reuses flatChipClassFor verbatim (same tokens as AssessmentChip/
// ScoreBadge) -- Debt's verdict vocabulary ("Fail"/"Pass"/"Strong Pass"/
// "Pass with caution") is a strict subset of what that function already
// handles, and score=null (not_supported/insufficient_data) already maps
// to its existing muted "no score" tier.
//
// Unlike AssessmentChip (which renders nothing when there's no score),
// this chip stays visible and renders a muted "Debt N/A" for
// not_supported (Bank without CET1 entered, Insurance) and
// insufficient_data -- these are common, meaningful states (Banks in
// particular), not a transient loading gap, and silently hiding the chip
// would look identical to "still loading" rather than "not scored for a
// specific, known reason."
const VERDICT_LABELS: Record<string, string> = {
  Fail: "Debt · Fail",
  Pass: "Debt · Pass",
  "Strong Pass": "Debt · Strong Pass",
  "Pass with caution": "Debt · Caution",
  not_supported: "Debt · N/A",
  insufficient_data: "Debt · N/A",
};

// Short, tailored reason for the muted N/A states -- mirrors Step5Card's
// own per-case blurb (its full text is scoped to the Analysis tab's fuller
// layout; this is the condensed, tooltip-length version of the same
// reasoning) rather than falling back to classification_note's generic
// "best-effort sector/industry match" text, which doesn't explain why a
// given ticker landed on not_supported/insufficient_data specifically.
function naReason(data: { company_type: string; verdict: string; bank_capital_metrics_editable: boolean }): string {
  if (data.verdict === "insufficient_data") return "Required balance sheet/income statement figures unavailable.";
  if (data.company_type === "Bank") {
    return data.bank_capital_metrics_editable
      ? "CET1 ratio not yet entered."
      : "Not a traditional deposit-taking bank — Debt isn't assessed.";
  }
  if (data.company_type === "Insurance") return "Standard debt ratios aren't meaningful for insurers.";
  return "Not scored.";
}

export function DebtVerdictChip({ ticker }: { ticker: string }) {
  const { data } = useStep5(ticker);
  if (!data) return null;

  const label = VERDICT_LABELS[data.verdict] ?? `Debt · ${data.verdict}`;
  const title =
    data.verdict === "not_supported" || data.verdict === "insufficient_data" ? naReason(data) : undefined;

  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-md px-2 py-1 text-xs font-semibold ${flatChipClassFor(data.score, data.verdict)}`}
    >
      {label}
    </span>
  );
}

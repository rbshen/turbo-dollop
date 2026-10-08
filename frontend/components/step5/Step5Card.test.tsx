// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Step5Card } from "@/components/step5/Step5Card";
import type { Step5Out } from "@/lib/api/types";

let hook: { data?: Step5Out; error?: Error };

vi.mock("@/lib/hooks/useStep5", () => ({ useStep5: () => hook }));
vi.mock("@/lib/hooks/useTickerBankCapitalMetrics", () => ({ useTickerBankCapitalMetrics: () => ({ data: undefined }) }));

afterEach(cleanup);

const ratio = (value: number | null, label: string, points: number, extra: Record<string, unknown> = {}) => ({
  value,
  adjusted_value: null,
  label,
  points,
  saved_by_tiebreaker: false,
  breach_context: null,
  note: null,
  ...extra,
});

function step5(overrides: Record<string, unknown> = {}): Step5Out {
  return {
    ticker: "ABC",
    company_type: "Standard",
    classification_note: "",
    ratios: {
      current_ratio: ratio(0.9, "borderline_fail", 0),
      debt_to_ebitda: ratio(0.5, "excellent", 100),
      debt_servicing_ratio: ratio(4, "excellent", 100),
      interest_coverage_ratio: ratio(12, "safe", 0),
    },
    bank_capital_metrics_editable: false,
    deferred_revenue_current: null,
    score: 74,
    verdict: "Pass with caution",
    unrescued_breaches: ["current_ratio"],
    pass_with_caution: true,
    weights: { current_ratio: 0.25, debt_to_ebitda: 0.45, debt_servicing_ratio: 0.3 },
    outlier_warnings: [],
    data_quality: [],
    ...overrides,
  } as unknown as Step5Out;
}

describe("Step5Card", () => {
  it("names the unrescued breached ratio in the caution note and the blurb", () => {
    hook = { data: step5() };
    render(<Step5Card ticker="ABC" />);
    // The Debt step's own caution is drawn "Pass, ratio in breach"; "Pass with caution" is the Overall verdict's word only.
    expect(screen.getByText("Pass, ratio in breach")).toBeInTheDocument();
    expect(screen.queryByText(/Pass with caution/)).toBeNull();
    expect(screen.getByText(/Pass, ratio in breach: Current Ratio \(Borderline — may not pass, 0\/100\) is in breach and not excused/)).toBeInTheDocument();
    expect(screen.getByText(/other ratios carry the blend to 74/)).toBeInTheDocument();
  });

  it("shows the stored Fail verdict as 'May not pass' and says why", () => {
    hook = {
      data: step5({
        score: 51,
        verdict: "Fail",
        pass_with_caution: false,
        unrescued_breaches: ["debt_to_ebitda"],
        ratios: {
          current_ratio: ratio(2, "excellent", 100),
          debt_to_ebitda: ratio(null, "negative_ebitda", 0, { note: "EBITDA is negative." }),
          debt_servicing_ratio: ratio(4, "excellent", 100),
          interest_coverage_ratio: ratio(12, "safe", 0),
        },
      }),
    };
    render(<Step5Card ticker="ABC" />);
    expect(screen.getByText("May not pass")).toBeInTheDocument();
    expect(screen.getByText("May not pass")).toHaveClass("text-not-pass"); // the pill, in the slate not-pass tone
    expect(screen.getByText("EBITDA is negative.")).toHaveClass("text-not-pass"); // the breach note
    expect(screen.queryByText("Fail")).toBeNull();
    expect(screen.getByText(/Debt \/ EBITDA is in breach and the blended score falls short of the Pass threshold \(70\), so Debt may not pass\./)).toBeInTheDocument();
  });

  it("reads the weights from the payload, never from constants", () => {
    hook = { data: step5({ weights: { current_ratio: 0.2, debt_to_ebitda: 0.5, debt_servicing_ratio: 0.3 } }) };
    render(<Step5Card ticker="ABC" />);
    expect(screen.getByText(/A weighted blend of Current Ratio 20%, Debt \/ EBITDA 50%, Debt Servicing Ratio 30%/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/33%|34%/);
  });

  it("names a REIT gearing breach in the score-based wording (no hard fail), with 'May not pass' as the display word", () => {
    hook = {
      data: step5({
        company_type: "REIT/Property Developer",
        score: 0,
        verdict: "Fail",
        pass_with_caution: false,
        unrescued_breaches: ["gearing_ratio"],
        ratios: { gearing_ratio: ratio(50, "fail", 0) },
        weights: { gearing_ratio: 1 },
      }),
    };
    render(<Step5Card ticker="ABC" />);
    expect(screen.getByText(/Gearing Ratio is in breach and the blended score falls short of the Pass threshold \(70\), so Debt may not pass\./)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/hard limit|regardless of the blended score/);
    expect(screen.getAllByText(/May not pass/).length).toBeGreaterThan(0);
  });
});

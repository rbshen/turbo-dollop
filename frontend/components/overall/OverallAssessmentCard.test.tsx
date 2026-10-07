// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OverallAssessmentView } from "@/components/overall/OverallAssessmentCard";
import type { OverallAssessment } from "@/lib/overallScore";

afterEach(cleanup);

function result(overrides: Partial<OverallAssessment>): OverallAssessment {
  return {
    status: "complete",
    score: 70,
    stepsScore: 70,
    moatMultiplier: 1,
    moat: "wide_moat",
    moatNote: null,
    verdict: "Pass",
    breakdown: [],
    incompleteSteps: [],
    failingSteps: [],
    cautionSteps: [],
    ...overrides,
  };
}

describe("OverallAssessmentView: the failing and caution notes", () => {
  it("shows no note when nothing failed or passed with caution", () => {
    render(<OverallAssessmentView result={result({})} />);
    expect(screen.queryByText(/worth reviewing/)).not.toBeInTheDocument();
  });

  it("names the failing steps in a warn-toned note", () => {
    render(<OverallAssessmentView result={result({ failingSteps: ["Debt", "Growth Rate"] })} />);
    const note = screen.getByText(/Debt, Growth Rate failed — reflected in the weighted score above/);
    expect(note).toHaveClass("text-warn");
  });

  it("names the pass-with-caution steps in a caution-toned note", () => {
    render(<OverallAssessmentView result={result({ cautionSteps: ["Debt"] })} />);
    const note = screen.getByText(/Debt passed with caution — a real breach was excused/);
    expect(note).toHaveClass("text-caution");
  });

  it("draws each note's warning as an aria-hidden icon in the note's own tone, never as an emoji", () => {
    const { container } = render(
      <OverallAssessmentView result={result({ failingSteps: ["Debt"], cautionSteps: ["Growth Rate"] })} />,
    );
    expect(container.textContent).not.toMatch(/[\u26A0\uFE0F]/);
    const notes = [screen.getByText(/Debt failed/), screen.getByText(/Growth Rate passed with caution/)];
    for (const note of notes) {
      expect(note.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
      expect(note.querySelector(".sr-only")).toHaveTextContent("Warning:");
    }
    expect(notes[0]).toHaveClass("text-warn");
    expect(notes[1]).toHaveClass("text-caution");
  });
});

const STEP_ROWS: OverallAssessment["breakdown"] = [
  { key: "step1", label: "Financials", baseWeight: 0.3, effectiveWeight: 0.3, score: 84, verdict: "Pass", status: "ok" },
  { key: "step2", label: "Growth Rate", baseWeight: 0.2, effectiveWeight: 0.2, score: 84, verdict: "Pass", status: "ok" },
  { key: "step4", label: "Profitability", baseWeight: 0.2, effectiveWeight: 0.2, score: 83, verdict: "Pass", status: "ok" },
  { key: "step5", label: "Debt", baseWeight: 0.3, effectiveWeight: 0.3, score: 84, verdict: "Pass", status: "ok" },
];

describe("OverallAssessmentView: the arithmetic block", () => {
  it("lists each step's score, weight and points, then the Steps score, then Steps x multiplier = Overall", () => {
    render(
      <OverallAssessmentView
        result={result({ score: 71, stepsScore: 83.8, moatMultiplier: 0.85, moat: "narrow_moat", breakdown: STEP_ROWS })}
      />,
    );
    const block = screen.getByTestId("score-arithmetic");
    const rows = within(block).getAllByRole("row").map((row) => row.textContent);
    expect(rows[0]).toBe("StepScoreWeightPoints");
    expect(rows[1]).toBe("Financials8430%25.2");
    expect(rows[2]).toBe("Growth Rate8420%16.8");
    expect(rows[3]).toBe("Profitability8320%16.6");
    expect(rows[4]).toBe("Debt8430%25.2");
    expect(rows[5]).toBe("Steps score83.8");
    expect(screen.getByTestId("score-equation")).toHaveTextContent("Steps 83.8 × Narrow moat 0.85 = 71");
  });

  it("shows the Steps score to one decimal even when it is whole", () => {
    render(<OverallAssessmentView result={result({ score: 90, stepsScore: 90, moatMultiplier: 1, breakdown: STEP_ROWS })} />);
    expect(screen.getByTestId("score-equation")).toHaveTextContent("Steps 90.0 × Wide moat 1.0 = 90");
  });

  it("marks an exempt step as not scored and shows the renormalized weights of the others", () => {
    const rows: OverallAssessment["breakdown"] = [
      { ...STEP_ROWS[0], effectiveWeight: 0.428571 },
      { ...STEP_ROWS[1], effectiveWeight: 0.285714 },
      { ...STEP_ROWS[2], effectiveWeight: 0.285714 },
      { key: "step5", label: "Debt", baseWeight: 0.3, effectiveWeight: null, score: null, verdict: "not_supported", status: "exempt" },
    ];
    render(<OverallAssessmentView result={result({ score: 84, stepsScore: 83.7, breakdown: rows })} />);
    const block = screen.getByTestId("score-arithmetic");
    expect(within(block).getByText("not scored for this company")).toBeInTheDocument();
    expect(within(block).getByText("42.9%")).toBeInTheDocument();
  });

  it("is absent when the assessment is incomplete", () => {
    render(<OverallAssessmentView result={result({ status: "incomplete", score: null, stepsScore: null, moatMultiplier: null, verdict: null, incompleteSteps: ["Debt"] })} />);
    expect(screen.queryByTestId("score-arithmetic")).not.toBeInTheDocument();
  });
});

describe("OverallAssessmentView: the multiplier description (dynamic)", () => {
  it("quotes the weights from the breakdown and the saved multipliers", () => {
    render(
      <OverallAssessmentView
        result={result({ breakdown: STEP_ROWS })}
        multipliers={{ wide: 1, narrow: 0.9, noMoat: 0.7 }}
      />,
    );
    const note = screen.getByTestId("weighting-note");
    expect(note).toHaveTextContent("Financials 30%, Growth Rate 20%, Profitability 20%, Debt 30%");
    expect(note).toHaveTextContent("Wide moat × 1.0, Narrow moat × 0.90, No moat × 0.70");
    expect(note).toHaveTextContent("A ticker with no Moat rated is scored as No moat");
    expect(within(note).getByRole("link", { name: "Adjust the weights" })).toHaveAttribute("href", "/settings?section=score-weighting");
    expect(within(note).getByRole("link", { name: "the Narrow multiplier" })).toHaveAttribute("href", "/settings?section=economic-moat");
  });

  it("follows a custom weight set and an exempt step (renormalized shares)", () => {
    const rows = STEP_ROWS.map((r, i) => ({ ...r, effectiveWeight: [0.5, 0.1, 0.1, 0.3][i] }));
    render(<OverallAssessmentView result={result({ breakdown: rows })} />);
    expect(screen.getByTestId("weighting-note")).toHaveTextContent("Financials 50%, Growth Rate 10%, Profitability 10%, Debt 30%");
  });
});

describe("OverallAssessmentView: Moat not rated", () => {
  it("shows the note and scores the ticker as No moat with a normal verdict pill", () => {
    render(
      <OverallAssessmentView
        result={result({
          score: 56,
          stepsScore: 80,
          moatMultiplier: 0.7,
          moat: null,
          moatNote: "Moat not rated, scored as No moat",
          verdict: "Fail",
          breakdown: STEP_ROWS,
        })}
      />,
    );
    expect(screen.getByTestId("moat-not-rated-note")).toHaveTextContent("Moat not rated, scored as No moat");
    expect(screen.getByText("Fail", { selector: "span" })).toBeInTheDocument(); // the verdict is read from the score; no neutral pill
    expect(screen.queryByText("Moat not rated", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByTestId("score-equation")).toHaveTextContent("Steps 80.0 × No moat 0.70 = 56");
  });

  it("shows no note for a rated ticker", () => {
    render(<OverallAssessmentView result={result({})} />);
    expect(screen.queryByTestId("moat-not-rated-note")).not.toBeInTheDocument();
  });
});


describe("OverallAssessmentView: the Review status block", () => {
  const STORED = {
    overall_verdict: "Pass",
    review_status: "review_unclear",
    review_reasons: [
      {
        step: "step5",
        score: 43,
        verdict: "Fail",
        hint: "unclear",
        raw_hint: "unclear",
        guarded: false,
        rule: "not_covered",
        evidence: "Debt/EBITDA 3.59x (borderline_fail): outside +/-20%",
      },
    ],
    conviction: "high",
  } as unknown as Parameters<typeof OverallAssessmentView>[0]["stored"];

  it("lists the status, the conviction and each reason with its evidence", () => {
    render(<OverallAssessmentView result={result({})} stored={STORED} />);
    const block = screen.getByTestId("review-status");
    expect(block).toHaveTextContent("Review (unclear)");
    expect(block).toHaveTextContent("Conviction: high");
    expect(block).toHaveTextContent("Debt scored 43 (Fail): Debt/EBITDA 3.59x (borderline_fail): outside +/-20%");
    expect(block).toHaveClass("text-warn");
  });

  it("uses the deeper caution tone for a structural reading and the guarded sentence for a guarded one", () => {
    const guarded = {
      ...STORED!,
      review_status: "data_uncertain",
      review_reasons: [{ ...STORED!.review_reasons![0], hint: "data_uncertain", raw_hint: "structural", guarded: true }],
    } as unknown as Parameters<typeof OverallAssessmentView>[0]["stored"];
    render(<OverallAssessmentView result={result({})} stored={guarded} />);
    expect(screen.getByTestId("review-status")).toHaveTextContent("If the data is confirmed this would read Review (structural).");
    cleanup();
    const structural = { ...STORED!, review_status: "review_structural" } as unknown as Parameters<typeof OverallAssessmentView>[0]["stored"];
    render(<OverallAssessmentView result={result({})} stored={structural} />);
    expect(screen.getByTestId("review-status")).toHaveClass("text-caution");
  });

  it("shows nothing when the stored verdict is not the one the card computes live", () => {
    render(<OverallAssessmentView result={result({ verdict: "Fail", score: 60 })} stored={STORED} />);
    expect(screen.queryByTestId("review-status")).not.toBeInTheDocument();
  });

  it("renders nothing for a null status, a missing row or an incomplete assessment", () => {
    const none = { ...STORED!, review_status: null, review_reasons: null } as unknown as Parameters<typeof OverallAssessmentView>[0]["stored"];
    const { rerender } = render(<OverallAssessmentView result={result({})} stored={none} />);
    expect(screen.queryByTestId("review-status")).not.toBeInTheDocument();
    rerender(<OverallAssessmentView result={result({})} stored={null} />);
    expect(screen.queryByTestId("review-status")).not.toBeInTheDocument();
    rerender(<OverallAssessmentView result={result({ status: "incomplete", score: null, verdict: null, incompleteSteps: ["Debt"] })} stored={STORED} />);
    expect(screen.queryByTestId("review-status")).not.toBeInTheDocument();
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OverallAssessmentView } from "@/components/overall/OverallAssessmentCard";
import type { OverallAssessment } from "@/lib/overallScore";

afterEach(cleanup);

const expand = () => fireEvent.click(screen.getByRole("button", { name: /Show calculation/ }));

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
    weakSteps: [],
    cautionReasons: [],
    ...overrides,
  };
}

describe("OverallAssessmentView: the failing and caution notes", () => {
  it("shows no note when nothing failed or passed with caution", () => {
    render(<OverallAssessmentView result={result({})} />);
    expect(screen.queryByText(/worth reviewing/)).not.toBeInTheDocument();
  });

  it("names the failing steps in a warn-toned note", () => {
    render(<OverallAssessmentView result={result({ verdict: "Fail", score: 60, failingSteps: ["Debt", "Growth Rate"] })} />);
    const note = screen.getByText(/Debt and Growth Rate may not pass — reflected in the weighted score above/);
    expect(note).toHaveClass("text-not-pass");
  });

  it("names the pass-with-caution steps in a caution-toned note", () => {
    render(<OverallAssessmentView result={result({ verdict: "Pass with caution", cautionSteps: ["Debt"], cautionReasons: ["step_caution"] })} />);
    const note = screen.getByTestId("tiebreaker-caution-note");
    expect(note).toHaveTextContent(/^Warning: Passed with caution: Debt — a real breach was excused by its tiebreaker/);
    expect(note).toHaveClass("text-caution");
    expect(screen.queryByTestId("failing-steps-note")).toBeNull();
    expect(screen.queryByTestId("weak-step-caution-note")).toBeNull();
  });

  it("names the weak steps for a Pass with caution that came from a step below the pass line", () => {
    render(
      <OverallAssessmentView
        result={result({ verdict: "Pass with caution", weakSteps: ["Profitability"], failingSteps: ["Profitability"], cautionReasons: ["weak_step"] })}
      />,
    );
    const note = screen.getByTestId("weak-step-caution-note");
    expect(note).toHaveTextContent(/Passed with caution: Profitability may not pass — the overall score is 70 or more/);
    expect(note).toHaveClass("text-caution");
    // The grey failing-steps line would only repeat the amber one, so it is hidden on a Pass with caution.
    expect(screen.queryByTestId("failing-steps-note")).toBeNull();
    expect(screen.queryByText(/reflected in the weighted score above/)).toBeNull();
    // None of the Step 5 tiebreaker wording appears for this reason alone.
    expect(screen.queryByText(/a real breach was excused/)).toBeNull();
  });

  it("shows both notes when a step caution and a weak step both apply", () => {
    render(
      <OverallAssessmentView
        result={result({
          verdict: "Pass with caution",
          cautionSteps: ["Debt"],
          weakSteps: ["Financials", "Profitability"],
          failingSteps: ["Financials", "Profitability"],
          cautionReasons: ["step_caution", "weak_step"],
        })}
      />,
    );
    expect(screen.getByTestId("tiebreaker-caution-note")).toHaveTextContent(/Passed with caution: Debt — a real breach was excused/);
    expect(screen.getByTestId("weak-step-caution-note")).toHaveTextContent(/Financials and Profitability may not pass.*these steps are under the pass line/);
    expect(screen.queryByTestId("failing-steps-note")).toBeNull();
  });

  it("keeps the failing-steps line on a May not pass verdict, beside no caution line", () => {
    render(<OverallAssessmentView result={result({ verdict: "Fail", score: 60, failingSteps: ["Financials", "Debt", "Growth Rate"] })} />);
    expect(screen.getByTestId("failing-steps-note")).toHaveTextContent(/Financials, Debt and Growth Rate may not pass — reflected in the weighted score above/);
    expect(screen.queryByTestId("weak-step-caution-note")).toBeNull();
    expect(screen.queryByTestId("tiebreaker-caution-note")).toBeNull();
  });

  it("starts both amber lines with 'Passed with caution:' and joins several steps naturally", () => {
    render(
      <OverallAssessmentView
        result={result({
          verdict: "Pass with caution",
          cautionSteps: ["Debt", "Growth Rate"],
          weakSteps: ["Financials", "Growth Rate", "Profitability"],
          cautionReasons: ["step_caution", "weak_step"],
        })}
      />,
    );
    expect(screen.getByTestId("tiebreaker-caution-note")).toHaveTextContent(/^Warning: Passed with caution: Debt and Growth Rate — /);
    expect(screen.getByTestId("weak-step-caution-note")).toHaveTextContent(/^Warning: Passed with caution: Financials, Growth Rate and Profitability may not pass — /);
  });

  it("shows no weak-step note unless the verdict came from one", () => {
    render(<OverallAssessmentView result={result({ weakSteps: ["Debt"], failingSteps: ["Debt"], verdict: "Fail", cautionReasons: [] })} />);
    expect(screen.queryByTestId("weak-step-caution-note")).toBeNull();
  });

  it("draws each note's warning as an aria-hidden icon in the note's own tone, never as an emoji", () => {
    const { container } = render(
      <OverallAssessmentView result={result({ verdict: "Fail", score: 60, failingSteps: ["Debt"], cautionSteps: ["Growth Rate"] })} />,
    );
    expect(container.textContent).not.toMatch(/[\u26A0\uFE0F]/);
    const notes = [screen.getByText(/Debt may not pass/), screen.getByText(/Passed with caution: Growth Rate/)];
    for (const note of notes) {
      expect(note.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
      expect(note.querySelector(".sr-only")).toHaveTextContent("Warning:");
    }
    expect(notes[0]).toHaveClass("text-not-pass");
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
  it("lists each step's score, weight and points, then the Fundamentals score, then Fundamentals x multiplier = Overall", () => {
    render(
      <OverallAssessmentView
        result={result({ score: 71, stepsScore: 83.8, moatMultiplier: 0.85, moat: "narrow_moat", breakdown: STEP_ROWS })}
      />,
    );
    expand();
    const block = screen.getByTestId("score-arithmetic");
    const rows = within(block).getAllByRole("row").map((row) => row.textContent);
    expect(rows[0]).toBe("FundamentalScoreWeightPoints");
    expect(rows[1]).toBe("Financials8430%25.2");
    expect(rows[2]).toBe("Growth Rate8420%16.8");
    expect(rows[3]).toBe("Profitability8320%16.6");
    expect(rows[4]).toBe("Debt8430%25.2");
    expect(rows[5]).toBe("Fundamentals score83.8");
    expect(screen.getByTestId("score-equation")).toHaveTextContent("Fundamentals 83.8 × Narrow moat 0.85 = 71");
  });

  it("shows the Fundamentals score to one decimal even when it is whole", () => {
    render(<OverallAssessmentView result={result({ score: 90, stepsScore: 90, moatMultiplier: 1, breakdown: STEP_ROWS })} />);
    expect(screen.getByTestId("score-equation")).toHaveTextContent("Fundamentals 90.0 × Wide moat 1.0 = 90");
  });

  it("marks an exempt step as not scored and shows the renormalized weights of the others", () => {
    const rows: OverallAssessment["breakdown"] = [
      { ...STEP_ROWS[0], effectiveWeight: 0.428571 },
      { ...STEP_ROWS[1], effectiveWeight: 0.285714 },
      { ...STEP_ROWS[2], effectiveWeight: 0.285714 },
      { key: "step5", label: "Debt", baseWeight: 0.3, effectiveWeight: null, score: null, verdict: "not_supported", status: "exempt" },
    ];
    render(<OverallAssessmentView result={result({ score: 84, stepsScore: 83.7, breakdown: rows })} />);
    expand();
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
    expand();
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
    expand();
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
    expect(screen.getByText("May not pass", { selector: "span" })).toBeInTheDocument(); // the verdict is read from the score; no neutral pill
    expect(screen.queryByText("Moat not rated", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByTestId("score-equation")).toHaveTextContent("Fundamentals 80.0 × No moat 0.70 = 56");
  });

  it("shows no note for a rated ticker", () => {
    render(<OverallAssessmentView result={result({})} />);
    expect(screen.queryByTestId("moat-not-rated-note")).not.toBeInTheDocument();
  });
});


const rows4 = (scores: [number, string][]): OverallAssessment["breakdown"] =>
  STEP_ROWS.map((r, i) => ({ ...r, score: scores[i][0], verdict: scores[i][1] }));

describe("OverallAssessmentView: no breakdown pills", () => {
  it("has no row of 'Label · weight · score' pills under the header (score and weight live in the table)", () => {
    render(<OverallAssessmentView result={result({ breakdown: STEP_ROWS, stepsScore: 83.8 })} />);
    expect(screen.queryByText(/Financials · 30%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ · 30% · /)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/·\s*\d+%\s*·/);
  });

  it("keeps the verdict label and the 'N of 4 weighted components' line", () => {
    render(<OverallAssessmentView result={result({ breakdown: STEP_ROWS, stepsScore: 83.8 })} />);
    expect(screen.getByText("Pass", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("4 of 4 weighted components at Pass level or better.")).toBeInTheDocument();
  });
});

describe("OverallAssessmentView: the collapsible calculation", () => {
  const props = { score: 71, stepsScore: 83.8, moatMultiplier: 0.85, moat: "narrow_moat" as const, breakdown: STEP_ROWS };

  it("is collapsed by default: only the one-line result and the toggle show", () => {
    render(<OverallAssessmentView result={result(props)} />);
    const toggle = screen.getByRole("button", { name: /Show calculation/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("score-equation")).toHaveTextContent("Fundamentals 83.8 × Narrow moat 0.85 = 71");
    expect(screen.queryByTestId("score-arithmetic")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weighting-note")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Adjust the weights" })).not.toBeInTheDocument();
  });

  it("expands to the table, the result line (once) and the paragraph with its links, and collapses again", () => {
    render(<OverallAssessmentView result={result(props)} />);
    expand();
    const toggle = screen.getByRole("button", { name: /Hide calculation/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("score-arithmetic")).toBeInTheDocument();
    expect(screen.getAllByTestId("score-equation")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Adjust the weights" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "the Narrow multiplier" })).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /Show calculation/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("score-arithmetic")).not.toBeInTheDocument();
    expect(screen.getByTestId("score-equation")).toBeInTheDocument();
  });

  it("is collapsed again on every fresh render (the state is not persisted)", () => {
    const first = render(<OverallAssessmentView result={result(props)} />);
    expand();
    first.unmount();
    render(<OverallAssessmentView result={result(props)} />);
    expect(screen.getByRole("button", { name: /Show calculation/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the failing and caution warning lines outside the collapsible, visible in both states", () => {
    render(<OverallAssessmentView result={result({ ...props, verdict: "Fail", score: 60, failingSteps: ["Debt"], cautionSteps: ["Growth Rate"] })} />);
    for (let pass = 0; pass < 2; pass++) {
      expect(screen.getByText(/Debt may not pass — reflected/)).toBeInTheDocument();
      expect(screen.getByText(/Passed with caution: Growth Rate/)).toBeInTheDocument();
      expect(screen.getByTestId("calculation")).not.toContainElement(screen.getByText(/Debt may not pass — reflected/));
      fireEvent.click(screen.getAllByRole("button", { name: /calculation/ })[0]);
    }
  });
});

describe("OverallAssessmentView: score colouring in the table", () => {
  it("colours each score by the pills' own thresholds: Fail slate (not-pass), 70-90 green, over 90 the deeper green, caution tone for a caution verdict", () => {
    const rows = rows4([[60, "Fail"], [72, "Pass"], [80, "Pass"], [95, "Strong Pass"]]);
    render(<OverallAssessmentView result={result({ stepsScore: 77, breakdown: rows })} />);
    expand();
    expect(screen.getByTestId("score-step1")).toHaveClass("text-not-pass");
    expect(screen.getByTestId("score-step2")).toHaveClass("text-positive");
    expect(screen.getByTestId("score-step4")).toHaveClass("text-positive");
    expect(screen.getByTestId("score-step5")).toHaveClass("text-positive-strong");
    cleanup();
    render(<OverallAssessmentView result={result({ stepsScore: 77, breakdown: rows4([[74, "Pass with caution"], [80, "Pass"], [80, "Pass"], [80, "Pass"]]) })} />);
    expand();
    expect(screen.getByTestId("score-step1")).toHaveClass("text-caution");
  });

  it("does not colour the weight, points or Fundamentals score cells", () => {
    render(<OverallAssessmentView result={result({ stepsScore: 77, breakdown: rows4([[60, "Fail"], [72, "Pass"], [80, "Pass"], [95, "Strong Pass"]]) })} />);
    expand();
    const row = within(screen.getByTestId("score-step1").closest("tr") as HTMLElement).getAllByRole("cell");
    expect(row[2].className).not.toMatch(/text-(negative|warn|positive|caution)/);
    expect(row[3].className).not.toMatch(/text-(negative|warn|positive|caution)/);
    const stepsRow = within(screen.getByText("Fundamentals score").closest("tr") as HTMLElement).getAllByRole("cell");
    for (const cell of stepsRow) expect(cell.className).not.toMatch(/text-(negative|warn|positive|caution)/);
  });
});

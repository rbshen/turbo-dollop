// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OverallAssessmentView } from "@/components/overall/OverallAssessmentCard";
import type { OverallAssessment } from "@/lib/overallScore";

afterEach(cleanup);

function result(overrides: Partial<OverallAssessment>): OverallAssessment {
  return {
    status: "complete",
    score: 70,
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

describe("OverallAssessmentView: Moat not rated", () => {
  it("shows a neutral Moat not rated pill and the reason line, keeping the steps-only score", () => {
    render(
      <OverallAssessmentView
        result={result({ score: 81, verdict: "moat_not_rated", verdictReason: "Moat not rated: rate the moat to enable a Pass" })}
      />,
    );
    const pill = screen.getByText("Moat not rated");
    expect(pill).toHaveClass("text-text-secondary"); // the neutral tone, not a Pass colour
    expect(screen.queryByText(/^Pass$/i)).not.toBeInTheDocument();
    expect(screen.getByText("Moat not rated: rate the moat to enable a Pass")).toBeInTheDocument();
    expect(screen.getByText("81")).toBeInTheDocument();
  });

  it("shows no reason line for a normal verdict", () => {
    render(<OverallAssessmentView result={result({})} />);
    expect(screen.queryByText(/rate the moat/)).not.toBeInTheDocument();
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

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

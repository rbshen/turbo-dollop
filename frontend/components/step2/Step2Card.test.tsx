// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Step2Card, step2Methodology } from "@/components/step2/Step2Card";
import type { Step2Out } from "@/lib/api/types";
import { useStep2 } from "@/lib/hooks/useStep2";

vi.mock("@/lib/hooks/useStep2", () => ({ useStep2: vi.fn() }));
const mockedStep2 = vi.mocked(useStep2);

function step2(weights: Record<string, number>): Step2Out {
  return {
    ticker: "AAPL",
    score: 88,
    verdict: "Pass",
    growth_rate: 12.5,
    estimate_spread: 8,
    estimates: [],
    growth_catalysts: [],
    components: {
      magnitude: { score: 85, tier: "solid", growth_rate: 12.5 },
      agreement: { score: 100, tier: "tight", spread: 8 },
    },
    weights,
  } as unknown as Step2Out;
}

function serve(data: Step2Out) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedStep2.mockReturnValue({ data, error: undefined, isLoading: false } as any);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("step2Methodology", () => {
  it("is today's sentence at the default 70/30", () => {
    expect(step2Methodology({ magnitude: 0.7, agreement: 0.3 })).toBe(
      "70% projected growth magnitude, 30% analyst estimate agreement (spread as a % of the average estimate); " +
        "negative growth always fails regardless of the blended score.",
    );
  });

  it("follows the saved weights", () => {
    expect(step2Methodology({ magnitude: 0.6, agreement: 0.4 })).toContain("60% projected growth magnitude, 40% analyst estimate agreement");
  });

  it("says a component weighted 0 is shown but not counted, instead of quoting 0%", () => {
    const noAgreement = step2Methodology({ magnitude: 1, agreement: 0 });
    expect(noAgreement).toContain("100% projected growth magnitude");
    expect(noAgreement).toContain("is shown but not counted");
    expect(noAgreement).not.toContain("0% analyst");
  });
});

describe("Step2Card", () => {
  it("renders the note and the per-bullet weights from the step payload, not from constants", () => {
    serve(step2({ magnitude: 0.6, agreement: 0.4 }));
    render(<Step2Card ticker="AAPL" />);
    fireEvent.click(screen.getByText("Show reasoning"));
    expect(screen.getByText(/60% projected growth magnitude, 40% analyst estimate agreement/)).toBeInTheDocument();
    expect(screen.getByText(/Growth Magnitude \(60%, 85\/100\)/)).toBeInTheDocument();
    expect(screen.getByText(/Estimate Agreement \(40%, 100\/100\)/)).toBeInTheDocument();
  });
});

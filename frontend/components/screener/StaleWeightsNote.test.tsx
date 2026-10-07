// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StaleWeightsNote } from "@/components/screener/StaleWeightsNote";
import type { TickerScoreOut } from "@/lib/api/types";

const h = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/hooks/useScoreWeights", () => ({ useScoreWeights: () => ({ data: h.data }) }));

const row = (weights_version: number | null) => ({ weights_version }) as unknown as TickerScoreOut;

afterEach(() => {
  cleanup();
  h.data = undefined;
});

describe("StaleWeightsNote", () => {
  it("says how many listed scores are still on the previous weights, muted", () => {
    h.data = { weights_version: 3, recompute: null };
    render(<StaleWeightsNote rows={[row(2), row(2), row(3), row(null)]} />);
    const note = screen.getByTestId("stale-weights-note");
    expect(note).toHaveTextContent("2 scores are still on the previous weights.");
    expect(note).toHaveClass("text-text-tertiary");
  });

  it("counts rows scored under an older Overall formula too (the multiplier redesign), whatever their weights version", () => {
    h.data = { weights_version: 3, formula_version: 2, recompute: null };
    const rows = [
      { weights_version: 3, formula_version: 2 },
      { weights_version: 3, formula_version: null },
      { weights_version: 3, formula_version: 1 },
    ] as unknown as TickerScoreOut[];
    render(<StaleWeightsNote rows={rows} />);
    expect(screen.getByTestId("stale-weights-note")).toHaveTextContent("2 scores are still on the previous weights.");
  });

  it("adds that a recompute is running while one is", () => {
    h.data = { weights_version: 3, recompute: { state: "running" } };
    render(<StaleWeightsNote rows={[row(2)]} />);
    expect(screen.getByTestId("stale-weights-note")).toHaveTextContent("1 score is still on the previous weights (recomputing now).");
  });

  it("renders nothing when every listed row is current, or before anything has loaded", () => {
    h.data = { weights_version: 3, recompute: null };
    const { container, rerender } = render(<StaleWeightsNote rows={[row(3), row(null)]} />);
    expect(container).toBeEmptyDOMElement();
    h.data = undefined;
    rerender(<StaleWeightsNote rows={[row(1)]} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<StaleWeightsNote rows={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});

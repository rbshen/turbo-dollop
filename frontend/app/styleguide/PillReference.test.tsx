// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PillReference } from "./PillReference";

afterEach(cleanup);

// Smoke test: the styleguide's pill reference renders from mock data alone
// (no API/hooks) and shows every representation the design system defines.
describe("PillReference", () => {
  it("renders every pill family representation from mock data", () => {
    render(<PillReference />);

    // Jobs statuses
    for (const word of ["Success", "Failed", "Overdue", "Skipped", "Unknown"]) {
      expect(screen.getAllByText(word).length).toBeGreaterThan(0);
    }

    // Sentence-case labels, and the index chip is neutral
    expect(screen.getAllByText("Wide moat").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Speculative growth").length).toBeGreaterThan(0);
    const index = screen.getAllByText("S&P 500 · Nasdaq")[0];
    expect(index.className).toContain("bg-surface-2");

    // Watchlist Rating stays coloured text, not a pill
    const rating = screen.getByText("HOLD");
    expect(rating.className).toMatch(/text-warn/);
    expect(rating.className).not.toMatch(/bg-/);
  });

  it("shows the ticker header in both widths", () => {
    render(<PillReference />);
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(2);
    for (const h1 of headings) {
      const header = h1.closest("div.space-y-3") as HTMLElement;
      expect(within(header).getByText("Strong pass")).toBeInTheDocument();
      expect(within(header).getByText("Stage 3 · Top")).toBeInTheDocument();
    }
  });
});

// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScoreBadge } from "@/components/step1/ScoreBadge";

afterEach(cleanup);

describe("ScoreBadge (Screener card)", () => {
  it("draws any Overall verdict in its own tone and label (an unrated ticker reads its verdict from its x0.7 score)", () => {
    render(<ScoreBadge score={56} verdict="Fail" />);
    expect(screen.getByText("56")).toBeInTheDocument();
    expect(screen.getByText("May not pass")).toHaveClass("text-negative-soft");
  });

  it("still tones a real Pass", () => {
    render(<ScoreBadge score={81} verdict="Pass" />);
    expect(screen.getByText("Pass")).toHaveClass("text-positive");
  });
});

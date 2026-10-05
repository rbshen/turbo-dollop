// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScoreBadge } from "@/components/step1/ScoreBadge";

afterEach(cleanup);

describe("ScoreBadge (Screener card)", () => {
  it("shows a Moat not rated ticker's steps-only score above a neutral Moat not rated pill", () => {
    render(<ScoreBadge score={81} verdict="moat_not_rated" />);
    expect(screen.getByText("81")).toBeInTheDocument();
    expect(screen.getByText("Moat not rated")).toHaveClass("text-text-secondary");
    expect(screen.queryByText("Moat_not_rated")).not.toBeInTheDocument();
  });

  it("still tones a real Pass", () => {
    render(<ScoreBadge score={81} verdict="Pass" />);
    expect(screen.getByText("Pass")).toHaveClass("text-positive");
  });
});

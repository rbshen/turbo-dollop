// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CircularScoreBadge } from "@/components/overall/CircularScoreBadge";

afterEach(cleanup);

describe("CircularScoreBadge", () => {
  it("keeps the number neutral and puts the tone on the ring stroke, with no fill", () => {
    render(<CircularScoreBadge score={95} verdict="Strong Pass" />);
    const number = screen.getByText("95");
    expect(number.className).toContain("text-text-primary");
    expect(number.className).not.toMatch(/text-positive/);
    const ring = number.parentElement as HTMLElement;
    expect(ring.className).toContain("border-positive-strong");
    expect(ring.className).not.toMatch(/bg-/);
  });

  it.each([
    [50, "Fail", "border-not-pass"],
    [74, "Pass with caution", "border-caution"],
    [72, "Pass", "border-positive"],
    [80, "Pass", "border-positive"],
  ])("score %s / %s uses %s", (score, verdict, cls) => {
    render(<CircularScoreBadge score={score} verdict={verdict} />);
    expect((screen.getByText(String(score)).parentElement as HTMLElement).className).toContain(cls);
  });
});

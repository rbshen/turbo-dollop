// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChartPrimitivesReference } from "./ChartPrimitivesReference";

afterEach(cleanup);

describe("ChartPrimitivesReference", () => {
  it("draws every state of every primitive, with no tooltip anywhere", () => {
    const { container } = render(<ChartPrimitivesReference />);
    // gauge states
    const states = new Set(Array.from(container.querySelectorAll("[data-state]")).map((el) => el.getAttribute("data-state")));
    expect(states).toEqual(new Set(["ok", "monitor", "breach", "missing"]));
    // diverging tones
    const tones = new Set(Array.from(container.querySelectorAll("[data-tone]")).map((el) => el.getAttribute("data-tone")));
    expect(tones).toEqual(new Set(["ahead", "behind", "in_line", "missing"]));
    // price positions
    const positions = new Set(Array.from(container.querySelectorAll("[data-position]")).map((el) => el.getAttribute("data-position")));
    expect(positions).toEqual(new Set(["below", "inside", "above"]));
    // all four stages and the unavailable timeline
    const stages = new Set(Array.from(container.querySelectorAll("[data-testid=stage-run]")).map((el) => el.getAttribute("data-stage")));
    expect(stages).toEqual(new Set(["base", "advance", "top", "decline"]));
    expect(screen.getAllByText("Fewer than 40 weeks of cached history").length).toBeGreaterThan(0);
    expect(screen.getByText("Debt is not applied to insurers")).toBeTruthy();
    expect(screen.getAllByText(/No fair value: no valuation method applies/).length).toBeGreaterThan(0);
    expect(screen.getByText("No price history")).toBeTruthy();
    expect(container.querySelectorAll("[title]")).toHaveLength(0); // inline text only
  });

  it("stacks the narrow rows by container width", () => {
    const { container } = render(<ChartPrimitivesReference />);
    expect(container.querySelectorAll(".\\@container").length).toBeGreaterThanOrEqual(6);
    expect(container.querySelector(".w-\\[320px\\]")).not.toBeNull();
  });
});

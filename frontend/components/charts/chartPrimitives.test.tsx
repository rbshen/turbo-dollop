// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DivergingBar } from "@/components/charts/DivergingBar";
import { PriceRangeBar } from "@/components/charts/PriceRangeBar";
import { Sparkline } from "@/components/charts/Sparkline";
import { StageTimeline } from "@/components/charts/StageTimeline";
import { ThresholdGauge } from "@/components/charts/ThresholdGauge";
import { VisualRow } from "@/components/charts/VisualRow";

afterEach(cleanup);

const x = (n: number) => `${n.toFixed(1)}x`;

describe("ThresholdGauge", () => {
  it("is neutral inside the pass line, with no amber anywhere", () => {
    const { container } = render(<ThresholdGauge value={2.1} passLine={3} hardLimit={4} direction="ceiling" format={x} label="Debt / EBITDA" />);
    expect(screen.getByRole("img").getAttribute("data-state")).toBe("ok");
    expect(screen.getByTestId("gauge-fill").className).toContain("bg-text-tertiary");
    expect(screen.getByTestId("gauge-fill").className).not.toContain("warn");
    expect(screen.getAllByTestId("gauge-tick")).toHaveLength(2);
    expect(screen.getByText("2.1x")).toBeTruthy();
    expect(screen.getByText("Passes at 3.0x or lower · hard limit 4.0x")).toBeTruthy();
    expect(container.querySelector(".bg-warn\\/20")).not.toBeNull(); // the monitor zone is drawn, tinted
  });

  it("turns the fill amber in the monitor zone and past the hard limit, and clamps an extreme value", () => {
    const { rerender } = render(<ThresholdGauge value={3.5} passLine={3} hardLimit={4} direction="ceiling" format={x} />);
    expect(screen.getByRole("img").getAttribute("data-state")).toBe("monitor");
    expect(screen.getByTestId("gauge-fill").className).toContain("bg-warn");
    rerender(<ThresholdGauge value={84.6} passLine={3} hardLimit={4} direction="ceiling" format={x} />);
    expect(screen.getByRole("img").getAttribute("data-state")).toBe("breach");
    expect(screen.getByText("84.6x ›")).toBeTruthy();
    expect((screen.getByTestId("gauge-fill") as HTMLElement).style.width).toBe("100%");
  });

  it("floor: a ratio under the pass line is the breach", () => {
    render(<ThresholdGauge value={0.8} passLine={1} hardLimit={0.7} direction="floor" format={x} />);
    expect(screen.getByRole("img").getAttribute("data-state")).toBe("monitor");
    expect(screen.getByText("Passes at 1.0x or higher · hard limit 0.7x")).toBeTruthy();
  });

  it("one line only: a single tick, no zone, no hard limit in the caption", () => {
    const { container } = render(<ThresholdGauge value={38} passLine={45} direction="ceiling" format={(n) => `${n}%`} />);
    expect(screen.getAllByTestId("gauge-tick")).toHaveLength(1);
    expect(container.querySelector(".bg-warn\\/20")).toBeNull();
    expect(screen.getByText("Passes at 45% or lower")).toBeTruthy();
  });

  it("missing data and not applicable", () => {
    const { rerender } = render(<ThresholdGauge value={null} passLine={3} hardLimit={4} direction="ceiling" format={x} />);
    expect(screen.getByText("No data")).toBeTruthy();
    expect(screen.queryByTestId("gauge-fill")).toBeNull();
    rerender(<ThresholdGauge value={1} passLine={3} direction="ceiling" format={x} notApplicable="Debt is not applied to insurers" />);
    expect(screen.getByText("Debt is not applied to insurers")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("DivergingBar", () => {
  it("green ahead, red behind, neutral inside the band", () => {
    const { rerender } = render(<DivergingBar value={8} band={2} scale={20} />);
    expect(screen.getByTestId("diverging-bar").className).toContain("bg-positive");
    expect(screen.getByText("+8.0%")).toBeTruthy();
    rerender(<DivergingBar value={-8} band={2} scale={20} />);
    expect(screen.getByTestId("diverging-bar").className).toContain("bg-negative");
    expect(screen.getByText("−8.0%")).toBeTruthy();
    rerender(<DivergingBar value={1.2} band={2} scale={20} />);
    expect(screen.getByTestId("diverging-bar").className).toContain("bg-text-tertiary");
    expect(screen.getByText("in line")).toBeTruthy();
  });

  it("writes the stock's and the benchmark's own returns next to the gap", () => {
    render(<DivergingBar value={3.1} band={2} scale={20} stockReturn={12.1} benchmarkReturn={9} benchmarkLabel="XLK" />);
    expect(screen.getByText("stock +12.1% · XLK +9.0%")).toBeTruthy();
  });

  it("missing data draws the axis and the band only", () => {
    render(<DivergingBar value={null} band={2} scale={20} />);
    expect(screen.getByText("No data")).toBeTruthy();
    expect(screen.queryByTestId("diverging-bar")).toBeNull();
    expect(screen.getByTestId("diverging-band")).toBeTruthy();
  });
});

describe("StageTimeline", () => {
  const weeks = [
    { week: "2025-11-03", stage: "advance" },
    { week: "2025-11-10", stage: "advance" },
    { week: "2025-11-17", stage: "top" },
    { week: "2025-11-24", stage: "decline" },
    { week: "2025-12-01", stage: "decline" },
  ];

  it("draws a segment per run in the Weinstein pill's tones and marks the switch date", () => {
    render(<StageTimeline weeks={weeks} since="2025-11-24" />);
    const runs = screen.getAllByTestId("stage-run");
    expect(runs.map((r) => r.getAttribute("data-stage"))).toEqual(["advance", "top", "decline"]);
    expect(runs[0].className).toContain("bg-positive");
    expect(runs[1].className).toContain("bg-warn");
    expect(runs[2].className).toContain("bg-negative");
    expect((screen.getByTestId("stage-since-marker") as HTMLElement).style.left).toBe("60%");
    expect(screen.getByText(/^Since /)).toBeTruthy();
    expect(screen.getByText("Stage 4 · Decline")).toBeTruthy();
  });

  it("a lower-bound since date reads 'Since at least' with the data-starts caveat", () => {
    render(<StageTimeline weeks={[{ week: "2025-11-03", stage: "advance" }, { week: "2025-11-10", stage: "advance" }]} since="2025-11-03" sinceIsLowerBound />);
    expect(screen.getByText(/Since at least/)).toBeTruthy();
    expect(screen.getByText(/Data starts here/)).toBeTruthy();
  });

  it("base is neutral", () => {
    render(<StageTimeline weeks={[{ week: "2025-11-03", stage: "base" }, { week: "2025-11-10", stage: "base" }]} />);
    expect(screen.getByTestId("stage-run").className).toContain("bg-text-tertiary");
  });

  it("unavailable and empty states show the reason instead of a strip", () => {
    const { rerender } = render(<StageTimeline weeks={[]} unavailableReason="Fewer than 40 weeks of cached history" />);
    expect(screen.getByText("Fewer than 40 weeks of cached history")).toBeTruthy();
    expect(screen.queryByTestId("stage-run")).toBeNull();
    rerender(<StageTimeline weeks={[]} />);
    expect(screen.getByText("No stage history yet")).toBeTruthy();
  });
});

describe("PriceRangeBar", () => {
  it("places the price against the band in words, all neutral", () => {
    const { container } = render(<PriceRangeBar price={80} fairValue={100} />);
    expect(screen.getByRole("img").getAttribute("data-position")).toBe("below");
    expect(screen.getByText("Price is 20.0% below fair value, below the fair-value band")).toBeTruthy();
    expect(screen.getByText("$90.00")).toBeTruthy();
    expect(screen.getByText("$110.00")).toBeTruthy();
    expect(container.innerHTML).not.toMatch(/positive|negative|warn/);
  });

  it("inside and above the band", () => {
    const { rerender } = render(<PriceRangeBar price={103} fairValue={100} />);
    expect(screen.getByText("Price is 3.0% above fair value, inside the fair-value band")).toBeTruthy();
    rerender(<PriceRangeBar price={125} fairValue={100} />);
    expect(screen.getByRole("img").getAttribute("data-position")).toBe("above");
  });

  it("no fair value shows the reason and the price in words", () => {
    render(<PriceRangeBar price={42} fairValue={null} unavailableReason="no valuation method applies" />);
    expect(screen.getByText("No fair value: no valuation method applies")).toBeTruthy();
    expect(screen.getByText("Price $42.00")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("no price keeps the fair value", () => {
    render(<PriceRangeBar price={null} fairValue={100} />);
    expect(screen.getByText("Fair value $100.00")).toBeTruthy();
    expect(screen.getByText(/No price to compare/)).toBeTruthy();
  });
});

describe("Sparkline", () => {
  it("draws the line in the one-series colour with an end dot and the end captions", () => {
    const { container } = render(<Sparkline values={[10, 12, 11, 15]} startLabel="Oct 2021" endLabel="Oct 2026" format={(n) => `$${n}`} />);
    expect(container.querySelector("polyline")?.getAttribute("stroke")).toBe("var(--color-series-1)");
    expect(screen.getByTestId("sparkline-end")).toBeTruthy();
    expect(screen.getByText("Oct 2021")).toBeTruthy();
    expect(screen.getByText("$15")).toBeTruthy();
  });

  it("under two points it says so instead of drawing", () => {
    render(<Sparkline values={[10]} />);
    expect(screen.getByText("No price history")).toBeTruthy();
  });
});

describe("VisualRow", () => {
  it("stacks by container width: flex-col by default, a row only from the container's xl", () => {
    const { container } = render(
      <VisualRow label="Debt / EBITDA" pill={<span>pill</span>}>
        <div>visual</div>
      </VisualRow>,
    );
    expect(container.firstElementChild?.className).toContain("@container");
    const inner = container.querySelector(".flex-col") as HTMLElement;
    expect(inner.className).toContain("@xl:flex-row");
    expect(inner.firstElementChild?.textContent).toBe("Debt / EBITDApill"); // label and pill first, the visual after
  });
});

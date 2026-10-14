// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { SectorBarChart } from "@/components/sectors/SectorBarChart";
import type { SectorHeatmapRowOut } from "@/lib/api/types";

afterEach(cleanup);

const WINDOWS = ["1d", "1w", "1m", "3m", "6m", "9m", "ytd", "1y"];

function makeRow(ticker: string, name: string, byWindow: Record<string, number | null>): SectorHeatmapRowOut {
  return {
    ticker,
    name,
    cells: Object.fromEntries(
      WINDOWS.map((w) => [w, { return_pct: byWindow[w] ?? null, base_date: byWindow[w] == null ? null : "2025-12-31" }])
    ),
  };
}

const ROWS = [
  makeRow("XLK", "Technology", { "1d": -0.04, "3m": -5.93, "1y": 38.05 }),
  makeRow("XLE", "Energy", { "1d": 1.8, "3m": 20.46, "1y": 40.6 }),
  makeRow("XLC", "Communication Services", { "1d": 0.74, "3m": 1.51 }), // no 1y
];

function Harness({ initial = "1d" }: { initial?: string }) {
  const [w, setW] = useState(initial);
  return <SectorBarChart rows={ROWS} window={w} onWindowChange={setW} index={1} />;
}

const order = () => screen.getAllByRole("listitem").map((li) => within(li).getByText(/^XL/).textContent);
const select = () => screen.getByLabelText("Return window, chart 1") as HTMLSelectElement;
const barFor = (name: RegExp) => screen.getByRole("img", { name });
const tickValues = () => Array.from(screen.getByTestId("axis").querySelectorAll("[data-tick]")).map((el) => Number(el.getAttribute("data-tick")));

describe("SectorBarChart", () => {
  it("offers the eight windows, Today first", () => {
    render(<Harness />);
    expect(Array.from(select().options).map((o) => o.textContent)).toEqual(["Today", "1W", "1M", "3M", "6M", "9M", "YTD", "1Y"]);
    expect(select().value).toBe("1d");
  });

  it("sorts descending by the selected window and re-sorts when it changes", () => {
    render(<Harness />);
    expect(order()).toEqual(["XLE", "XLC", "XLK"]);
    fireEvent.change(select(), { target: { value: "3m" } });
    expect(order()).toEqual(["XLE", "XLC", "XLK"]);
    fireEvent.change(select(), { target: { value: "1y" } });
    expect(order()).toEqual(["XLE", "XLK", "XLC"]); // XLC has no 1y: sinks last
  });

  it("draws positive bars right of the zero line in green and negative bars left in red, with signed 2-decimal labels", () => {
    render(<Harness initial="3m" />);
    const zero = parseFloat(screen.getAllByTestId("zero-line")[0].style.left);

    const up = barFor(/Energy/);
    expect(up.getAttribute("data-direction")).toBe("positive");
    expect(up.className).toContain("bg-positive");
    expect(parseFloat(up.style.left)).toBeCloseTo(zero, 5);
    expect(parseFloat(up.style.width)).toBeGreaterThan(0);

    const down = barFor(/Technology/);
    expect(down.getAttribute("data-direction")).toBe("negative");
    expect(down.className).toContain("bg-negative");
    expect(parseFloat(down.style.left) + parseFloat(down.style.width)).toBeCloseTo(zero, 5);

    expect(screen.getByText("+20.46%")).toBeInTheDocument();
    expect(screen.getByText("-5.93%")).toBeInTheDocument();
  });

  it("scales bar length to the value", () => {
    render(<Harness initial="3m" />);
    const width = (name: RegExp) => parseFloat(barFor(name).style.width);
    expect(width(/Energy/) / width(/Technology/)).toBeCloseTo(20.46 / 5.93, 3);
  });

  it("shows n/a with no bar for a sector missing the window, and ignores it for the axis", () => {
    render(<Harness initial="1y" />);
    expect(screen.getByText("n/a")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Communication/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(screen.getByText("Communication Services")).toBeInTheDocument();
  });

  it("refits the axis to the selected window's own range", () => {
    render(<Harness />);
    const today = tickValues();
    expect(Math.max(...today)).toBeLessThan(5);
    fireEvent.change(select(), { target: { value: "1y" } });
    const year = tickValues();
    expect(Math.max(...year)).toBeGreaterThanOrEqual(40.6);
    expect(year).not.toEqual(today);
    expect(year).toContain(0);
  });

  it("has no links and no tooltips", () => {
    const { container } = render(<Harness />);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(container.querySelector("[title]")).toBeNull();
  });
});

// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataQualityFlagsNote } from "@/components/ticker/DataQualityFlagsNote";
import type { DataQualityFlagOut } from "@/lib/api/types";
import { useTickerDataQuality } from "@/lib/hooks/useDataQualityFlags";

vi.mock("@/lib/hooks/useDataQualityFlags");
const mockedHook = vi.mocked(useTickerDataQuality);

afterEach(cleanup);

function flag(id: number, detail: string, over: Partial<DataQualityFlagOut> = {}): DataQualityFlagOut {
  return {
    id,
    ticker: "MU",
    check: "zero_newest_capex",
    field: "capitalExpenditure",
    fiscal_year: "2026",
    fmp_value: 0,
    comparison_value: -1,
    kind: "zero_line",
    detail,
    found_at: "2026-10-10T03:26:00",
    last_seen_at: "2026-10-10T03:26:00",
    reviewed_at: null,
    ...over,
  };
}

function mockData(data: DataQualityFlagOut[] | undefined) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  mockedHook.mockReturnValue({ data } as any);
}

describe("DataQualityFlagsNote", () => {
  it("renders nothing while loading or when the ticker has no open flags", () => {
    mockData(undefined);
    const { container, rerender } = render(<DataQualityFlagsNote ticker="MU" />);
    expect(container).toBeEmptyDOMElement();
    mockData([]);
    rerender(<DataQualityFlagsNote ticker="MU" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows each open flag as a plain amber line, nothing red and no pill", () => {
    mockData([flag(1, "FY2026 capex is 0 in the newest row, so free cash flow may be overstated.")]);
    render(<DataQualityFlagsNote ticker="MU" />);
    const line = screen.getByText(/FY2026 capex is 0 in the newest row/);
    expect(line.className).toMatch(/text-warn/);
    expect(document.body.innerHTML).not.toMatch(/negative|bg-warn|border-warn/);
  });

  it("asks for the ticker's own flags and caps the note at three lines", () => {
    mockData([1, 2, 3, 4].map((id) => flag(id, `line ${id}`, { check: "net_income_disagreement", kind: "large_gap" })));
    render(<DataQualityFlagsNote ticker="MU" />);
    expect(mockedHook).toHaveBeenCalledWith("MU");
    const lines = screen.getByTestId("data-quality-note").querySelectorAll("p");
    expect(lines).toHaveLength(3);
    expect(lines[2].textContent).toContain("2 more in Settings > Data quality.");
  });
});

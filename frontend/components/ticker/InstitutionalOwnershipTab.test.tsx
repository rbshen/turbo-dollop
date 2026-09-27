// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InstitutionalOwnershipTab } from "@/components/ticker/InstitutionalOwnershipTab";
import { useInstitutionalOwnership } from "@/lib/hooks/useInstitutionalOwnership";
import type { InstitutionalOwnershipOut } from "@/lib/api/types";

// jsdom has no layout, so ResponsiveContainer would render a 0x0 chart --
// same fixed-size stub MarketBreadthCharts.test.tsx uses.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number; height?: number }> }) =>
      cloneElement(children, { width: 800, height: 200 }),
  };
});

vi.mock("@/lib/hooks/useInstitutionalOwnership");
const mockedHook = vi.mocked(useInstitutionalOwnership);

afterEach(cleanup);

function mockResult(overrides: Partial<{ data: InstitutionalOwnershipOut | undefined; error: Error | undefined; isLoading: boolean }>) {
  mockedHook.mockReturnValue({
    data: undefined,
    error: undefined,
    isLoading: false,
    isValidating: false,
    mutate: vi.fn(),
    ...overrides,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

const BASE: InstitutionalOwnershipOut = {
  ticker: "AAPL",
  enabled: true,
  no_coverage: false,
  as_of_quarter: "2026Q2",
  as_of_date: "2026-06-30",
  fetched_at: "2026-08-10T00:00:00",
  data_stale_warning: false,
  ownership_valid: true,
  ownership_percent: 66.49,
  ownership_percent_change: 2.55,
  holder_count: 6471,
  holder_count_change: 67,
  shares_held: 9_780_538_684,
  shares_outstanding: 14_710_718_204,
  shares_outstanding_source: "marketCap / price (latest quote)",
  sentiment: "Accumulating",
  sentiment_rising_count: 3,
  positions: {
    opened: 213,
    opened_change: 8,
    increased: 2792,
    increased_change: 174,
    reduced: 2968,
    reduced_change: -140,
    closed: 183,
    closed_change: -30,
  },
  trend: [
    { year: 2026, quarter: 2, date: "2026-06-30", ownership_percent: 66.49, ownership_percent_change: 2.55, investors_holding: 6471, investors_holding_change: 67 },
    { year: 2026, quarter: 1, date: "2026-03-31", ownership_percent: 63.94, ownership_percent_change: -0.8, investors_holding: 6404, investors_holding_change: 6 },
  ],
  trend_quarters_shown: 2,
  trend_quarters_total: 8,
  top_holders: [
    { investor_name: "BLACKROCK, INC.", market_value: 336_524_794_350, market_value_change_pct: 15.84, shares: 1_162_996_939, shares_change_pct: 1.6 },
  ],
  note: null,
};

describe("InstitutionalOwnershipTab", () => {
  it("shows a loading state", () => {
    mockResult({ isLoading: true });
    render(<InstitutionalOwnershipTab ticker="AAPL" />);
    expect(screen.getByText(/Loading/)).toBeInTheDocument();
  });

  it("shows an error state", () => {
    mockResult({ error: new Error("boom") });
    render(<InstitutionalOwnershipTab ticker="AAPL" />);
    expect(screen.getByText(/Couldn't load Institutional Ownership/)).toBeInTheDocument();
  });

  it("shows a plain note when the data group is disabled", () => {
    mockResult({ data: { ...BASE, enabled: false } });
    render(<InstitutionalOwnershipTab ticker="AAPL" />);
    expect(screen.getByText(/turned off/)).toBeInTheDocument();
    expect(screen.queryByText("Institutional Ownership", { selector: "h2" })).toBeInTheDocument();
  });

  it("shows a distinct note when there's genuinely no 13F coverage", () => {
    mockResult({ data: { ...BASE, enabled: true, no_coverage: true } });
    render(<InstitutionalOwnershipTab ticker="CNSWF" />);
    expect(screen.getByText(/No 13F institutional-ownership data found for CNSWF/)).toBeInTheDocument();
  });

  it("renders the full stat cards, positions, trend, and top holders for a normal ticker", () => {
    mockResult({ data: BASE });
    render(<InstitutionalOwnershipTab ticker="AAPL" />);

    expect(screen.getByText("66.5%")).toBeInTheDocument();
    expect(screen.getByText("6471")).toBeInTheDocument();
    expect(screen.getByText("Accumulating")).toBeInTheDocument();
    expect(screen.getByText("3 of last 4 quarters rising")).toBeInTheDocument();
    expect(screen.getByText("213")).toBeInTheDocument(); // opened positions
    expect(screen.getByText("BLACKROCK, INC.")).toBeInTheDocument();
    expect(screen.getByText("2 of 8 quarters shown")).toBeInTheDocument();
  });

  it("degrades the stat cards to a note when the latest quarter fails plausibility, but still renders positions and top holders", () => {
    mockResult({
      data: {
        ...BASE,
        ownership_valid: false,
        ownership_percent: null,
        ownership_percent_change: null,
        holder_count: null,
        holder_count_change: null,
        shares_held: null,
        sentiment: null,
        sentiment_rising_count: null,
        note: "This quarter's institutional-ownership figures look unreliable and have been hidden.",
      },
    });
    render(<InstitutionalOwnershipTab ticker="ARES" />);

    expect(screen.getByText(/look unreliable/)).toBeInTheDocument();
    expect(screen.queryByText("Accumulating")).not.toBeInTheDocument();
    // Positions and top holders are unaffected.
    expect(screen.getByText("213")).toBeInTheDocument();
    expect(screen.getByText("BLACKROCK, INC.")).toBeInTheDocument();
  });

  it("shows a stale-data warning only when data_stale_warning is true", () => {
    mockResult({ data: { ...BASE, data_stale_warning: true } });
    render(<InstitutionalOwnershipTab ticker="AAPL" />);
    expect(screen.getByText(/hasn't refreshed in a while/)).toBeInTheDocument();
  });

  it("shows a no-holders note when top_holders is empty", () => {
    mockResult({ data: { ...BASE, top_holders: [] } });
    render(<InstitutionalOwnershipTab ticker="AAPL" />);
    expect(screen.getByText("No institutional holders reported this quarter.")).toBeInTheDocument();
  });
});

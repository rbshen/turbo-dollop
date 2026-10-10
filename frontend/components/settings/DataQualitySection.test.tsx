// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mutate } from "swr";

import { DataQualitySection } from "@/components/settings/DataQualitySection";
import * as client from "@/lib/api/client";
import type { DataQualityFlagOut, DataQualityFlagsOut, DataQualityScope } from "@/lib/api/types";
import { useDataQualityFlags } from "@/lib/hooks/useDataQualityFlags";

vi.mock("swr", async (importOriginal) => ({ ...(await importOriginal<typeof import("swr")>()), mutate: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPost: vi.fn(),
}));
vi.mock("@/lib/hooks/useDataQualityFlags");
const mockedHook = vi.mocked(useDataQualityFlags);

beforeEach(() => {
  vi.mocked(client.apiPost).mockReset();
  vi.mocked(mutate).mockReset();
});
afterEach(cleanup);

function flag(over: Partial<DataQualityFlagOut>): DataQualityFlagOut {
  return {
    id: 1,
    ticker: "MU",
    check: "zero_newest_capex",
    field: "capitalExpenditure",
    fiscal_year: "2026",
    fmp_value: 0,
    comparison_value: -15857000000,
    kind: "zero_line",
    detail: "FY2026 capex is 0 in the newest row, so free cash flow may be overstated.",
    found_at: "2026-10-10T03:26:00",
    last_seen_at: "2026-10-10T03:26:00",
    reviewed_at: null,
    ...over,
  };
}

function mockData(flags: DataQualityFlagOut[], over: Partial<DataQualityFlagsOut> = {}) {
  mockedHook.mockImplementation(
    (scope: DataQualityScope) =>
      ({
        data: { scope, flags, open_watchlisted: flags.length, open_all: flags.length + 4, ...over },
        error: undefined,
      }) as never,
  );
}

describe("DataQualitySection", () => {
  it("has a sentence-case heading with the open count and says nothing here changes a score", () => {
    mockData([flag({})]);
    render(<DataQualitySection />);
    expect(screen.getByRole("heading", { name: /Data quality/ })).toHaveTextContent("1 open");
    expect(screen.getByText(/nothing here changes a score or a verdict/)).toBeInTheDocument();
  });

  it("is a plain table: ticker, check, fiscal year, FMP and compared values, kind, found date", () => {
    mockData([flag({}), flag({ id: 2, ticker: "WTW", check: "net_income_disagreement", field: "netIncome", fiscal_year: "2024", fmp_value: -98e6, comparison_value: 1248e6, kind: "sign_differs", detail: "opposite signs", found_at: "2026-10-09T03:26:00" })]);
    render(<DataQualitySection />);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3); // header + two flags, newest first as the API sent them
    expect(within(rows[1]).getByRole("link", { name: "MU" })).toHaveAttribute("href", "/tickers/MU");
    expect(within(rows[1]).getByText("FY2026")).toBeInTheDocument();
    expect(within(rows[1]).getByText("-$15.86B")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Line missing")).toBeInTheDocument();
    expect(within(rows[1]).getByText("2026-10-10")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Net income disagreement", { exact: false })).toBeInTheDocument();
    expect(within(rows[2]).getByText("$1.25B")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Opposite signs")).toBeInTheDocument();
  });

  it("uses plain amber for the kind, no red, no pill, no banner", () => {
    mockData([flag({})]);
    render(<DataQualitySection />);
    expect(screen.getByText("Line missing").className).toMatch(/text-warn/);
    expect(document.body.innerHTML).not.toMatch(/text-negative|bg-warn|border-warn/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("defaults to watchlisted tickers and switches to all", () => {
    mockData([flag({})]);
    render(<DataQualitySection />);
    expect(mockedHook).toHaveBeenLastCalledWith("watchlisted");
    fireEvent.click(screen.getByRole("button", { name: "All tickers" }));
    expect(mockedHook).toHaveBeenLastCalledWith("all");
    expect(screen.getByRole("heading", { name: /Data quality/ })).toHaveTextContent("5 open");
  });

  it("shows an empty state, and mentions the other tickers when only they have flags", () => {
    mockData([], { open_watchlisted: 0, open_all: 7 });
    render(<DataQualitySection />);
    expect(screen.getByText(/No open flags on your watchlisted tickers\./)).toBeInTheDocument();
    expect(screen.getByText(/7 open on other tracked tickers/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "All tickers" }));
    expect(screen.getByText("No open flags.")).toBeInTheDocument();
  });

  it("marks a flag reviewed and revalidates the lists", async () => {
    mockData([flag({})]);
    vi.mocked(client.apiPost).mockResolvedValue({});
    render(<DataQualitySection />);
    fireEvent.click(screen.getByRole("button", { name: /Mark reviewed: MU, Zero newest capex, FY2026/ }));
    await waitFor(() => expect(client.apiPost).toHaveBeenCalledWith("/data-quality/flags/1/review"));
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
  });

  it("shows the server's reason when marking fails, and keeps the row", async () => {
    mockData([flag({})]);
    vi.mocked(client.apiPost).mockRejectedValue(new Error("boom"));
    render(<DataQualitySection />);
    fireEvent.click(screen.getByRole("button", { name: /Mark reviewed/ }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "MU" })).toBeInTheDocument();
  });

  it("says so when the flags cannot be loaded", () => {
    mockedHook.mockReturnValue({ data: undefined, error: new Error("x") } as never);
    render(<DataQualitySection />);
    expect(screen.getByText("Could not load the data-quality flags.")).toBeInTheDocument();
  });
});

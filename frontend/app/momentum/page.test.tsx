// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

import MomentumPage from "@/app/momentum/page";
import type { EtfMomentumOut, MomentumOut } from "@/lib/api/types";

afterEach(cleanup);

const CURRENT: MomentumOut = {
  as_of_date: "2026-08-31",
  computed_at: "2026-09-08T07:11:15.217090",
  rows: [
    {
      ticker: "SNDK",
      company_name: "Sandisk Corporation",
      moat: "no_moat",
      return_3mo: -0.0757,
      return_6mo: 1.4658,
      return_12mo: 28.859,
      composite_score: 10.083,
      rank: 1,
      overall_score: 47,
      return_1w: 0.0123,
      return_1mo: -0.0456,
      last_price: 1234.5,
      quote_currency: "USD",
    },
  ],
};

const EMPTY: MomentumOut = { as_of_date: null, computed_at: null, rows: [] };

const ETF_CURRENT: EtfMomentumOut = {
  as_of_date: "2026-09-30",
  computed_at: "2026-10-05T07:00:00",
  total_ranked: 61,
  rows: [
    {
      ticker: "SOXL",
      company_name: "Direxion Daily Semiconductor Bull 3X",
      return_3mo: 0.4,
      return_6mo: 0.9,
      return_12mo: 2.1,
      composite_score: 1.1333,
      rank: 1,
      return_1w: 0.02,
      return_1mo: 0.1,
      last_price: 55.25,
    },
  ],
};

const ETF_PREVIOUS: EtfMomentumOut = {
  ...ETF_CURRENT,
  as_of_date: "2026-08-31",
  rows: [{ ...ETF_CURRENT.rows[0], ticker: "TQQQ", company_name: "ProShares UltraPro QQQ" }],
};

// A fresh SWRConfig cache per test, matching the "fresh cache provider"
// pattern SWR's own docs recommend for tests -- this codebase has no prior
// SWR-mocking precedent to follow, so the isolation itself (rather than a
// specific existing convention) is what matters here.
function renderPage() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <MomentumPage />
    </SWRConfig>
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const parsed = new URL(url, "http://localhost");
      const period = parsed.searchParams.get("period");
      const isEtf = parsed.pathname.endsWith("/momentum/etf");
      const body = isEtf ? (period === "previous" ? ETF_PREVIOUS : ETF_CURRENT) : period === "previous" ? EMPTY : CURRENT;
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    })
  );
});

const stock = () => within(screen.getByRole("region", { name: "Stock" }));
const etf = () => within(screen.getByRole("region", { name: "ETF" }));

describe("MomentumPage", () => {
  it("shows a pulsing row skeleton in each section before data arrives", () => {
    const { container } = renderPage();
    // 10 stock rows + 5 ETF rows.
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(15);
  });

  it("renders a Stock and an ETF section, each with a title, below the page title", async () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "Momentum" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Stock" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "ETF" })).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Stock", "ETF"]);
    await waitFor(() => expect(etf().getByText("SOXL")).toBeInTheDocument());
  });

  it("renders the current month's data in both sections once loaded", async () => {
    renderPage();
    await waitFor(() => expect(stock().getByText("SNDK")).toBeInTheDocument());
    await waitFor(() => expect(etf().getByText("SOXL")).toBeInTheDocument());
    expect(etf().getByText("Direxion Daily Semiconductor Bull 3X")).toBeInTheDocument();
    expect(stock().getByText(/As of/)).toBeInTheDocument();
    expect(etf().getByText(/As of/)).toBeInTheDocument();
  });

  it("the ETF table has no Moat or Score columns; the Stock table keeps them", async () => {
    renderPage();
    await waitFor(() => expect(etf().getByText("SOXL")).toBeInTheDocument());
    await waitFor(() => expect(stock().getByText("SNDK")).toBeInTheDocument());
    expect(stock().getByText("Moat")).toBeInTheDocument();
    expect(stock().getByText("Score")).toBeInTheDocument();
    expect(etf().queryByText("Moat")).not.toBeInTheDocument();
    expect(etf().queryByText("Score")).not.toBeInTheDocument();
    // Every other column is there, including Last and the return columns.
    for (const name of ["Rank", "Ticker", "Last", "1 w", "1 mo", "3 mo", "6 mo", "12 mo", "Composite"]) {
      expect(etf().getByText(name)).toBeInTheDocument();
    }
    // Null quote_currency falls back to USD.
    expect(etf().getByText("$55.25")).toBeInTheDocument();
  });

  it("has two independent period toggles", async () => {
    renderPage();
    await waitFor(() => expect(stock().getByText("SNDK")).toBeInTheDocument());
    await waitFor(() => expect(etf().getByText("SOXL")).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: "Previous month" })).toHaveLength(2);

    // Flipping the ETF toggle changes only the ETF section.
    fireEvent.click(etf().getByRole("button", { name: "Previous month" }));
    await waitFor(() => expect(etf().getByText("TQQQ")).toBeInTheDocument());
    expect(etf().queryByText("SOXL")).not.toBeInTheDocument();
    expect(stock().getByText("SNDK")).toBeInTheDocument();
    expect(stock().getByRole("button", { name: "This month" })).toHaveAttribute("aria-pressed", "true");

    // Flipping the Stock toggle changes only the Stock section.
    fireEvent.click(stock().getByRole("button", { name: "Previous month" }));
    await waitFor(() => expect(stock().getByText("No previous month's snapshot available yet.")).toBeInTheDocument());
    expect(stock().queryByText("SNDK")).not.toBeInTheDocument();
    expect(etf().getByText("TQQQ")).toBeInTheDocument();
  });

  it("there is no page-level period toggle (one per section)", async () => {
    renderPage();
    await waitFor(() => expect(stock().getByText("SNDK")).toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: "This month" })).toHaveLength(2);
    expect(screen.getAllByRole("group")).toHaveLength(2);
  });

  it("shows the Moat caveat under Stock only, and the ETF footnote under ETF only", async () => {
    renderPage();
    await waitFor(() => expect(stock().getByText("SNDK")).toBeInTheDocument());
    expect(stock().getByText(/Point-in-time caveat/)).toBeInTheDocument();
    expect(etf().queryByText(/Point-in-time caveat/)).not.toBeInTheDocument();
    const note = etf().getByText(/Price-only basis/);
    expect(note).toHaveTextContent(/split-adjusted/);
    expect(note).toHaveTextContent(/no dividends/);
    expect(note).toHaveTextContent(/Leveraged funds are included/);
    expect(note).toHaveTextContent(/today's ETF universe/);
    expect(stock().queryByText(/Price-only basis/)).not.toBeInTheDocument();
  });

  it("the ad hoc disclaimer is always visible, not behind any collapse toggle", async () => {
    renderPage();
    await waitFor(() => expect(stock().getByText("SNDK")).toBeInTheDocument());
    expect(screen.getByText(/Ad hoc external research/)).toBeInTheDocument();
  });

  it("an ETF fetch failure shows an error in the ETF section only", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (new URL(url, "http://localhost").pathname.endsWith("/momentum/etf")) {
          return new Response("boom", { status: 500 });
        }
        return new Response(JSON.stringify(CURRENT), { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );
    renderPage();
    await waitFor(() => expect(etf().getByText("Failed to load ETF Momentum data.")).toBeInTheDocument());
    await waitFor(() => expect(stock().getByText("SNDK")).toBeInTheDocument());
    expect(stock().queryByText(/Failed to load/)).not.toBeInTheDocument();
  });
});

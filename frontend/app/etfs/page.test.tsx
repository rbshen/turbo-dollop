// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EtfsPage from "@/app/etfs/page";
import type { EtfScreenerMeta, EtfScreenerRowOut, SavedEtfFilter, WatchlistOut } from "@/lib/api/types";
import { DEFAULT_ETF_FILTER_STATE } from "@/lib/etfScreenerFilters";

// Page-level tests for the ETFs page: rows, filtering, sorting, the empty states, and the saved-view round trip. The
// data hooks and the add-to-watchlist button are mocked; the sidebar, the card, the saved-views bar and the page's own
// state are real.
const h = vi.hoisted(() => ({
  rows: undefined as unknown[] | undefined,
  error: undefined as Error | undefined,
  meta: undefined as unknown,
  watchlists: [] as unknown[],
  saved: [] as unknown[],
  save: vi.fn(),
  del: vi.fn(),
}));

vi.mock("@/lib/hooks/useEtfScreener", () => ({
  useEtfScreener: () => ({ data: h.rows, error: h.error }),
  useEtfScreenerMeta: () => ({ data: h.meta }),
}));
vi.mock("@/lib/hooks/useWatchlists", () => ({ useWatchlists: () => ({ data: h.watchlists }) }));
vi.mock("@/lib/hooks/useSavedEtfFilters", () => ({
  useSavedEtfFilters: () => ({ data: h.saved }),
  saveEtfFilter: (...args: unknown[]) => h.save(...args),
  deleteEtfFilter: (...args: unknown[]) => h.del(...args),
}));
vi.mock("@/components/ticker/AddToWatchlistButton", () => ({
  AddToWatchlistButton: ({ tickers }: { tickers: string[] }) => <span data-testid="add-to-watchlist">{tickers.join(",")}</span>,
}));

function etf(ticker: string, overrides: Partial<EtfScreenerRowOut> = {}): EtfScreenerRowOut {
  return {
    ticker,
    name: `${ticker} fund`,
    asset_class: "Equity",
    expense_ratio: 0.1,
    aum: 1e9,
    last_price: 100,
    pct_change_1d: 0.5,
    beta: 1,
    return_1y: 10,
    vs_spy_1y: 0,
    weinstein_stage: null,
    weinstein_stage_since_date: null,
    weinstein_stage_since_is_lower_bound: null,
    weinstein_ma_slope_pct: null,
    weinstein_vs_ma_pct: null,
    weinstein_pending_direction: null,
    bb_rsi_entry_signal: null,
    warren_active_signal_kind: null,
    warren_last_buy_fired_at: null,
    as_of_date: null,
    info_updated_at: null,
    updated_at: null,
    ...overrides,
  };
}

const ROWS = [
  etf("SPY", { aum: 5e11, expense_ratio: 0.09 }),
  etf("TLT", { asset_class: "Fixed Income", aum: 5e10, expense_ratio: 0.15, beta: null }),
  etf("GLD", { asset_class: "Commodities", aum: 7e10, expense_ratio: 0.4, beta: null }),
];

function meta(overrides: Partial<EtfScreenerMeta> = {}): EtfScreenerMeta {
  return {
    total_etfs: 3,
    row_count: 3,
    asset_classes: ["Commodities", "Equity", "Fixed Income"],
    ranges: {},
    ...overrides,
  };
}

function watchlist(id: number, name: string, tickers: string[]): WatchlistOut {
  return { id, name, tickers: tickers.map((t) => ({ ticker: t })) } as unknown as WatchlistOut;
}

function savedView(overrides: Partial<SavedEtfFilter> & { name: string }): SavedEtfFilter {
  return {
    id: 1,
    kind: "etf",
    universe: "all",
    sort_field: "aum",
    sort_direction: "desc",
    filters: DEFAULT_ETF_FILTER_STATE,
    watchlist_id: null,
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

const cards = () => screen.queryAllByRole("link").map((a) => a.querySelector("p")?.textContent);
const sortSelect = () => screen.getByLabelText("Sort by") as HTMLSelectElement;
const watchlistSelect = () => screen.getByLabelText(/^Limit results to/) as HTMLSelectElement;
const directionButton = () => screen.getByRole("button", { name: /^Sort direction:/ });

beforeEach(() => {
  h.rows = ROWS;
  h.error = undefined;
  h.meta = meta();
  h.watchlists = [watchlist(1, "ETF", ["SPY", "GLD"]), watchlist(2, "E1", ["TLT"])];
  h.saved = [];
  h.save.mockReset().mockResolvedValue(undefined);
  h.del.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

describe("the ETFs page: shell", () => {
  it("is titled ETFs and has no universe selector or Recompute button", () => {
    render(<EtfsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "ETFs" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /recompute/i })).toBeNull();
    expect(screen.queryByText("S&P 500")).toBeNull();
  });

  it("orders the sidebar Watchlist, Fundamental, Technical, with Watchlist never dimmed", () => {
    render(<EtfsPage />);
    const headings = screen.getAllByRole("heading", { level: 2 }).map((el) => el.textContent);
    expect(headings).toEqual(["Watchlist", "Fundamental", "Technical"]);
    expect(watchlistSelect()).not.toBeDisabled();
  });

  it("offers every watchlist, ETF and E-lists included", () => {
    render(<EtfsPage />);
    expect(Array.from(watchlistSelect().options).map((o) => o.textContent)).toEqual(["None", "ETF", "E1"]);
  });

  it("lists the ETF sort options, AUM first by default, descending", () => {
    render(<EtfsPage />);
    expect(Array.from(sortSelect().options).map((o) => o.textContent)).toEqual([
      "AUM",
      "Expense ratio",
      "Quote",
      "1D change",
      "Beta",
      "1Y vs SPY",
      "Warren signal recency",
      "Weinstein: stage since",
    ]);
    expect(sortSelect().value).toBe("aum");
    expect(directionButton().getAttribute("aria-label")).toContain("descending");
  });
});

describe("rows", () => {
  it("renders a card per ETF, sorted by AUM descending, each a new-tab link to the ticker page", () => {
    render(<EtfsPage />);
    expect(cards()).toEqual(["SPY", "GLD", "TLT"]);
    const link = screen.getByRole("link", { name: /^GLD GLD fund/ });
    expect(link).toHaveAttribute("href", "/tickers/GLD");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("shows a dash for a null beta", () => {
    render(<EtfsPage />);
    const tlt = screen.getByRole("link", { name: /^TLT TLT fund/ });
    expect(within(tlt).getByText("Beta").nextElementSibling).toHaveTextContent("—");
    const spy = screen.getByRole("link", { name: /^SPY SPY fund/ });
    expect(within(spy).getByText("Beta").nextElementSibling).toHaveTextContent("1.00");
  });

  it("subtitle reads 'X of Y ETFs' and adds the match count (no hidden-ticker note since the opt-in universe)", () => {
    h.meta = meta({ total_etfs: 5 });
    render(<EtfsPage />);
    expect(screen.getByText(/^3 of 5 ETFs/)).toHaveTextContent("3 of 5 ETFs");
    expect(screen.queryByText(/not viewed in 30 days/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Asset class/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Equity" }));
    expect(screen.getByText(/^3 of 5 ETFs/)).toHaveTextContent("3 of 5 ETFs — 1 match the current filters");
  });

  it("passes the filtered tickers to Add to watchlist", () => {
    render(<EtfsPage />);
    expect(screen.getByTestId("add-to-watchlist")).toHaveTextContent("SPY,GLD,TLT");
  });
});

describe("filtering", () => {
  it("filters by asset class from the meta options", () => {
    render(<EtfsPage />);
    fireEvent.click(screen.getByRole("button", { name: /^Asset class/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Fixed Income" }));
    expect(cards()).toEqual(["TLT"]);
  });

  it("filters by a range, and an active Beta range drops the dash rows", () => {
    render(<EtfsPage />);
    const expense = screen.getByRole("group", { name: /Expense ratio/ });
    fireEvent.change(within(expense).getByLabelText("Maximum"), { target: { value: "0.15" } });
    expect(cards()).toEqual(["SPY", "TLT"]);
    const beta = screen.getByRole("group", { name: /^Beta/ });
    fireEvent.change(within(beta).getByLabelText("Minimum"), { target: { value: "0.5" } });
    expect(cards()).toEqual(["SPY"]);
  });

  it("scopes to a watchlist", () => {
    render(<EtfsPage />);
    fireEvent.change(watchlistSelect(), { target: { value: "1" } });
    expect(cards()).toEqual(["SPY", "GLD"]);
    expect(screen.getByText(/2 of 2 "ETF" tickers/)).toBeInTheDocument();
  });

  it("says so when no ETF matches the filters", () => {
    render(<EtfsPage />);
    const aum = screen.getByRole("group", { name: /AUM/ });
    fireEvent.change(within(aum).getByLabelText("Minimum"), { target: { value: "1T" } });
    expect(screen.getByText("No ETFs match the current filters.")).toBeInTheDocument();
    expect(screen.queryByText(/hasn't been loaded yet/)).toBeNull();
  });
});

describe("sorting", () => {
  it("sorts by the picked field and flips the direction", () => {
    render(<EtfsPage />);
    fireEvent.change(sortSelect(), { target: { value: "expense_ratio" } });
    expect(cards()).toEqual(["GLD", "TLT", "SPY"]);
    fireEvent.click(directionButton());
    expect(cards()).toEqual(["SPY", "TLT", "GLD"]);
  });
});

describe("empty and partial states", () => {
  it("explains an empty table (ETFs in the universe, no rows yet) instead of a blank grid", () => {
    h.rows = [];
    h.meta = meta({ total_etfs: 20, row_count: 0, asset_classes: [] });
    render(<EtfsPage />);
    expect(screen.getByText("ETF data hasn't been loaded yet. It is filled by the nightly ETF job.")).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.getByText(/^0 of 20 ETFs/)).toBeInTheDocument();
  });

  it("shows loading and error in the results area, with the sidebar still mounted", () => {
    h.rows = undefined;
    const { unmount } = render(<EtfsPage />);
    expect(screen.getByText("Loading ETFs…")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "ETFs" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fundamental" })).toBeInTheDocument();
    unmount();
    h.error = new Error("boom");
    render(<EtfsPage />);
    expect(screen.getByText("Failed to load the ETFs.")).toBeInTheDocument();
  });
});

describe("saved views (kind=etf)", () => {
  function openSavedViews() {
    fireEvent.click(screen.getByRole("button", { name: /^(Saved views|Cheap|Gone)/ }));
  }

  it("saves the current ETF view: all universe, ETF sort field and ETF filter state, watchlist", async () => {
    render(<EtfsPage />);
    fireEvent.change(sortSelect(), { target: { value: "expense_ratio" } });
    fireEvent.click(directionButton());
    fireEvent.change(watchlistSelect(), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /^Asset class/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Equity" }));

    fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "Cheap equity" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByRole("button", { name: /Cheap equity/ });
    expect(h.save).toHaveBeenCalledTimes(1);
    expect(h.save).toHaveBeenCalledWith("Cheap equity", {
      universe: "all",
      sort_field: "expense_ratio",
      sort_direction: "asc",
      filters: { ...DEFAULT_ETF_FILTER_STATE, assetClasses: ["Equity"] },
      watchlist_id: 1,
    });
  });

  it("loads a saved view: filters, sort, direction and watchlist; a missing key falls back to the default", () => {
    h.saved = [
      savedView({
        name: "Cheap",
        sort_field: "expense_ratio",
        sort_direction: "asc",
        // an older view without the newer keys
        filters: { assetClasses: ["Fixed Income"], aum: { min: null, max: 1e11 } } as never,
        watchlist_id: 2,
      }),
    ];
    render(<EtfsPage />);
    openSavedViews();
    fireEvent.click(within(screen.getByRole("group", { name: "Saved views" })).getByRole("button", { name: "Cheap" }));
    expect(sortSelect().value).toBe("expense_ratio");
    expect(directionButton().getAttribute("aria-label")).toContain("ascending");
    expect(watchlistSelect().value).toBe("2");
    expect(cards()).toEqual(["TLT"]);
  });

  it("falls back to no watchlist when the saved one is gone", () => {
    h.saved = [savedView({ name: "Gone", watchlist_id: 99 })];
    render(<EtfsPage />);
    openSavedViews();
    fireEvent.click(within(screen.getByRole("group", { name: "Saved views" })).getByRole("button", { name: "Gone" }));
    expect(watchlistSelect().value).toBe("");
    expect(cards()).toEqual(["SPY", "GLD", "TLT"]);
  });

  it("deletes a saved view through the ETF delete call", async () => {
    h.saved = [savedView({ name: "Cheap" })];
    render(<EtfsPage />);
    openSavedViews();
    fireEvent.click(screen.getByRole("button", { name: 'Delete view "Cheap"' }));
    await vi.waitFor(() => expect(h.del).toHaveBeenCalledWith("Cheap"));
  });

  it("Reset puts filters, watchlist and sort back to the defaults", () => {
    render(<EtfsPage />);
    fireEvent.change(sortSelect(), { target: { value: "beta" } });
    fireEvent.change(watchlistSelect(), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(sortSelect().value).toBe("aum");
    expect(watchlistSelect().value).toBe("");
    expect(cards()).toEqual(["SPY", "GLD", "TLT"]);
  });
});

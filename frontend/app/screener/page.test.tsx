// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScreenerPage from "@/app/screener/page";
import type { SavedScreenerFilter, TickerScoreOut, WatchlistOut } from "@/lib/api/types";
import { DEFAULT_FILTER_STATE } from "@/lib/screenerFilters";

// Page-level tests for the Screener: what loading a saved view and pressing
// Reset do, and (after the sidebar migration) that the sidebar survives a
// universe switch. The data hooks and the heavy leaf components are mocked; the
// sidebar, the saved-views bar and the page's own state are real.
const h = vi.hoisted(() => ({
  rows: {} as Record<string, unknown[] | undefined>,
  errors: {} as Record<string, Error | undefined>,
  universeCalls: [] as string[],
  watchlists: [] as unknown[],
  saved: [] as unknown[],
}));

vi.mock("@/lib/hooks/useScreener", () => ({
  useScreener: (universe: string) => {
    h.universeCalls.push(universe);
    return { data: h.rows[universe], error: h.errors[universe] };
  },
  useScreenerMeta: () => ({ data: { universe: "all", total_constituents: 500 } }),
}));
vi.mock("@/lib/hooks/useWatchlists", () => ({ useWatchlists: () => ({ data: h.watchlists }) }));
vi.mock("@/lib/hooks/useSavedFilters", () => ({
  useSavedFilters: () => ({ data: h.saved }),
  saveScreenerFilter: vi.fn(),
  deleteScreenerFilter: vi.fn(),
}));
vi.mock("@/components/screener/ScreenerCard", () => ({
  ScreenerCard: ({ data }: { data: { ticker: string } }) => <div data-testid="card">{data.ticker}</div>,
}));
vi.mock("@/components/screener/RecomputeButton", () => ({ RecomputeButton: () => null }));
vi.mock("@/components/ticker/AddToWatchlistButton", () => ({ AddToWatchlistButton: () => null }));

function scoreRow(ticker: string, overrides: Partial<TickerScoreOut> = {}): TickerScoreOut {
  return {
    ticker,
    company_name: ticker,
    sector: "Technology",
    company_type: "Standard",
    is_etf: false,
    overall_score: 50,
    market_cap: 1e9,
    ...overrides,
  } as TickerScoreOut;
}

const ALL_ROWS = [
  scoreRow("AAA", { overall_score: 90, market_cap: 5e12, sector: "Technology" }),
  scoreRow("BBB", { overall_score: 80, market_cap: 2e9, sector: "Healthcare" }),
  scoreRow("CCC", { overall_score: 40, market_cap: 8e8, sector: "Energy" }),
  scoreRow("DDD", { overall_score: null, market_cap: 3e9, sector: "Energy" }),
];

function watchlist(id: number, name: string, tickers: string[]): WatchlistOut {
  return { id, name, tickers: tickers.map((t) => ({ ticker: t })) } as unknown as WatchlistOut;
}

function savedView(overrides: Partial<SavedScreenerFilter> & { name: string }): SavedScreenerFilter {
  return {
    id: 1,
    universe: "all",
    sort_field: "overall_score",
    sort_direction: "desc",
    filters: DEFAULT_FILTER_STATE,
    watchlist_id: null,
    created_at: "",
    updated_at: "",
    ...overrides,
  } as SavedScreenerFilter;
}

const cards = () => screen.queryAllByTestId("card").map((c) => c.textContent);
const lastUniverse = () => h.universeCalls[h.universeCalls.length - 1];
const sortSelect = () => screen.getByDisplayValue(/score|Quote|Market cap|P\/E|Beta|Growth rate|Warren|Weinstein/) as HTMLSelectElement;
const watchlistSelect = () => screen.getByLabelText(/^Watchlist/) as HTMLSelectElement;

// The trigger reads "Saved views (n)", or the name of the view last loaded.
function openSavedViews() {
  fireEvent.click(screen.getByRole("button", { name: /^(Saved views|Big|Old|Legacy|WL|Gone)/ }));
}
function loadSavedView(name: string) {
  openSavedViews();
  fireEvent.click(screen.getByRole("option", { name }));
}

beforeEach(() => {
  h.rows = { all: ALL_ROWS, sp500: ALL_ROWS.slice(0, 3), nasdaq: ALL_ROWS.slice(0, 2), dow: ALL_ROWS.slice(0, 1) };
  h.errors = {};
  h.universeCalls = [];
  h.watchlists = [watchlist(1, "W1", ["AAA", "CCC"]), watchlist(2, "Other", ["BBB"])];
  h.saved = [];
});
afterEach(cleanup);

describe("loading a saved view", () => {
  it("applies its filters, sort, direction and universe", () => {
    h.saved = [
      savedView({
        name: "Big",
        universe: "sp500",
        sort_field: "market_cap",
        sort_direction: "asc",
        filters: { ...DEFAULT_FILTER_STATE, overallScore: { min: 50, max: null } },
      }),
    ];
    render(<ScreenerPage />);
    expect(cards()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
    loadSavedView("Big");
    expect(lastUniverse()).toBe("sp500");
    expect(sortSelect().value).toBe("market_cap");
    expect(screen.getByTitle("Ascending")).toBeInTheDocument();
    // overall >= 50 leaves AAA and BBB, ascending by market cap
    expect(cards()).toEqual(["BBB", "AAA"]);
    expect(screen.getByRole("button", { name: /^Big/ })).toBeInTheDocument();
  });

  it("loads a view saved before newer filter keys existed, with those keys at their defaults", () => {
    h.saved = [savedView({ name: "Old", filters: { overallScore: { min: 85, max: null } } as never })];
    render(<ScreenerPage />);
    loadSavedView("Old");
    expect(cards()).toEqual(["AAA"]);
  });

  it("loads a view carrying the removed 'country' key without complaint", () => {
    h.saved = [
      savedView({ name: "Legacy", filters: { ...DEFAULT_FILTER_STATE, country: ["US"], sectors: ["Energy"] } as never }),
    ];
    render(<ScreenerPage />);
    loadSavedView("Legacy");
    expect(cards()).toEqual(["CCC", "DDD"]);
    expect(screen.queryByText("Failed to load the Screener.")).toBeNull();
  });

  it("scopes to a saved watchlist that still exists, forcing the universe to All", () => {
    h.saved = [savedView({ name: "WL", universe: "sp500", watchlist_id: 1 })];
    render(<ScreenerPage />);
    loadSavedView("WL");
    expect(lastUniverse()).toBe("all");
    expect(watchlistSelect().value).toBe("1");
    expect(cards()).toEqual(["AAA", "CCC"]);
  });

  it("falls back to no watchlist (and the saved universe) when the saved watchlist is gone", () => {
    h.saved = [savedView({ name: "Gone", universe: "nasdaq", watchlist_id: 99 })];
    render(<ScreenerPage />);
    loadSavedView("Gone");
    expect(lastUniverse()).toBe("nasdaq");
    expect(watchlistSelect().value).toBe("");
  });
});

describe("Reset", () => {
  it("clears the filters, the universe, the watchlist and the active view name", () => {
    h.saved = [
      savedView({
        name: "Big",
        universe: "sp500",
        sort_field: "market_cap",
        sort_direction: "asc",
        filters: { ...DEFAULT_FILTER_STATE, overallScore: { min: 50, max: null } },
      }),
    ];
    render(<ScreenerPage />);
    loadSavedView("Big");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    fireEvent.change(watchlistSelect(), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Nasdaq" }));
    expect(lastUniverse()).toBe("nasdaq");
    expect(watchlistSelect()).toBeDisabled();
    expect(watchlistSelect().value).toBe("1"); // kept while dimmed

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    expect(lastUniverse()).toBe("all");
    expect(watchlistSelect().value).toBe("");
    expect(watchlistSelect()).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^Big/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^Saved views/ })).toBeInTheDocument();
    expect(cards().sort()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
  });

  it("today leaves the sort where it was (changed to a reset by the migration)", () => {
    h.saved = [savedView({ name: "Big", sort_field: "market_cap", sort_direction: "asc" })];
    render(<ScreenerPage />);
    loadSavedView("Big");
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(sortSelect().value).toBe("market_cap");
    expect(screen.getByTitle("Ascending")).toBeInTheDocument();
  });
});

// The range boxes hold typed text; Reset and a loaded view must rewrite them.
const box = (group: string, side: "Minimum" | "Maximum") =>
  within(screen.getByRole("group", { name: group })).getByRole("textbox", { name: side }) as HTMLInputElement;
const typeInto = (input: HTMLInputElement, text: string) => {
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: text } });
};

describe("range boxes on the real page", () => {
  it("filter the cards as you type", () => {
    render(<ScreenerPage />);
    typeInto(box("Overall", "Minimum"), "85");
    expect(cards()).toEqual(["AAA"]);
    typeInto(box("Overall", "Minimum"), "1x"); // invalid: that side becomes inactive
    expect(cards()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
    typeInto(box("Mkt cap", "Minimum"), "1B");
    expect(cards()).toEqual(["AAA", "BBB", "DDD"]);
  });

  it("Reset clears a box holding invalid text and every typed box", () => {
    render(<ScreenerPage />);
    typeInto(box("Growth", "Minimum"), "1x");
    typeInto(box("Overall", "Minimum"), "70");
    typeInto(box("Mkt cap", "Maximum"), "5T");
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(box("Growth", "Minimum").value).toBe("");
    expect(box("Overall", "Minimum").value).toBe("");
    expect(box("Mkt cap", "Maximum").value).toBe("");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(cards()).toHaveLength(4);
  });

  it("loading a saved view rewrites the boxes, including one holding invalid text, and shows 1B", () => {
    h.saved = [
      savedView({
        name: "Big",
        filters: { ...DEFAULT_FILTER_STATE, overallScore: { min: 70, max: null }, marketCap: { min: 1e9, max: 5e12 } },
      }),
    ];
    render(<ScreenerPage />);
    typeInto(box("Growth", "Minimum"), "1x");
    loadSavedView("Big");
    expect(box("Overall", "Minimum").value).toBe("70");
    expect(box("Mkt cap", "Minimum").value).toBe("1B");
    expect(box("Mkt cap", "Maximum").value).toBe("5T");
    expect(box("Growth", "Minimum").value).toBe("");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("loads a view saved before newer keys existed, and one with the stale 'country' key, into the boxes", () => {
    h.saved = [
      savedView({ id: 1, name: "Old", filters: { overallScore: { min: 85, max: null } } as never }),
      savedView({ id: 2, name: "Legacy", filters: { ...DEFAULT_FILTER_STATE, country: ["US"], beta: { min: 0.5, max: 2 } } as never }),
    ];
    render(<ScreenerPage />);
    loadSavedView("Old");
    expect(box("Overall", "Minimum").value).toBe("85");
    expect(box("Beta", "Minimum").value).toBe("");
    loadSavedView("Legacy");
    expect(box("Beta", "Minimum").value).toBe("0.5");
    expect(box("Beta", "Maximum").value).toBe("2");
    expect(box("Overall", "Minimum").value).toBe("");
  });
});

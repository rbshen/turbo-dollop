// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScreenerPage from "@/app/screener/page";
import { saveScreenerFilter } from "@/lib/hooks/useSavedFilters";
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
vi.mock("@/components/ticker/AddToWatchlistButton", () => ({
  AddToWatchlistButton: ({ label, audience }: { label?: string; audience?: string }) => (
    <span data-testid="add-to-watchlist-label" data-audience={audience ?? "default"}>
      {label}
    </span>
  ),
}));

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
  scoreRow("AAA", { overall_score: 90, overall_verdict: "Pass", step1_score: 90, market_cap: 5e12, sector: "Technology" }),
  scoreRow("BBB", { overall_score: 80, overall_verdict: "Pass", step1_score: 80, market_cap: 2e9, sector: "Healthcare" }),
  scoreRow("CCC", { overall_score: 40, overall_verdict: "Fail", step1_score: 40, market_cap: 8e8, sector: "Energy" }),
  scoreRow("DDD", { overall_score: null, overall_verdict: null, step1_score: null, market_cap: 3e9, sector: "Energy" }),
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
const sortSelect = () => screen.getByLabelText("Sort by") as HTMLSelectElement;
const directionButton = () => screen.getByRole("button", { name: /^Sort direction: (ascending|descending)\./ });
const isAscending = () => directionButton().getAttribute("aria-label")?.startsWith("Sort direction: ascending") ?? false;
const watchlistSelect = () => screen.getByLabelText(/^Limit results to/) as HTMLSelectElement;

// The trigger reads "Saved views (n)", or the name of the view last loaded.
function openSavedViews() {
  fireEvent.click(screen.getByRole("button", { name: /^(Saved views|Big|Old|Legacy|WL|Gone)/ }));
}
function loadSavedView(name: string) {
  openSavedViews();
  fireEvent.click(within(screen.getByRole("group", { name: "Saved views" })).getByRole("button", { name }));
}

beforeEach(() => {
  h.rows = { all: ALL_ROWS, sp500: ALL_ROWS.slice(0, 3), nasdaq: ALL_ROWS.slice(0, 2), dow: ALL_ROWS.slice(0, 1) };
  h.errors = {};
  h.universeCalls = [];
  h.watchlists = [watchlist(1, "W1", ["AAA", "CCC"]), watchlist(2, "Other", ["BBB"])];
  h.saved = [];
});
afterEach(cleanup);

describe("the results header", () => {
  it("passes the sentence-case Add to watchlist label to the shared button", () => {
    render(<ScreenerPage />);
    expect(screen.getByTestId("add-to-watchlist-label")).toHaveTextContent("Add to watchlist");
  });

  it("uses the default stock audience, so the Add menu hides the ETF list", () => {
    render(<ScreenerPage />);
    expect(screen.getByTestId("add-to-watchlist-label")).toHaveAttribute("data-audience", "default");
  });
});

describe("the ETF-only watchlist", () => {
  beforeEach(() => {
    h.watchlists = [watchlist(1, "W1", ["AAA", "CCC"]), watchlist(7, "ETF", ["SPY"]), watchlist(2, "Other", ["BBB"])];
  });

  it("is not an option of the sidebar Watchlist filter", () => {
    render(<ScreenerPage />);
    expect(Array.from(watchlistSelect().options).map((o) => o.textContent)).toEqual(["None", "W1", "Other"]);
  });

  it("is ignored when a saved view still names it: no watchlist filter, the saved universe applies", () => {
    h.saved = [savedView({ name: "WL", universe: "nasdaq", watchlist_id: 7 })];
    render(<ScreenerPage />);
    loadSavedView("WL");
    expect(lastUniverse()).toBe("nasdaq");
    expect(watchlistSelect().value).toBe("");
    expect(cards()).toEqual(["AAA", "BBB"]); // the whole nasdaq universe, not scoped to the ETF list's SPY
  });
});

describe("loading a saved view", () => {
  it("applies its filters, sort, direction and universe", () => {
    h.saved = [
      savedView({
        name: "Big",
        universe: "sp500",
        sort_field: "market_cap",
        sort_direction: "asc",
        filters: { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Strong Pass", "Pass"] },
      }),
    ];
    render(<ScreenerPage />);
    expect(cards()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
    loadSavedView("Big");
    expect(lastUniverse()).toBe("sp500");
    expect(sortSelect().value).toBe("market_cap");
    expect(isAscending()).toBe(true);
    // the Pass and Strong Pass verdicts leave AAA and BBB, ascending by market cap
    expect(cards()).toEqual(["BBB", "AAA"]);
    expect(screen.getByRole("button", { name: /^Big/ })).toBeInTheDocument();
  });

  it("loads a view saved before newer filter keys existed, with those keys at their defaults", () => {
    h.saved = [savedView({ name: "Old", filters: { overallVerdicts: ["Pass"] } as never })];
    render(<ScreenerPage />);
    loadSavedView("Old");
    expect(cards().sort()).toEqual(["AAA", "BBB"]);
  });

  it("loads a view carrying the removed 'country' key without complaint", () => {
    h.saved = [
      savedView({ name: "Legacy", filters: { ...DEFAULT_FILTER_STATE, country: ["US"], sectors: ["Energy"] } as never }),
    ];
    render(<ScreenerPage />);
    loadSavedView("Legacy");
    expect(cards()).toEqual(["CCC", "DDD"]);
    expect(screen.queryByText("Failed to load the Stocks Screener.")).toBeNull();
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
        filters: { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Strong Pass", "Pass"] },
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

  it("also puts the sort back to the default field and direction", () => {
    h.saved = [savedView({ name: "Big", sort_field: "market_cap", sort_direction: "asc" })];
    render(<ScreenerPage />);
    loadSavedView("Big");
    expect(sortSelect().value).toBe("market_cap");
    expect(isAscending()).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(sortSelect().value).toBe("overall_score");
    expect(isAscending()).toBe(false);
    // the default sort (Overall, high to low) is really applied to the cards
    expect(cards()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
  });

  it("resets a sort changed by hand, not only one loaded from a view", () => {
    render(<ScreenerPage />);
    fireEvent.change(sortSelect(), { target: { value: "beta" } });
    fireEvent.click(directionButton());
    expect(isAscending()).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(sortSelect().value).toBe("overall_score");
    expect(isAscending()).toBe(false);
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
    typeInto(box("Financials", "Minimum"), "85");
    expect(cards()).toEqual(["AAA"]);
    typeInto(box("Financials", "Minimum"), "1x"); // invalid: that side becomes inactive
    expect(cards()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
    typeInto(box("Mkt cap", "Minimum"), "1B");
    expect(cards()).toEqual(["AAA", "BBB", "DDD"]);
  });

  it("Reset clears a box holding invalid text and every typed box", () => {
    render(<ScreenerPage />);
    typeInto(box("Growth", "Minimum"), "1x");
    typeInto(box("Financials", "Minimum"), "70");
    typeInto(box("Mkt cap", "Maximum"), "5T");
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(box("Growth", "Minimum").value).toBe("");
    expect(box("Financials", "Minimum").value).toBe("");
    expect(box("Mkt cap", "Maximum").value).toBe("");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(cards()).toHaveLength(4);
  });

  it("loading a saved view rewrites the boxes, including one holding invalid text, and shows 1B", () => {
    h.saved = [
      savedView({
        name: "Big",
        filters: { ...DEFAULT_FILTER_STATE, overallVerdicts: ["Strong Pass", "Pass"], marketCap: { min: 1e9, max: 5e12 } },
      }),
    ];
    render(<ScreenerPage />);
    typeInto(box("Growth", "Minimum"), "1x");
    loadSavedView("Big");
    expect(screen.getByRole("button", { name: "Overall (2): 2 selected" })).toHaveClass("text-filter-active");
    expect(box("Mkt cap", "Minimum").value).toBe("1B");
    expect(box("Mkt cap", "Maximum").value).toBe("5T");
    expect(box("Growth", "Minimum").value).toBe("");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });

  it("loads a view saved before newer keys existed, and one with the stale 'country' key, into the boxes", () => {
    h.saved = [
      savedView({ id: 1, name: "Old", filters: { peRatio: { min: 15, max: null } } as never }),
      savedView({ id: 2, name: "Legacy", filters: { ...DEFAULT_FILTER_STATE, country: ["US"], beta: { min: 0.5, max: 2 } } as never }),
    ];
    render(<ScreenerPage />);
    loadSavedView("Old");
    expect(box("P/E", "Minimum").value).toBe("15");
    expect(screen.getByRole("button", { name: "Overall: none selected" })).toBeInTheDocument();
    expect(box("Beta", "Minimum").value).toBe("");
    loadSavedView("Legacy");
    expect(box("Beta", "Minimum").value).toBe("0.5");
    expect(box("Beta", "Maximum").value).toBe("2");
    expect(box("Financials", "Minimum").value).toBe("");
  });
});

describe("the sidebar across a universe switch", () => {
  // While a new universe loads there are no rows (SWR's data is undefined for the
  // new key). The page must keep the header, the sort row and the whole sidebar
  // mounted and show loading only in the results area.
  const groupBox = (name: string, side: "Minimum" | "Maximum") => box(name, side);
  const technicalTrigger = () => screen.getByRole("button", { name: /^Technical/ });

  function setUpSidebarState() {
    h.saved = [savedView({ name: "Big", filters: { ...DEFAULT_FILTER_STATE } })];
    h.rows.sp500 = undefined; // loading
    const utils = render(<ScreenerPage />);
    loadSavedView("Big"); // active view name
    fireEvent.click(technicalTrigger()); // collapse Technical
    typeInto(groupBox("Growth", "Minimum"), "1x"); // a range draft the numeric state cannot hold
    typeInto(groupBox("Financials", "Maximum"), "60"); // a valid draft
    fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "half typed" } });
    return utils;
  }

  it("keeps collapse state, the active view name, a half-typed view name and range drafts while the new universe loads", () => {
    setUpSidebarState();
    expect(screen.queryByRole("group", { name: "Beta" })).toBeNull(); // Technical collapsed

    fireEvent.click(screen.getByRole("button", { name: "S&P 500" }));
    expect(lastUniverse()).toBe("sp500");

    // loading shows in the results area only
    expect(screen.getByText("Loading Stocks Screener…")).toBeInTheDocument();
    expect(cards()).toEqual([]);
    expect(screen.getByRole("heading", { name: "Stocks Screener" })).toBeInTheDocument();
    expect(sortSelect()).toBeInTheDocument();
    // ...and the sidebar is the very same, untouched state
    expect(screen.queryByRole("group", { name: "Beta" })).toBeNull();
    expect(screen.getByRole("button", { name: /^Big/ })).toBeInTheDocument();
    expect((screen.getByLabelText("View name") as HTMLInputElement).value).toBe("half typed");
    expect(groupBox("Growth", "Minimum").value).toBe("1x");
    expect(groupBox("Financials", "Maximum").value).toBe("60");
    expect(within(screen.getByRole("group", { name: "Growth" })).getByRole("alert")).toHaveTextContent("Enter a number.");
  });

  it("still has all of it once the new universe's rows arrive", () => {
    const { rerender } = setUpSidebarState();
    fireEvent.click(screen.getByRole("button", { name: "S&P 500" }));
    h.rows.sp500 = ALL_ROWS.slice(0, 3);
    rerender(<ScreenerPage />);
    expect(screen.queryByText("Loading Stocks Screener…")).toBeNull();
    // Financials max 60 leaves CCC (40); DDD's null score is excluded from sp500's three rows anyway
    expect(cards()).toEqual(["CCC"]);
    expect(screen.queryByRole("group", { name: "Beta" })).toBeNull();
    expect((screen.getByLabelText("View name") as HTMLInputElement).value).toBe("half typed");
    expect(groupBox("Growth", "Minimum").value).toBe("1x");
    expect(groupBox("Financials", "Maximum").value).toBe("60");
  });

  it("shows a load error in the results area only, with the sidebar in place", () => {
    h.errors.sp500 = new Error("boom");
    h.rows.sp500 = undefined;
    render(<ScreenerPage />);
    typeInto(groupBox("Financials", "Minimum"), "70");
    fireEvent.click(screen.getByRole("button", { name: "S&P 500" }));
    expect(screen.getByText("Failed to load the Stocks Screener.")).toBeInTheDocument();
    expect(groupBox("Financials", "Minimum").value).toBe("70");
    expect(screen.getByRole("button", { name: /^Reset/ })).toBeInTheDocument();
    expect(screen.queryByText("Loading Stocks Screener…")).toBeNull();
  });

  it("keeps the last known Sector and Company type options while the new universe loads", () => {
    h.rows.dow = undefined;
    render(<ScreenerPage />);
    const openMulti = (label: string) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
    fireEvent.click(screen.getByRole("button", { name: "Dow 30" }));
    expect(screen.getByText("Loading Stocks Screener…")).toBeInTheDocument();
    openMulti("Sector");
    expect(within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Energy", "Healthcare", "Technology"]);
    openMulti("Sector"); // close it again
    openMulti("Company type");
    expect(within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Standard"]);
  });

  it("takes the new universe's own options once it has loaded", () => {
    h.rows.dow = undefined;
    const { rerender } = render(<ScreenerPage />);
    fireEvent.click(screen.getByRole("button", { name: "Dow 30" }));
    h.rows.dow = [ALL_ROWS[1]];
    rerender(<ScreenerPage />);
    fireEvent.click(screen.getByRole("button", { name: /^Sector/ }));
    expect(within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Healthcare"]);
  });

  it("keeps the header count text honest: no counts while loading, counts once loaded", () => {
    h.rows.sp500 = undefined;
    const { rerender } = render(<ScreenerPage />);
    expect(screen.getByText(/4 of 500 All tickers/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "S&P 500" }));
    expect(screen.queryByText(/^\d+ of/)).toBeNull();
    h.rows.sp500 = ALL_ROWS.slice(0, 3);
    rerender(<ScreenerPage />);
    expect(screen.getByText(/3 of 500 S&P 500 tickers/)).toBeInTheDocument();
  });
});

describe("a saved view from before the Review status filter was retired", () => {
  it("still loads: the leftover reviewStatuses key is ignored and filters nothing", () => {
    h.rows.all = [scoreRow("AAA", { overall_verdict: "Pass" }), scoreRow("BBB", { overall_verdict: "Pass" })];
    h.saved = [
      savedView({ name: "Old", filters: { ...DEFAULT_FILTER_STATE, reviewStatuses: ["review_unclear"] } as never }),
    ];
    render(<ScreenerPage />);
    loadSavedView("Old");
    expect(cards().sort()).toEqual(["AAA", "BBB"]);
    expect(screen.queryByRole("button", { name: /^Review status/ })).toBeNull();
  });
});

describe("a saved view from before the Overall verdict filter", () => {
  it("loads with the old overallScore key ignored: no Overall selection, nothing filtered by it", () => {
    h.saved = [savedView({ name: "OldOverall", filters: { ...DEFAULT_FILTER_STATE, overallScore: { min: 85, max: null }, reviewStatuses: [] } as never })];
    render(<ScreenerPage />);
    loadSavedView("OldOverall");
    expect(screen.getByRole("button", { name: "Overall: none selected" })).toBeInTheDocument();
    expect(cards().sort()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
  });

  it("does not write the dead keys back when the loaded view is saved again", () => {
    h.saved = [savedView({ name: "OldOverall", filters: { ...DEFAULT_FILTER_STATE, overallScore: { min: 85, max: null }, reviewStatuses: [] } as never })];
    render(<ScreenerPage />);
    loadSavedView("OldOverall");
    fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "Again" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const call = vi.mocked(saveScreenerFilter).mock.calls.at(-1);
    expect(call?.[0]).toBe("Again");
    const written = (call?.[1] as unknown as { filters: Record<string, unknown> }).filters;
    expect("overallScore" in written).toBe(false);
    expect("reviewStatuses" in written).toBe(false);
    expect(written.overallVerdicts).toEqual([]);
  });
});

describe("the Overall verdict filter on the page", () => {
  const pick = (option: string) => {
    // The panel stays open after a pick, so only open it when it is closed.
    if (!screen.queryByRole("listbox", { name: "Overall" })) fireEvent.click(screen.getByRole("button", { name: /^Overall/ }));
    fireEvent.click(within(screen.getByRole("listbox", { name: "Overall" })).getByRole("option", { name: option }).querySelector("input") as HTMLInputElement);
  };

  it("has no Overall score range any more, and filters the cards by the stored verdict", () => {
    render(<ScreenerPage />);
    expect(screen.queryByRole("group", { name: "Overall" })).toBeNull();
    expect(cards()).toEqual(["AAA", "BBB", "CCC", "DDD"]);
    pick("May not pass");
    expect(cards()).toEqual(["CCC"]);
  });

  it("ORs several verdicts, and Incomplete picks the row with no Overall verdict", () => {
    render(<ScreenerPage />);
    pick("Pass");
    expect(cards().sort()).toEqual(["AAA", "BBB"]);
    pick("Incomplete");
    expect(cards().sort()).toEqual(["AAA", "BBB", "DDD"]);
  });

  it("combines with a step score range: both must hold", () => {
    h.rows.all = ALL_ROWS.map((r) => ({ ...r, step1_score: r.ticker === "AAA" ? 95 : 60 }));
    render(<ScreenerPage />);
    pick("Pass");
    expect(cards().sort()).toEqual(["AAA", "BBB"]);
    typeInto(box("Financials", "Minimum"), "70");
    expect(cards()).toEqual(["AAA"]);
  });

  it("keeps the Overall score as a sort option and the default sort", () => {
    render(<ScreenerPage />);
    expect(sortSelect().value).toBe("overall_score");
  });
});

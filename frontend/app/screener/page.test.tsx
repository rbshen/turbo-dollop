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
    expect(isAscending()).toBe(true);
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
    typeInto(groupBox("Overall", "Maximum"), "60"); // a valid draft
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
    expect(screen.getByText("Loading Screener…")).toBeInTheDocument();
    expect(cards()).toEqual([]);
    expect(screen.getByRole("heading", { name: "Screener" })).toBeInTheDocument();
    expect(sortSelect()).toBeInTheDocument();
    // ...and the sidebar is the very same, untouched state
    expect(screen.queryByRole("group", { name: "Beta" })).toBeNull();
    expect(screen.getByRole("button", { name: /^Big/ })).toBeInTheDocument();
    expect((screen.getByLabelText("View name") as HTMLInputElement).value).toBe("half typed");
    expect(groupBox("Growth", "Minimum").value).toBe("1x");
    expect(groupBox("Overall", "Maximum").value).toBe("60");
    expect(within(screen.getByRole("group", { name: "Growth" })).getByRole("alert")).toHaveTextContent("Enter a number.");
  });

  it("still has all of it once the new universe's rows arrive", () => {
    const { rerender } = setUpSidebarState();
    fireEvent.click(screen.getByRole("button", { name: "S&P 500" }));
    h.rows.sp500 = ALL_ROWS.slice(0, 3);
    rerender(<ScreenerPage />);
    expect(screen.queryByText("Loading Screener…")).toBeNull();
    // Overall max 60 leaves CCC (40); DDD's null score is excluded from sp500's three rows anyway
    expect(cards()).toEqual(["CCC"]);
    expect(screen.queryByRole("group", { name: "Beta" })).toBeNull();
    expect((screen.getByLabelText("View name") as HTMLInputElement).value).toBe("half typed");
    expect(groupBox("Growth", "Minimum").value).toBe("1x");
    expect(groupBox("Overall", "Maximum").value).toBe("60");
  });

  it("shows a load error in the results area only, with the sidebar in place", () => {
    h.errors.sp500 = new Error("boom");
    h.rows.sp500 = undefined;
    render(<ScreenerPage />);
    typeInto(groupBox("Overall", "Minimum"), "70");
    fireEvent.click(screen.getByRole("button", { name: "S&P 500" }));
    expect(screen.getByText("Failed to load the Screener.")).toBeInTheDocument();
    expect(groupBox("Overall", "Minimum").value).toBe("70");
    expect(screen.getByRole("button", { name: /^Reset/ })).toBeInTheDocument();
    expect(screen.queryByText("Loading Screener…")).toBeNull();
  });

  it("keeps the last known Sector and Company type options while the new universe loads", () => {
    h.rows.dow = undefined;
    render(<ScreenerPage />);
    const openMulti = (label: string) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
    fireEvent.click(screen.getByRole("button", { name: "Dow 30" }));
    expect(screen.getByText("Loading Screener…")).toBeInTheDocument();
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

describe("the Watchlist scope and the section badges on the real page", () => {
  const scopeLabel = () => screen.getByText("Limit results to", { selector: "label" });

  it("is orange and counted only while in effect, and comes back when the universe returns to All", () => {
    render(<ScreenerPage />);
    fireEvent.change(watchlistSelect(), { target: { value: "1" } });
    expect(scopeLabel()).toHaveClass("text-filter-active");
    expect(screen.getByRole("button", { name: /^Watchlist/ })).toContainElement(screen.getByTitle("1 applied"));

    fireEvent.click(screen.getByRole("button", { name: "Nasdaq" }));
    expect(watchlistSelect()).toBeDisabled();
    expect(watchlistSelect().value).toBe("1");
    expect(scopeLabel()).not.toHaveClass("text-filter-active");
    expect(scopeLabel()).toHaveClass("opacity-45");
    expect(screen.queryByTitle("1 applied")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(watchlistSelect()).toBeEnabled();
    expect(watchlistSelect().value).toBe("1");
    expect(scopeLabel()).toHaveClass("text-filter-active");
    expect(screen.getByTitle("1 applied")).toBeInTheDocument();
  });

  it("counts the Fundamental and Technical filters in their own headers, and Reset clears every badge", () => {
    render(<ScreenerPage />);
    expect(screen.queryByTitle(/applied/)).toBeNull();
    typeInto(box("Overall", "Minimum"), "70");
    typeInto(box("Beta", "Maximum"), "2");
    fireEvent.click(screen.getByLabelText("BB + RSI entry (2h)"));
    expect(screen.getByRole("button", { name: /^Fundamental/ })).toContainElement(screen.getByTitle("1 applied", { exact: true }) as HTMLElement);
    expect(screen.getByRole("button", { name: /^Technical/ }).querySelector("[title='2 applied']")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.queryByTitle(/applied/)).toBeNull();
  });
});

// Sort and pagination on the real page (characterization, session 10 part 3).
// 40 rows is three pages at PAGE_SIZE 18: 18, 18 and 4.
describe("sorting and paging on the real page", () => {
  // -- selector helpers: the only markup-dependent part of this describe --
  const prevButton = () => screen.getByRole("button", { name: "Previous page" });
  const nextButton = () => screen.getByRole("button", { name: "Next page" });
  const pageButton = (n: number) => screen.getByRole("button", { name: String(n) });
  // ----------------------------------------------------------------------

  const tk = (i: number) => `T${String(i).padStart(2, "0")}`;
  beforeEach(() => {
    // T01 has the highest overall score and the lowest market cap
    h.rows.all = Array.from({ length: 40 }, (_, k) =>
      scoreRow(tk(k + 1), { overall_score: 100 - (k + 1), market_cap: (k + 1) * 1e9, beta: k % 7 })
    );
  });

  it("starts on Overall score, high to low, page 1", () => {
    render(<ScreenerPage />);
    expect(sortSelect().value).toBe("overall_score");
    expect(isAscending()).toBe(false);
    expect(cards()).toHaveLength(18);
    expect(cards()[0]).toBe("T01");
    expect(cards()[17]).toBe("T18");
  });

  it("re-sorts by the chosen field, and the direction toggle reverses it", () => {
    render(<ScreenerPage />);
    fireEvent.change(sortSelect(), { target: { value: "market_cap" } });
    expect(cards()[0]).toBe("T40"); // still descending
    fireEvent.click(directionButton());
    expect(isAscending()).toBe(true);
    expect(cards()[0]).toBe("T01");
    fireEvent.click(directionButton());
    expect(isAscending()).toBe(false);
    expect(cards()[0]).toBe("T40");
  });

  it("keeps the direction when the field changes", () => {
    render(<ScreenerPage />);
    fireEvent.click(directionButton());
    fireEvent.change(sortSelect(), { target: { value: "market_cap" } });
    expect(isAscending()).toBe(true);
    expect(cards()[0]).toBe("T01");
  });

  it("pages through 18, 18 and 4 rows", () => {
    render(<ScreenerPage />);
    fireEvent.click(pageButton(2));
    expect(cards()).toHaveLength(18);
    expect(cards()[0]).toBe("T19");
    fireEvent.click(nextButton());
    expect(cards()).toEqual(["T37", "T38", "T39", "T40"]);
    expect(nextButton()).toBeDisabled();
    fireEvent.click(prevButton());
    expect(cards()[0]).toBe("T19");
    fireEvent.click(prevButton());
    expect(cards()[0]).toBe("T01");
    expect(prevButton()).toBeDisabled();
  });

  it("changing the sort field returns to page 1", () => {
    render(<ScreenerPage />);
    fireEvent.click(pageButton(2));
    expect(cards()[0]).toBe("T19");
    fireEvent.change(sortSelect(), { target: { value: "market_cap" } });
    expect(cards()).toHaveLength(18);
    expect(cards()[0]).toBe("T40"); // top of the new order, i.e. page 1
  });

  it("toggling the direction returns to page 1", () => {
    render(<ScreenerPage />);
    fireEvent.click(pageButton(3));
    expect(cards()).toHaveLength(4);
    fireEvent.click(directionButton());
    expect(cards()).toHaveLength(18);
    expect(cards()[0]).toBe("T40"); // ascending overall: lowest score (T40) first
  });

  it("a filter change returns to page 1", () => {
    render(<ScreenerPage />);
    fireEvent.click(pageButton(2));
    expect(cards()[0]).toBe("T19");
    typeInto(box("Overall", "Minimum"), "1");
    expect(cards()[0]).toBe("T01");
  });

  it("shows no pagination when the rows fit on one page", () => {
    h.rows.all = h.rows.all!.slice(0, 5);
    render(<ScreenerPage />);
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
  });
});

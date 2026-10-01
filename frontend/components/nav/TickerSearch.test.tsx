// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TickerSearch } from "@/components/nav/TickerSearch";
import type { TickerSearchResult } from "@/lib/api/types";

// The search box's own behaviour (typing, debounce, keys, selection) is what is pinned here, with the SWR hook
// replaced by a controllable state so each branch (loading, error, empty, results) can be drawn on demand.
const requested: (string | null)[] = [];
let hookState: { data?: TickerSearchResult[]; error?: Error; isLoading: boolean };

vi.mock("@/lib/hooks/useApiResource", () => ({
  useApiResource: (url: string | null) => {
    requested.push(url);
    return url === null ? { data: undefined, error: undefined, isLoading: false } : hookState;
  },
}));

const RESULTS: TickerSearchResult[] = [
  { symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ" },
  { symbol: "AAP", name: "Advance Auto Parts", exchange: "NYSE" },
  { symbol: "AAL", name: null, exchange: null },
];

let openSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.useFakeTimers();
  requested.length = 0;
  hookState = { data: RESULTS, isLoading: false };
  openSpy = vi.spyOn(window, "open").mockReturnValue(null);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  openSpy.mockRestore();
});

function box() {
  return screen.getByRole("combobox");
}

function type(text: string) {
  fireEvent.change(box(), { target: { value: text } });
  act(() => {
    vi.advanceTimersByTime(300);
  });
}

function options() {
  return screen.queryAllByRole("option");
}

describe("TickerSearch: the box", () => {
  it("is a combobox with the 'Search ticker…' placeholder, closed, controlling the results listbox", () => {
    render(<TickerSearch />);
    expect(box()).toHaveAttribute("placeholder", "Search ticker…");
    expect(box()).toHaveAttribute("aria-expanded", "false");
    expect(box()).toHaveAttribute("aria-autocomplete", "list");
    expect(box()).toHaveAttribute("aria-controls", "ticker-search-listbox");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("TickerSearch: the kit input", () => {
  it("is the boxed kit Input with no outline-none, so the global keyboard focus ring applies", () => {
    render(<TickerSearch />);
    expect(box()).toHaveClass("h-9", "w-full", "rounded-md", "border", "border-border-control", "bg-page");
    expect(box().className).not.toMatch(/outline-none/);
    expect(box().className).not.toMatch(/focus:/);
  });

  it("is named for assistive technology", () => {
    render(<TickerSearch />);
    expect(screen.getByRole("combobox", { name: "Search ticker" })).toBe(box());
  });

  it("keeps its 160px (224px from sm) width on the wrapper", () => {
    const { container } = render(<TickerSearch />);
    expect(container.firstElementChild).toHaveClass("w-40", "sm:w-56");
  });

  it("has no outline-none anywhere in the results panel either", () => {
    const { container } = render(<TickerSearch />);
    type("aa");
    expect(container.innerHTML).not.toMatch(/outline-none/);
  });

  it("marks the highlighted option with a surface-2 fill", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(options()[0]).toHaveClass("bg-surface-2");
    expect(options()[1]).not.toHaveClass("bg-surface-2");
  });
});

describe("TickerSearch: typing", () => {
  it("upper-cases what is typed", () => {
    render(<TickerSearch />);
    fireEvent.change(box(), { target: { value: "aap" } });
    expect(box()).toHaveValue("AAP");
  });

  it("opens the listbox and requests the search once the 300ms debounce has passed", () => {
    render(<TickerSearch />);
    fireEvent.change(box(), { target: { value: "aap" } });
    // Open at once, but nothing is requested until the debounce settles.
    expect(box()).toHaveAttribute("aria-expanded", "false"); // no query yet, so no dropdown
    expect(requested.every((u) => u === null)).toBe(true);
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(requested.every((u) => u === null)).toBe(true);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(requested).toContain("/tickers/search?q=AAP");
    expect(box()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox", { name: "Ticker search results" })).toBeInTheDocument();
  });

  it("trims the query and url-encodes it", () => {
    render(<TickerSearch />);
    type("  a&b ");
    expect(requested).toContain("/tickers/search?q=A%26B");
  });

  it("makes no request for blank text", () => {
    render(<TickerSearch />);
    type("   ");
    expect(requested.every((u) => u === null)).toBe(true);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("lists each result with its symbol, name and exchange, in the order returned", () => {
    render(<TickerSearch />);
    type("aa");
    const rows = options();
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("AAPL");
    expect(rows[0]).toHaveTextContent("Apple Inc.");
    expect(rows[0]).toHaveTextContent("NASDAQ");
    expect(rows[1]).toHaveTextContent("AAP");
    expect(rows[2]).toHaveTextContent("AAL");
    expect(rows[2]).not.toHaveTextContent("NYSE");
    expect(rows.every((r) => r.getAttribute("aria-selected") === "false")).toBe(true);
  });
});

describe("TickerSearch: empty, loading and error states", () => {
  it("shows 'Searching…' while the first response is in flight", () => {
    hookState = { data: undefined, isLoading: true };
    render(<TickerSearch />);
    type("aa");
    expect(screen.getByText("Searching…")).toBeInTheDocument();
    expect(options()).toHaveLength(0);
  });

  it("shows the failure message when the search errors", () => {
    hookState = { data: undefined, error: new Error("boom"), isLoading: false };
    render(<TickerSearch />);
    type("aa");
    expect(screen.getByText("Search failed — try again")).toBeInTheDocument();
  });

  it("names the query when there are no matches", () => {
    hookState = { data: [], isLoading: false };
    render(<TickerSearch />);
    type("zzz");
    expect(screen.getByText(/No matches for/)).toHaveTextContent("No matches for “ZZZ”");
  });
});

describe("TickerSearch: keyboard", () => {
  it("ArrowDown highlights the first result, then the next, and wraps round", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(options()[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(options()[1]).toHaveAttribute("aria-selected", "true");
    expect(options()[0]).toHaveAttribute("aria-selected", "false");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(options()[0]).toHaveAttribute("aria-selected", "true");
  });

  it("ArrowUp from nothing highlighted lands on the second-to-last result (the index starts at -1, so -2 wraps to length - 2), then steps up and wraps", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(options()[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(options()[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(options()[2]).toHaveAttribute("aria-selected", "true");
  });

  it("prevents the default on the arrow keys and Enter", () => {
    render(<TickerSearch />);
    type("aa");
    expect(fireEvent.keyDown(box(), { key: "ArrowDown" })).toBe(false);
    expect(fireEvent.keyDown(box(), { key: "ArrowUp" })).toBe(false);
    expect(fireEvent.keyDown(box(), { key: "Enter" })).toBe(false);
  });

  it("Enter with nothing highlighted opens the first result in a new tab, then clears and closes", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("/tickers/AAPL", "_blank", "noopener,noreferrer");
    expect(box()).toHaveValue("");
    expect(box()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("Enter opens the highlighted result", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(openSpy).toHaveBeenCalledWith("/tickers/AAP", "_blank", "noopener,noreferrer");
  });

  it("Escape closes the results but keeps the text", () => {
    render(<TickerSearch />);
    type("aa");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(box()).toHaveValue("AA");
  });

  it("reopens on focus and on further typing after Escape", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.keyDown(box(), { key: "Escape" });
    fireEvent.focus(box());
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(box(), { key: "Escape" });
    fireEvent.change(box(), { target: { value: "aap" } });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("ignores the arrow keys and Enter when there are no results", () => {
    hookState = { data: [], isLoading: false };
    render(<TickerSearch />);
    type("zzz");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("does nothing for Home, End and Tab (no handler for them)", () => {
    render(<TickerSearch />);
    type("aa");
    for (const key of ["Home", "End", "Tab"]) {
      expect(fireEvent.keyDown(box(), { key })).toBe(true);
    }
    expect(options().every((r) => r.getAttribute("aria-selected") === "false")).toBe(true);
    expect(openSpy).not.toHaveBeenCalled();
  });
});

describe("TickerSearch: mouse", () => {
  it("hovering a result highlights it", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.mouseEnter(options()[1]);
    expect(options()[1]).toHaveAttribute("aria-selected", "true");
  });

  it("clicking a result opens it in a new tab and clears the box", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.click(options()[2]);
    expect(openSpy).toHaveBeenCalledWith("/tickers/AAL", "_blank", "noopener,noreferrer");
    expect(box()).toHaveValue("");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("a mouse press outside closes the results; one inside does not", () => {
    render(
      <div>
        <TickerSearch />
        <p>elsewhere</p>
      </div>,
    );
    type("aa");
    fireEvent.mouseDown(options()[0]);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByText("elsewhere"));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("highlights nothing again when the result set changes", () => {
    render(<TickerSearch />);
    type("aa");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(options()[0]).toHaveAttribute("aria-selected", "true");
    hookState = { data: [...RESULTS], isLoading: false };
    type("aap");
    expect(options().every((r) => r.getAttribute("aria-selected") === "false")).toBe(true);
  });
});

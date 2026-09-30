// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { FundamentalFilters } from "@/components/screener/FundamentalFilters";
import { TechnicalFilters } from "@/components/screener/TechnicalFilters";
import { WatchlistFilters } from "@/components/screener/WatchlistFilters";
import type { WatchlistOut } from "@/lib/api/types";
import { DEFAULT_FILTER_STATE, type ScreenerFilterState } from "@/lib/screenerFilters";

afterEach(cleanup);

// The Fundamental and Technical sections as the page renders them: chips,
// multi-selects, section count badges, sentence-case labels.
function Sections({ initial = DEFAULT_FILTER_STATE }: { initial?: ScreenerFilterState }) {
  const [filters, setFilters] = useState(initial);
  return (
    <div>
      <FundamentalFilters filters={filters} onFiltersChange={setFilters} sectors={["Energy", "Technology"]} companyTypes={["Bank", "Standard"]} />
      <TechnicalFilters filters={filters} onFiltersChange={setFilters} />
      <pre data-testid="state">{JSON.stringify(filters)}</pre>
    </div>
  );
}
const state = (): ScreenerFilterState => JSON.parse(screen.getByTestId("state").textContent as string);
const badge = (section: string) => screen.getByRole("button", { name: new RegExp(`^${section}`) }).querySelector("[title$='applied']");
const chip = (name: string) => screen.getByLabelText(name) as HTMLInputElement;
const openMulti = (label: string) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
const optionLabels = () => within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent);

describe("chips (Speculative growth, BB + RSI entry)", () => {
  it.each([
    ["Speculative growth", "speculativeGrowth"],
    ["BB + RSI entry (2h)", "bbRsiEntrySignal"],
  ] as const)("%s toggles its boolean and is full-width, 32px, with the inner check box", (name, key) => {
    render(<Sections />);
    const input = chip(name);
    const label = input.closest("label") as HTMLElement;
    expect(label).toHaveClass("w-full", "h-8", "rounded-md", "border", "border-border-input");
    expect(label.querySelector("svg")).not.toBeNull(); // the inner check box's tick
    expect(input).not.toBeChecked();
    fireEvent.click(input);
    expect(state()[key]).toBe(true);
    expect(input).toBeChecked();
    fireEvent.click(input);
    expect(state()[key]).toBe(false);
  });

  it.each(["Speculative growth", "BB + RSI entry (2h)"])("%s shows applied through its checked fill, never orange", (name) => {
    render(<Sections />);
    const input = chip(name);
    const label = input.closest("label") as HTMLElement;
    // the checked fill is a class on the label, keyed off :checked
    expect(label.className).toContain("has-[:checked]:bg-surface-2");
    expect(label.className).toContain("has-[:checked]:text-text-primary");
    fireEvent.click(input);
    expect(input).toBeChecked();
    expect(label.className).not.toContain("filter-active");
    expect(label.querySelector("[class*='filter-active']")).toBeNull();
    // the tick's box fills neutral (text-primary), not brand
    expect(label.innerHTML).toContain("peer-checked:bg-text-primary");
    expect(label.innerHTML).not.toContain("bg-brand");
  });
});

describe("multi-select checkboxes are the bare neutral Checkbox", () => {
  it("has no extra <label> per option, no brand accent, and a neutral checked fill", () => {
    render(<Sections />);
    openMulti("Sector");
    const panel = screen.getByRole("listbox");
    expect(panel.querySelectorAll("label")).toHaveLength(2); // exactly the two option wrappers
    expect(panel.innerHTML).not.toContain("accent-brand");
    expect(panel.innerHTML).toContain("peer-checked:bg-text-primary");
    const first = within(panel).getAllByRole("checkbox")[0];
    expect(first.closest("label")).toHaveAttribute("role", "option");
  });

  it("still filters by the option's stored value", () => {
    render(<Sections />);
    openMulti("Sector");
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Technology"));
    expect(state().sectors).toEqual(["Technology"]);
  });
});

describe("sentence case, with stored values unchanged", () => {
  it("re-cases the Moat options and stores the same keys", () => {
    render(<Sections />);
    openMulti("Moat");
    expect(optionLabels()).toEqual(["Wide moat", "Narrow moat", "No moat", "Not set"]);
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Wide moat"));
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Not set"));
    expect(state().moat).toEqual(["wide_moat", "not_set"]);
  });

  it("re-cases the Warren options and stores the same keys", () => {
    render(<Sections />);
    openMulti("Warren entry");
    expect(optionLabels()).toEqual(["Blue up", "Yellow up", "Gray up"]);
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Blue up"));
    expect(state().warrenSignalKinds).toEqual(["blue_up"]);
  });

  it("re-cases the field, chip and multi-select labels", () => {
    render(<Sections />);
    for (const label of ["Growth rate", "Mkt cap", "Overall", "Financials", "Profitability", "Debt", "Quote", "P/E", "Growth", "Beta"]) {
      expect(screen.getByRole("group", { name: label })).toBeInTheDocument();
    }
    for (const label of ["Sector", "Company type", "Moat", "Valuation", "5Y vs SPY", "Weinstein stage", "Reversal", "Pullback", "Warren entry (2h)"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${label.replace(/[()]/g, "\\$&")}`) })).toBeInTheDocument();
    }
    expect(screen.queryByText("Growth Rate")).toBeNull();
    expect(screen.queryByText("Mkt Cap")).toBeNull();
    expect(screen.queryByText("Speculative Growth")).toBeNull();
    expect(screen.queryByText(/Weinstein Stage/)).toBeNull();
  });

  it("keeps the Weinstein stage option labels and values", () => {
    render(<Sections />);
    openMulti("Weinstein stage");
    expect(optionLabels()).toEqual(["Stage 1 · Base", "Stage 2 · Advance", "Stage 3 · Top", "Stage 4 · Decline", "Pending"]);
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Stage 2 · Advance"));
    expect(state().weinsteinStages).toEqual(["advance"]);
  });
});

describe("section count badges", () => {
  it("shows no badge at zero (a neutral zero would be noise on every header)", () => {
    render(<Sections />);
    expect(badge("Fundamental")).toBeNull();
    expect(badge("Technical")).toBeNull();
  });

  it("counts each section's own applied filters, neutral and compact", () => {
    render(<Sections />);
    fireEvent.change(within(screen.getByRole("group", { name: "Overall" })).getByRole("textbox", { name: "Minimum" }), { target: { value: "70" } });
    fireEvent.click(chip("Speculative growth"));
    openMulti("Sector");
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Energy"));
    expect(badge("Fundamental")).toHaveAttribute("title", "3 applied");
    expect(badge("Technical")).toBeNull();
    fireEvent.click(chip("BB + RSI entry (2h)"));
    fireEvent.change(within(screen.getByRole("group", { name: "Beta" })).getByRole("textbox", { name: "Maximum" }), { target: { value: "2" } });
    expect(badge("Technical")).toHaveAttribute("title", "2 applied");
    expect(badge("Fundamental")).toHaveAttribute("title", "3 applied"); // Technical filters are not counted here
    expect(badge("Fundamental")?.textContent).toContain("3");
  });

  it("counts a filter once however many options or sides it has, and drops when cleared", () => {
    render(<Sections />);
    openMulti("Sector");
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Energy"));
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Technology"));
    expect(badge("Fundamental")).toHaveAttribute("title", "1 applied");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(badge("Fundamental")).toBeNull();
  });

  it("stays visible while the section is collapsed", () => {
    render(<Sections initial={{ ...DEFAULT_FILTER_STATE, quote: { min: 5, max: null }, beta: { min: 1, max: 2 } }} />);
    fireEvent.click(screen.getByRole("button", { name: /^Fundamental/ }));
    expect(screen.queryByRole("group", { name: "Quote" })).toBeNull();
    expect(badge("Fundamental")).toHaveAttribute("title", "1 applied");
    expect(badge("Technical")).toHaveAttribute("title", "1 applied");
  });

  it("ignores a stale key carried by a loaded view", () => {
    const stale = { ...DEFAULT_FILTER_STATE, country: ["US"] } as ScreenerFilterState;
    render(<Sections initial={stale} />);
    expect(badge("Fundamental")).toBeNull();
    expect(badge("Technical")).toBeNull();
  });
});

describe("WatchlistFilters", () => {
  const watchlists = [
    { id: 1, name: "W1", tickers: [] },
    { id: 2, name: "Other", tickers: [] },
  ] as unknown as WatchlistOut[];
  const label = () => screen.getByText("Limit results to", { selector: "label" });
  const select = () => screen.getByLabelText("Limit results to") as HTMLSelectElement;
  const hint = (text: RegExp) => screen.getByText(text);

  it("is a labelled select ('Limit results to', not a second 'Watchlist') with the helper sentence as its hint", () => {
    render(<WatchlistFilters watchlists={watchlists} value={null} onChange={() => {}} disabled={false} />);
    expect(screen.getAllByText("Watchlist")).toHaveLength(1); // the section title only
    expect(select()).toBeInstanceOf(HTMLSelectElement);
    expect(select()).toHaveClass("h-9"); // the full-size box
    expect(within(select()).getAllByRole("option").map((o) => o.textContent)).toEqual(["None", "W1", "Other"]);
    expect(hint(/Scopes every Fundamental and Technical filter/)).toBeInTheDocument();
    expect(select()).toHaveAccessibleDescription(/Scopes every Fundamental and Technical filter/);
    expect(label()).not.toHaveClass("text-filter-active");
    expect(select()).toBeEnabled();
  });

  it("calls onChange with the id, or null for None", () => {
    const seen: (number | null)[] = [];
    render(<WatchlistFilters watchlists={watchlists} value={null} onChange={(v) => seen.push(v)} disabled={false} />);
    fireEvent.change(select(), { target: { value: "2" } });
    fireEvent.change(select(), { target: { value: "" } });
    expect(seen).toEqual([2, null]);
  });

  it("is orange and counted only while the filter is in effect", () => {
    render(<WatchlistFilters watchlists={watchlists} value={1} onChange={() => {}} disabled={false} />);
    expect(label()).toHaveClass("text-filter-active");
    expect(screen.getByTitle("1 applied")).toBeInTheDocument();
  });

  it("is disabled and dimmed (label and hint together), keeps its selection, and is not orange or counted while the universe is not All", () => {
    render(<WatchlistFilters watchlists={watchlists} value={1} onChange={() => {}} disabled />);
    expect(select()).toBeDisabled();
    expect(select().value).toBe("1");
    expect(label()).not.toHaveClass("text-filter-active");
    expect(label()).toHaveClass("opacity-45");
    expect(hint(/Only applies when the universe toggle above is set to "All."/)).toHaveClass("opacity-45");
    expect(screen.queryByTitle(/applied/)).toBeNull();
  });

  it("shows no badge with nothing selected", () => {
    render(<WatchlistFilters watchlists={watchlists} value={null} onChange={() => {}} disabled={false} />);
    expect(screen.queryByTitle(/applied/)).toBeNull();
  });
});

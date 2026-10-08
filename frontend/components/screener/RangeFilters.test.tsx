// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { FundamentalFilters } from "@/components/screener/FundamentalFilters";
import { TechnicalFilters } from "@/components/screener/TechnicalFilters";
import { DEFAULT_FILTER_STATE, type ScreenerFilterState } from "@/lib/screenerFilters";

afterEach(cleanup);

// The sidebar's nine Min/Max pairs (the Overall filter is a verdict multi-select, see "the Overall verdict dropdown" below), driven through the real Fundamental and
// Technical sections. The harness holds the numeric filter state like the page
// does and shows it as JSON, so what a box emits can be read back exactly.
function Harness({ initial = DEFAULT_FILTER_STATE }: { initial?: ScreenerFilterState }) {
  const [filters, setFilters] = useState(initial);
  return (
    <div>
      <FundamentalFilters filters={filters} onFiltersChange={setFilters} sectors={[]} companyTypes={[]} />
      <TechnicalFilters filters={filters} onFiltersChange={setFilters} />
      <button onClick={() => setFilters(DEFAULT_FILTER_STATE)}>reset</button>
      <button
        onClick={() =>
          // A view loaded from the API: every range is a brand-new object.
          setFilters({
            ...DEFAULT_FILTER_STATE,
            step1Score: { min: 70, max: null },
            growthRate: { min: null, max: null },
            marketCap: { min: 1e9, max: 5e12 },
          })
        }
      >
        load
      </button>
      <pre data-testid="state">{JSON.stringify(filters)}</pre>
    </div>
  );
}

const state = (): ScreenerFilterState => JSON.parse(screen.getByTestId("state").textContent as string);
const group = (name: string) => screen.getByRole("group", { name });
const minBox = (name: string) => within(group(name)).getByRole("textbox", { name: "Minimum" }) as HTMLInputElement;
const maxBox = (name: string) => within(group(name)).getByRole("textbox", { name: "Maximum" }) as HTMLInputElement;
const alertIn = (name: string) => within(group(name)).queryByRole("alert");
const type = (box: HTMLInputElement, text: string) => {
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value: text } });
};

const PAIRS: { label: string; key: keyof ScreenerFilterState; unit: string | null }[] = [
  { label: "Financials", key: "step1Score", unit: null },
  { label: "Growth rate", key: "step2Score", unit: null },
  { label: "Profitability", key: "step4Score", unit: null },
  { label: "Debt", key: "step5Score", unit: null },
  { label: "Quote", key: "quote", unit: "USD" },
  { label: "Mkt cap", key: "marketCap", unit: "USD" },
  { label: "P/E", key: "peRatio", unit: "x" },
  { label: "Growth", key: "growthRate", unit: "%" },
  { label: "Beta", key: "beta", unit: null },
];

describe("the nine range pairs", () => {
  it.each(PAIRS)("$label emits numeric filter state from each box", ({ label, key }) => {
    render(<Harness />);
    type(minBox(label), "12.5");
    expect(state()[key]).toEqual({ min: 12.5, max: null });
    type(maxBox(label), "40");
    expect(state()[key]).toEqual({ min: 12.5, max: 40 });
    type(minBox(label), "");
    expect(state()[key]).toEqual({ min: null, max: 40 });
    // and no other filter was touched
    const others = { ...state() } as Record<string, unknown>;
    delete others[key];
    const defaults = { ...DEFAULT_FILTER_STATE } as Record<string, unknown>;
    delete defaults[key];
    expect(others).toEqual(defaults);
  });

  it("has all nine labelled pairs, Beta under Technical, with the placeholders and names", () => {
    render(<Harness />);
    for (const { label } of PAIRS) {
      expect(minBox(label)).toHaveAttribute("placeholder", "Min");
      expect(maxBox(label)).toHaveAttribute("placeholder", "Max");
    }
    const technical = screen.getByText("Technical").closest("div") as HTMLElement;
    expect(technical.parentElement?.contains(group("Beta"))).toBe(true);
  });

  it.each(PAIRS)("$label: unit $unit sits in the label row, right-aligned and tertiary", ({ label, unit }) => {
    render(<Harness />);
    const labelEl = within(group(label)).getByText(label);
    if (unit === null) {
      // No unit element in the label row at all.
      expect(labelEl.parentElement?.children).toHaveLength(1);
      return;
    }
    const unitEl = within(group(label)).getByText(unit);
    expect(unitEl.parentElement).toBe(labelEl.parentElement);
    expect(unitEl).toHaveClass("text-text-tertiary");
  });

  it("gives only Mkt cap the one-line hint", () => {
    render(<Harness />);
    expect(within(group("Mkt cap")).getByText("Type 500M or 2B.")).toBeInTheDocument();
    for (const { label } of PAIRS.filter((p) => p.label !== "Mkt cap")) {
      expect(group(label).querySelector("p")).toBeNull();
    }
  });

  it("turns the label orange only while that pair holds a value", () => {
    render(<Harness />);
    const label = () => within(group("Financials")).getByText("Financials");
    expect(label()).not.toHaveClass("text-filter-active");
    type(minBox("Financials"), "70");
    expect(label()).toHaveClass("text-filter-active");
    type(minBox("Financials"), "");
    expect(label()).not.toHaveClass("text-filter-active");
  });
});

describe("the commit rule, on a real sidebar pair", () => {
  it("commits 12. and .5 at once", () => {
    render(<Harness />);
    type(minBox("P/E"), "12.");
    expect(state().peRatio).toEqual({ min: 12, max: null });
    type(maxBox("P/E"), ".5");
    expect(state().peRatio).toEqual({ min: 12, max: 0.5 });
  });

  it.each([["-"], ["."], ["-."]])("holds the previous value for %s while focused, with no error, and goes invalid on blur", (partial) => {
    render(<Harness />);
    type(minBox("Quote"), "50");
    type(minBox("Quote"), partial);
    expect(state().quote).toEqual({ min: 50, max: null }); // held
    expect(alertIn("Quote")).toBeNull();
    fireEvent.blur(minBox("Quote"));
    expect(state().quote).toEqual({ min: null, max: null }); // that side is now inactive
    expect(alertIn("Quote")).toHaveTextContent("Enter a number.");
  });

  it.each([["1x"], ["5e"], ["abc"]])("makes the side inactive at once for %s, with an inline error", (bad) => {
    render(<Harness />);
    type(maxBox("Beta"), "2");
    type(minBox("Beta"), "1");
    type(minBox("Beta"), bad);
    expect(state().beta).toEqual({ min: null, max: 2 });
    expect(alertIn("Beta")).toHaveTextContent("Enter a number.");
    expect(minBox("Beta")).toHaveAttribute("aria-invalid", "true");
    expect(maxBox("Beta")).not.toHaveAttribute("aria-invalid");
    // fixing the text clears it
    type(minBox("Beta"), "1");
    expect(state().beta).toEqual({ min: 1, max: 2 });
    expect(alertIn("Beta")).toBeNull();
  });

  it("never clamps, swaps or corrects: negative and out-of-order values stay as typed", () => {
    render(<Harness />);
    type(minBox("Debt"), "-20");
    expect(state().step5Score).toEqual({ min: -20, max: null });
    expect(minBox("Debt").value).toBe("-20");
    type(maxBox("Debt"), "-30");
    expect(state().step5Score).toEqual({ min: -20, max: -30 });
    expect(minBox("Debt").value).toBe("-20");
    expect(maxBox("Debt").value).toBe("-30");
  });

  it("shows ONE message for a reversed range, invalid only on the Max box, and still applies it literally", () => {
    render(<Harness />);
    type(minBox("Financials"), "90");
    type(maxBox("Financials"), "10");
    expect(state().step1Score).toEqual({ min: 90, max: 10 });
    const alerts = within(group("Financials")).getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent("Min is higher than max, so no ticker can match.");
    expect(maxBox("Financials")).toHaveAttribute("aria-invalid", "true");
    expect(minBox("Financials")).not.toHaveAttribute("aria-invalid");
    type(maxBox("Financials"), "95");
    expect(alertIn("Financials")).toBeNull();
  });
});

describe("Mkt cap text", () => {
  it.each([
    ["500M", 5e8],
    ["2B", 2e9],
    ["5T", 5e12],
    ["2 m", 2e6],
    ["1 b", 1e9],
    ["1.5t", 1.5e12],
    ["1000000000", 1e9],
    ["12.", 12],
    [".5", 0.5],
  ])("%s commits %d", (text, expected) => {
    render(<Harness />);
    type(minBox("Mkt cap"), text);
    expect(state().marketCap).toEqual({ min: expected, max: null });
    expect(alertIn("Mkt cap")).toBeNull();
  });

  it.each([["1BX"], ["1x"], ["5e"], ["1 gazillion"]])("%s is invalid: inactive at once, with an error", (text) => {
    render(<Harness />);
    type(maxBox("Mkt cap"), "5B");
    type(minBox("Mkt cap"), text);
    expect(state().marketCap).toEqual({ min: null, max: 5e9 });
    expect(alertIn("Mkt cap")).toHaveTextContent("Enter a number.");
  });

  it("is bounded below by 0 and nothing else: a negative is invalid, not clamped", () => {
    render(<Harness />);
    type(minBox("Mkt cap"), "-5B");
    expect(state().marketCap).toEqual({ min: null, max: null });
    expect(alertIn("Mkt cap")).toHaveTextContent("Enter a value of at least 0.");
    expect(minBox("Mkt cap").value).toBe("-5B");
  });

  it("does not step on the arrow keys", () => {
    render(<Harness />);
    type(minBox("Mkt cap"), "5B");
    fireEvent.keyDown(minBox("Mkt cap"), { key: "ArrowUp" });
    expect(state().marketCap).toEqual({ min: 5e9, max: null });
  });

  it("reads back as 1B after a remount (a collapse and reopen or a saved-view load)", () => {
    const { unmount } = render(<Harness initial={{ ...DEFAULT_FILTER_STATE, marketCap: { min: 1e9, max: 2.5e12 } }} />);
    expect(minBox("Mkt cap").value).toBe("1B");
    expect(maxBox("Mkt cap").value).toBe("2.5T");
    unmount();
    render(<Harness initial={{ ...DEFAULT_FILTER_STATE, marketCap: { min: 1_234_567, max: null } }} />);
    expect(minBox("Mkt cap").value).toBe("1234567");
  });

  it("shows 1B after collapsing and reopening the Fundamental section (the content is unmounted)", () => {
    render(<Harness />);
    type(minBox("Mkt cap"), "1000000000");
    expect(minBox("Mkt cap").value).toBe("1000000000");
    const trigger = screen.getByRole("button", { name: /^Fundamental/ });
    fireEvent.click(trigger);
    expect(screen.queryByRole("group", { name: "Mkt cap" })).toBeNull();
    fireEvent.click(trigger);
    expect(minBox("Mkt cap").value).toBe("1B");
    expect(state().marketCap).toEqual({ min: 1e9, max: null });
  });
});

describe("external changes re-sync the boxes", () => {
  it("Reset clears a box holding invalid text such as 1x, and every filled box", () => {
    render(<Harness />);
    type(minBox("Financials"), "70");
    type(minBox("Growth"), "1x");
    type(maxBox("Mkt cap"), "5B");
    expect(minBox("Growth").value).toBe("1x");
    fireEvent.click(screen.getByRole("button", { name: "reset" }));
    expect(minBox("Financials").value).toBe("");
    expect(minBox("Growth").value).toBe("");
    expect(maxBox("Mkt cap").value).toBe("");
    expect(alertIn("Growth")).toBeNull();
  });

  it("Reset after a held prefix that was left by blur also clears it", () => {
    render(<Harness />);
    type(minBox("Beta"), "-");
    fireEvent.blur(minBox("Beta"));
    expect(alertIn("Beta")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "reset" }));
    expect(minBox("Beta").value).toBe("");
    expect(alertIn("Beta")).toBeNull();
  });

  it("loading a view rewrites the boxes, including one holding invalid text, and shows 1B and 5T", () => {
    render(<Harness />);
    type(minBox("Growth"), "1x");
    type(minBox("Financials"), "5");
    fireEvent.click(screen.getByRole("button", { name: "load" }));
    expect(minBox("Financials").value).toBe("70");
    expect(minBox("Growth").value).toBe("");
    expect(alertIn("Growth")).toBeNull();
    expect(minBox("Mkt cap").value).toBe("1B");
    expect(maxBox("Mkt cap").value).toBe("5T");
  });

  it("does not overwrite what is being typed when the parent hands the emitted object back", () => {
    render(<Harness />);
    type(minBox("Quote"), "12.");
    expect(minBox("Quote").value).toBe("12.");
    type(minBox("Quote"), "12.5");
    expect(minBox("Quote").value).toBe("12.5");
  });
});

describe("the Overall verdict dropdown in the Fundamental section", () => {
  it("is a multi-select with the five verdict options, Fail drawn as May not pass, and no Overall range pair", () => {
    render(<Harness />);
    expect(screen.queryByRole("group", { name: "Overall" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Overall: none selected" }));
    const options = within(screen.getByRole("listbox", { name: "Overall" })).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Strong pass", "Pass", "Pass with caution", "May not pass", "Incomplete"]);
  });

  it("emits the raw stored keys (Fail stays Fail), several at once, and clears back to none", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Overall: none selected" }));
    fireEvent.click(screen.getByRole("option", { name: "May not pass" }).querySelector("input") as HTMLInputElement);
    expect(state().overallVerdicts).toEqual(["Fail"]);
    fireEvent.click(screen.getByRole("option", { name: "Incomplete" }).querySelector("input") as HTMLInputElement);
    expect(state().overallVerdicts).toEqual(["Fail", "incomplete"]);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(state().overallVerdicts).toEqual([]);
  });

  it("turns orange only while something is selected, and counts once in the Fundamental badge", () => {
    render(<Harness />);
    const trigger = () => screen.getByRole("button", { name: /^Overall/ });
    expect(trigger()).not.toHaveClass("text-filter-active");
    fireEvent.click(trigger());
    fireEvent.click(screen.getByRole("option", { name: "Pass" }).querySelector("input") as HTMLInputElement);
    expect(trigger()).toHaveClass("text-filter-active");
    expect(screen.getByTitle("1 applied")).toBeInTheDocument();
  });
});

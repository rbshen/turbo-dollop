// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SORT_OPTIONS, SortControls } from "@/components/screener/SortControls";
import type { SortDirection, SortField } from "@/lib/screenerFilters";

afterEach(cleanup);

function setup(sortField: SortField = "overall_score", sortDirection: SortDirection = "desc") {
  const onChange = vi.fn();
  render(<SortControls sortField={sortField} sortDirection={sortDirection} onChange={onChange} />);
  return onChange;
}
const select = () => screen.getByLabelText("Sort by") as HTMLSelectElement;
const direction = () => screen.getByRole("button", { name: /^Sort direction:/ });

describe("SortControls: the field", () => {
  it("is a native select named by a real 'Sort by' label", () => {
    setup();
    expect(select().tagName).toBe("SELECT");
    expect(screen.getByText("Sort by", { selector: "label" })).toHaveAttribute("for", select().id);
  });

  it("uses the wide boxed Select: 36px, 320px capped to its container", () => {
    setup();
    expect(select()).toHaveClass("h-9", "border-border-control");
    expect(select().parentElement).toHaveClass("w-80", "max-w-full");
    expect(select().className).not.toContain("focus:outline-none");
  });

  it("keeps the stored option values and shows sentence-case labels", () => {
    setup();
    const options = Array.from(select().options).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["overall_score", "Overall score"],
      ["step1_score", "Financials score"],
      ["step2_score", "Growth rate score"],
      ["step4_score", "Profitability score"],
      ["step5_score", "Debt score"],
      ["last_price", "Quote"],
      ["market_cap", "Market cap"],
      ["pe_ratio", "P/E"],
      ["beta", "Beta"],
      ["growth_rate", "Growth rate"],
      ["warren_signal_recency", "Warren signal recency"],
      ["weinstein_stage_since", "Weinstein: stage since"],
    ]);
    expect(SORT_OPTIONS).toHaveLength(12);
  });

  it("reports the chosen field with the current direction", () => {
    const onChange = setup("overall_score", "asc");
    fireEvent.change(select(), { target: { value: "beta" } });
    expect(onChange).toHaveBeenCalledWith("beta", "asc");
  });

  it("shows the current field", () => {
    setup("market_cap");
    expect(select().value).toBe("market_cap");
  });
});

describe("SortControls: the direction toggle", () => {
  it("is an outline Button at the select's 36px, with an icon and the visible word", () => {
    setup("overall_score", "desc");
    expect(direction()).toHaveClass("h-9", "border", "border-border-input", "hover:border-brand");
    expect(direction()).toHaveTextContent("Desc");
    expect(direction().querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(direction()).not.toHaveAttribute("title");
  });

  it("names the current direction and the action, descending", () => {
    setup("overall_score", "desc");
    expect(direction()).toHaveAccessibleName("Sort direction: descending. Switch to ascending.");
  });

  it("names the current direction and the action, ascending", () => {
    setup("overall_score", "asc");
    expect(direction()).toHaveAccessibleName("Sort direction: ascending. Switch to descending.");
    expect(direction()).toHaveTextContent("Asc");
  });

  it("flips the direction and keeps the field", () => {
    const onChange = setup("beta", "desc");
    fireEvent.click(direction());
    expect(onChange).toHaveBeenCalledWith("beta", "asc");
  });

  it("flips back from ascending", () => {
    const onChange = setup("beta", "asc");
    fireEvent.click(direction());
    expect(onChange).toHaveBeenCalledWith("beta", "desc");
  });

  it("is a single button, not a segmented control", () => {
    setup();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});

describe("SortControls: layout", () => {
  it("wraps rather than overflowing", () => {
    const { container } = render(<SortControls sortField="beta" sortDirection="asc" onChange={() => {}} />);
    expect(container.firstElementChild).toHaveClass("flex", "flex-wrap", "justify-end");
  });
});

describe("SortControls: custom options", () => {
  it("lists exactly the options it is given, and reports the picked field typed as that set", () => {
    const onChange = vi.fn();
    render(
      <SortControls
        sortField="aum"
        sortDirection="asc"
        onChange={onChange}
        options={[
          { value: "aum", label: "AUM" },
          { value: "beta", label: "Beta" },
        ]}
      />
    );
    expect(Array.from(select().options).map((o) => [o.value, o.textContent])).toEqual([
      ["aum", "AUM"],
      ["beta", "Beta"],
    ]);
    fireEvent.change(select(), { target: { value: "beta" } });
    expect(onChange).toHaveBeenCalledWith("beta", "asc");
  });
});

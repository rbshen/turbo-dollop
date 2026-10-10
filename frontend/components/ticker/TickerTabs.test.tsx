// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TickerTabs } from "@/components/ticker/TickerTabs";
import { TICKER_TABS } from "@/lib/tickerTabs";

afterEach(cleanup);

describe("TickerTabs", () => {
  it("renders all 10 tabs in order via the shared Tabs primitive", () => {
    render(<TickerTabs active="summary" onChange={() => {}} />);
    expect(screen.getAllByRole("tab").map((el) => el.textContent)).toEqual(TICKER_TABS.map((t) => t.label));
  });

  it("marks the active tab selected", () => {
    render(<TickerTabs active="valuation" onChange={() => {}} />);
    expect(screen.getByRole("tab", { name: "Valuation" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "false");
  });

  it("calls onChange with the clicked tab's key", () => {
    const onChange = vi.fn();
    render(<TickerTabs active="summary" onChange={onChange} />);
    fireEvent.click(screen.getByRole("tab", { name: "Economic Moat" }));
    expect(onChange).toHaveBeenCalledWith("moat");
  });
});

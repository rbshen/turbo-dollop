// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Tabs } from "@/components/ui/tabs";

afterEach(cleanup);

const items = [
  { value: "summary", label: "Summary" },
  { value: "financials", label: "Financials" },
  { value: "ratios", label: "Ratios", count: 12 },
];

describe("Tabs", () => {
  it("marks the selected tab as aria-selected and leaves the rest unselected", () => {
    render(<Tabs value="financials" onValueChange={() => {}} items={items} />);
    expect(screen.getByRole("tab", { name: "Financials" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "Ratios12" })).toHaveAttribute("aria-selected", "false");
  });

  it("calls onValueChange when a different tab is clicked", () => {
    const onValueChange = vi.fn();
    render(<Tabs value="summary" onValueChange={onValueChange} items={items} />);
    fireEvent.click(screen.getByRole("tab", { name: "Ratios12" }));
    expect(onValueChange).toHaveBeenCalledWith("ratios");
  });

  it("moves focus to the next tab on ArrowRight", async () => {
    render(<Tabs value="summary" onValueChange={() => {}} items={items} />);
    const summaryTab = screen.getByRole("tab", { name: "Summary" });
    summaryTab.focus();
    fireEvent.keyDown(summaryTab, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Financials" })).toHaveFocus());
  });

  it("renders the count in the mono figure style", () => {
    render(<Tabs value="summary" onValueChange={() => {}} items={items} />);
    expect(screen.getByText("12")).toBeInTheDocument();
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "@/components/ui/segmented-control";

afterEach(cleanup);

const options = [
  { value: "sp500", label: "S&P 500" },
  { value: "nasdaq", label: "Nasdaq" },
  { value: "dow", label: "Dow 30" },
];

describe("SegmentedControl", () => {
  it("exposes aria-pressed on the selected segment only", () => {
    render(<SegmentedControl value="nasdaq" onValueChange={() => {}} options={options} />);
    expect(screen.getByRole("button", { name: "Nasdaq" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "S&P 500" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Dow 30" })).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onValueChange when a different segment is clicked", () => {
    const onValueChange = vi.fn();
    render(<SegmentedControl value="sp500" onValueChange={onValueChange} options={options} />);
    fireEvent.click(screen.getByRole("button", { name: "Dow 30" }));
    expect(onValueChange).toHaveBeenCalledWith("dow");
  });

  it("never calls onValueChange with an empty value when the selected segment is clicked again", () => {
    const onValueChange = vi.fn();
    render(<SegmentedControl value="sp500" onValueChange={onValueChange} options={options} />);
    fireEvent.click(screen.getByRole("button", { name: "S&P 500" }));
    expect(onValueChange).not.toHaveBeenCalled();
  });

  it("names the group when given an aria-label, and is an unnamed group otherwise", () => {
    const { rerender } = render(<SegmentedControl value="sp500" onValueChange={() => {}} options={options} />);
    expect(screen.getByRole("group")).not.toHaveAttribute("aria-label");
    rerender(<SegmentedControl value="sp500" onValueChange={() => {}} options={options} aria-label="Index universe" />);
    expect(screen.getByRole("group", { name: "Index universe" })).toBeInTheDocument();
  });
});

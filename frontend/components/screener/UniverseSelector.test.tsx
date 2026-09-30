// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UniverseSelector } from "@/components/screener/UniverseSelector";

afterEach(cleanup);

// Regression test for the session-5c swap off the pre-session-1
// shared/SegmentedControl.tsx onto the shared ui/segmented-control.tsx
// primitive -- confirms the value/onValueChange adapter still surfaces a
// plain ScreenerUniverse to the caller, and that re-clicking the already-
// active segment is a no-op (unchanged single-select behavior).
describe("UniverseSelector", () => {
  it("calls onChange with the clicked universe", () => {
    const onChange = vi.fn();
    render(<UniverseSelector value="sp500" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Dow 30" }));
    expect(onChange).toHaveBeenCalledWith("dow");
  });

  it("does not call onChange when the already-active universe is clicked again", () => {
    const onChange = vi.fn();
    render(<UniverseSelector value="all" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

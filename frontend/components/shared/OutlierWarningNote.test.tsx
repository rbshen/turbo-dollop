// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { OutlierWarningNote } from "@/components/shared/OutlierWarningNote";
import type { OutlierWarning } from "@/lib/api/types";

afterEach(cleanup);

const warning = {
  metric: "total_debt",
  date: "2026-06-30",
  value: 5_000_000_000,
  trailing_median: 1_000_000_000,
  sec_cross_check: null,
} as unknown as OutlierWarning;

describe("OutlierWarningNote", () => {
  it("renders nothing without warnings", () => {
    const { container } = render(<OutlierWarningNote warnings={[]} labels={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says one or more recent quarters look anomalous, and lists each warned metric", () => {
    render(<OutlierWarningNote warnings={[warning]} labels={{ total_debt: "Total debt" }} />);
    expect(screen.getByText(/One or more recent quarters look anomalous/)).toBeInTheDocument();
    expect(screen.getByText(/Total debt \(2026-06-30\): FMP/)).toBeInTheDocument();
  });

  it("draws the warning as an icon, not an emoji, and keeps the word for a screen reader", () => {
    const { container } = render(<OutlierWarningNote warnings={[warning]} labels={{}} />);
    expect(container.textContent).not.toMatch(/[\u26A0\uFE0F]/);
    const icon = container.querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Warning:", { exact: false, selector: ".sr-only" })).toBeInTheDocument();
  });
});

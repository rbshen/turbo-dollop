// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SecCellCheckButton } from "@/components/ticker/SecCellCheckButton";

// Characterization of the on-demand SEC EDGAR cross-check: one click, one request, and the cell then shows the result.
const h = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiFetch: (...args: unknown[]) => h.apiFetch(...args) }));

afterEach(cleanup);
beforeEach(() => {
  h.apiFetch.mockReset();
});

const idleButton = () => screen.getByRole("button");

describe("SecCellCheckButton", () => {
  it("starts as one icon button with a title, and makes no request until clicked", () => {
    render(<SecCellCheckButton ticker="AAPL" field="incomeTaxesPaid" periodEnd="2025-09-27" />);
    expect(idleButton()).toHaveAttribute("title", "Check SEC EDGAR's filed figure for this period");
    expect(h.apiFetch).not.toHaveBeenCalled();
  });

  it("requests that ticker, field and period on click, then shows the SEC figure", async () => {
    h.apiFetch.mockResolvedValue({ available: true, matches_fmp: true, sec_value: 1_500_000_000, note: "n" });
    render(<SecCellCheckButton ticker="AAPL" field="interestPaid" periodEnd="2025-09-27" />);
    fireEvent.click(idleButton());
    expect(screen.getByText("checking…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/^SEC:/)).toBeInTheDocument());
    expect(h.apiFetch).toHaveBeenCalledWith("/tickers/AAPL/financials/cash-flow-cell-check?field=interestPaid&period_end=2025-09-27");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows 'n/a' when SEC has no figure, and 'error' when the request fails", async () => {
    h.apiFetch.mockResolvedValueOnce({ available: false, note: "none" });
    const first = render(<SecCellCheckButton ticker="AAPL" field="interestPaid" periodEnd="2025-09-27" />);
    fireEvent.click(idleButton());
    await waitFor(() => expect(screen.getByText("n/a")).toBeInTheDocument());
    first.unmount();
    h.apiFetch.mockRejectedValueOnce(new Error("boom"));
    render(<SecCellCheckButton ticker="AAPL" field="interestPaid" periodEnd="2025-09-27" />);
    fireEvent.click(idleButton());
    await waitFor(() => expect(screen.getByText("error")).toBeInTheDocument());
  });

  // Session 16: an icon-only button needs an accessible name; the title stays as its tooltip.
  it("is named for what it checks (field and period), keeps its title, and hides the icon from assistive tech", () => {
    render(<SecCellCheckButton ticker="AAPL" field="incomeTaxesPaid" periodEnd="2025-09-27" />);
    expect(screen.getByRole("button", { name: "Check SEC EDGAR figure for income taxes paid, period ending 2025-09-27" })).toHaveAttribute(
      "title",
      "Check SEC EDGAR's filed figure for this period",
    );
    expect(idleButton().querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("names the interest field too", () => {
    render(<SecCellCheckButton ticker="AAPL" field="interestPaid" periodEnd="2024-12-31" />);
    expect(screen.getByRole("button", { name: "Check SEC EDGAR figure for interest paid, period ending 2024-12-31" })).toBeInTheDocument();
  });
});

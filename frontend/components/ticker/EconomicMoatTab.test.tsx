// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EconomicMoatTab } from "@/components/ticker/EconomicMoatTab";
import type { TickerMoatOut } from "@/lib/api/types";

const apiPut = vi.fn();
const mutate = vi.fn();
let hook: { data?: TickerMoatOut; error?: Error; isLoading?: boolean };

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));
vi.mock("swr", () => ({ mutate: (...args: unknown[]) => mutate(...args) }));
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => hook }));

beforeEach(() => {
  hook = { data: { ticker: "AAPL", moat: "narrow_moat", updated_at: "2026-06-01T00:00:00" } };
  apiPut.mockReset().mockResolvedValue(undefined);
  mutate.mockReset().mockResolvedValue(undefined);
});
afterEach(cleanup);

function pick(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

describe("EconomicMoatTab: confirm panel", () => {
  it("shows the current rating's description and no confirm panel at first", () => {
    render(<EconomicMoatTab ticker="AAPL" />);
    expect(screen.getByText(/Some durable advantage/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("asks before saving a different rating, with Confirm and Cancel", () => {
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Wide Moat");
    expect(screen.getByText(/This changes how Overall Assessment is scored for AAPL\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("words the question in sentence case: the economic moat and the chosen rating", () => {
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Wide Moat");
    expect(screen.getByText(/Set economic moat to/)).toBeInTheDocument();
    expect(screen.getByText("Wide moat", { selector: "span" })).toBeInTheDocument();
  });

  it("draws Cancel as an outline Button (no hand-written ghost-plus-border override)", () => {
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Wide Moat");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveClass("border", "border-border-input", "h-9");
    expect(cancel).not.toHaveClass("bg-surface-2");
  });

  it("does not ask when the current rating is picked again", () => {
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Narrow Moat");
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  });

  it("Cancel drops the pending choice without saving", () => {
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Wide Moat");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.getByText(/Some durable advantage/)).toBeInTheDocument();
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("Confirm PUTs the pending moat and refreshes this ticker's data and the Screener", async () => {
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Wide Moat");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith("/tickers/AAPL/moat", { moat: "wide_moat" }));
    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(2));
    expect(mutate.mock.calls[1][0]).toBe("/screener");
  });

  it("disables Confirm and Cancel while saving", async () => {
    let resolve: (v?: unknown) => void = () => {};
    apiPut.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Wide Moat");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    resolve();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Saving…" })).not.toBeInTheDocument());
  });

  it("shows a failure message when the save is rejected", async () => {
    apiPut.mockRejectedValue(new Error("PUT x failed: 500"));
    render(<EconomicMoatTab ticker="AAPL" />);
    pick("Wide Moat");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Failed to save — please try again.")).toBeInTheDocument();
  });
});

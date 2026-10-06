// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RefreshButton } from "@/components/ticker/RefreshButton";

const apiPost = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
}));
const mutate = vi.fn();
vi.mock("swr", () => ({
  mutate: (...args: unknown[]) => mutate(...args),
}));

beforeEach(() => {
  vi.useFakeTimers();
  apiPost.mockReset();
  mutate.mockReset();
  apiPost.mockResolvedValue({});
  mutate.mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("RefreshButton", () => {
  it("is an enabled button reading 'Refresh data' when idle", () => {
    render(<RefreshButton ticker="AAPL" />);
    expect(screen.getByRole("button", { name: /^Refresh data$/i })).toBeEnabled();
  });

  it("shows Refreshing… and disables itself while the request is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    apiPost.mockReturnValue(new Promise((r) => (resolve = r)));
    render(<RefreshButton ticker="AAPL" />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    expect(apiPost).toHaveBeenCalledWith("/tickers/AAPL/refresh", undefined);
    resolve({});
    await flush();
  });

  it("revalidates every key under the ticker, then shows Refreshed and returns to idle after 3 seconds", async () => {
    render(<RefreshButton ticker="AAPL" />);
    fireEvent.click(screen.getByRole("button"));
    await flush();
    expect(screen.getByRole("button", { name: /^Refreshed/ })).toBeEnabled();
    const matcher = mutate.mock.calls[0][0] as (key: unknown) => boolean;
    expect(matcher("/tickers/AAPL/summary")).toBe(true);
    expect(matcher("/tickers/AAPL/score")).toBe(true); // the stored row the Review status is read from
    expect(matcher("/tickers/MSFT/summary")).toBe(false);
    expect(matcher(["/tickers/AAPL"])).toBe(false);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("button", { name: /^Refresh data$/i })).toBeInTheDocument();
  });

  it("shows Refresh failed on an error and returns to idle after 3 seconds", async () => {
    apiPost.mockRejectedValue(new Error("POST failed: 503"));
    render(<RefreshButton ticker="AAPL" />);
    fireEvent.click(screen.getByRole("button"));
    await flush();
    expect(screen.getByRole("button", { name: "Refresh failed" })).toBeEnabled();
    expect(mutate).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("button", { name: /^Refresh data$/i })).toBeInTheDocument();
  });

  it("is a 32px outline button in every state", async () => {
    render(<RefreshButton ticker="AAPL" />);
    const button = screen.getByRole("button");
    expect(button).toHaveClass("border", "border-border-input", "h-8");
    fireEvent.click(button);
    await flush();
    expect(screen.getByRole("button")).toHaveClass("border", "border-border-input", "h-8");
  });

  it("replaces the old check-mark glyph with a hidden icon beside the word Refreshed", async () => {
    render(<RefreshButton ticker="AAPL" />);
    expect(screen.getByRole("button").querySelector("svg")).toBeNull();
    fireEvent.click(screen.getByRole("button"));
    await flush();
    const button = screen.getByRole("button", { name: "Refreshed" });
    expect(button.textContent).toBe("Refreshed");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});

// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RecomputeButton } from "@/components/screener/RecomputeButton";

const h = vi.hoisted(() => ({ apiPost: vi.fn(), mutate: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiPost: (...args: unknown[]) => h.apiPost(...args) }));
vi.mock("swr", () => ({ mutate: (...args: unknown[]) => h.mutate(...args) }));

// Characterization: RecomputeButton's logic is unchanged by the outline-button
// restyle (session 10, part 3), and these pin it.
beforeEach(() => {
  h.apiPost.mockReset().mockResolvedValue({ processed: 580, failed: 2, duration_seconds: 12.34 });
  h.mutate.mockReset().mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("RecomputeButton", () => {
  it("starts as 'Recompute all scores'", () => {
    render(<RecomputeButton />);
    expect(screen.getByRole("button", { name: "Recompute all scores" })).toBeEnabled();
  });

  it("is an outline Button (32px), not the hand-written ghost-plus-border override", () => {
    render(<RecomputeButton />);
    const button = screen.getByRole("button");
    expect(button).toHaveClass("h-8", "border", "border-border-input", "hover:border-brand", "bg-transparent");
  });

  it("posts to /screener/recompute, refreshes the /screener SWR keys and summarises the run", async () => {
    render(<RecomputeButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });
    expect(h.apiPost).toHaveBeenCalledWith("/screener/recompute", undefined);
    const matcher = h.mutate.mock.calls[0][0] as (key: unknown) => boolean;
    expect(matcher("/screener?universe=all")).toBe(true);
    expect(matcher("/watchlists")).toBe(false);
    expect(matcher(["/screener"])).toBe(false);
    expect(screen.getByRole("button", { name: "Recomputed ✓" })).toBeInTheDocument();
    expect(screen.getByText("580 processed, 2 failed in 12.3s")).toBeInTheDocument();
  });

  it("is disabled and reads 'Recomputing…' while the request is in flight", async () => {
    let finish: (v: unknown) => void = () => {};
    h.apiPost.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    render(<RecomputeButton />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button", { name: "Recomputing…" })).toBeDisabled();
    await act(async () => {
      finish({ processed: 1, failed: 0, duration_seconds: 1 });
    });
  });

  it("omits the failed count when nothing failed", async () => {
    h.apiPost.mockResolvedValueOnce({ processed: 10, failed: 0, duration_seconds: 1 });
    render(<RecomputeButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });
    expect(screen.getByText("10 processed in 1.0s")).toBeInTheDocument();
  });

  it("shows 'Recompute failed' on an error, and both states revert after 4 seconds", async () => {
    vi.useFakeTimers();
    h.apiPost.mockRejectedValueOnce(new Error("boom"));
    render(<RecomputeButton />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button"));
    });
    expect(screen.getByRole("button", { name: "Recompute failed" })).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.getByRole("button", { name: "Recompute all scores" })).toBeInTheDocument();
  });
});

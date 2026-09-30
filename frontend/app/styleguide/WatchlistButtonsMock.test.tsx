// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WatchlistButtonsMock } from "./WatchlistButtonsMock";

// Smoke tests: the reference renders from mock data alone, shows every state the
// brief lists, the real components inside it behave, and nothing reaches the network.
const fetchSpy = vi.fn();
beforeEach(() => {
  fetchSpy.mockReset();
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const frame = (id: string) => within(screen.getByTestId(id));

describe("WatchlistButtonsMock: rename", () => {
  it("shows idle, editing, invalid and two server-error states", () => {
    render(<WatchlistButtonsMock />);
    expect(frame("rename-idle").getByText("Growth · 3 tickers")).toBeInTheDocument();
    expect(frame("rename-idle").getByRole("button", { name: "Rename Growth" })).toBeInTheDocument();
    expect(frame("rename-editing").getByRole("textbox", { name: "Watchlist name" })).toHaveValue("Growth");

    const invalid = frame("rename-invalid");
    expect(invalid.getByRole("textbox", { name: "Watchlist name" })).toHaveAttribute("aria-invalid", "true");
    expect(invalid.getByRole("alert")).toHaveTextContent("Name can't be empty");

    expect(frame("rename-server-error").getByRole("alert")).toHaveTextContent('"Value" already exists');
    expect(frame("rename-server-message").getByRole("alert")).toHaveTextContent("name: String should have at most 100 characters");
  });

  it("draws the editing state on the kit input with outline buttons, and wraps at 311px", () => {
    render(<WatchlistButtonsMock />);
    const editing = frame("rename-editing");
    const input = editing.getByRole("textbox", { name: "Watchlist name" });
    expect(input.className).toContain("w-80");
    expect(input.className).not.toContain("focus:outline-none");
    expect(editing.getByRole("button", { name: "Save" })).toHaveClass("border-border-input", "h-9");
    expect(frame("rename-narrow").getByRole("textbox", { name: "Watchlist name" }).parentElement).toHaveClass("flex-wrap");
  });

  it("a live rename with the mock request never touches the network", async () => {
    vi.useFakeTimers();
    render(<WatchlistButtonsMock />);
    const editing = frame("rename-editing");
    fireEvent.change(editing.getByRole("textbox", { name: "Watchlist name" }), { target: { value: "Value" } });
    fireEvent.click(editing.getByRole("button", { name: "Save" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("a live rejected rename shows the duplicate-name message", async () => {
    vi.useFakeTimers();
    render(<WatchlistButtonsMock />);
    const f = frame("rename-server-error");
    fireEvent.click(f.getByRole("button", { name: "Save" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(f.getByRole("alert")).toHaveTextContent('"Value" already exists');
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WatchlistButtonsMock: delete", () => {
  it("shows idle, asking and failed states", () => {
    render(<WatchlistButtonsMock />);
    expect(frame("delete-idle").getByRole("button", { name: "Delete Growth" })).toHaveAttribute("title", "Delete watchlist");
    const asking = frame("delete-confirming");
    expect(asking.getByText('Delete "Growth"?')).toBeInTheDocument();
    expect(asking.getByRole("button", { name: "Confirm" })).toHaveClass("text-negative");
    expect(asking.getByRole("button", { name: "Cancel" })).toHaveClass("border-border-input");
    expect(frame("delete-error").getByRole("button", { name: "Delete Growth" })).toHaveAttribute("title", "Failed to delete — retry");
  });

  it("confirming with the mock request never touches the network", async () => {
    vi.useFakeTimers();
    render(<WatchlistButtonsMock />);
    fireEvent.click(frame("delete-confirming").getByRole("button", { name: "Confirm" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WatchlistButtonsMock: export and refresh", () => {
  it("shows the export menu closed, open and disabled", () => {
    render(<WatchlistButtonsMock />);
    expect(frame("export-closed").getByRole("button", { name: "Export list" })).toHaveAttribute("aria-expanded", "false");
    expect(frame("export-closed").queryByRole("menu")).not.toBeInTheDocument();
    expect(frame("export-open").getByRole("button", { name: "Export list" })).toHaveAttribute("aria-expanded", "true");
    expect(frame("export-open").getAllByRole("menuitem")).toHaveLength(2);
    expect(frame("export-disabled").getByRole("button", { name: "Export list" })).toBeDisabled();
  });

  it("shows refresh idle, loading, refreshed and failed", () => {
    render(<WatchlistButtonsMock />);
    expect(frame("refresh-idle").getByRole("button", { name: "Refresh data" })).toBeEnabled();
    expect(frame("refresh-loading").getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    expect(frame("refresh-success").getByRole("button", { name: "Refreshed" })).toBeEnabled();
    expect(frame("refresh-error").getByRole("button", { name: "Refresh failed" })).toBeEnabled();
  });

  it("a live refresh cycles through the mock request and never touches the network", async () => {
    vi.useFakeTimers();
    render(<WatchlistButtonsMock />);
    const idle = frame("refresh-idle");
    fireEvent.click(idle.getByRole("button", { name: "Refresh data" }));
    expect(idle.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(idle.getByRole("button", { name: "Refreshed" })).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("uses no text-glyph icons anywhere in the section", () => {
    const { container } = render(<WatchlistButtonsMock />);
    const text = container.textContent ?? "";
    for (const glyph of ["▾", "▴", "✓", "×", "−"]) expect(text).not.toContain(glyph);
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WarrenWatchRemoveButton } from "@/components/technical-ideas/WarrenWatchRemoveButton";
import { WarrenWatchTable } from "@/components/technical-ideas/WarrenWatchTable";
import type { WarrenWatchRowOut } from "@/lib/api/types";
import { TestAuth } from "@/lib/auth/testAuth";
import type { Role } from "@/lib/auth/AuthProvider";

const removeMock = vi.hoisted(() => vi.fn(async () => {}));
vi.mock("@/lib/hooks/useWarrenWatch", () => ({ removeWarrenWatchRow: removeMock, useWarrenWatch: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  removeMock.mockClear();
});

function row(over: Partial<WarrenWatchRowOut>): WarrenWatchRowOut {
  return {
    ticker: "AAA", profile: "any", latest_arrow_color: "yellow", latest_arrow_direction: "up", latest_arrow_at: "2026-10-15T13:30:00",
    instruction_type: 3, instruction_text: "YELLOW UP - Buy.", entry_kind: "yellow", entry_price: 100, stop_price: 90, stop_basis: "10%",
    status: "active", breached_at: null, last_signal_at: "2026-10-15T13:30:00", last_updated_at: "2026-10-16T01:25:00", age_bars: 5,
    last_signal_age_bars: 5, ...over,
  };
}

function draw(rows: WarrenWatchRowOut[], role: Role = "admin") {
  return render(
    <TestAuth role={role}>
      <WarrenWatchTable rows={rows} />
    </TestAuth>,
  );
}

function bodyRow(ticker: string): HTMLElement {
  return screen.getByRole("link", { name: ticker }).closest("tr")!;
}

describe("WarrenWatchTable", () => {
  it("has the seven columns and sorts the most recent last signal first", () => {
    draw([
      row({ ticker: "OLD", last_signal_at: "2026-10-01T09:30:00" }),
      row({ ticker: "NEW", last_signal_at: "2026-10-15T15:30:00" }),
    ]);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Ticker", "Signal", "Instruction", "Stop", "Status", "Last signal", "Last updated", "Actions",
    ]);
    const tickers = screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("link")[0].textContent);
    expect(tickers).toEqual(["NEW", "OLD"]);
  });

  it("links the ticker to its page in a new tab and shows the profile for a profiled ticker only", () => {
    draw([row({ ticker: "QQQ", profile: "qqq" }), row({ ticker: "AAA" })]);
    const link = screen.getByRole("link", { name: "QQQ" });
    expect(link).toHaveAttribute("href", "/tickers/QQQ");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("qqq profile")).toBeInTheDocument();
    expect(screen.getAllByText(/profile$/)).toHaveLength(1);
  });

  it("opens the ticker in a new tab on a row click, but not from the ticker link or the remove control", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    draw([row({ ticker: "AAA" })]);
    fireEvent.click(within(bodyRow("AAA")).getByText("YELLOW UP - Buy."));
    expect(open).toHaveBeenCalledWith("/tickers/AAA", "_blank", "noopener,noreferrer");
    open.mockClear();
    fireEvent.click(screen.getByRole("link", { name: "AAA" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove AAA" }));
    expect(open).not.toHaveBeenCalled();
  });

  it("draws the signal pill with the arrow's colour and direction", () => {
    draw([
      row({ ticker: "BLU", latest_arrow_color: "blue", latest_arrow_direction: "up" }),
      row({ ticker: "YEL", latest_arrow_color: "yellow", latest_arrow_direction: "down" }),
      row({ ticker: "GRY", latest_arrow_color: "gray", latest_arrow_direction: "up" }),
    ]);
    expect(within(bodyRow("BLU")).getByText("Blue Up")).toHaveClass("text-chart-ema21");
    expect(within(bodyRow("YEL")).getByText("Yellow Down")).toHaveClass("text-chart-warren-yellow");
    expect(within(bodyRow("GRY")).getByText("Gray Up")).toHaveClass("text-chart-warren-gray");
    expect(within(bodyRow("YEL")).getByText("Yellow Down")).toHaveAttribute("title", "Yellow Down · candle Oct 15, 13:30 ET");
  });

  it("shows the stop price with its basis tag, and a dash when there is no stop", () => {
    draw([
      row({ ticker: "PCT", stop_price: 90, stop_basis: "10%" }),
      row({ ticker: "LPS", stop_price: 95.5, stop_basis: "LP" }),
      row({ ticker: "ENT", stop_price: 100, stop_basis: "entry" }),
      row({ ticker: "NON", stop_price: null, stop_basis: "none", entry_kind: "blue" }),
    ]);
    expect(within(bodyRow("PCT")).getByText("$90.00")).toBeInTheDocument();
    expect(within(bodyRow("PCT")).getByText("10%")).toBeInTheDocument();
    expect(within(bodyRow("LPS")).getByText("LP")).toBeInTheDocument();
    expect(within(bodyRow("ENT")).getByText("Entry")).toBeInTheDocument();
    const none = within(bodyRow("NON"));
    expect(none.getByText("—")).toBeInTheDocument();
    expect(none.queryByText("10%")).toBeNull();
  });

  it("explains a stop above the entry price and stays quiet otherwise", () => {
    draw([
      row({ ticker: "ABV", entry_price: 142.42, stop_price: 162.55, stop_basis: "LP" }),
      row({ ticker: "BLW", entry_price: 100, stop_price: 90 }),
    ]);
    expect(within(bodyRow("ABV")).getByText("$162.55")).toBeInTheDocument();
    expect(within(bodyRow("ABV")).getByLabelText(/Above the entry price \(\$142\.42\)/)).toBeInTheDocument();
    expect(within(bodyRow("BLW")).queryByLabelText(/Above the entry price/)).toBeNull();
  });

  it("marks a breached row with a red Stop breached badge and an active row Active", () => {
    draw([row({ ticker: "BRC", status: "breached", breached_at: "2026-10-16T11:30:00" }), row({ ticker: "ACT" })]);
    const badge = within(bodyRow("BRC")).getByText("Stop breached");
    expect(badge).toHaveClass("text-negative");
    expect(badge).toHaveAttribute("title", "Low reached the stop on the Oct 16, 11:30 ET candle");
    expect(within(bodyRow("ACT")).getByText("Active")).toBeInTheDocument();
    expect(within(bodyRow("ACT")).queryByText("Stop breached")).toBeNull();
  });

  it("shows the last signal as ET date and bars ago, and the last-updated stamp", () => {
    draw([row({ ticker: "AAA", last_signal_age_bars: 5 }), row({ ticker: "BBB", last_signal_at: "2026-10-15T15:30:00", last_signal_age_bars: 0 })]);
    expect(within(bodyRow("AAA")).getByText("Oct 15, 13:30")).toBeInTheDocument();
    expect(within(bodyRow("AAA")).getByText("5 bars ago")).toBeInTheDocument();
    expect(within(bodyRow("AAA")).getByText("Oct 16, 01:25")).toBeInTheDocument();
    expect(within(bodyRow("BBB")).getByText("this candle")).toBeInTheDocument();
  });

  it("gives an admin a Remove button per row and a viewer none", () => {
    draw([row({ ticker: "AAA" }), row({ ticker: "BBB" })], "admin");
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(2);
    cleanup();
    draw([row({ ticker: "AAA" }), row({ ticker: "BBB" })], "viewer");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("WarrenWatchRemoveButton", () => {
  function drawButton(remove?: (t: string) => Promise<void>, role: Role = "admin") {
    return render(
      <TestAuth role={role}>
        <WarrenWatchRemoveButton ticker="AAA" remove={remove} />
      </TestAuth>,
    );
  }

  it("asks to confirm and removes nothing until Confirm", async () => {
    const remove = vi.fn(async () => {});
    drawButton(remove);
    fireEvent.click(screen.getByRole("button", { name: "Remove AAA" }));
    expect(screen.getByText("Remove AAA?")).toBeInTheDocument();
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("AAA"));
  });

  it("Cancel backs out without a request", () => {
    const remove = vi.fn(async () => {});
    drawButton(remove);
    fireEvent.click(screen.getByRole("button", { name: "Remove AAA" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Remove AAA" })).toBeInTheDocument();
    expect(remove).not.toHaveBeenCalled();
  });

  it("shows a retry state when the request fails", async () => {
    drawButton(async () => {
      throw new Error("boom");
    });
    fireEvent.click(screen.getByRole("button", { name: "Remove AAA" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove AAA" })).toHaveAttribute("title", "Failed to remove — retry"));
  });

  it("renders nothing for a viewer", () => {
    drawButton(undefined, "viewer");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

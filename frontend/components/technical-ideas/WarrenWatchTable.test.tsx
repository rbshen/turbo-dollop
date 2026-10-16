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
    instruction_type: 3, instruction_text: "YELLOW UP - Buy.", entry_kind: "yellow", entry_at: "2026-10-15T13:30:00", last_price: 110, last_price_date: "2026-10-15", pl_pct: 0.1, stop_distance_pct: 0.1818, entry_price: 100, stop_price: 90, stop_basis: "10%", stop_moved_at: null, stop_moved_by: null,
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
  it("has the eleven columns and sorts the newest latest arrow first", () => {
    draw([
      row({ ticker: "OLD", latest_arrow_at: "2026-10-01T09:30:00" }),
      row({ ticker: "NEW", latest_arrow_at: "2026-10-15T15:30:00" }),
    ]);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Ticker", "Signal", "Instruction", "Entry", "Last", "P/L %", "Stop", "Stop dist.", "Status", "Last signal", "Last updated", "Actions",
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

  it("puts the stop age and the rule that set it in the Stop cell tooltip, and none when the row has no stop age", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-16T12:00:00Z"));
    draw([
      row({ ticker: "TRL", stop_price: 95.5, stop_basis: "LP", stop_moved_at: "2026-10-16T09:30:00", stop_moved_by: "trail" }),
      row({ ticker: "BDN", stop_price: 95.5, stop_basis: "LP", stop_moved_at: "2026-10-09T11:30:00", stop_moved_by: "blue_down" }),
      row({ ticker: "OLD", stop_price: 90, stop_basis: "10%" }),
      row({ ticker: "NON", stop_price: null, stop_basis: "none", entry_kind: "blue" }),
    ]);
    const stopCell = (ticker: string) => within(bodyRow(ticker)).getAllByText(/^\$|^—$/).map((n) => n.closest("td")!).find((td) => td.textContent?.includes("LP") || td.textContent?.includes("10%"));
    expect(stopCell("TRL")).toHaveAttribute("title", "Trailed to 2nd LP Oct 16, 09:30 ET · today");
    expect(stopCell("BDN")).toHaveAttribute("title", "Set Oct 9, 11:30 ET by Blue Down (2nd LP) · 7 days ago");
    expect(stopCell("OLD")).not.toHaveAttribute("title");
    expect(within(bodyRow("NON")).getByText("—").closest("td")).not.toHaveAttribute("title");
    vi.useRealTimers();
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

  it("wraps a long instruction to two lines with the full text in the tooltip, on a bounded cell", () => {
    const longest =
      "YELLOW UP: new entry = 10% stop; already in trade = stop to 2nd LP or 10% below candle low, whichever is lower";
    const grayDown = "GRAY DOWN: yellow entry = stop to entry; blue entry = no action";
    draw([row({ ticker: "LNG", instruction_text: longest }), row({ ticker: "GRD", instruction_text: grayDown })]);
    for (const [ticker, text] of [["LNG", longest], ["GRD", grayDown]] as const) {
      const text_el = within(bodyRow(ticker)).getByText(text);
      expect(text_el).toHaveAttribute("title", text);
      expect(text_el).toHaveClass("line-clamp-2");
      const cell = text_el.closest("td")!;
      expect(cell).toHaveClass("min-w-[160px]", "max-w-[300px]", "whitespace-normal");
    }
  });

  it("shows the entry price with a tooltip of kind, ET date, age and the close-not-fill note, and a dash with no entry", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-16T12:00:00Z"));
    draw([
      row({ ticker: "OLD", entry_kind: "yellow", entry_at: "2026-03-10T13:30:00", entry_price: 142.5 }),
      row({ ticker: "BLU", entry_kind: "blue", entry_at: "2026-10-09T09:30:00", entry_price: 55 }),
      row({ ticker: "NOE", entry_kind: null, entry_at: null, entry_price: null, pl_pct: null, stop_price: null, stop_distance_pct: null, stop_basis: "none" }),
    ]);
    const old = within(bodyRow("OLD")).getByText("$142.50");
    expect(old).toHaveAttribute("title", "Yellow entry · Mar 10, 13:30 ET · 7 months ago. The close of the entry candle, not an actual fill.");
    expect(within(bodyRow("BLU")).getByText("$55.00")).toHaveAttribute("title", expect.stringContaining("Blue entry · Oct 9, 09:30 ET · 7 days ago"));
    // Gray-born row: Entry, P/L % and Stop dist. and Stop are all dashes.
    expect(within(bodyRow("NOE")).getAllByText("—")).toHaveLength(4);
    vi.useRealTimers();
  });

  it("shows the last daily close with its date in the tooltip, and a dash when none is cached", () => {
    draw([
      row({ ticker: "AAA", last_price: 123.45, last_price_date: "2026-10-15" }),
      row({ ticker: "NOP", last_price: null, last_price_date: null, pl_pct: null, stop_distance_pct: null }),
    ]);
    expect(within(bodyRow("AAA")).getByText("$123.45")).toHaveAttribute("title", "Daily close of Oct 15");
    expect(within(bodyRow("NOP")).getAllByText("—")).toHaveLength(3); // Last, P/L %, Stop dist.
  });

  it("draws P/L % signed with one decimal, green above and red below, and muted with a hypothetical note on a breached row", () => {
    draw([
      row({ ticker: "WIN", pl_pct: 0.1234 }),
      row({ ticker: "LOS", pl_pct: -0.0456 }),
      row({ ticker: "BRC", status: "breached", breached_at: "2026-10-13T09:30:00", pl_pct: -0.3 }),
      row({ ticker: "BRW", status: "breached", breached_at: "2026-10-13T09:30:00", pl_pct: 0.2 }),
    ]);
    expect(within(bodyRow("WIN")).getByText("+12.3%")).toHaveClass("text-positive");
    expect(within(bodyRow("LOS")).getByText("-4.6%")).toHaveClass("text-negative");
    for (const [ticker, text] of [["BRC", "-30.0%"], ["BRW", "+20.0%"]] as const) {
      const cell = within(bodyRow(ticker)).getByText(text);
      expect(cell).toHaveClass("text-text-tertiary");
      expect(cell).not.toHaveClass("text-positive");
      expect(cell).not.toHaveClass("text-negative");
      expect(cell).toHaveAttribute("title", "Hypothetical: this trade was stopped out at its stop, not at today's price.");
    }
    expect(within(bodyRow("WIN")).getByText("+12.3%")).not.toHaveAttribute("title");
  });

  it("draws Stop dist. % signed, red only when negative on an ACTIVE row, and a dash with no stop", () => {
    draw([
      row({ ticker: "OK", stop_distance_pct: 0.0812 }),
      row({ ticker: "MIS", stop_distance_pct: -0.0345 }),
      row({ ticker: "BRC", status: "breached", breached_at: "2026-10-13T09:30:00", stop_distance_pct: -0.2 }),
      row({ ticker: "NON", stop_price: null, stop_basis: "none", stop_distance_pct: null }),
    ]);
    const ok = within(bodyRow("OK")).getByText("+8.1%");
    expect(ok).not.toHaveClass("text-negative");
    expect(ok).toHaveClass("text-text-secondary");
    const missed = within(bodyRow("MIS")).getByText("-3.5%");
    expect(missed).toHaveClass("text-negative");
    expect(missed).toHaveAttribute("title", expect.stringContaining("below the stop"));
    expect(within(bodyRow("BRC")).getByText("-20.0%")).not.toHaveClass("text-negative"); // breached: neutral
    expect(within(bodyRow("NON")).getAllByText("—")).toHaveLength(2); // Stop and Stop dist.
  });

  it("fits without horizontal scrolling: tight cell padding and no cell is wider than the page container allows", () => {
    const { container } = draw([row({ ticker: "AAA" })]);
    // Every body cell uses the tight padding (the kit's pr-4 would add ~72px across the twelve columns); only the Instruction cell wraps.
    for (const td of container.querySelectorAll("tbody td")) {
      expect(td).not.toHaveClass("pr-4");
      if (!td.className.includes("whitespace-normal")) expect(td).toHaveClass("whitespace-nowrap");
    }
    expect(container.querySelectorAll("tbody td")).toHaveLength(12);
  });

  it("keeps the header row sticky inside a bounded scroll box", () => {
    const { container } = draw([row({ ticker: "AAA" })]);
    expect(container.querySelector('[data-slot="table-container"]')).toHaveClass("max-h-[70vh]", "overflow-auto");
    for (const th of screen.getAllByRole("columnheader")) expect(th).toHaveClass("sticky", "top-0", "bg-page");
  });

  it("shows Stop hit since the breach candle on a breached row, keeping the stop and the last instruction in the tooltip", () => {
    draw([row({ ticker: "BRC", status: "breached", breached_at: "2026-10-13T09:30:00", instruction_text: "YELLOW UP INITIAL ENTRY - Use appropriate stop.", stop_price: 376.25 })]);
    const r = within(bodyRow("BRC"));
    expect(r.getByText("Stop hit")).toHaveAttribute("title", "Last instruction: YELLOW UP INITIAL ENTRY - Use appropriate stop.");
    expect(r.getByText("since Oct 13, 09:30 ET")).toBeInTheDocument();
    expect(r.queryByText("YELLOW UP INITIAL ENTRY - Use appropriate stop.")).toBeNull();
    expect(r.getByText("$376.25")).toBeInTheDocument();
  });

  it("shows a neutral No entry status, with a note and a dash for the stop, when the row has no entry price", () => {
    draw([row({ ticker: "NOE", entry_kind: null, entry_at: null, entry_price: null, pl_pct: null, stop_price: null, stop_distance_pct: null, stop_basis: "none", instruction_text: "GRAY UP - NO ACTION. Stopped out twice." })]);
    const r = within(bodyRow("NOE"));
    const badge = r.getByText("No entry");
    expect(badge).toHaveAttribute("title", expect.stringContaining("earlier trade may exist"));
    expect(badge).not.toHaveClass("text-positive");
    expect(r.queryByText("Active")).toBeNull();
    expect(r.getAllByText("—")).toHaveLength(4); // Entry, P/L %, Stop, Stop dist.
    expect(r.getByText("GRAY UP - NO ACTION. Stopped out twice.")).toBeInTheDocument();
  });

  it("sorts by the latest arrow of any kind, so a down arrow or a gray up on a breached row rises above an older up arrow", () => {
    draw([
      row({ ticker: "UPP", latest_arrow_at: "2026-10-14T11:30:00", last_signal_at: "2026-10-14T11:30:00" }),
      // A Gray Up on a breached row: last_signal_at is frozen at the entry (Sep 16), the arrow is Oct 15 15:30.
      row({
        ticker: "WDC", status: "breached", breached_at: "2026-10-13T09:30:00", latest_arrow_color: "gray", latest_arrow_direction: "up",
        latest_arrow_at: "2026-10-15T15:30:00", last_signal_at: "2026-09-16T09:30:00",
      }),
      // A down arrow never moves last_signal_at.
      row({
        ticker: "DWN", latest_arrow_color: "yellow", latest_arrow_direction: "down", latest_arrow_at: "2026-10-15T11:30:00",
        last_signal_at: "2026-09-20T09:30:00",
      }),
    ]);
    const tickers = screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("link")[0].textContent);
    expect(tickers).toEqual(["WDC", "DWN", "UPP"]);
  });

  it("shows the latest arrow's ET candle time and age in bars, the last-updated stamp, and the last entry/refresh date in the tooltip", () => {
    draw([
      row({ ticker: "AAA", age_bars: 5, last_signal_age_bars: 99 }),
      row({ ticker: "BBB", latest_arrow_at: "2026-10-15T15:30:00", age_bars: 0, last_signal_at: "2026-09-16T09:30:00" }),
      row({ ticker: "CCC", age_bars: 1 }),
    ]);
    const a = within(bodyRow("AAA"));
    expect(a.getByText("Oct 15, 13:30")).toBeInTheDocument();
    expect(a.getByText("5 bars ago")).toBeInTheDocument();
    expect(a.queryByText("99 bars ago")).toBeNull(); // last_signal_age_bars is no longer read
    expect(a.getByText("Oct 16, 01:25")).toBeInTheDocument();
    expect(within(bodyRow("BBB")).getByText("this candle")).toBeInTheDocument();
    expect(within(bodyRow("CCC")).getByText("1 bar ago")).toBeInTheDocument();
    const cell = within(bodyRow("BBB")).getByText("Oct 15, 15:30").closest("td")!;
    expect(cell).toHaveAttribute("title", "Last entry/refresh: Sep 16, 09:30 ET");
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

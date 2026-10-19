import { describe, expect, it } from "vitest";

import type { WarrenWatchRowOut } from "@/lib/api/types";
import { entryTitle, fmtAgeAgo, fmtAsOf, fmtBarsAgo, fmtDay, fmtEtDate, fmtEtStamp, fmtSignedPct1, lastEntryRefreshTitle, sortByLatestArrow, stopAboveEntry, stopAboveEntryNote, stopAgeTitle, stopCellTitle, showTrailedPill } from "@/lib/technicalIdeas";

function row(over: Partial<WarrenWatchRowOut>): WarrenWatchRowOut {
  return {
    ticker: "AAA", profile: "any", latest_arrow_color: "yellow", latest_arrow_direction: "up", latest_arrow_at: "2026-10-15T13:30:00",
    instruction_type: 3, instruction_text: "YELLOW UP", entry_kind: "yellow", entry_at: "2026-10-15T13:30:00", last_price: 110, last_price_date: "2026-10-15", pl_pct: 0.1, stop_distance_pct: 0.1818, entry_price: 100, stop_price: 90, stop_basis: "10%", stop_moved_at: null, stop_moved_by: null, stop_trailed_since_arrow: false,
    status: "active", breached_at: null, last_signal_at: "2026-10-15T13:30:00", last_updated_at: "2026-10-16T01:25:00", age_bars: 5,
    last_signal_age_bars: 5, ...over,
  };
}

describe("technicalIdeas", () => {
  it("formats a naive ET stamp from its own digits, 24-hour", () => {
    expect(fmtEtStamp("2026-10-15T13:30:00")).toBe("Oct 15, 13:30");
    expect(fmtEtStamp("2026-01-05T09:30:00")).toBe("Jan 5, 09:30");
    expect(fmtEtStamp("2026-10-16T01:25:00.123456")).toBe("Oct 16, 01:25");
    expect(fmtAsOf("2026-10-15T15:30:00")).toBe("Oct 15, 15:30 ET");
  });

  it("leaves an unparseable stamp as it came", () => {
    expect(fmtEtStamp("soon")).toBe("soon");
    expect(fmtEtStamp("2026-13-01T10:00:00")).toBe("2026-13-01T10:00:00");
  });

  it("words an age in candles", () => {
    expect(fmtBarsAgo(null)).toBeNull();
    expect(fmtBarsAgo(0)).toBe("this candle");
    expect(fmtBarsAgo(1)).toBe("1 bar ago");
    expect(fmtBarsAgo(7)).toBe("7 bars ago");
  });

  it("sorts the newest latest-arrow candle first (any kind, not last_signal_at), ties by ticker, without mutating the input", () => {
    const rows = [
      row({ ticker: "OLD", latest_arrow_at: "2026-10-01T09:30:00", last_signal_at: "2026-10-14T09:30:00" }),
      row({ ticker: "ZZZ", latest_arrow_at: "2026-10-15T13:30:00" }),
      row({ ticker: "AAA", latest_arrow_at: "2026-10-15T13:30:00" }),
      row({ ticker: "NEW", latest_arrow_at: "2026-10-15T15:30:00", last_signal_at: "2026-09-16T09:30:00" }),
    ];
    expect(sortByLatestArrow(rows).map((r) => r.ticker)).toEqual(["NEW", "AAA", "ZZZ", "OLD"]);
    expect(rows.map((r) => r.ticker)).toEqual(["OLD", "ZZZ", "AAA", "NEW"]);
  });

  it("words the last entry/refresh tooltip from the last up arrow's candle", () => {
    expect(lastEntryRefreshTitle({ last_signal_at: "2026-09-16T09:30:00" })).toBe("Last entry/refresh: Sep 16, 09:30 ET");
  });

  it("flags a stop above the entry price only when both exist", () => {
    expect(stopAboveEntry({ stop_price: 110, entry_price: 100 })).toBe(true);
    expect(stopAboveEntry({ stop_price: 100, entry_price: 100 })).toBe(false);
    expect(stopAboveEntry({ stop_price: 90, entry_price: 100 })).toBe(false);
    expect(stopAboveEntry({ stop_price: null, entry_price: 100 })).toBe(false);
    expect(stopAboveEntry({ stop_price: 110, entry_price: null })).toBe(false);
  });

  it("explains an above-entry stop by its basis", () => {
    expect(stopAboveEntryNote({ entry_price: 142.42, stop_basis: "LP" })).toContain("the LP support");
    expect(stopAboveEntryNote({ entry_price: 142.42, stop_basis: "LP" })).toContain("$142.42");
    expect(stopAboveEntryNote({ entry_price: 100, stop_basis: "entry" })).toContain("from the entry price plus 1%");
  });
});

describe("entry and P/L formatting", () => {
  const now = Date.UTC(2026, 9, 16, 12);
  it("words an age by day, month and year", () => {
    expect(fmtAgeAgo("2026-10-16T09:30:00", now)).toBe("today");
    expect(fmtAgeAgo("2026-10-15T09:30:00", now)).toBe("1 day ago");
    expect(fmtAgeAgo("2026-10-09T09:30:00", now)).toBe("7 days ago");
    expect(fmtAgeAgo("2026-03-10T13:30:00", now)).toBe("7 months ago");
    expect(fmtAgeAgo("2024-03-10T13:30:00", now)).toBe("2 years ago");
    expect(fmtAgeAgo("garbage", now)).toBeNull();
  });
  it("formats a date and a signed one-decimal percent", () => {
    expect(fmtEtDate("2026-10-15")).toBe("Oct 15");
    expect(fmtDay("2027-01-18")).toBe("Jan 18, 2027");
    expect(fmtDay("2026-12-09")).toBe("Dec 9, 2026");
    expect(fmtDay("soon")).toBe("soon");
    expect(fmtSignedPct1(0.1234)).toBe("+12.3%");
    expect(fmtSignedPct1(-0.0456)).toBe("-4.6%");
    expect(fmtSignedPct1(0)).toBe("0.0%");
    expect(fmtSignedPct1(0.00004)).toBe("0.0%");
  });
  it("builds the entry tooltip, with or without an entry time", () => {
    expect(entryTitle({ entry_kind: "blue", entry_at: "2026-10-09T09:30:00" }, now)).toBe(
      "Blue entry · Oct 9, 09:30 ET · 7 days ago. The close of the entry candle, not an actual fill.",
    );
    expect(entryTitle({ entry_kind: "gray", entry_at: "2026-10-09T09:30:00" }, now)).toBe(
      "Gray entry · Oct 9, 09:30 ET · 7 days ago. The close of the entry candle, not an actual fill.",
    );
    expect(entryTitle({ entry_kind: null, entry_at: null }, now)).toBe("Entry. The close of the entry candle, not an actual fill.");
  });
  it("words the stop-age tooltip for each rule, and gives nothing without a stop age", () => {
    const at = (by: WarrenWatchRowOut["stop_moved_by"], when = "2026-10-09T11:30:00") => stopAgeTitle({ stop_moved_at: when, stop_moved_by: by }, now);
    expect(at("blue_down")).toBe("Set Oct 9, 11:30 ET by Blue Down (LP support) · 7 days ago");
    expect(at("yellow_down")).toBe("Set Oct 9, 11:30 ET by Yellow Down (LP support) · 7 days ago");
    expect(at("trail", "2026-10-16T09:30:00")).toBe("Trailed to LP support Oct 16, 09:30 ET · today");
    expect(at("yellow_up_entry", "2026-06-11T09:30:00")).toBe("Set at entry, Jun 11, 09:30 ET (10% of the candle low) · 4 months ago");
    expect(at("yellow_up_repeat", "2026-08-03T11:30:00")).toBe("Repeat yellow, Aug 3, 11:30 ET (lower of LP support and 10%) · 2 months ago");
    expect(at("gray_up_entry", "2026-09-23T13:30:00")).toBe("Set at entry, Sep 23, 13:30 ET (10% of the candle low, gray entry) · 23 days ago");
    expect(at("gray_down", "2026-09-23T13:30:00")).toBe("Gray Down: stop set to entry + 1%, Sep 23, 13:30 ET · 23 days ago");
    expect(stopAgeTitle({ stop_moved_at: null, stop_moved_by: null }, now)).toBeNull();
    expect(stopAgeTitle({ stop_moved_at: "2026-10-09T11:30:00", stop_moved_by: null }, now)).toBeNull();
  });
  it("never says '2nd LP' in a stop-age hover (the ATR gate can walk to the 3rd support)", () => {
    const rules: NonNullable<WarrenWatchRowOut["stop_moved_by"]>[] = [
      "yellow_up_entry", "gray_up_entry", "yellow_up_repeat", "blue_down", "yellow_down", "gray_down", "trail",
    ];
    for (const by of rules) expect(stopAgeTitle({ stop_moved_at: "2026-10-09T11:30:00", stop_moved_by: by }, now)).not.toMatch(/2nd/i);
  });
});

describe("trailed-since-arrow display", () => {
  const now = Date.UTC(2026, 9, 16, 12, 0, 0);
  const base = { stop_moved_at: "2026-10-16T09:30:00", stop_moved_by: "trail" as const, stop_trailed_since_arrow: true, status: "active" as const, stop_basis: "LP" as const };
  it("highlights only an active LP stop the API flagged", () => {
    expect(showTrailedPill(base)).toBe(true);
    expect(showTrailedPill({ ...base, stop_trailed_since_arrow: false })).toBe(false);
    expect(showTrailedPill({ ...base, status: "breached" })).toBe(false);
    expect(showTrailedPill({ ...base, stop_basis: "10%" })).toBe(false);
    expect(showTrailedPill({ ...base, stop_basis: "entry" })).toBe(false);
  });
  it("adds one tooltip line only when highlighted, and leaves the stop-age line as it is otherwise", () => {
    expect(stopCellTitle(base, now)).toBe(
      "Trailed to LP support Oct 16, 09:30 ET · today\nTrailed since last arrow: the stop was moved by the trailing LP (not by an arrow) at Oct 16, 09:30 ET, and stays highlighted until the next arrow.",
    );
    expect(stopCellTitle({ ...base, stop_trailed_since_arrow: false }, now)).toBe("Trailed to LP support Oct 16, 09:30 ET · today");
    expect(stopCellTitle({ ...base, stop_moved_at: null, stop_moved_by: null, stop_trailed_since_arrow: false }, now)).toBeNull();
  });
});

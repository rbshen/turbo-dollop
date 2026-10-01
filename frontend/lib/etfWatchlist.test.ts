import { describe, expect, it } from "vitest";

import type { WatchlistOut } from "@/lib/api/types";
import { monitoredListsHolding, onWatchlistLabel } from "@/lib/etfWatchlist";

function list(id: number, name: string, monitored: boolean, tickers: string[]): WatchlistOut {
  return {
    id,
    name,
    sort_field: "ticker",
    sort_direction: "asc",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    tickers: tickers.map((ticker) => ({ ticker, added_at: "2026-01-01T00:00:00Z" })),
    monitored,
  };
}

describe("monitoredListsHolding", () => {
  const lists = [
    list(1, "E10", true, ["QQQ"]),
    list(2, "E2", true, ["QQQ", "SMH"]),
    list(3, "ETF", true, ["QQQ"]),
    list(4, "Growth", false, ["QQQ"]),
    list(5, "E3", true, ["XLK"]),
  ];

  it("returns only monitored lists that hold the ticker, in natural name order", () => {
    expect(monitoredListsHolding(lists, "qqq")).toEqual(["E2", "E10", "ETF"]);
    expect(monitoredListsHolding(lists, "SMH")).toEqual(["E2"]);
  });

  it("is empty for a ticker only on an unmonitored list, a ticker on none, or while loading", () => {
    expect(monitoredListsHolding([list(4, "Growth", false, ["QQQ"])], "QQQ")).toEqual([]);
    expect(monitoredListsHolding(lists, "GLD")).toEqual([]);
    expect(monitoredListsHolding(undefined, "QQQ")).toEqual([]);
  });
});

describe("onWatchlistLabel", () => {
  it("names the first list, plus a count when there are several", () => {
    expect(onWatchlistLabel(["ETF"])).toBe("On watchlist ETF");
    expect(onWatchlistLabel(["E2", "E10", "ETF"])).toBe("On watchlist E2 +2");
  });
});

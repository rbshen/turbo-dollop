import { describe, expect, it } from "vitest";

import type { WatchlistExportListOut } from "@/lib/api/types";
import {
  buildMultiExport,
  buildTradingViewText,
  dedupeRows,
  exportResultParts,
  multiExportFilename,
} from "@/lib/watchlistExport";

const row = (ticker: string, exchange: string | null, sector: string | null = null) => ({ ticker, exchange, sector });
const list = (id: number, name: string, tickers: ReturnType<typeof row>[]): WatchlistExportListOut => ({ id, name, tickers });

describe("buildTradingViewText", () => {
  it("groups by sector in first-encounter order, keeping each row's order inside its sector", () => {
    const { content, skipped, symbolCount } = buildTradingViewText([
      row("AAPL", "NASDAQ", "Technology"),
      row("JPM", "NYSE", "Financial Services"),
      row("MSFT", "NASDAQ", "Technology"),
    ]);
    expect(content).toBe("###Technology,NASDAQ:AAPL,NASDAQ:MSFT,###Financial Services,NYSE:JPM");
    expect(skipped).toBe(0);
    expect(symbolCount).toBe(3);
  });

  it("puts a row with no sector under a literal Other section", () => {
    expect(buildTradingViewText([row("SPY", "AMEX"), row("QQQ", "NASDAQ")]).content).toBe("###Other,AMEX:SPY,NASDAQ:QQQ");
  });

  it("writes the FMP exchange string as is, with no mapping and no share-class conversion", () => {
    expect(buildTradingViewText([row("BRK-B", "NYSE", "Financial Services"), row("IGV", "CBOE")]).content).toBe(
      "###Financial Services,NYSE:BRK-B,###Other,CBOE:IGV",
    );
  });

  it("skips a row with no exchange, counts it, and drops a section left empty", () => {
    const { content, skipped, symbolCount } = buildTradingViewText([row("NEWCO", null, "Energy"), row("AAPL", "NASDAQ", "Technology")]);
    expect(content).toBe("###Technology,NASDAQ:AAPL");
    expect(skipped).toBe(1);
    expect(symbolCount).toBe(1);
  });

  it("returns an empty file for no exportable rows", () => {
    expect(buildTradingViewText([])).toEqual({ content: "", skipped: 0, symbolCount: 0 });
    expect(buildTradingViewText([row("NEWCO", null)])).toEqual({ content: "", skipped: 1, symbolCount: 0 });
  });
});

describe("dedupeRows", () => {
  it("keeps the first occurrence across lists and counts the rest", () => {
    const result = dedupeRows([
      list(1, "A", [row("AAPL", "NASDAQ", "Technology"), row("MSFT", "NASDAQ", "Technology")]),
      list(2, "B", [row("MSFT", "OTHER", "Other sector"), row("NVDA", "NASDAQ", "Technology")]),
    ]);
    expect(result.rows.map((r) => r.ticker)).toEqual(["AAPL", "MSFT", "NVDA"]);
    expect(result.rows[1]).toEqual(row("MSFT", "NASDAQ", "Technology"));
    expect(result.duplicates).toBe(1);
    expect(result.emptyLists).toBe(0);
  });

  it("counts empty lists", () => {
    expect(dedupeRows([list(1, "A", []), list(2, "B", [row("AAPL", "NASDAQ")]), list(3, "C", [])]).emptyLists).toBe(2);
  });
});

describe("buildMultiExport", () => {
  const lists = [
    list(1, "Growth, big", [row("AAPL", "NASDAQ", "Technology"), row("JPM", "NYSE", "Financial Services")]),
    list(2, "### Value", [row("AAPL", "NASDAQ", "Technology"), row("XOM", "NYSE", "Energy"), row("NEWCO", null, "Energy")]),
    list(3, "Empty", []),
  ];

  it("TradingView: merged sectors, no list names, de-duplicated, with the skipped count", () => {
    const result = buildMultiExport(lists, "tradingview");
    expect(result.content).toBe("###Technology,NASDAQ:AAPL,###Financial Services,NYSE:JPM,###Energy,NYSE:XOM");
    expect(result.content).not.toContain("Growth");
    expect(result).toMatchObject({ skipped: 1, duplicates: 1, symbolCount: 3, emptyLists: 1 });
  });

  it("thinkorswim: bare symbols one per line, no header, de-duplicated in first-seen order", () => {
    const result = buildMultiExport(lists, "thinkorswim");
    expect(result.content).toBe("AAPL\nJPM\nXOM\nNEWCO\n");
    expect(result).toMatchObject({ skipped: 0, duplicates: 1, symbolCount: 4, emptyLists: 1 });
  });

  it("writes an empty file when every selected list is empty", () => {
    expect(buildMultiExport([list(1, "A", [])], "thinkorswim")).toEqual({
      content: "",
      skipped: 0,
      duplicates: 0,
      symbolCount: 0,
      emptyLists: 1,
    });
  });
});

describe("multiExportFilename", () => {
  const now = new Date(2026, 9, 9, 23, 30);
  it("names the list count, the local date and the format", () => {
    expect(multiExportFilename(3, "tradingview", now)).toBe("fathom-watchlists_3-lists_2026-10-09_tradingview.txt");
    expect(multiExportFilename(12, "thinkorswim", now)).toBe("fathom-watchlists_12-lists_2026-10-09_thinkorswim.csv");
  });
});

describe("exportResultParts", () => {
  it("leaves out zero counts and pluralises", () => {
    const parts = exportResultParts({ content: "x", skipped: 2, duplicates: 5, symbolCount: 42, emptyLists: 1 }, 3);
    expect(parts.summary).toBe("Exported 42 symbols from 3 lists");
    expect(parts.notes).toEqual(["5 duplicates removed", "1 empty list skipped"]);
    expect(parts.skippedNote).toBe("2 skipped (no cached exchange)");
    const plain = exportResultParts({ content: "x", skipped: 0, duplicates: 0, symbolCount: 1, emptyLists: 0 }, 1);
    expect(plain).toEqual({ summary: "Exported 1 symbol from 1 list", notes: [], skippedNote: null });
  });

  it("says so when nothing was written", () => {
    expect(exportResultParts({ content: "", skipped: 0, duplicates: 0, symbolCount: 0, emptyLists: 2 }, 2).summary).toBe("Nothing to export");
  });
});

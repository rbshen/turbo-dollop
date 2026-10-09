import type { WatchlistExportListOut, WatchlistExportTickerOut } from "@/lib/api/types";

// The Watchlists page exports (docs/specs/watchlist-export.md). Pure functions: the page and the multi-list panel fetch
// and download, this file only builds the text. TradingView's "Upload list" reads one comma-separated line in which a
// `###Name` item starts a section; thinkorswim's import takes bare symbols, one per line.

export type ExportFormat = "tradingview" | "thinkorswim";

export const EXPORT_FORMAT_OPTIONS: { value: ExportFormat; label: string }[] = [
  { value: "tradingview", label: "TradingView (.txt)" },
  { value: "thinkorswim", label: "thinkorswim (.csv)" },
];

/** What a TradingView section needs from a row: its symbol, FMP's exchange string and sector (null falls in "Other"). */
export type ExportRow = WatchlistExportTickerOut;

export interface TradingViewText {
  content: string;
  /** Rows left out because no exchange is cached (a bare symbol is not a valid EXCHANGE:SYMBOL pair). */
  skipped: number;
  symbolCount: number;
}

/** The TradingView file for `rows`, grouped by sector (a row with no sector goes in a literal "Other" section, so no
 * ticker loses its `###` marker). One pass in the order given, so each row keeps its relative order inside its sector and
 * sections appear in first-encounter order. The exchange is FMP's own string, written as is. A section left with nothing
 * exportable is dropped, so a `###` marker never stands with zero tickers under it. Shared by the single-list export
 * (the page) and the multi-list export. */
export function buildTradingViewText(rows: ExportRow[]): TradingViewText {
  const bySector = new Map<string, ExportRow[]>();
  for (const row of rows) {
    const key = row.sector ?? "Other";
    const bucket = bySector.get(key);
    if (bucket) {
      bucket.push(row);
    } else {
      bySector.set(key, [row]);
    }
  }

  const parts: string[] = [];
  let symbolCount = 0;
  for (const [sector, sectorRows] of bySector) {
    const pairs = sectorRows.filter((r) => r.exchange != null).map((r) => `${r.exchange}:${r.ticker}`);
    if (pairs.length === 0) continue;
    parts.push(`###${sector}`, ...pairs);
    symbolCount += pairs.length;
  }
  return { content: parts.join(","), skipped: rows.length - symbolCount, symbolCount };
}

export interface DedupedRows {
  rows: ExportRow[];
  /** Occurrences dropped because the same symbol was already taken from an earlier list. */
  duplicates: number;
  /** Lists with no tickers at all (skipped silently from the file, named in the result line). */
  emptyLists: number;
}

/** All lists flattened in the order given, each symbol kept once: the first occurrence wins (its exchange and sector
 * too), later ones count as duplicates. */
export function dedupeRows(lists: WatchlistExportListOut[]): DedupedRows {
  const seen = new Set<string>();
  const rows: ExportRow[] = [];
  let duplicates = 0;
  let emptyLists = 0;
  for (const list of lists) {
    if (list.tickers.length === 0) emptyLists += 1;
    for (const row of list.tickers) {
      if (seen.has(row.ticker)) {
        duplicates += 1;
        continue;
      }
      seen.add(row.ticker);
      rows.push(row);
    }
  }
  return { rows, duplicates, emptyLists };
}

export interface MultiExport {
  content: string;
  /** TradingView only: unique symbols with no cached exchange, left out of the file. Always 0 for thinkorswim. */
  skipped: number;
  duplicates: number;
  /** Symbols written to the file. */
  symbolCount: number;
  emptyLists: number;
}

/** One file for several lists in ONE format. TradingView: grouped by sector across the merged lists (list names do not
 * appear). thinkorswim: bare symbols, one per line, no header. Both de-duplicate across lists, first seen first. */
export function buildMultiExport(lists: WatchlistExportListOut[], format: ExportFormat): MultiExport {
  const { rows, duplicates, emptyLists } = dedupeRows(lists);
  if (format === "tradingview") {
    const { content, skipped, symbolCount } = buildTradingViewText(rows);
    return { content, skipped, duplicates, symbolCount, emptyLists };
  }
  const content = rows.map((r) => `${r.ticker}\n`).join("");
  return { content, skipped: 0, duplicates, symbolCount: rows.length, emptyLists };
}

/** `fathom-watchlists_3-lists_2026-10-09_tradingview.txt` (local date). */
export function multiExportFilename(listCount: number, format: ExportFormat, now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const suffix = format === "tradingview" ? "tradingview.txt" : "thinkorswim.csv";
  return `fathom-watchlists_${listCount}-lists_${date}_${suffix}`;
}

/** The text of one export-result line: "Exported 42 symbols from 3 lists · 5 duplicates removed · ...". Zero counts are
 * left out; nothing written reads "Nothing to export". */
export function exportResultParts(result: MultiExport, listCount: number): { summary: string; notes: string[]; skippedNote: string | null } {
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const summary =
    result.symbolCount === 0
      ? "Nothing to export"
      : `Exported ${plural(result.symbolCount, "symbol", "symbols")} from ${plural(listCount, "list", "lists")}`;
  const notes: string[] = [];
  if (result.duplicates > 0) notes.push(`${plural(result.duplicates, "duplicate", "duplicates")} removed`);
  if (result.emptyLists > 0) notes.push(`${plural(result.emptyLists, "empty list", "empty lists")} skipped`);
  const skippedNote = result.skipped > 0 ? `${result.skipped} skipped (no cached exchange)` : null;
  return { summary, notes, skippedNote };
}

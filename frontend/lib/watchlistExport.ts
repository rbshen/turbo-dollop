import type { WatchlistExportListOut, WatchlistExportTickerOut } from "@/lib/api/types";

// The Watchlists page exports (docs/specs/watchlist-export.md). Pure functions: the page and the multi-list panel fetch
// and download, this file only builds the text. TradingView's "Upload list" reads one comma-separated line in which a
// `###Name` item starts a section; thinkorswim's import takes bare symbols, one per line.

export type ExportFormat = "tradingview" | "thinkorswim";

export const EXPORT_FORMAT_OPTIONS: { value: ExportFormat; label: string }[] = [
  { value: "tradingview", label: "TradingView (.txt)" },
  { value: "thinkorswim", label: "thinkorswim (.csv)" },
];

// Export safety (docs/specs/watchlist-export.md, "Export safety"; backend twin: data/export_safety.py). A stored symbol is
// already validated, so these are the second layer, applied where the files are written.

// Whitespace and control characters (CR/LF/tab and the Unicode line separators), commas and double quotes.
const CSV_UNSAFE = /[\s\u0000-\u001f\u007f,"]/g;
// A TradingView item (symbol, exchange or sector): control and line-separator characters become a space, and "," (item
// separator), "#" (starts a `###` section) and ":" (EXCHANGE:SYMBOL separator) are dropped.
const TV_CONTROL = /[\u0000-\u001f\u007f\u0085\u2028\u2029]/g;
const TV_DROPPED = /[,"#:]/g;
const FORMULA_LEADERS = ["=", "+", "-", "@"];

/** One thinkorswim .csv line's symbol: CR/LF, whitespace, commas and quotes removed, then a leading single quote when it
 * starts with = + - @ (a spreadsheet formula). Only the first character is checked, so BRK-B and ^GSPC are unchanged.
 * "" when nothing is left (the caller leaves it out). */
export function neutraliseCsvSymbol(raw: string): string {
  const cleaned = raw.replace(CSV_UNSAFE, "");
  return FORMULA_LEADERS.some((c) => cleaned.startsWith(c)) ? `'${cleaned}` : cleaned;
}

/** thinkorswim file text: bare symbols, one per line, no header, each neutralised, empty ones dropped. */
export function buildThinkorswimText(symbols: string[]): string {
  return symbols
    .map(neutraliseCsvSymbol)
    .filter((s) => s !== "")
    .map((s) => `${s}\n`)
    .join("");
}

/** An exchange or sector as one TradingView list item: no comma, newline, `#` or `:` can get through, so a value cannot
 * add an item, start a `###` section or fake an EXCHANGE:SYMBOL pair. Ordinary inner spaces ("Consumer Cyclical") stay. */
export function cleanTradingViewItem(raw: string): string {
  return raw.replace(TV_CONTROL, " ").replace(TV_DROPPED, "").replace(/\s+/g, " ").trim();
}

/** A ticker as one TradingView list item: the same cleaning, and no space at all. */
export function cleanTradingViewSymbol(raw: string): string {
  return cleanTradingViewItem(raw).replace(/\s/g, "");
}

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
    const key = (row.sector != null ? cleanTradingViewItem(row.sector) : "") || "Other";
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
    const pairs = sectorRows.flatMap((r) => {
      const exchange = r.exchange != null ? cleanTradingViewItem(r.exchange) : "";
      const symbol = cleanTradingViewSymbol(r.ticker);
      return exchange && symbol ? [`${exchange}:${symbol}`] : [];
    });
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
  const content = buildThinkorswimText(rows.map((r) => r.ticker));
  return { content, skipped: 0, duplicates, symbolCount: content.split("\n").length - 1, emptyLists };
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

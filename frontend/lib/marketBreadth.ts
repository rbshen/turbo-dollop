import type { MarketBreadthPointOut } from "@/lib/api/types";

/** Index of the first LIVE (point-in-time) session, or -1 when every session is backfilled. Rows are
 * oldest first and a backfill only ever covers the past, so this is the boundary between the two. */
export function firstLiveIndex(series: MarketBreadthPointOut[]): number {
  return series.findIndex((p) => !p.is_backfilled);
}

/** Index of the first session inside the trailing year ending at the newest session (oldest-first rows).
 * 0 when the whole history is a year or less -- a short-history universe just shows everything it has,
 * never a padded window. */
export function defaultWindowStart(series: MarketBreadthPointOut[]): number {
  if (series.length === 0) return 0;
  const last = new Date(`${series[series.length - 1].as_of_date}T00:00:00Z`);
  if (Number.isNaN(last.getTime())) return 0;
  const cutoff = new Date(last);
  cutoff.setUTCFullYear(cutoff.getUTCFullYear() - 1);
  const iso = cutoff.toISOString().slice(0, 10);
  const idx = series.findIndex((p) => p.as_of_date >= iso);
  return idx < 0 ? 0 : idx;
}

/** The 11 SPDR sector ETFs, in the same order/display names as the Sector Heatmap
 * (backend/data/sector_heatmap_data.py::SECTOR_ETFS) -- kept in sync by hand, since the
 * frontend has no reason to fetch the heatmap just to read this fixed, rarely-changing list. */
export const SECTOR_ETFS: { ticker: string; name: string }[] = [
  { ticker: "XLK", name: "Technology" },
  { ticker: "XLF", name: "Financials" },
  { ticker: "XLV", name: "Health Care" },
  { ticker: "XLE", name: "Energy" },
  { ticker: "XLI", name: "Industrials" },
  { ticker: "XLY", name: "Consumer Discretionary" },
  { ticker: "XLP", name: "Consumer Staples" },
  { ticker: "XLU", name: "Utilities" },
  { ticker: "XLB", name: "Materials" },
  { ticker: "XLRE", name: "Real Estate" },
  { ticker: "XLC", name: "Communication Services" },
];

/** "sector:XLK" -- matches backend/data/market_breadth_data.py::sector_universe exactly. */
export function sectorUniverse(ticker: string): string {
  return `sector:${ticker}`;
}

export function isKnownSectorTicker(ticker: string): boolean {
  return SECTOR_ETFS.some((s) => s.ticker === ticker);
}

/** The sector's display name, or undefined for an unrecognized ticker. */
export function sectorDisplayName(ticker: string): string | undefined {
  return SECTOR_ETFS.find((s) => s.ticker === ticker)?.name;
}

/** "+78" / "-24" / "0" -- a signed count (net new highs minus lows). */
export function fmtSignedCount(n: number): string {
  if (n === 0) return "0";
  return `${n > 0 ? "+" : "-"}${Math.abs(n)}`;
}

/** "27.8%" or "—" when the metric had no eligible constituents. */
export function fmtBreadthPct(n: number | null): string {
  return n == null ? "—" : `${n.toFixed(1)}%`;
}

/** "2026-09-18" -> "Sep '26", for a time-axis tick. Parsed/formatted in UTC so the calendar date can never
 * shift with the viewer's timezone. */
export function fmtAxisMonth(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  const month = d.toLocaleDateString("en-US", { timeZone: "UTC", month: "short" });
  return `${month} '${String(d.getUTCFullYear()).slice(2)}`;
}

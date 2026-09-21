import type { MarketBreadthPointOut } from "@/lib/api/types";

/** Index of the first LIVE (point-in-time) session, or -1 when every session is backfilled. Rows are
 * oldest first and a backfill only ever covers the past, so this is the boundary between the two. */
export function firstLiveIndex(series: MarketBreadthPointOut[]): number {
  return series.findIndex((p) => !p.is_backfilled);
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

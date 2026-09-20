import { currencyPrefix } from "@/lib/format";
import type { ChartDividendMarkerOut, ChartEarningsMarkerOut } from "@/lib/api/types";

// Pure marker builders + hover-detail text for the Chart tab's earnings/dividend markers. Kept out of
// TickerChart.tsx (which imports lightweight-charts and its canvas dependency) so both are unit-testable
// in plain vitest, mirroring how lib/weinsteinStage.ts sits beside its card.
//
// Each marker carries an `id` so a hover can be resolved back to its detail: lightweight-charts 5.2.0
// reports `hoveredInfo.objectKind === "series-marker"` with `objectId === marker.id` on crosshair moves.
// The id encodes kind + bar time (one marker per kind per bar, enforced server-side), so it is unique
// across both marker plugins sharing the candle series.

export const EARNINGS_MARKER_ID_PREFIX = "earnings:";
export const DIVIDEND_MARKER_ID_PREFIX = "dividend:";

export function buildEarningsMarkers(markers: ChartEarningsMarkerOut[], color: string) {
  return markers.map((m) => ({
    id: `${EARNINGS_MARKER_ID_PREFIX}${m.time}`,
    time: m.time,
    position: "aboveBar" as const,
    color,
    shape: "circle" as const,
    text: "E",
    size: 1,
  }));
}

export function buildDividendMarkers(markers: ChartDividendMarkerOut[], color: string) {
  return markers.map((m) => ({
    id: `${DIVIDEND_MARKER_ID_PREFIX}${m.time}`,
    time: m.time,
    position: "belowBar" as const,
    color,
    shape: "square" as const,
    text: "D",
    size: 1,
  }));
}

export interface EventTooltip {
  title: string;
  lines: string[];
}

/** "2026-07-30" -> "Jul 30, 2026". Parsed/formatted in UTC so the calendar date can never shift with the
 * viewer's timezone (these are exchange-calendar dates, not instants). */
export function fmtEventDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}

/** 2-4 decimals, trailing zeros trimmed back to 2: 0.27 -> "0.27", 0.1925 -> "0.1925", 1 -> "1.00". Dividends
 * are split-adjusted and can carry sub-cent precision, which fmtMoney's fixed 2 decimals would round away. */
function fmtDividendAmount(n: number): string {
  return n.toFixed(4).replace(/0{1,2}$/, "");
}

function fmtEps(n: number): string {
  return n.toFixed(2);
}

/** Surprise vs the estimate as a signed percent, or null when it isn't meaningful (no estimate, or an
 * estimate of exactly 0, where a percentage is undefined). */
export function epsSurprisePct(actual: number, estimate: number | null): number | null {
  if (estimate === null || estimate === 0) return null;
  return ((actual - estimate) / Math.abs(estimate)) * 100;
}

/** Resolves a hovered marker id to its tooltip text, or null for any id that isn't one of ours (BB+RSI and
 * Warren markers carry no id at all, so they never match). */
export function describeEventMarker(
  id: unknown,
  earnings: ChartEarningsMarkerOut[],
  dividends: ChartDividendMarkerOut[],
  currency: string = "USD"
): EventTooltip | null {
  if (typeof id !== "string") return null;

  if (id.startsWith(EARNINGS_MARKER_ID_PREFIX)) {
    const time = id.slice(EARNINGS_MARKER_ID_PREFIX.length);
    const m = earnings.find((e) => e.time === time);
    if (!m) return null;
    const lines: string[] = [];
    if (m.eps_actual !== null) lines.push(`EPS ${fmtEps(m.eps_actual)}`);
    if (m.eps_estimated !== null) lines.push(`Estimate ${fmtEps(m.eps_estimated)}`);
    if (m.eps_actual !== null) {
      const s = epsSurprisePct(m.eps_actual, m.eps_estimated);
      if (s !== null) lines.push(`Surprise ${s >= 0 ? "+" : "-"}${Math.abs(s).toFixed(1)}%`);
    }
    if (lines.length === 0) lines.push("EPS not reported");
    return { title: `Earnings · ${fmtEventDate(m.event_date)}`, lines };
  }

  if (id.startsWith(DIVIDEND_MARKER_ID_PREFIX)) {
    const time = id.slice(DIVIDEND_MARKER_ID_PREFIX.length);
    const m = dividends.find((d) => d.time === time);
    if (!m) return null;
    return {
      title: `Ex-dividend · ${fmtEventDate(m.event_date)}`,
      lines: [`${currencyPrefix(currency)}${fmtDividendAmount(m.amount)} per share`],
    };
  }

  return null;
}

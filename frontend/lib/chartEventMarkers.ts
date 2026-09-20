import { currencyPrefix } from "@/lib/format";
import type { ChartDividendMarkerOut, ChartEarningsMarkerOut } from "@/lib/api/types";

// Pure marker builders + hover-detail text for the Chart tab's earnings/dividend markers. Kept out of
// TickerChart.tsx (which imports lightweight-charts and its canvas dependency) so both are unit-testable
// in plain vitest, mirroring how lib/weinsteinStage.ts sits beside its card.
//
// Each marker carries an `id` so a hover can be resolved back to its detail: lightweight-charts 5.2.0
// reports `hoveredInfo.objectKind === "series-marker"` with `objectId === marker.id` on crosshair moves.
// The id encodes kind + bar time (one marker per kind per bar, enforced server-side), so it is unique
// across both marker plugins sharing the event-row series.
//
// FIXED-ROW PLACEMENT. Every marker position in lightweight-charts 5.2.0 (aboveBar/belowBar/inBar and
// atPriceTop/atPriceBottom/atPriceMiddle) is resolved through `series.priceToCoordinate`, so no marker can be
// pinned to the pane itself. The markers here therefore attach to a hidden helper series on its OWN overlay
// price scale (EVENT_ROW_SCALE_ID), whose range is pinned to 0..1 with zero scale margins -- which makes price
// `p` map linearly onto the pane, independent of the candles' price range: y_from_pane_bottom = (H - 1) * p
// (PriceScale._private__logicalToCoordinate). A marker's `price` is thus just a pixel offset from the pane
// floor divided by (H - 1). `atPriceTop` puts a shape's BOTTOM edge exactly on that coordinate (and its letter
// above it), so the icons sit on a floor that doesn't move with zoom/shape size.

export const EARNINGS_MARKER_ID_PREFIX = "earnings:";
export const DIVIDEND_MARKER_ID_PREFIX = "dividend:";

/** priceScaleId of the helper series the event markers attach to (any id other than left/right is an overlay). */
export const EVENT_ROW_SCALE_ID = "event-row";
/** Fixed autoscale range for that overlay scale; with zero scale margins it spans the whole pane height. */
export const EVENT_ROW_PRICE_RANGE = { minValue: 0, maxValue: 1 } as const;
/** Distance from the pane's bottom edge to the bottom edge of an event icon. */
export const EVENT_ROW_FLOOR_PX = 6;
/** How far a dividend is lifted above an earnings marker on the SAME bar, so the two never sit on top of each
 * other. Clears the largest icon (24px circle at max bar spacing) plus its letter (~16px). */
export const EVENT_ROW_STACK_PX = 44;

/** Converts a pixel offset above the pane floor into a price on the event-row scale (see the header). */
export function eventRowPrice(offsetPx: number, paneHeightPx: number): number {
  return offsetPx / (paneHeightPx - 1);
}

export function buildEarningsMarkers(markers: ChartEarningsMarkerOut[], color: string, paneHeightPx: number) {
  const price = eventRowPrice(EVENT_ROW_FLOOR_PX, paneHeightPx);
  return markers.map((m) => ({
    id: `${EARNINGS_MARKER_ID_PREFIX}${m.time}`,
    time: m.time,
    position: "atPriceTop" as const,
    price,
    color,
    shape: "circle" as const,
    text: "E",
    size: 1,
  }));
}

/** `earnings` is consulted only to detect a same-bar collision (the weekly view makes one plausible): such a
 * dividend is stacked one slot above the earnings marker. Deliberately independent of the Earnings toggle, so
 * hiding earnings never makes a dividend jump. */
export function buildDividendMarkers(
  markers: ChartDividendMarkerOut[],
  color: string,
  paneHeightPx: number,
  earnings: ChartEarningsMarkerOut[] = []
) {
  const earningsTimes = new Set(earnings.map((e) => e.time));
  const floor = eventRowPrice(EVENT_ROW_FLOOR_PX, paneHeightPx);
  const stacked = eventRowPrice(EVENT_ROW_FLOOR_PX + EVENT_ROW_STACK_PX, paneHeightPx);
  return markers.map((m) => ({
    id: `${DIVIDEND_MARKER_ID_PREFIX}${m.time}`,
    time: m.time,
    position: "atPriceTop" as const,
    price: earningsTimes.has(m.time) ? stacked : floor,
    color,
    shape: "square" as const,
    text: "D",
    size: 1,
  }));
}

/** Where the hover tooltip goes, relative to the chart container. Always ABOVE the cursor: the markers live on
 * the price pane's floor, so a below-the-cursor box would spill over the RSI/Stochastic panes (or out of the
 * chart entirely when they're absent). Flips to the cursor's left near the right edge so it never clips. */
export const TOOLTIP_OFFSET_PX = 12;
export const TOOLTIP_FLIP_MARGIN_PX = 200;

export interface TooltipPlacement {
  left: number;
  top: number;
  transform: string;
}

export function eventTooltipPlacement(x: number, y: number, containerWidthPx: number): TooltipPlacement {
  const flipLeft = x > containerWidthPx - TOOLTIP_FLIP_MARGIN_PX;
  return {
    left: flipLeft ? x - TOOLTIP_OFFSET_PX : x + TOOLTIP_OFFSET_PX,
    top: y - TOOLTIP_OFFSET_PX,
    transform: `translate(${flipLeft ? "-100%" : "0"}, -100%)`,
  };
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

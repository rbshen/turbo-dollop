import { currencyPrefix } from "@/lib/format";
import type { ChartDividendMarkerOut, ChartEarningsMarkerOut } from "@/lib/api/types";

// Pure marker builders + hover-detail text for the Chart tab's earnings/dividend markers. Kept out of
// TickerChart.tsx (which imports lightweight-charts and its canvas dependency) so both are unit-testable
// in plain vitest, mirroring how lib/weinsteinStage.ts sits beside its card.
//
// Each label carries an `id` so a hover can be resolved back to its detail: the custom primitive's hitTest
// (components/chart/EventLabelsPrimitive.ts) reports it as `externalId`, which lightweight-charts 5.2.0 surfaces
// as `hoveredInfo.objectKind === "primitive"` with `objectId === label.id` on crosshair moves. The id encodes
// kind + bar time (one label per kind per bar, enforced server-side), so it is unique across both kinds.
//
// FIXED-ROW PLACEMENT, LETTERS ONLY. lightweight-charts 5.2.0's built-in series markers can't do this: every
// marker position resolves through a price coordinate (so none is pinned to the pane), every marker has a shape
// (there is no "none"), and its text is fixed at the chart-wide axis font size. So the labels are drawn by a
// small custom series primitive instead, in the pane's own pixel space -- which gives an exact floor (the
// pane's real height, not a price-derived guess) and a font size of our own choosing.

export const EARNINGS_MARKER_ID_PREFIX = "earnings:";
export const DIVIDEND_MARKER_ID_PREFIX = "dividend:";

/** Letter size. The signal-arrow labels and axes use the chart-wide 12px; these are deliberately a bit bigger. */
export const EVENT_LABEL_FONT_PX = 13;
/** Distance from the pane's bottom edge to the bottom of a letter's box. */
export const EVENT_LABEL_FLOOR_PX = 6;
/** How far a dividend is lifted above an earnings label on the SAME bar (one letter height plus a gap). */
export const EVENT_LABEL_STACK_PX = 18;
/** Half-extents of a label's hover box, around its centre. */
export const EVENT_LABEL_HIT_HALF_WIDTH_PX = 8;
export const EVENT_LABEL_HIT_HALF_HEIGHT_PX = EVENT_LABEL_FONT_PX / 2 + 2;

export interface EventLabel {
  id: string;
  /** Bar time ("YYYY-MM-DD") the label is anchored to. */
  time: string;
  text: "E" | "D";
  color: string;
  /** 0 = on the row; 1 = lifted one slot (a dividend sharing a bar with an earnings report). */
  stackSlot: 0 | 1;
}

export function buildEarningsLabels(markers: ChartEarningsMarkerOut[], color: string): EventLabel[] {
  return markers.map((m) => ({
    id: `${EARNINGS_MARKER_ID_PREFIX}${m.time}`,
    time: m.time,
    text: "E",
    color,
    stackSlot: 0,
  }));
}

/** `earnings` is consulted only to detect a same-bar collision (the weekly view makes one plausible): such a
 * dividend is stacked one slot above the earnings label. Deliberately independent of the Earnings toggle, so
 * hiding earnings never makes a dividend jump. */
export function buildDividendLabels(
  markers: ChartDividendMarkerOut[],
  color: string,
  earnings: ChartEarningsMarkerOut[] = []
): EventLabel[] {
  const earningsTimes = new Set(earnings.map((e) => e.time));
  return markers.map((m) => ({
    id: `${DIVIDEND_MARKER_ID_PREFIX}${m.time}`,
    time: m.time,
    text: "D",
    color,
    stackSlot: earningsTimes.has(m.time) ? 1 : 0,
  }));
}

/** Vertical centre (px from the pane's TOP) of a label, given the pane's real height. */
export function eventLabelCenterY(paneHeightPx: number, stackSlot: 0 | 1): number {
  return paneHeightPx - EVENT_LABEL_FLOOR_PX - EVENT_LABEL_FONT_PX / 2 - stackSlot * EVENT_LABEL_STACK_PX;
}

/** The id of the placed label under (x, y), or null. Ties (overlapping boxes) go to the nearest centre. */
export function hitTestEventLabels(placed: { id: string; x: number; y: number }[], x: number, y: number): string | null {
  let best: { id: string; d: number } | null = null;
  for (const p of placed) {
    if (Math.abs(x - p.x) > EVENT_LABEL_HIT_HALF_WIDTH_PX || Math.abs(y - p.y) > EVENT_LABEL_HIT_HALF_HEIGHT_PX) continue;
    const d = Math.hypot(x - p.x, y - p.y);
    if (best === null || d < best.d) best = { id: p.id, d };
  }
  return best?.id ?? null;
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

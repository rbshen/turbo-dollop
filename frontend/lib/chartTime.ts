// Time handling for the Chart tab's 2H·90D range. The backend sends naive-ET wall-clock ISO strings
// ("2026-09-29T11:30:00", the candle's window START). lightweight-charts takes UTCTimestamp seconds and renders
// them as UTC, so the ET wall-clock is encoded AS IF it were UTC ("fake UTC"): axis and crosshair labels then read
// as ET, and nothing here ever consults a time zone, so DST switch dates cannot shift a candle. Daily and weekly
// ranges keep their plain "YYYY-MM-DD" business-day strings and never touch this module.

import type { UTCTimestamp } from "lightweight-charts";

const NAIVE_ET_ISO = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/;

export function etIsoToFakeUtc(iso: string): UTCTimestamp {
  const m = NAIVE_ET_ISO.exec(iso);
  if (!m) throw new Error(`Not a naive-ET ISO time: ${iso}`);
  return (Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) / 1000) as UTCTimestamp;
}

export function fakeUtcToEtIso(t: number): string {
  return new Date(t * 1000).toISOString().slice(0, 19);
}

// Each 2h candle's window end (the session's regular windows, anchored at the 09:30 ET open). The last candle is the
// short 15:30-16:00 one. (An early-close day's final candle really ends at 13:00; the wire carries no end time.)
const WINDOW_END: Record<string, string> = { "09:30": "11:30", "11:30": "13:30", "13:30": "15:30", "15:30": "16:00" };

export function candleWindow(iso: string): { start: string; end: string } {
  const start = iso.slice(11, 16);
  return { start, end: WINDOW_END[start] ?? start };
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The OHLC legend's time: the candle's date and its full window, e.g. "Tue Sep 29 · 11:30–13:30 ET". */
export function formatCandleLegendTime(iso: string): string {
  const m = NAIVE_ET_ISO.exec(iso);
  if (!m) return iso;
  const day = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  const { start, end } = candleWindow(iso);
  return `${WEEKDAYS[day.getUTCDay()]} ${MONTHS[+m[2] - 1]} ${+m[3]} · ${start}–${end} ET`;
}

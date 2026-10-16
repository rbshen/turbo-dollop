import type { WarrenWatchRowOut } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";

// Helpers for the Technical Ideas page. Every timestamp from the API is a naive America/New_York ISO string ("2026-10-15T13:30:00"):
// they are formatted from their own digits, never through Date, so the browser's time zone cannot shift them. Candle times are 2h
// window STARTS (the Chart tab's convention), the page's single time convention.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const NAIVE_ISO = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/;

/** "Oct 15, 13:30" from a naive ET ISO string; the input unchanged when it does not parse. */
export function fmtEtStamp(iso: string): string {
  const m = NAIVE_ISO.exec(iso);
  if (!m) return iso;
  const month = MONTHS[Number(m[2]) - 1];
  if (!month) return iso;
  return `${month} ${Number(m[3])}, ${m[4]}:${m[5]}`;
}

/** "Oct 15, 15:30 ET" -- the table's as-of stamp. */
export function fmtAsOf(iso: string): string {
  return `${fmtEtStamp(iso)} ET`;
}

/** "this candle" / "1 bar ago" / "5 bars ago" for an age in 2h candles; null when the age is unknown. */
export function fmtBarsAgo(age: number | null): string | null {
  if (age == null) return null;
  if (age === 0) return "this candle";
  return `${age} ${age === 1 ? "bar" : "bars"} ago`;
}

/** Newest latest-arrow candle first (the arrow the Signal pill shows, of ANY kind: up, down, any colour); ties by ticker. ISO strings of
 * one format sort as text. */
export function sortByLatestArrow(rows: readonly WarrenWatchRowOut[]): WarrenWatchRowOut[] {
  return [...rows].sort((a, b) => (a.latest_arrow_at === b.latest_arrow_at ? a.ticker.localeCompare(b.ticker) : a.latest_arrow_at < b.latest_arrow_at ? 1 : -1));
}

/** The Last signal cell's tooltip: the last UP arrow (entry or refresh), which the column no longer shows. */
export function lastEntryRefreshTitle(row: Pick<WarrenWatchRowOut, "last_signal_at">): string {
  return `Last entry/refresh: ${fmtEtStamp(row.last_signal_at)} ET`;
}

export const STOP_BASIS_LABEL: Record<"10%" | "LP" | "entry", string> = { "10%": "10%", LP: "LP", entry: "Entry" };

/** True when the stored stop sits above the entry price: legitimate (an instruction moved it: the 2nd LP after a rally, or the entry
 * price from a Gray Down), but it reads as a bug without a note. */
export function stopAboveEntry(row: Pick<WarrenWatchRowOut, "stop_price" | "entry_price">): boolean {
  return row.stop_price != null && row.entry_price != null && row.stop_price > row.entry_price;
}

/** The note shown beside a stop that is above the entry price. */
export function stopAboveEntryNote(row: Pick<WarrenWatchRowOut, "entry_price" | "stop_basis">): string {
  const source = row.stop_basis === "LP" ? "the 2nd support (LP)" : row.stop_basis === "entry" ? "the entry price" : "an instruction";
  return `Above the entry price${row.entry_price != null ? ` (${fmtMoney(row.entry_price)})` : ""}: the latest instruction set this stop from ${source}, not from the entry.`;
}

/** What the Instruction column draws. A breached row reads "Stop hit" with the breach candle beneath (display only: the stored
 * instruction type, text and stop are unchanged and the stored text stays in the tooltip); any other row draws its stored text. */
export function instructionDisplay(
  row: Pick<WarrenWatchRowOut, "status" | "breached_at" | "instruction_text">,
): { primary: string; secondary: string | null; title: string } {
  if (row.status !== "breached") return { primary: row.instruction_text, secondary: null, title: row.instruction_text };
  return {
    primary: "Stop hit",
    secondary: row.breached_at ? `since ${fmtEtStamp(row.breached_at)} ET` : null,
    title: `Last instruction: ${row.instruction_text}`,
  };
}

/** The tooltip on a "No entry" status: a row born from a Gray Up has no entry price. */
export const NO_ENTRY_NOTE =
  "No up-arrow entry fell inside the 12-month replay window, so an earlier trade may exist. The row only records the latest arrow.";

/** "Oct 15" from a "YYYY-MM-DD" date (or a naive ISO datetime); the input unchanged when it does not parse. */
export function fmtEtDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  return m && month ? `${month} ${Number(m[3])}` : iso;
}

/** "today" / "5 days ago" / "7 months ago" / "2 years ago" for a naive ET stamp against `nowMs`. Day granularity: the few hours between
 * ET and the browser's clock cannot change the wording. Null when the stamp does not parse. */
export function fmtAgeAgo(iso: string, nowMs: number): string | null {
  const m = NAIVE_ISO.exec(iso);
  if (!m) return null;
  const days = Math.floor((nowMs - Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))) / 86_400_000);
  if (days < 1) return "today";
  if (days < 31) return `${days} ${days === 1 ? "day" : "days"} ago`;
  const months = Math.floor(days / 30.44);
  if (months < 24) return `${months} ${months === 1 ? "month" : "months"} ago`;
  const years = Math.floor(months / 12);
  return `${years} years ago`;
}

export const ENTRY_PRICE_NOTE = "The close of the entry candle, not an actual fill.";

/** The Entry cell's tooltip: entry kind, the entry candle's ET stamp, its age, and the close-not-fill note. */
export function entryTitle(row: Pick<WarrenWatchRowOut, "entry_kind" | "entry_at">, nowMs: number): string {
  const kind = row.entry_kind ? `${row.entry_kind === "blue" ? "Blue" : "Yellow"} entry` : "Entry";
  const parts = [kind];
  if (row.entry_at) {
    parts.push(`${fmtEtStamp(row.entry_at)} ET`);
    const age = fmtAgeAgo(row.entry_at, nowMs);
    if (age) parts.push(age);
  }
  return `${parts.join(" · ")}. ${ENTRY_PRICE_NOTE}`;
}

/** A fraction as a signed one-decimal percent: 0.1234 -> "+12.3%", -0.05 -> "-5.0%", 0 -> "0.0%". */
export function fmtSignedPct1(fraction: number): string {
  const pct = fraction * 100;
  const text = Math.abs(pct).toFixed(1);
  return pct > 0 && text !== "0.0" ? `+${text}%` : pct < 0 && text !== "0.0" ? `-${text}%` : `${text}%`;
}

export const BREACHED_PL_NOTE = "Hypothetical: this trade was stopped out at its stop, not at today's price.";

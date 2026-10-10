// Display helpers for the "Why might it be stuck?" Dashboard section (docs/specs/stuck-check.md). Pure. The section feeds nothing and uses no
// verdict colour: statuses are plain labels and figures are neutral text.
import type { StuckFigure, StuckRow, StuckStatus } from "@/lib/api/types";
import { fmtCompactMoney, fmtPlainPct } from "@/lib/format";

export const STATUS_LABEL: Record<StuckStatus, string> = {
  // "Not flagged" (2026-10-10, was "OK"), drawn neutral: it is not a green "pass".
  not_flagged: "Not flagged",
  flagged: "Flagged",
  not_applicable: "Not applicable",
  not_reported: "Not reported",
};

const SIGNED = (n: number, decimals: number, suffix: string): string => {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toFixed(decimals)}${suffix}`;
};

export function formatFigure(figure: StuckFigure, currency = "USD"): string {
  const text = figure.text;
  if (figure.unit === "text" || figure.unit === "count") return text ?? (figure.value == null ? "—" : String(Math.round(figure.value)));
  if (figure.value == null) return text ?? "—";
  const n = figure.value;
  let base: string;
  switch (figure.unit) {
    case "money":
      base = fmtCompactMoney(n, currency);
      break;
    case "pct":
      base = fmtPlainPct(n, 1);
      break;
    case "pp":
      base = SIGNED(n, 1, "%"); // percentage points are written as "%" in the UI (2026-10-10)
      break;
    case "ratio":
      base = n.toFixed(2);
      break;
    case "multiple":
      base = `${n.toFixed(1)}×`;
      break;
    default:
      base = String(n);
  }
  return text ? `${base} · ${text}` : base;
}

// --- Dashboard section (docs/specs/dashboard.md) --------------------------------------------------------------------------------

/** The rows a status-labelled group shows as rows: Flagged and Not flagged, and the figure-only ones. Not applicable and Not reported rows are
 * not drawn per row; their reasons are collapsed into one note (`collapseNotes`). */
export function isShownRow(row: StuckRow): boolean {
  return row.status !== "not_applicable" && row.status !== "not_reported";
}

// "Share count" reads "share count" mid-sentence; an acronym ("FCF after ...") keeps its capitals.
const lowerFirst = (t: string): string => (/^[A-Z][a-z]/.test(t) ? t.charAt(0).toLowerCase() + t.slice(1) : t);

/** One note for a group: every Not-applicable / Not-reported reason and every row note, identical wording merged ("Cash conversion and FCF
 * after stock-based compensation: Free cash flow is not comparable for a bank."), in row order. */
export function collapseNotes(rows: StuckRow[]): string[] {
  const byText = new Map<string, string[]>();
  const add = (text: string | null | undefined, title: string | null) => {
    if (!text) return;
    const clean = text.replace(/\.$/, "");
    const titles = byText.get(clean) ?? [];
    if (title && !titles.includes(title)) titles.push(title);
    byText.set(clean, titles);
  };
  for (const row of rows) {
    if (!isShownRow(row)) add(row.reason, row.title);
    for (const note of row.notes) add(note, null);
  }
  return Array.from(byText, ([text, titles]) => {
    if (titles.length === 0) return `${text}.`;
    const joined = titles.length === 1 ? titles[0] : `${titles.slice(0, -1).join(", ")} and ${lowerFirst(titles[titles.length - 1])}`;
    return `${joined}: ${text}.`;
  });
}

/** The caption under a stuck-check gauge: where the row flags. */
export function gaugeCaption(direction: "ceiling" | "floor", line: number, format: (n: number) => string): string {
  if (direction === "floor" && line === 0) return "Flagged at zero or below";
  return `Flagged ${direction === "ceiling" ? "above" : "below"} ${format(line)}`;
}

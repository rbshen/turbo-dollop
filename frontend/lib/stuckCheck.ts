// Display helpers for the "Why might it be stuck?" card (docs/specs/stuck-check.md). Pure. The card feeds nothing and uses no verdict
// colour: statuses are plain labels and figures are neutral text.
import type { StuckFigure, StuckRow, StuckStatus } from "@/lib/api/types";
import { fmtCompactMoney, fmtPlainPct } from "@/lib/format";
import { verdictDisplay } from "@/lib/tierColor";
import { WEINSTEIN_STAGE_LABEL, type WeinsteinStage } from "@/lib/weinsteinStage";

export const STATUS_LABEL: Record<StuckStatus, string> = {
  // "Not flagged" (2026-10-10), neutral: it is not a green "pass". The stored key stays "ok".
  ok: "Not flagged",
  flagged: "Flagged",
  not_applicable: "Not applicable",
  not_reported: "Not reported",
};

/** Row groups, by row number: rows 1-6 earnings quality and capital allocation, 7-8 price, 9-12 the fundamentals trend. */
export const STUCK_GROUPS: { key: string; title: string; numbers: number[] }[] = [
  { key: "quality", title: "Earnings quality and capital allocation", numbers: [1, 2, 3, 4, 5, 6] },
  { key: "price", title: "Price", numbers: [7, 8] },
  { key: "trend", title: "Fundamentals trend", numbers: [9, 10, 12] },
];

export function rowsForGroup(rows: StuckRow[], numbers: number[]): StuckRow[] {
  return rows.filter((r) => numbers.includes(r.number));
}

const VALUATION_LABEL: Record<string, string> = { undervalued: "Undervalued", fair: "Fairvalued", overvalued: "Overvalued" };
const SPY_STATUS_LABEL: Record<string, string> = {
  outperform: "outperform",
  underperform: "underperform",
  match: "in line",
  no_data: "no data",
};

function signed(n: number, decimals: number, suffix: string): string {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toFixed(decimals)}${suffix}`;
}

/** The text a stored-value figure (row 7) shows: the app's own display words, never recomputed. */
function storedText(figure: StuckFigure): string | null {
  const text = figure.text;
  if (text == null) return null;
  switch (figure.key) {
    case "overall_verdict":
      return verdictDisplay(text);
    case "valuation_verdict":
      return VALUATION_LABEL[text] ?? text;
    case "weinstein_stage":
      return WEINSTEIN_STAGE_LABEL[text as WeinsteinStage] ?? text;
    case "perf_5y_vs_spy":
      return SPY_STATUS_LABEL[text] ?? text;
    default:
      return text;
  }
}

export function formatFigure(figure: StuckFigure, currency = "USD"): string {
  const text = storedText(figure);
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
      base = signed(n, 1, " pp");
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
    const joined = titles.length === 1 ? titles[0] : `${titles.slice(0, -1).join(", ")} and ${titles[titles.length - 1].toLowerCase()}`;
    return `${joined}: ${text}.`;
  });
}

/** The caption under a stuck-check gauge: where the row flags. */
export function gaugeCaption(direction: "ceiling" | "floor", line: number, format: (n: number) => string): string {
  if (direction === "floor" && line === 0) return "Flagged at zero or below";
  return `Flagged ${direction === "ceiling" ? "above" : "below"} ${format(line)}`;
}

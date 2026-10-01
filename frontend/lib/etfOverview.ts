import type { EtfOverviewOut, EtfTradingDataOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtCompactNumber, fmtMoney, fmtNumber, fmtPct, fmtPlainPct } from "@/lib/format";

export interface FundFact {
  label: string;
  value: string;
  /** Signed-return colouring (performance rows only). */
  tone?: "positive" | "negative";
}

/** The "Fund facts" rows, in display order. A fact FMP did not return (null) is left out entirely rather
 * than shown blank -- the backend already turns a meaningless 0 (GLD's holdings count) into null. */
export function fundFacts(o: EtfOverviewOut): FundFact[] {
  const nav = o.nav != null ? fmtMoney(o.nav, o.nav_currency ?? "USD") : null;
  const facts: [string, string | null][] = [
    ["Issuer", o.issuer],
    ["Asset class", o.asset_class],
    ["Expense ratio", o.expense_ratio != null ? fmtPlainPct(o.expense_ratio, 2) : null],
    ["Assets under management", o.assets_under_management != null ? fmtCompactMoney(o.assets_under_management) : null],
    ["Holdings", o.holdings_count != null ? o.holdings_count.toLocaleString("en-US") : null],
    ["NAV", nav],
    ["Average volume", o.avg_volume != null ? fmtCompactNumber(o.avg_volume) : null],
    ["Inception date", o.inception_date],
    ["Domicile", o.domicile],
  ];
  return facts.flatMap(([label, value]) => (value != null && value !== "" ? [{ label, value }] : []));
}

/** The "Trading data" rows, in display order. Anything null, zero or not finite is left out (never a blank or
 * a 0), so the list is empty -- and the block hidden -- when nothing is known. The backend already omits
 * these; this is the one place the page decides what a row looks like. */
export function tradingDataRows(t: EtfTradingDataOut | null): FundFact[] {
  if (!t) return [];
  const has = (n: number | null): n is number => n != null && Number.isFinite(n) && n !== 0;
  const perf = (label: string, n: number | null): FundFact | null =>
    has(n) ? { label, value: fmtPct(n, 2), tone: n > 0 ? "positive" : "negative" } : null;
  const rows: (FundFact | null)[] = [
    perf("1M performance", t.perf_1m),
    perf("YTD performance", t.perf_ytd),
    perf("1Y performance", t.perf_1y),
    has(t.week52_low) && has(t.week52_high)
      ? { label: "52-week range", value: `${fmtMoney(t.week52_low)} – ${fmtMoney(t.week52_high)}` }
      : null,
    has(t.avg_volume_30d) ? { label: "Average volume (30d)", value: fmtCompactNumber(t.avg_volume_30d) } : null,
    has(t.avg_dollar_volume_20d)
      ? { label: "Average dollar volume (20d)", value: fmtCompactMoney(t.avg_dollar_volume_20d) }
      : null,
    has(t.distribution_ttm_yield_pct)
      ? {
          label: "Distribution yield (TTM)",
          value: has(t.distribution_ttm_per_share)
            ? `${fmtPlainPct(t.distribution_ttm_yield_pct, 2)} (${fmtMoney(t.distribution_ttm_per_share)}/sh)`
            : fmtPlainPct(t.distribution_ttm_yield_pct, 2),
        }
      : null,
    has(t.beta) ? { label: "Beta", value: fmtNumber(t.beta, 2) } : null,
  ];
  return rows.filter((r): r is FundFact => r !== null);
}

/** The block's caption: only the notes for rows that are actually shown. */
export function tradingDataCaption(t: EtfTradingDataOut | null, rows: FundFact[]): string | null {
  if (!t || rows.length === 0) return null;
  const shown = new Set(rows.map((r) => r.label));
  const notes: string[] = [];
  if (["1M performance", "YTD performance", "1Y performance"].some((l) => shown.has(l))) {
    notes.push(
      `Performance is price return from daily closes${t.perf_as_of ? ` through ${t.perf_as_of}` : ""}; dividends are not included.`,
    );
  }
  if (shown.has("Distribution yield (TTM)")) {
    notes.push("Distribution yield is the trailing 12-month distribution over the current price, not an SEC yield.");
  }
  return notes.length > 0 ? notes.join(" ") : null;
}

/** "2026-10-01" from FMP's ISO `updatedAt`, or null. */
export function fundDataAsOf(o: EtfOverviewOut): string | null {
  return o.updated_at && /^\d{4}-\d{2}-\d{2}/.test(o.updated_at) ? o.updated_at.slice(0, 10) : null;
}

export const SECTOR_WEIGHTS_NOT_SHOWN_NOTE = "Sector weights are not shown for funds that don't hold stocks.";

/** Why the Overview has nothing to show, in a sentence. */
export function unavailableMessage(o: EtfOverviewOut): string {
  if (o.status === "no_data") return `FMP has no fund details for ${o.ticker}.`;
  if (o.reason === "group_off") {
    return `Fund details are unavailable: the ETF info data group is off (or not on your FMP plan) and nothing is cached for ${o.ticker}. Turn it on in Settings > FMP data groups.`;
  }
  return `Couldn't load fund details for ${o.ticker} from FMP just now, and nothing is cached. Try again shortly.`;
}

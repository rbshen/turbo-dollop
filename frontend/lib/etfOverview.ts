import type { EtfOverviewOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtCompactNumber, fmtMoney, fmtPlainPct } from "@/lib/format";

export interface FundFact {
  label: string;
  value: string;
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

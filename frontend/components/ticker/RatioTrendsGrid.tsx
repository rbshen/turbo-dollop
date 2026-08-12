"use client";

import { TrendCardsGrid, type TrendCard } from "@/components/charts/TrendCardsGrid";
import { useStep4 } from "@/lib/hooks/useStep4";
import { useStep5 } from "@/lib/hooks/useStep5";
import { useRatios } from "@/lib/hooks/useRatios";
import { fmtPct, fmtPlainPct, fmtRatio } from "@/lib/format";
import type { RatiosOut } from "@/lib/api/types";

interface Props {
  ticker: string;
}

// Looks up a single Ratios-tab line item by its exact label, regardless of
// which category group it lives in -- labels are unique across the whole
// RatiosOut payload (see backend/data/ratios_data.py's CATEGORIES).
function ratioValues(data: RatiosOut, label: string): (number | null)[] {
  for (const group of data.groups) {
    const item = group.items.find((i) => i.label === label);
    if (item) return item.values;
  }
  return [];
}

// Margin/ROE/ROIC preview cards at the top of the Ratios tab -- same
// TrendCardsGrid house style as the Financials tab's own
// HistoricalTrendsGrid (moved here since they're profitability ratios, not
// raw financial-statement line items).
//
// Sourced from RatiosOut (2026-08-15), not Step1/Step4 -- confirmed via a
// 20-ticker empirical comparison that RatiosOut's Gross/Net Margin and ROE/
// ROIC already agree with Step1/Step4's own versions essentially exactly
// (219-220/220 and 220/220 respectively; the one Gross/Net Margin miss was
// root-caused to a genuine FMP raw-quarterly-data defect for one ticker,
// not a Fathom bug either side of). Consolidating onto the data-fetching
// pipeline here means this grid and the RatiosTable directly below it can
// never show two different numbers for the same metric/ticker again.
// Scoring itself is untouched -- score_step1/score_step4 still compute
// from their own independent fetch inside step1_data.py/step4_data.py;
// this only changes which pipeline's numbers feed these preview cards.
//
// Current Ratio / Debt-to-EBITDA / Interest Coverage cards (2026-08-13):
// the three ratios whose breach drives Debt's hard-fail verdict (see
// CLAUDE.md). Current Ratio and Interest Coverage are read straight off
// RatiosOut -- confirmed via real cached data (AAPL/T/SBUX/MSFT/NKE) to be
// numerically identical to Step 5's own computation, so no backend change
// was needed for those two. Debt/EBITDA deliberately does NOT reuse
// RatiosOut's "Net Debt/EBITDA" -- that field nets against cash and uses
// FMP's own broader totalDebt (which folds in capital lease obligations),
// not the gross short+long-term debt figure Step 5 actually scores;
// confirmed the two can land in different Comfortable/Borderline bands for
// the same ticker (e.g. SBUX: 2.26x gross vs 3.23x FMP-net). Debt/EBITDA is
// instead sourced from Step5Out's own new debt_to_ebitda_series field.
// All three are gated on `debt_ratios_evaluated` (same flag the Financials
// tab's Total Debt card already uses) so the group appears together or not
// at all -- these ratios don't apply the way they're scored here for
// Bank/Insurance/REIT company types (Bank: CET1/NPL blend; REIT: Gearing).
export function RatioTrendsGrid({ ticker }: Props) {
  const step4 = useStep4(ticker);
  const step5 = useStep5(ticker);
  const ratios = useRatios(ticker);

  if (!step4.data || !step5.data || !ratios.data) {
    return <div className="h-24 animate-pulse rounded-lg border border-border-card bg-surface" />;
  }

  const s4 = step4.data;
  const s5 = step5.data;
  const r = ratios.data;

  const evaluated = s5.debt_ratios_evaluated;
  // ROIC stays suppressed for company types Step 4 exempts (Bank/
  // Insurance/Utility/REIT -- see Step4Out.roic_exempt_reason): s4.roic
  // still reads null (the whole field) for those types, even though
  // RatiosOut's own ROIC field has no such exemption and would otherwise
  // show a value FMP happily computes but Step 4 has never scored or
  // displayed for these company types before.
  const roicExempt = s4.roic == null;

  const cards: (TrendCard | null)[] = [
    { key: "gross_margin", label: "Gross Profit Margin", years: r.periods, values: ratioValues(r, "Gross Margin"), format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "net_margin", label: "Net Profit Margin", years: r.periods, values: ratioValues(r, "Net Margin"), format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "roe", label: "ROE", years: r.periods, values: ratioValues(r, "ROE"), format: fmtPlainPct, tooltipFormat: fmtPct },
    { key: "roic", label: "ROIC", years: r.periods, values: roicExempt ? [] : ratioValues(r, "ROIC"), format: fmtPlainPct, tooltipFormat: fmtPct },
    {
      key: "current_ratio",
      label: "Current Ratio",
      years: r.periods,
      values: evaluated ? ratioValues(r, "Current Ratio") : [],
      format: fmtRatio,
      tooltipFormat: fmtRatio,
    },
    {
      key: "debt_to_ebitda",
      label: "Debt / EBITDA",
      years: s5.debt_to_ebitda_years,
      values: evaluated ? s5.debt_to_ebitda_series : [],
      format: fmtRatio,
      tooltipFormat: fmtRatio,
    },
    {
      key: "interest_coverage",
      label: "Interest Coverage",
      years: r.periods,
      values: evaluated ? ratioValues(r, "Interest Coverage") : [],
      format: fmtRatio,
      tooltipFormat: fmtRatio,
    },
  ];

  return <TrendCardsGrid cards={cards} />;
}

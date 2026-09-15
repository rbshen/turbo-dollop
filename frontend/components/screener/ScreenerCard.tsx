import Link from "next/link";

import { MoatPill } from "@/components/ticker/MoatPill";
import { PerfVsSpyPill } from "@/components/ticker/PerfVsSpyPill";
import { PullbackPill } from "@/components/ticker/PullbackPill";
import { ReversalPill } from "@/components/ticker/ReversalPill";
import { SPECULATIVE_GROWTH_TEXT_CLASS } from "@/components/ticker/SpeculativeGrowthPill";
import { WeinsteinStagePill } from "@/components/ticker/WeinsteinStagePill";
import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { ValuationBadge } from "@/components/screener/ValuationBadge";
import type { TickerScoreOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtMoney, fmtNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  data: TickerScoreOut;
}

export function ScreenerCard({ data }: Props) {
  const isSpeculativeGrowth = data.speculative_growth_qualifies === true;

  return (
    <Link
      href={`/tickers/${data.ticker}`}
      target="_blank"
      rel="noopener noreferrer"
      className="flex flex-col gap-3 rounded-lg border border-border-card bg-surface p-4 transition-colors hover:border-brand"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={cn("truncate font-mono text-sm font-bold", isSpeculativeGrowth ? SPECULATIVE_GROWTH_TEXT_CLASS : "text-text-primary")}>
            {data.ticker}
          </p>
          <p className={cn("truncate text-xs", isSpeculativeGrowth ? SPECULATIVE_GROWTH_TEXT_CLASS : "text-text-tertiary")}>
            {data.company_name ?? "—"}
          </p>
        </div>
        {data.overall_score != null && data.overall_verdict != null ? (
          <ScoreBadge score={data.overall_score} verdict={data.overall_verdict} />
        ) : (
          <span className="shrink-0 text-xs font-medium text-text-tertiary">Incomplete</span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="rounded-md bg-surface-2 px-2 py-1 font-semibold text-text-secondary">
          {data.company_type ?? "Unclassified"}
        </span>
        <span className="truncate text-text-tertiary">{data.sector ?? "—"}</span>
      </div>

      {(data.moat != null ||
        data.valuation_verdict != null ||
        (data.perf_5y_vs_spy_status != null && data.perf_5y_vs_spy_status !== "no_data")) && (
        <div className="flex flex-wrap items-center gap-1.5">
          <MoatPill moat={data.moat} variant="flat" labelSet="screener" />
          {/* No `source` prop here -- suppresses ValuationBadge's "· Custom"
              marker, matching the constant color-only "Valuation" label. */}
          <ValuationBadge verdict={data.valuation_verdict} variant="flat" labelSet="screener" />
          <PerfVsSpyPill status={data.perf_5y_vs_spy_status} variant="flat" labelSet="screener" />
        </div>
      )}

      {/* Technical row -- Weinstein Stage, Reversal, Pullback -- kept
          separate from the fundamental row above so the two families of
          signal (fundamentals-driven vs. price-structure-driven) don't
          visually blend together. */}
      {(data.weinstein_stage != null ||
        (data.reversal_status != null && data.reversal_status !== "not_present") ||
        (data.pullback_status != null && data.pullback_status !== "no_pullback")) && (
        <div className="flex flex-wrap items-center gap-1.5">
          <WeinsteinStagePill data={data} variant="flat" labelSet="screener" />
          <ReversalPill status={data.reversal_status} variant="flat" />
          <PullbackPill status={data.pullback_status} variant="flat" />
        </div>
      )}

      {/* Weighted column widths, not equal grid-cols-4 -- Quote (e.g.
          "$6,299.56" for a high-priced ticker like NVR) and Mkt Cap need
          meaningfully more room than P/E/Beta. Ratio calibrated against the
          real cached-data distribution (577 scored tickers, 2026-09):
          formatted-string length p50/max is Quote 7/9 ("$190.24".."$6,299.56"),
          Mkt Cap 7/8 ("$17.00B".."$938.18B"), P/E 5/7 ("30.00".."-154.08"),
          Beta 4/5 ("1.20".."-7.34") -- P/E's real tail is close to Mkt Cap's,
          Beta's isn't, hence 0.8fr/0.6fr rather than splitting the two
          evenly. min-w-0 on every cell is required alongside this -- a grid
          item won't shrink below its content's intrinsic width by default,
          so without it a long Quote value still overflows into Mkt Cap's
          cell even with more fr-space allocated to it. */}
      <div className="mt-auto grid grid-cols-[1.3fr_1fr_0.8fr_0.6fr] gap-2 border-t border-border-subtle pt-2 text-xs">
        <div className="min-w-0">
          <p className="text-text-tertiary">Quote</p>
          <p className="break-words font-mono text-text-secondary">
            {data.last_price != null ? fmtMoney(data.last_price, data.quote_currency ?? "USD") : "—"}
          </p>
        </div>
        <div className="min-w-0">
          <p className="text-text-tertiary">Mkt Cap</p>
          <p className="font-mono text-text-secondary">
            {data.market_cap != null ? fmtCompactMoney(data.market_cap, data.quote_currency ?? "USD") : "—"}
          </p>
        </div>
        <div className="min-w-0">
          <p className="text-text-tertiary">P/E</p>
          <p className="font-mono text-text-secondary">{data.pe_ratio != null ? fmtNumber(data.pe_ratio) : "—"}</p>
        </div>
        <div className="min-w-0">
          <p className="text-text-tertiary">Beta</p>
          <p className="font-mono text-text-secondary">{data.beta != null ? fmtNumber(data.beta) : "—"}</p>
        </div>
      </div>
    </Link>
  );
}

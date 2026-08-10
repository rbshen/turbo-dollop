import Link from "next/link";

import { MoatPill } from "@/components/ticker/MoatPill";
import { PerfVsSpyPill } from "@/components/ticker/PerfVsSpyPill";
import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { ValuationBadge } from "@/components/screener/ValuationBadge";
import type { TickerScoreOut } from "@/lib/api/types";
import { fmtCompactMoney, fmtNumber } from "@/lib/format";

interface Props {
  data: TickerScoreOut;
}

export function ScreenerCard({ data }: Props) {
  return (
    <Link
      href={`/tickers/${data.ticker}`}
      target="_blank"
      rel="noopener noreferrer"
      className="flex flex-col gap-3 rounded-lg border border-border-card bg-surface p-4 transition-colors hover:border-brand"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-sm font-bold text-text-primary">{data.ticker}</p>
          <p className="truncate text-xs text-text-tertiary">{data.company_name ?? "—"}</p>
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

      <div className="mt-auto grid grid-cols-3 gap-2 border-t border-border-subtle pt-2 text-xs">
        <div>
          <p className="text-text-tertiary">Mkt Cap</p>
          <p className="font-mono text-text-secondary">{data.market_cap != null ? fmtCompactMoney(data.market_cap) : "—"}</p>
        </div>
        <div>
          <p className="text-text-tertiary">P/E</p>
          <p className="font-mono text-text-secondary">{data.pe_ratio != null ? fmtNumber(data.pe_ratio) : "—"}</p>
        </div>
        <div>
          <p className="text-text-tertiary">Beta</p>
          <p className="font-mono text-text-secondary">{data.beta != null ? fmtNumber(data.beta) : "—"}</p>
        </div>
      </div>
    </Link>
  );
}

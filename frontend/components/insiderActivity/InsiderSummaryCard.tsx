import type { InsiderSummary } from "@/lib/api/types";
import { fmtCompactNumber } from "@/lib/format";
import { SENTIMENT_LABELS, SENTIMENT_STYLES, fmtIsoDate } from "@/lib/insiderActivity";
import { cn } from "@/lib/utils";

interface Props {
  summary: InsiderSummary;
}

// Cluster-buy reuses Speculative Growth's chart-purple chip look: like that
// pill it's an orthogonal flag, not another rung on the green/red sentiment
// scale next to it. The window dates go in the tooltip so a stale cluster
// (the fetched history reaches back years, not just recent filings) can
// never pass as a current one.
const CLUSTER_PILL = "border-chart-purple/40 bg-chart-purple/16 text-chart-purple";

export function InsiderSummaryCard({ summary }: Props) {
  const { cluster_buy: cluster } = summary;
  const windowNote =
    summary.quarters_in_window === 0
      ? "No filed quarterly totals yet."
      : `${fmtCompactNumber(summary.total_purchases)} purchases vs. ${fmtCompactNumber(summary.total_sales)} sales over the last ${summary.quarters_in_window} filed quarter${summary.quarters_in_window === 1 ? "" : "s"}.`;

  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <div className="flex flex-wrap items-start gap-x-10 gap-y-4">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-widest text-text-tertiary">Insider sentiment</p>
          <span
            className={cn(
              "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold",
              SENTIMENT_STYLES[summary.sentiment]
            )}
          >
            {SENTIMENT_LABELS[summary.sentiment]}
          </span>
        </div>

        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-widest text-text-tertiary">Open-market buys : sells</p>
          <p className="font-mono text-sm font-semibold tabular-nums">
            <span className="text-positive">{summary.open_market_buy_count}</span>
            <span className="text-text-tertiary"> : </span>
            <span className="text-negative">{summary.open_market_sale_count}</span>
          </p>
        </div>

        {cluster && (
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-widest text-text-tertiary">Cluster buy</p>
            <span
              className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold", CLUSTER_PILL)}
              title={`${cluster.insider_count} distinct insiders bought on the open market between ${fmtIsoDate(cluster.window_start)} and ${fmtIsoDate(cluster.window_end)}`}
            >
              Cluster buy · {cluster.insider_count} insiders
            </span>
          </div>
        )}
      </div>

      <div className="space-y-1 text-xs text-text-tertiary">
        <p>{windowNote}</p>
        <p>
          The trailing window sums the last 2 filed quarters — an approximation, not a true rolling 6 months. Buy/sell
          counts cover the same window.
        </p>
      </div>
    </div>
  );
}

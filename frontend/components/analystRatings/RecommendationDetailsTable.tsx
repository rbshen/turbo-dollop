import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { RecommendationDetailsColumn } from "@/lib/api/types";
import { fmtMoney, fmtNumber } from "@/lib/format";

interface Props {
  columns: RecommendationDetailsColumn[];
  currency?: string;
}

type RowKey = "buy" | "outperform" | "hold" | "underperform" | "sell" | "mean" | "consensus" | "target";

// Distinct icon from MetricsGrid's own "⚠" data-quality flag -- a
// methodology caveat, not an anomaly warning. See analyst_ratings_data.py's
// _details_column / RecommendationDetailsColumn.consensus for why "Current"
// alone uses FMP's own live rating text rather than this table's own
// weighted-score banding.
const TOOLTIP_ICON = "ⓘ";
const CURRENT_CONSENSUS_TOOLTIP =
  '"Current" is FMP\'s own live consensus rating; 2M/6M/1Y Ago are calculated from Fathom\'s weighted-score thresholds.';

// Row labels are FMP's own 5 rating bucket names (strongBuy->Strong Buy,
// buy->Buy, hold->Hold, sell->Sell, strongSell->Strong Sell); the `key`s
// keep the original buy/outperform/hold/underperform/sell identifiers,
// matching backend/analyst_ratings_data.py's _details_column field names
// exactly -- only the display label changed.
const ROWS: { key: RowKey; label: string }[] = [
  { key: "buy", label: "Strong Buy" },
  { key: "outperform", label: "Buy" },
  { key: "hold", label: "Hold" },
  { key: "underperform", label: "Sell" },
  { key: "sell", label: "Strong Sell" },
  { key: "mean", label: "Mean" },
  { key: "consensus", label: "Consensus" },
  { key: "target", label: "Target" },
];

function formatCell(key: RowKey, column: RecommendationDetailsColumn, currency: string): string {
  const value = column[key];
  if (value == null) return "—";
  if (key === "mean") return fmtNumber(value as number, 2);
  if (key === "consensus") return value as string;
  if (key === "target") return fmtMoney(value as number, currency);
  return String(value);
}

// Same sticky-left-label-column structure as RatiosTable -- rows are fixed
// (Strong Buy/Buy/Hold/Sell/Strong Sell/Mean/Consensus/Target) rather than
// FMP-driven groups, so there's no group-header row to carry over. No outer
// border/bg of its own -- always embedded inside SentimentOverTimeCard's
// own card, so an outer container here would double up the border.
export function RecommendationDetailsTable({ columns, currency = "USD" }: Props) {
  return (
    <Table className="border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className="sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-page pr-8">
            Metric
          </TableHead>
          {columns.map((column) => (
            <TableHead
              key={column.label}
              className="whitespace-nowrap border-b border-border-subtle text-right"
            >
              {column.label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {ROWS.map((row) => (
          <TableRow key={row.key} dense>
            <TableCell className="sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-page pr-8 text-text-secondary">
              {row.label}
            </TableCell>
            {columns.map((column) => (
              <TableCell
                key={column.label}
                className="border-b border-border-subtle text-right font-mono tabular-nums text-text-primary"
              >
                {formatCell(row.key, column, currency)}
                {row.key === "consensus" && column.label === "Current" && (
                  <span className="ml-1 text-text-tertiary" title={CURRENT_CONSENSUS_TOOLTIP}>
                    {TOOLTIP_ICON}
                  </span>
                )}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

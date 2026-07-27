import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { RecommendationDetailsColumn } from "@/lib/api/types";
import { fmtMoney, fmtNumber } from "@/lib/format";

interface Props {
  columns: RecommendationDetailsColumn[];
}

type RowKey = "buy" | "outperform" | "hold" | "underperform" | "sell" | "mean" | "consensus" | "target";

// Row order/labels are a 1:1 relabel of FMP's 5 rating buckets
// (strongBuy->Buy, buy->Outperform, hold->Hold, sell->Underperform,
// strongSell->Sell), matching backend/analyst_ratings_data.py's
// _details_column mapping exactly.
const ROWS: { key: RowKey; label: string }[] = [
  { key: "buy", label: "Buy" },
  { key: "outperform", label: "Outperform" },
  { key: "hold", label: "Hold" },
  { key: "underperform", label: "Underperform" },
  { key: "sell", label: "Sell" },
  { key: "mean", label: "Mean" },
  { key: "consensus", label: "Consensus" },
  { key: "target", label: "Target" },
];

function formatCell(key: RowKey, column: RecommendationDetailsColumn): string {
  const value = column[key];
  if (value == null) return "—";
  if (key === "mean") return fmtNumber(value as number, 2);
  if (key === "consensus") return value as string;
  if (key === "target") return fmtMoney(value as number);
  return String(value);
}

// Same sticky-left-label-column structure as RatiosTable -- rows are fixed
// (Buy/Outperform/Hold/Underperform/Sell/Mean/Consensus/Target) rather than
// FMP-driven groups, so there's no group-header row to carry over.
export function RecommendationDetailsTable({ columns }: Props) {
  return (
    <Table className="border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="sticky left-0 z-10 whitespace-nowrap border-b border-zinc-800 bg-zinc-950 py-2 pr-8 text-xs font-medium uppercase tracking-widest text-zinc-500">
            Metric
          </TableHead>
          {columns.map((column) => (
            <TableHead
              key={column.label}
              className="whitespace-nowrap border-b border-zinc-800 py-2 pr-4 text-right text-xs font-medium uppercase tracking-widest text-zinc-500"
            >
              {column.label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {ROWS.map((row) => (
          <TableRow key={row.key} className="hover:bg-transparent">
            <TableCell className="sticky left-0 z-10 whitespace-nowrap border-b border-zinc-900 bg-zinc-950 py-2 pr-8 text-zinc-400">
              {row.label}
            </TableCell>
            {columns.map((column) => (
              <TableCell
                key={column.label}
                className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-300"
              >
                {formatCell(row.key, column)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

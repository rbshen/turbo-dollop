import type { MouseEvent } from "react";

import { MOAT_LABEL_SHORT, MOAT_TONE } from "@/components/ticker/MoatPill";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { MomentumSnapshotRowOut } from "@/lib/api/types";
import { fmtPct, pnlClass } from "@/lib/format";

const HEAD_CLASS = "text-xs font-medium text-text-tertiary";

interface Props {
  rows: MomentumSnapshotRowOut[];
}

// The whole row opens the ticker page in a new tab (matching WatchlistTable's
// row click) -- but the ticker itself stays a real <a target="_blank"> for
// keyboard/middle-click access. A click that originates from that anchor (or
// any other interactive child, e.g. a future action button) is left alone --
// the anchor's own native navigation already handles it, and re-triggering
// window.open here would open two tabs.
function handleRowClick(e: MouseEvent<HTMLTableRowElement>, ticker: string) {
  if ((e.target as HTMLElement).closest("a, button")) return;
  window.open(`/tickers/${ticker}`, "_blank", "noopener,noreferrer");
}

// null on snapshots that predate these columns (or a ticker without a price that far back).
function InfoReturnCell({ value }: { value: number | null }) {
  if (value == null) return <TableCell className="text-right font-mono text-text-tertiary">—</TableCell>;
  return <TableCell className={`text-right font-mono ${pnlClass(value)}`}>{fmtPct(value * 100)}</TableCell>;
}

export function MomentumTable({ rows }: Props) {
  if (rows.length === 0) {
    return <p className="text-xs text-text-tertiary">No tickers in this snapshot.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className={`${HEAD_CLASS} w-12 text-center`}>Rank</TableHead>
          <TableHead className={`${HEAD_CLASS} w-[280px]`}>Ticker</TableHead>
          <TableHead className={`${HEAD_CLASS} w-16 text-center`}>Moat</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>1 w</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>1 mo</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>3 mo</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>6 mo</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>12 mo</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Composite</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Score</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.ticker} interactive onClick={(e) => handleRowClick(e, row.ticker)}>
            <TableCell className="text-center font-mono text-text-secondary">{row.rank}</TableCell>
            <TableCell className="max-w-[280px] overflow-hidden">
              <a
                href={`/tickers/${row.ticker}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-sm font-semibold text-text-primary"
              >
                {row.ticker}
              </a>
              <p className="truncate text-xs text-text-secondary" title={row.company_name ?? undefined}>
                {row.company_name ?? "—"}
              </p>
            </TableCell>
            <TableCell className="text-center">
              <Badge size="compact" tone={MOAT_TONE[row.moat]}>
                {MOAT_LABEL_SHORT[row.moat]}
              </Badge>
            </TableCell>
            {/* 1w/1mo are informational only -- the ranking uses 3/6/12 mo. */}
            <InfoReturnCell value={row.return_1w} />
            <InfoReturnCell value={row.return_1mo} />
            <TableCell className={`text-right font-mono ${pnlClass(row.return_3mo)}`}>{fmtPct(row.return_3mo * 100)}</TableCell>
            <TableCell className={`text-right font-mono ${pnlClass(row.return_6mo)}`}>{fmtPct(row.return_6mo * 100)}</TableCell>
            <TableCell className={`text-right font-mono ${pnlClass(row.return_12mo)}`}>{fmtPct(row.return_12mo * 100)}</TableCell>
            <TableCell className={`text-right font-mono font-bold ${pnlClass(row.composite_score)}`}>
              {fmtPct(row.composite_score * 100)}
            </TableCell>
            {/* No verdict field exists alongside overall_score here
                (MomentumSnapshotRowOut has no overall_verdict) -- unlike
                every other Badge/Status score cell in the app, tierColor's
                tone functions can't tier this one without guessing at a
                mapping, so it stays a neutral compact pill (same always-gray
                read as before this migration, just via Badge's `missing`
                state instead of a bare "—"). See the design-system session
                5a report. */}
            <TableCell className="text-right">
              {row.overall_score != null ? (
                <Badge size="compact" tone="neutral">
                  {row.overall_score}
                </Badge>
              ) : (
                <Badge size="compact" missing />
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

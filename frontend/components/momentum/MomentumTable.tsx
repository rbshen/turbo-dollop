import Link from "next/link";

import { MomentumOverallInfoIcon } from "@/components/momentum/MomentumOverallInfoIcon";
import { MoatPill } from "@/components/ticker/MoatPill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { MomentumSnapshotRowOut } from "@/lib/api/types";
import { fmtPct, pnlClass } from "@/lib/format";

const HEAD_CLASS = "whitespace-nowrap text-xs font-semibold uppercase tracking-widest text-text-tertiary";

interface Props {
  rows: MomentumSnapshotRowOut[];
}

export function MomentumTable({ rows }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className={`${HEAD_CLASS} w-12 text-center`}>Rank</TableHead>
          <TableHead className={`${HEAD_CLASS} w-20`}>Ticker</TableHead>
          <TableHead className={`${HEAD_CLASS} w-[280px]`}>Company</TableHead>
          <TableHead className={`${HEAD_CLASS} w-16 text-center`}>Moat</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>3mo</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>6mo</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>12mo</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Composite</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>
            <span className="inline-flex items-center gap-1">
              Overall
              <MomentumOverallInfoIcon />
            </span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.ticker}>
            <TableCell className="text-center font-mono text-text-secondary">{row.rank}</TableCell>
            <TableCell className="font-mono font-bold">
              <Link href={`/tickers/${row.ticker}`} target="_blank" rel="noopener noreferrer" className="text-brand hover:underline">
                {row.ticker}
              </Link>
            </TableCell>
            <TableCell className="max-w-[280px] truncate text-text-secondary" title={row.company_name ?? undefined}>
              {row.company_name ?? "—"}
            </TableCell>
            <TableCell className="text-center">
              <MoatPill moat={row.moat} />
            </TableCell>
            <TableCell className={`text-right font-mono ${pnlClass(row.return_3mo)}`}>{fmtPct(row.return_3mo * 100)}</TableCell>
            <TableCell className={`text-right font-mono ${pnlClass(row.return_6mo)}`}>{fmtPct(row.return_6mo * 100)}</TableCell>
            <TableCell className={`text-right font-mono ${pnlClass(row.return_12mo)}`}>{fmtPct(row.return_12mo * 100)}</TableCell>
            <TableCell className={`text-right font-mono font-bold ${pnlClass(row.composite_score)}`}>
              {fmtPct(row.composite_score * 100)}
            </TableCell>
            <TableCell className="text-right font-mono text-text-tertiary">{row.overall_score ?? "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

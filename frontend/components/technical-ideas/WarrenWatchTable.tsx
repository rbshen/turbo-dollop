import type { MouseEvent } from "react";
import { ArrowDown, ArrowUp, Info } from "@phosphor-icons/react";

import { WarrenWatchRemoveButton } from "@/components/technical-ideas/WarrenWatchRemoveButton";
import { Badge } from "@/components/ui/badge";
import { pillVariants } from "@/components/ui/pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { WarrenWatchRowOut } from "@/lib/api/types";
import { fmtMoney } from "@/lib/format";
import {
  fmtBarsAgo,
  fmtEtStamp,
  sortByLastSignal,
  STOP_BASIS_LABEL,
  stopAboveEntry,
  stopAboveEntryNote,
} from "@/lib/technicalIdeas";
import { cn } from "@/lib/utils";

const HEAD_CLASS = "text-xs font-medium text-text-tertiary";

// The arrow's colour as the chart draws it: Blue is the chart's blue (chart-ema21), Yellow and Gray their own chart-warren tokens.
// Literal class names so Tailwind sees them.
const SIGNAL_TONE_CLASS: Record<WarrenWatchRowOut["latest_arrow_color"], string> = {
  blue: "bg-chart-ema21/16 text-chart-ema21",
  yellow: "bg-chart-warren-yellow/16 text-chart-warren-yellow",
  gray: "bg-chart-warren-gray/16 text-chart-warren-gray",
};
const SIGNAL_LABEL: Record<WarrenWatchRowOut["latest_arrow_color"], string> = { blue: "Blue", yellow: "Yellow", gray: "Gray" };

interface Props {
  rows: WarrenWatchRowOut[];
}

// The whole row opens the ticker page in a new tab (as MomentumTable does); a click that starts on the ticker link or the Remove
// control is left to that element.
function handleRowClick(e: MouseEvent<HTMLTableRowElement>, ticker: string) {
  if ((e.target as HTMLElement).closest("a, button")) return;
  window.open(`/tickers/${ticker}`, "_blank", "noopener,noreferrer");
}

function SignalPill({ row }: { row: WarrenWatchRowOut }) {
  const Arrow = row.latest_arrow_direction === "up" ? ArrowUp : ArrowDown;
  const label = `${SIGNAL_LABEL[row.latest_arrow_color]} ${row.latest_arrow_direction === "up" ? "Up" : "Down"}`;
  return (
    <span
      className={cn(pillVariants({ size: "compact" }), SIGNAL_TONE_CLASS[row.latest_arrow_color])}
      title={`${label} · candle ${fmtEtStamp(row.latest_arrow_at)} ET`}
    >
      <Arrow size={10} weight="bold" aria-hidden="true" />
      {label}
    </span>
  );
}

function StopCell({ row }: { row: WarrenWatchRowOut }) {
  if (row.stop_price == null) return <TableCell className="text-right font-mono text-text-tertiary">—</TableCell>;
  const above = stopAboveEntry(row);
  const basis = row.stop_basis === "none" ? null : STOP_BASIS_LABEL[row.stop_basis];
  return (
    <TableCell className="whitespace-nowrap text-right">
      <span className="inline-flex items-center justify-end gap-1.5">
        {above && (
          <span title={stopAboveEntryNote(row)} aria-label={stopAboveEntryNote(row)} className="inline-flex text-text-tertiary">
            <Info size={14} aria-hidden="true" />
          </span>
        )}
        <span className="font-mono text-text-primary">{fmtMoney(row.stop_price)}</span>
        {basis && (
          <Badge size="compact" tone="neutral">
            {basis}
          </Badge>
        )}
      </span>
    </TableCell>
  );
}

export function WarrenWatchTable({ rows }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="h-9">
          <TableHead className={`${HEAD_CLASS} w-24`}>Ticker</TableHead>
          <TableHead className={HEAD_CLASS}>Signal</TableHead>
          <TableHead className={HEAD_CLASS}>Instruction</TableHead>
          <TableHead className={`${HEAD_CLASS} text-right`}>Stop</TableHead>
          <TableHead className={HEAD_CLASS}>Status</TableHead>
          <TableHead className={HEAD_CLASS}>Last signal</TableHead>
          <TableHead className={HEAD_CLASS}>Last updated</TableHead>
          <TableHead className={`${HEAD_CLASS} w-px`}>
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sortByLastSignal(rows).map((row) => (
          <TableRow key={row.ticker} interactive onClick={(e) => handleRowClick(e, row.ticker)}>
            <TableCell>
              <a
                href={`/tickers/${row.ticker}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-sm font-semibold text-text-primary"
              >
                {row.ticker}
              </a>
              {row.profile !== "any" && <p className="text-xs uppercase text-text-tertiary">{row.profile} profile</p>}
            </TableCell>
            <TableCell className="whitespace-nowrap">
              <SignalPill row={row} />
            </TableCell>
            <TableCell className="max-w-[420px] text-xs text-text-secondary" title={row.instruction_text}>
              {row.instruction_text}
            </TableCell>
            <StopCell row={row} />
            <TableCell className="whitespace-nowrap">
              {row.status === "breached" ? (
                <Badge
                  size="compact"
                  tone="negative"
                  title={row.breached_at ? `Low reached the stop on the ${fmtEtStamp(row.breached_at)} ET candle` : undefined}
                >
                  Stop breached
                </Badge>
              ) : (
                <Badge size="compact" tone="positive">
                  Active
                </Badge>
              )}
            </TableCell>
            <TableCell className="whitespace-nowrap font-mono text-xs text-text-secondary">
              {fmtEtStamp(row.last_signal_at)}
              {fmtBarsAgo(row.last_signal_age_bars) && (
                <span className="block font-sans text-text-tertiary">{fmtBarsAgo(row.last_signal_age_bars)}</span>
              )}
            </TableCell>
            <TableCell className="whitespace-nowrap font-mono text-xs text-text-secondary">{fmtEtStamp(row.last_updated_at)}</TableCell>
            <TableCell className="text-right">
              <WarrenWatchRemoveButton ticker={row.ticker} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

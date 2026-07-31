import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface SeriesTrendTableSeries {
  key: string;
  label: string;
  color: string;
}

interface Props {
  labelHeader: string;
  years: string[];
  series: SeriesTrendTableSeries[];
  values: Record<string, (number | null)[]>;
  formatValue: (v: number) => string;
  /** Appends an "Avg" column computed across each series' non-null years (Margins only). */
  showAverage?: boolean;
}

function average(values: (number | null)[]): number | null {
  const nums = values.filter((v): v is number => v != null);
  if (!nums.length) return null;
  return nums.reduce((sum, v) => sum + v, 0) / nums.length;
}

// Single sticky-label-column table, same technique as
// FinancialsStatementTable.tsx -- replaces the former two-tables-side-by-
// side layout (an independent shrink-0 label <table> beside a scrollable
// years <table>) that six components used to hand-roll identically. One
// <tr> per series can't drift out of row-height alignment with itself the
// way two separately-laid-out tables could.
export function SeriesTrendTable({ labelHeader, years, series, values, formatValue, showAverage }: Props) {
  return (
    <Table className="border-separate border-spacing-0 text-sm">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="sticky left-0 z-10 whitespace-nowrap border-b border-border-card bg-surface py-2 pr-8 text-xs font-medium uppercase tracking-widest text-text-secondary">
            {labelHeader}
          </TableHead>
          {years.map((year) => (
            <TableHead
              key={year}
              className="whitespace-nowrap border-b border-border-card py-2 pr-4 text-right text-xs font-medium uppercase tracking-widest text-text-secondary"
            >
              {year}
            </TableHead>
          ))}
          {showAverage && (
            <TableHead className="whitespace-nowrap border-b border-border-card py-2 pr-4 text-right text-xs font-medium uppercase tracking-widest text-text-secondary">
              Avg
            </TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {series.map((s) => {
          const seriesValues = values[s.key] ?? [];
          const avg = showAverage ? average(seriesValues) : null;
          return (
            <TableRow key={s.key} className="hover:bg-transparent">
              <TableCell className="sticky left-0 z-10 whitespace-nowrap border-b border-border-subtle bg-surface py-2 pr-8 text-text-secondary">
                <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ backgroundColor: s.color }} />
                {s.label}
              </TableCell>
              {seriesValues.map((v, i) => (
                <TableCell key={i} className="border-b border-border-subtle py-2 pr-4 text-right font-mono tabular-nums text-text-primary">
                  {v != null ? formatValue(v) : "—"}
                </TableCell>
              ))}
              {showAverage && (
                <TableCell className="border-b border-border-subtle py-2 pr-4 text-right font-mono tabular-nums text-text-primary">
                  {avg != null ? formatValue(avg) : "—"}
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

import { RechartsPieChart } from "@/components/charts/RechartsPieChart";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fmtPlainPct, fmtTableMoney } from "@/lib/format";
import { OTHER_COLOR, OTHER_LABEL, SEGMENT_COLORS } from "@/lib/segmentColors";

interface Props {
  title: string;
  /** The row's overall FY label (the more recent of product/geographic). */
  headerYear: string | null;
  /** This side's own latest disclosed FY -- may lag headerYear if product
   * and geographic segmentation happen to have different latest years. */
  year: string | null;
  segments: string[] | null;
  values: Record<string, number | null>;
  notDisclosedNote: string;
}

// Single-period sibling to SegmentationSection: a donut chart plus a
// value/share table for the latest disclosed fiscal year, rather than a
// multi-year stacked trend. Reuses the same ranked segment list (and
// therefore the same segment -> color assignment) as the historical
// section above it on the Summary tab, so a segment reads as the same
// color in both views.
export function SegmentationSnapshotSection({ title, headerYear, year, segments, values, notDisclosedNote }: Props) {
  if (!segments || segments.length === 0 || year == null) {
    return (
      <div className="space-y-3">
        <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">{title}</h3>
        <p className="text-sm text-zinc-500">{notDisclosedNote}</p>
      </div>
    );
  }

  const series = segments.map((name, i) => ({
    key: name,
    label: name,
    color: name === OTHER_LABEL ? OTHER_COLOR : SEGMENT_COLORS[i % SEGMENT_COLORS.length],
  }));

  const total = segments.reduce((sum, name) => sum + (values[name] ?? 0), 0);

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">
        {title}
        {year !== headerYear && (
          <span className="ml-2 normal-case tracking-normal text-zinc-600">(FY{year})</span>
        )}
      </h3>

      <RechartsPieChart series={series} values={values} valueFormat={fmtTableMoney} />

      <Table className="w-full border-separate border-spacing-0 text-sm">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="whitespace-nowrap border-b border-zinc-800 py-2 pr-8 font-medium">Segment</TableHead>
            <TableHead className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">Revenue</TableHead>
            <TableHead className="border-b border-zinc-800 py-2 text-right font-medium">Share</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {series.map((s) => {
            const v = values[s.key];
            return (
              <TableRow key={s.key} className="hover:bg-transparent">
                <TableCell className="whitespace-nowrap border-b border-zinc-900 py-2 pr-8 text-zinc-400">
                  <span
                    className="mr-1.5 inline-block size-2 rounded-full align-middle"
                    style={{ backgroundColor: s.color }}
                  />
                  {s.label}
                </TableCell>
                <TableCell className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                  {v != null ? fmtTableMoney(v) : "—"}
                </TableCell>
                <TableCell className="border-b border-zinc-900 py-2 text-right font-mono tabular-nums text-zinc-400">
                  {v != null && total > 0 ? fmtPlainPct((v / total) * 100) : "—"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

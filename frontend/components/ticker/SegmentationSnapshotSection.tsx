import { ChartLegend } from "@/components/charts/ChartLegend";
import { RechartsPieChart } from "@/components/charts/RechartsPieChart";
import { fmtTableMoney } from "@/lib/format";
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
      <div className="space-y-3 rounded-lg border border-border-card bg-surface p-5">
        <h3 className="text-xs font-medium uppercase tracking-widest text-text-secondary">{title}</h3>
        <p className="text-sm text-text-tertiary">{notDisclosedNote}</p>
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
    <div className="space-y-3 rounded-lg border border-border-card bg-surface p-5">
      <h3 className="text-xs font-medium uppercase tracking-widest text-text-secondary">
        {title}
        {year !== headerYear && (
          <span className="ml-2 normal-case tracking-normal text-text-tertiary">(FY{year})</span>
        )}
      </h3>

      <div className="flex items-center gap-6">
        <div className="w-[180px] shrink-0">
          <RechartsPieChart series={series} values={values} valueFormat={fmtTableMoney} height={180} />
        </div>
        <ChartLegend
          layout="column"
          className="min-w-0 flex-1"
          items={series.map((s) => {
            const v = values[s.key];
            return { ...s, percent: v != null && total > 0 ? (v / total) * 100 : undefined };
          })}
        />
      </div>
    </div>
  );
}

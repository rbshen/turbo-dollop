import { RechartsStackedChart } from "@/components/charts/RechartsStackedChart";
import { SeriesTrendTable } from "@/components/shared/SeriesTrendTable";
import { computeNiceTicks } from "@/lib/charts";
import { fmtAxisMoney, fmtTableMoney, pickAxisMoneyUnit } from "@/lib/format";
import { OTHER_COLOR, OTHER_LABEL, SEGMENT_COLORS } from "@/lib/segmentColors";

interface Props {
  title: string;
  years: string[];
  segments: string[] | null;
  values: Record<string, (number | null)[]>;
  notDisclosedNote: string;
}

export function SegmentationSection({ title, years, segments, values, notDisclosedNote }: Props) {
  if (!segments || segments.length === 0) {
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

  // Stacked totals (not each series' own max) drive the axis, since bars
  // stack additively.
  const totals = years.map((_, i) => segments.reduce((sum, name) => sum + (values[name]?.[i] ?? 0), 0));
  const maxValue = Math.max(0, ...totals);
  const yTicks = computeNiceTicks(maxValue);
  const unit = pickAxisMoneyUnit(yTicks[yTicks.length - 1] || 1);

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-medium uppercase tracking-widest text-zinc-500">{title}</h3>

      <RechartsStackedChart
        categories={years}
        series={series}
        values={values}
        yTicks={yTicks}
        yTickFormat={(v) => fmtAxisMoney(v, unit)}
      />

      <SeriesTrendTable labelHeader="Segment" years={years} series={series} values={values} formatValue={fmtTableMoney} />
    </div>
  );
}

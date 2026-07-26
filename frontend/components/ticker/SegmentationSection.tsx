import { RechartsStackedChart } from "@/components/charts/RechartsStackedChart";
import { computeNiceTicks } from "@/lib/charts";
import { fmtAxisMoney, fmtTableMoney, pickAxisMoneyUnit } from "@/lib/format";

// Same 8-hue categorical palette already hardcoded elsewhere in this app's
// charts (FinancialsSection.tsx/CccSection.tsx) -- validated dataviz-skill
// reference order, assigned here in descending-contribution rank so the
// most prominent segment always lands on the same hue. Segments are
// dynamic per-company free text, so unlike those fixed-metric charts there
// can be more series than fit the palette -- segmentation_data.py caps real
// segments at 7 and folds any remainder into "Other", which always renders
// in this fixed muted gray rather than a "generated" 8th/9th hue.
const SEGMENT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"];
const OTHER_COLOR = "#71717a";
const OTHER_LABEL = "Other";

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

      <div className="flex">
        <table className="shrink-0 border-separate border-spacing-0 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
              <th className="whitespace-nowrap border-b border-zinc-800 py-2 pr-8 font-medium">Segment</th>
            </tr>
          </thead>
          <tbody>
            {series.map((s) => (
              <tr key={s.key}>
                <td className="whitespace-nowrap border-b border-zinc-900 py-2 pr-8 text-zinc-400">
                  <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ backgroundColor: s.color }} />
                  {s.label}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex-1 overflow-x-auto">
          <table className="w-full min-w-max border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-widest text-zinc-500">
                {years.map((year) => (
                  <th key={year} className="border-b border-zinc-800 py-2 pr-4 text-right font-medium">
                    {year}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {series.map((s) => (
                <tr key={s.key}>
                  {(values[s.key] ?? []).map((v, i) => (
                    <td key={i} className="border-b border-zinc-900 py-2 pr-4 text-right font-mono tabular-nums text-zinc-100">
                      {v != null ? fmtTableMoney(v) : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

"use client";

import { Bar, BarChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { computeNiceTicksRange } from "@/lib/charts";

export interface StackedBarSegment {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

interface Props {
  categories: string[];
  /** Single-series mode -- ignored when `segments` is provided. */
  values?: (number | null)[];
  /** Stacked mode -- when provided, renders one stacked bar per category
   * combining every segment instead of a single-series bar, and the
   * tooltip lists each segment's value plus the combined total. `values`
   * is ignored in this mode. */
  segments?: StackedBarSegment[];
  /** Formats a hovered bar's value for the tooltip (2-decimal, signed --
   * see HistoricalTrendsGrid's per-metric fmtCompactMoney/fmtPct/fmtDays
   * choice). No tooltip is shown if omitted. */
  valueFormat?: (v: number) => string;
  color?: string;
  height?: number;
  /** Percentage of each category band reserved as gap between bars, passed
   * straight through to Recharts' BarChart -- higher gap means narrower
   * bars. Defaults to "10%" (unchanged from before this prop existed), so
   * every caller besides WatchlistTable's TrendCell (which passes a
   * slightly wider gap for a small width trim) is unaffected. */
  barCategoryGap?: string;
}

interface StackedTooltipContentProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: Record<string, number | string | null> }>;
  segments: StackedBarSegment[];
  valueFormat: (v: number) => string;
}

// Stacked-mode tooltip -- lists each segment's value (with its color swatch)
// plus a combined total row, unlike the single-series tooltip which just
// shows one formatted number. Reads segment values straight off the
// hovered row's own payload (built in MiniBarChart below) rather than off
// recharts' per-Bar payload entries, so a null segment for this period
// reliably reads "--" instead of being silently dropped from the list.
// Deliberately typed with a small local interface instead of recharts'
// own tooltip-content prop types (TooltipContentProps requires fields
// recharts only ever supplies at runtime via prop-injection into a
// content element, not fields this component itself needs to declare).
function StackedTooltipContent({ active, payload, segments, valueFormat }: StackedTooltipContentProps) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload as Record<string, number | string | null> | undefined;
  if (!row) return null;

  const total = segments.reduce((sum, s) => {
    const v = row[s.key];
    return sum + (typeof v === "number" ? v : 0);
  }, 0);

  return (
    <div className="grid min-w-36 gap-1.5 rounded-none border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl">
      <div className="grid gap-1">
        {segments.map((s) => {
          const v = row[s.key];
          return (
            <div key={s.key} className="flex w-full items-center gap-2">
              <div className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: s.color }} />
              <div className="flex flex-1 items-center justify-between gap-3">
                <span className="text-muted-foreground">{s.label}</span>
                <span className="font-mono font-semibold tabular-nums text-text-primary">
                  {typeof v === "number" ? valueFormat(v) : "—"}
                </span>
              </div>
            </div>
          );
        })}
        <div className="mt-0.5 flex items-center justify-between gap-3 border-t border-border/50 pt-1">
          <span className="text-muted-foreground">Total</span>
          <span className="font-mono font-semibold tabular-nums text-text-primary">{valueFormat(total)}</span>
        </div>
      </div>
    </div>
  );
}

// Single-series/stacked preview bar chart for the Financials tab's
// "Historical Trends" grid -- multiple of these render at once, so it's
// kept deliberately minimal (no gridlines or ticks) unlike the full-size
// charts elsewhere in the app. A hover tooltip (period + formatted value,
// or one row per segment + total in stacked mode) is the only way to read
// an exact figure off a given bar, since there's no axis.
export function MiniBarChart({
  categories,
  values,
  segments,
  valueFormat,
  color = "var(--color-brand)",
  height = 64,
  barCategoryGap = "10%",
}: Props) {
  const isStacked = !!segments && segments.length > 0;

  const chartData = categories.map((cat, i) => {
    if (isStacked) {
      const row: Record<string, string | number | null> = { category: cat };
      for (const s of segments!) row[s.key] = s.values[i] ?? null;
      return row;
    }
    return { category: cat, value: values?.[i] ?? null };
  });

  const nums = isStacked
    ? categories.map((_, i) => segments!.reduce((sum, s) => sum + (s.values[i] ?? 0), 0))
    : (values ?? []).filter((v): v is number => v != null);
  const yTicks = computeNiceTicksRange(Math.min(0, ...nums, 0), Math.max(0, ...nums, 0));
  const domain: [number, number] = [yTicks[0] ?? 0, yTicks[yTicks.length - 1] ?? 1];

  const chartConfig: ChartConfig = isStacked
    ? Object.fromEntries(segments!.map((s) => [s.key, { label: s.label, color: s.color }]))
    : { value: { label: "Value", color } };

  return (
    <ChartContainer config={chartConfig} className="aspect-auto w-full" style={{ height }} role="img" aria-label="Historical trend">
      <BarChart data={chartData} barCategoryGap={barCategoryGap}>
        {/* No dataKey on YAxis needed, but XAxis's dataKey is what lets
            Recharts resolve the tooltip's `label` to the period string --
            without it (chart previously had no XAxis at all), the tooltip
            fell back to the series config's own "Value" label instead. */}
        <XAxis dataKey="category" hide />
        <YAxis domain={domain} hide />
        {valueFormat && isStacked && (
          <ChartTooltip cursor={false} content={<StackedTooltipContent segments={segments!} valueFormat={valueFormat} />} />
        )}
        {valueFormat && !isStacked && (
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value) => (
                  <span className="font-mono font-semibold tabular-nums text-text-primary">{valueFormat(Number(value))}</span>
                )}
              />
            }
          />
        )}
        {isStacked
          ? segments!.map((s) => <Bar key={s.key} dataKey={s.key} stackId="segments" fill={s.color} radius={1} isAnimationActive={false} />)
          : <Bar dataKey="value" fill={color} radius={1} isAnimationActive={false} />}
      </BarChart>
    </ChartContainer>
  );
}

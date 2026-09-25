"use client";

import { useState } from "react";
import { Bar, BarChart, Brush, CartesianGrid, Cell, Line, LineChart, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts";

import { ChartLegend } from "@/components/charts/ChartLegend";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import type { MarketBreadthPointOut } from "@/lib/api/types";
import { fmtEventDate } from "@/lib/chartEventMarkers";
import { capXAxisTickInterval, computeNiceTicksRange } from "@/lib/charts";
import { defaultWindowStart, firstLiveIndex, fmtAxisMonth, fmtBreadthPct, fmtSignedCount } from "@/lib/marketBreadth";
import { cn } from "@/lib/utils";

interface Props {
  // Oldest first, as served.
  series: MarketBreadthPointOut[];
}

// chart-1 (green): the 50-day is chart-4 (blue) and the 200-day chart-2 (amber). Red (chart-3) is the app's
// "negative" hue and purple (chart-5) is too close to the blue to tell apart, so neither is used here.
const SMA20_COLOR = "var(--color-chart-1)";
const SMA50_COLOR = "var(--color-chart-4)";
const SMA200_COLOR = "var(--color-chart-2)";
const GRID_COLOR = "var(--color-border-subtle)";
const TICK = { fill: "var(--color-text-tertiary)", fontSize: 10 };
// Same left gutter on both panels so their time axes line up.
const Y_AXIS_WIDTH = 36;
const PCT_TICKS = [0, 25, 50, 75, 100];
const CHART_HEIGHT = 240;
const SYNC_ID = "market-breadth";

const config: ChartConfig = {
  pct_above_sma20: { label: "Above 20-day SMA", color: SMA20_COLOR },
  pct_above_sma50: { label: "Above 50-day SMA", color: SMA50_COLOR },
  pct_above_sma200: { label: "Above 200-day SMA", color: SMA200_COLOR },
  net_new_highs: { label: "Net new 52-week highs" },
};

// The tooltip body is shared by both panels -- `kind` picks which figures lead. Anything that qualifies a
// reading (a backfilled session, constituents left out of every count) is shown here rather than hidden.
interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: MarketBreadthPointOut }>;
  kind?: "pct" | "net";
}

function BreadthTooltip({ active, payload, kind }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;

  return (
    <div className="grid min-w-44 gap-1.5 rounded-none border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium text-text-primary">{fmtEventDate(point.as_of_date)}</div>
      {kind === "pct" ? (
        <>
          <TooltipRow
            color={SMA20_COLOR}
            label="Above 20-day"
            value={fmtBreadthPct(point.pct_above_sma20)}
            note={point.sma20_eligible == null ? undefined : `${point.sma20_above} of ${point.sma20_eligible}`}
          />
          <TooltipRow color={SMA50_COLOR} label="Above 50-day" value={fmtBreadthPct(point.pct_above_sma50)} note={`${point.sma50_above} of ${point.sma50_eligible}`} />
          <TooltipRow color={SMA200_COLOR} label="Above 200-day" value={fmtBreadthPct(point.pct_above_sma200)} note={`${point.sma200_above} of ${point.sma200_eligible}`} />
        </>
      ) : (
        <>
          <TooltipRow
            color={point.net_new_highs >= 0 ? "var(--color-positive)" : "var(--color-negative)"}
            label="Net new highs"
            value={fmtSignedCount(point.net_new_highs)}
          />
          <TooltipRow label="52-week highs" value={String(point.new_highs)} />
          <TooltipRow label="52-week lows" value={String(point.new_lows)} note={`of ${point.hl_eligible}`} />
        </>
      )}
      {point.stale_excluded > 0 && <div className="text-text-tertiary">{point.stale_excluded} without a bar, excluded</div>}
      {point.is_backfilled && <div className="text-text-tertiary">Backfilled · today&apos;s constituents</div>}
    </div>
  );
}

function TooltipRow({ color, label, value, note }: { color?: string; label: string; value: string; note?: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="size-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: color ?? "transparent" }} />
      <span className="text-text-secondary">{label}</span>
      <span className="ml-auto pl-3 font-mono font-semibold tabular-nums text-text-primary">{value}</span>
      {note && <span className="font-mono tabular-nums text-text-tertiary">{note}</span>}
    </div>
  );
}

function Panel({ title, subtitle, className, children }: { title: string; subtitle?: string; className?: string; children: React.ReactNode }) {
  return (
    <section className={cn("space-y-3 rounded-lg border border-border-card bg-surface p-6", className)}>
      <div>
        <h2 className="text-sm font-medium text-text-primary">{title}</h2>
        {subtitle && <p className="text-xs text-text-tertiary">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

// Two panels, never one shared axis: the three SMA lines are percentages (0-100) while net new highs is a
// signed count, and a dual-axis chart would let either one masquerade as the other's scale. `syncId` links
// the hover across both so one date reads across the whole page.
//
// Opens on the trailing year; the Brush under the SMA panel pans (drag the slide) or resizes the window over
// the full history. Keyed by the series' first date so switching universe resets to that universe's own year.
export function MarketBreadthCharts({ series }: Props) {
  return <BreadthChartsInner key={series[0]?.as_of_date ?? "empty"} series={series} />;
}

function BreadthChartsInner({ series }: Props) {
  const [range, setRange] = useState<{ start: number; end: number } | null>(null);
  const last = Math.max(0, series.length - 1);
  const start = Math.min(range?.start ?? defaultWindowStart(series), last);
  const end = Math.min(range?.end ?? last, last);
  const visible = series.slice(start, end + 1);

  const liveAt = firstLiveIndex(series);
  // Only a boundary worth marking when there IS a backfilled past before the first live session.
  const boundaryDate = liveAt > 0 ? series[liveAt].as_of_date : null;
  const tickInterval = capXAxisTickInterval(visible.length, 8);

  const nets = series.map((p) => p.net_new_highs);
  const netTicks = computeNiceTicksRange(Math.min(0, ...nets), Math.max(0, ...nets));
  const netDomain: [number, number] = [netTicks[0] ?? 0, netTicks[netTicks.length - 1] ?? 1];

  const xAxis = (
    <XAxis
      dataKey="as_of_date"
      tickLine={false}
      axisLine={false}
      interval={tickInterval}
      tickFormatter={fmtAxisMonth}
      tick={TICK}
    />
  );
  const boundary = boundaryDate && boundaryDate >= (visible[0]?.as_of_date ?? "") && (
    <ReferenceLine
      x={boundaryDate}
      stroke="var(--color-text-tertiary)"
      strokeDasharray="2 3"
      label={{ value: "Live →", position: "insideTopRight", fill: "var(--color-text-tertiary)", fontSize: 10 }}
    />
  );

  return (
    <div className="space-y-4">
      <Panel title="Constituents above their moving average" subtitle="% of S&P 500 stocks closing above their own 20-, 50- and 200-day SMA">
        <ChartContainer config={config} className="aspect-auto w-full" style={{ height: CHART_HEIGHT }} role="img" aria-label="Percent of S&P 500 constituents above their 20-day, 50-day and 200-day moving averages over time">
          <LineChart data={series} syncId={SYNC_ID} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID_COLOR} />
            {xAxis}
            <YAxis domain={[0, 100]} ticks={PCT_TICKS} width={Y_AXIS_WIDTH} tickLine={false} axisLine={false} tick={TICK} tickFormatter={(v: number) => `${v}%`} />
            <ReferenceLine y={50} stroke="var(--color-text-tertiary)" strokeDasharray="4 4" />
            {boundary}
            <Tooltip cursor={{ stroke: "var(--color-text-tertiary)", strokeWidth: 1 }} content={<BreadthTooltip kind="pct" />} isAnimationActive={false} />
            <Line type="monotone" dataKey="pct_above_sma200" stroke={SMA200_COLOR} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="pct_above_sma50" stroke={SMA50_COLOR} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="pct_above_sma20" stroke={SMA20_COLOR} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} />
            <Brush
              dataKey="as_of_date"
              height={24}
              startIndex={start}
              endIndex={end}
              onChange={(r) => {
                if (r.startIndex != null && r.endIndex != null) setRange({ start: r.startIndex, end: r.endIndex });
              }}
              tickFormatter={fmtAxisMonth}
              stroke="var(--color-text-tertiary)"
              fill="transparent"
            />
          </LineChart>
        </ChartContainer>
        <ChartLegend
          items={[
            { key: "sma20", label: "Above 20-day SMA", color: SMA20_COLOR },
            { key: "sma50", label: "Above 50-day SMA", color: SMA50_COLOR },
            { key: "sma200", label: "Above 200-day SMA", color: SMA200_COLOR },
          ]}
        />
      </Panel>

      <Panel title="Net new 52-week highs" subtitle="Stocks at a new 52-week high minus stocks at a new 52-week low (intraday), per session">
        <ChartContainer config={config} className="aspect-auto w-full" style={{ height: CHART_HEIGHT }} role="img" aria-label="Net new 52-week highs minus lows for S&P 500 constituents over time">
          <BarChart data={visible} syncId={SYNC_ID} barCategoryGap="10%" margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={GRID_COLOR} />
            {xAxis}
            <YAxis domain={netDomain} ticks={netTicks} width={Y_AXIS_WIDTH} tickLine={false} axisLine={false} tick={TICK} />
            <ReferenceLine y={0} stroke="var(--color-text-tertiary)" />
            {boundary}
            <Tooltip cursor={{ fill: "var(--color-text-tertiary)", fillOpacity: 0.12 }} content={<BreadthTooltip kind="net" />} isAnimationActive={false} />
            <Bar dataKey="net_new_highs" isAnimationActive={false}>
              {series.map((p) => (
                <Cell key={p.as_of_date} fill={p.net_new_highs >= 0 ? "var(--color-positive)" : "var(--color-negative)"} />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </Panel>
    </div>
  );
}

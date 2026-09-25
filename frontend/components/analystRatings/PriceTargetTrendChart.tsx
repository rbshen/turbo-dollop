"use client";

import { useState } from "react";
import { Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts";

import { RechartsAreaChart } from "@/components/charts/RechartsAreaChart";
import { ChartLegend } from "@/components/charts/ChartLegend";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { RatingHistoryPoint } from "@/lib/api/types";
import { capXAxisTickInterval, computeNiceTicksRange } from "@/lib/charts";
import { fmtMoney } from "@/lib/format";

interface Props {
  history: RatingHistoryPoint[];
  currency?: string;
}

// Target-consensus line color -- unchanged from before this overlay existed
// (RechartsAreaChart's own default). The overlay uses chart-1 (green),
// already validated against this exact blue (chart-4/brand) as an adjacent
// pair on the dark surface -- see CLAUDE.md's Market Breadth entry, which
// ran the dataviz palette validator for this same chart-1/chart-4 pairing.
const TARGET_COLOR = "var(--color-brand)";
const PRICE_COLOR = "var(--color-chart-1)";

// The target line is drawn as two series split by methodology (never joined,
// so the seam reads as a definition change rather than a market move):
// legacy = dashed, live = solid, same hue.
export const LEGACY = "legacy_all_analysts";
export const LIVE = "live_consensus";

const CHART_CONFIG: ChartConfig = {
  targetLegacy: { label: "Avg. Price Target (all analysts)", color: TARGET_COLOR },
  targetLive: { label: "Price Target (live consensus)", color: TARGET_COLOR },
  price: { label: "Stock Price", color: PRICE_COLOR },
};

// "Average Price Target Trend" -- one x (period) to one y (avg_price_target)
// value per point, rendered as a smooth line + gradient-area chart. An
// optional toggle overlays the actual closing price on the same $ axis
// (never a second/dual axis -- both series are already the same unit).
export function PriceTargetTrendChart({ history, currency = "USD" }: Props) {
  const [showPriceOverlay, setShowPriceOverlay] = useState(false);

  const hasPriceTargetHistory = history.some((point) => point.avg_price_target != null);
  // The toggle itself is only ever rendered when there's at least one point
  // where the price overlay actually has something to show -- e.g. a
  // delisted ticker (Yahoo has nothing at all) or one where the only Yahoo
  // data available doesn't land on/before any plotted date. No separate
  // check/request needed: this falls straight out of the one field already
  // returned by the same request this chart already consumes.
  // Only when BOTH methodologies are present is there a seam to mark; a
  // single-methodology history keeps the original smooth area chart.
  const hasSplit = history.some((p) => p.methodology === LEGACY) && history.some((p) => p.methodology === LIVE);
  const hasPriceOverlay = history.some((point) => point.price_on_date != null);

  if (!hasPriceTargetHistory) {
    return (
      <p className="text-sm text-text-tertiary">
        Price target history hasn&apos;t accumulated yet — this fills in as the daily snapshot job runs.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {hasPriceOverlay && (
        <div className="flex justify-end">
          <button
            onClick={() => setShowPriceOverlay((v) => !v)}
            aria-pressed={showPriceOverlay}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              showPriceOverlay ? "bg-zinc-700 text-zinc-100" : "text-text-tertiary hover:text-text-secondary hover:bg-surface-2"
            }`}
          >
            Overlay stock price
          </button>
        </div>
      )}
      {(showPriceOverlay && hasPriceOverlay) || hasSplit ? (
        <TargetLineChart history={history} currency={currency} showPrice={showPriceOverlay && hasPriceOverlay} />
      ) : (
        <RechartsAreaChart
          categories={history.map((point) => point.date.slice(0, 7))}
          values={history.map((point) => point.avg_price_target)}
          valueFormat={(v) => fmtMoney(v, currency)}
          height={216}
        />
      )}
      {hasSplit && <MethodologyNote />}
    </div>
  );
}

function MethodologyNote() {
  return (
    <p className="text-xs text-text-tertiary" data-testid="methodology-note">
      <span className="font-medium text-text-secondary">Dashed line:</span> historical average of every analyst price target since 2021 (no
      recency cutoff). <span className="font-medium text-text-secondary">Solid line:</span> live consensus from daily snapshots, which
      reflects only recent analyst activity (about the last 6 months). The two are defined differently, so a step where they meet is a
      methodology change, not a market move.
    </p>
  );
}

function TargetLineChart({ history, currency, showPrice }: { history: RatingHistoryPoint[]; currency: string; showPrice: boolean }) {
  const categories = history.map((point) => point.date.slice(0, 7));
  const chartData = history.map((point, i) => ({
    category: categories[i],
    targetLegacy: point.methodology === LIVE ? null : point.avg_price_target,
    targetLive: point.methodology === LIVE ? point.avg_price_target : null,
    price: showPrice ? point.price_on_date : null,
  }));

  const targetValues = history.map((p) => p.avg_price_target).filter((v): v is number => v != null);
  const priceValues = (showPrice ? history : []).map((p) => p.price_on_date).filter((v): v is number => v != null);
  const allValues = [...targetValues, ...priceValues];
  const yTicks = computeNiceTicksRange(Math.min(0, ...allValues, 0), Math.max(0, ...allValues, 0));
  const domain: [number, number] = [yTicks[0] ?? 0, yTicks[yTicks.length - 1] ?? 1];

  // The price line only ever starts at or after the target line's own
  // first real point (see RatingHistoryPoint.price_on_date's own comment)
  // -- if it starts LATER, Yahoo's history didn't reach back as far as the
  // target series does, and that gap is marked here rather than left to be
  // silently read as "the two lines just happen to line up".
  const hasLive = history.some((p) => p.avg_price_target != null && p.methodology === LIVE);
  const hasLegacy = history.some((p) => p.avg_price_target != null && p.methodology !== LIVE);
  const targetStart = history.findIndex((p) => p.avg_price_target != null);
  const priceStart = history.findIndex((p) => p.price_on_date != null);
  const showPriceStartMarker = showPrice && priceStart > targetStart;

  return (
    <div className="space-y-3">
      <ChartContainer config={CHART_CONFIG} className="aspect-auto w-full" style={{ height: 216 }} role="img" aria-label="Price target trend vs. stock price chart">
        <LineChart data={chartData}>
          <XAxis
            dataKey="category"
            tickLine={false}
            axisLine={false}
            interval={capXAxisTickInterval(categories.length)}
            tick={{ fill: "var(--color-text-tertiary)", fontSize: 10 }}
          />
          <YAxis domain={domain} ticks={yTicks} hide />
          {showPriceStartMarker && (
            <ReferenceLine
              x={categories[priceStart]}
              stroke="var(--color-text-tertiary)"
              strokeDasharray="2 3"
              label={{ value: "Price data starts →", position: "insideTopLeft", fill: "var(--color-text-tertiary)", fontSize: 10 }}
            />
          )}
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value, name) => (
                  <div className="flex w-full flex-1 items-center gap-2">
                    <div className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: CHART_CONFIG[name as string]?.color }} />
                    <div className="flex flex-1 items-center justify-between gap-4">
                      <span className="text-muted-foreground">{CHART_CONFIG[name as string]?.label ?? name}</span>
                      <span className="font-mono font-semibold tabular-nums text-text-primary">{fmtMoney(Number(value), currency)}</span>
                    </div>
                  </div>
                )}
              />
            }
          />
          {hasLegacy && (
            <Line
              type="monotone"
              dataKey="targetLegacy"
              stroke={TARGET_COLOR}
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          )}
          {hasLive && (
            <Line
              type="monotone"
              dataKey="targetLive"
              stroke={TARGET_COLOR}
              strokeWidth={2}
              dot={{ r: 2, strokeWidth: 0, fill: TARGET_COLOR }}
              activeDot={{ r: 4, strokeWidth: 0 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          )}
          {showPrice && (
            <Line
              type="monotone"
              dataKey="price"
              stroke={PRICE_COLOR}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              connectNulls={false}
              isAnimationActive={false}
            />
        
          )}
        </LineChart>
      </ChartContainer>
      <ChartLegend
        items={[
          { key: "target", label: "Avg. Price Target", color: TARGET_COLOR },
          ...(showPrice ? [{ key: "price", label: "Stock Price", color: PRICE_COLOR }] : []),
        ]}
      />
    </div>
  );
}

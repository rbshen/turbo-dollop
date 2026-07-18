"use client";

import { useState } from "react";

import { BAR_GAP, BAR_WIDTH, DEFAULT_GROUP_GAP } from "@/lib/charts";

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
}

interface Props {
  categories: string[];
  series: ChartSeries[];
  values: Record<string, (number | null)[]>;
  mode: "bar" | "line";
  yTicks: number[];
  yTickFormat: (v: number) => string;
  height?: number;
  /** The chart's actual measured container width (full width, including axis
   * margins) — the SVG stretches to exactly this by adjusting the gap
   * between groups, never the bar width itself (which stays fixed at
   * BAR_WIDTH regardless of series count, per spec). Falls back to a fixed
   * default gap if omitted or not yet measured (0). */
  containerWidth?: number;
}

const MARGIN = { top: 12, right: 16, bottom: 24, left: 56 };

export function GroupedBarLineChart({
  categories,
  series,
  values,
  mode,
  yTicks,
  yTickFormat,
  height = 216,
  containerWidth,
}: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  const groupWidth = series.length * BAR_WIDTH + Math.max(0, series.length - 1) * BAR_GAP;
  const groupCount = categories.length;
  const hasMeasuredWidth = containerWidth != null && containerWidth > 0;
  const plotWidth = hasMeasuredWidth
    ? Math.max(0, containerWidth - MARGIN.left - MARGIN.right)
    : groupCount * groupWidth + Math.max(0, groupCount - 1) * DEFAULT_GROUP_GAP;
  const groupGap =
    hasMeasuredWidth && groupCount > 1 ? Math.max(0, (plotWidth - groupCount * groupWidth) / (groupCount - 1)) : DEFAULT_GROUP_GAP;
  const plotHeight = height;
  const svgWidth = plotWidth + MARGIN.left + MARGIN.right;
  const svgHeight = plotHeight + MARGIN.top + MARGIN.bottom;
  const scaleMax = yTicks[yTicks.length - 1] || 1;

  const yFor = (v: number) => plotHeight - (v / scaleMax) * plotHeight;
  const groupX = (categoryIndex: number) => categoryIndex * (groupWidth + groupGap);

  return (
    <div className="overflow-x-auto">
      <svg width={svgWidth} height={svgHeight} role="img" aria-label="Financial trend chart">
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {yTicks.map((tick) => (
            <g key={tick}>
              <line
                x1={0}
                x2={plotWidth}
                y1={yFor(tick)}
                y2={yFor(tick)}
                stroke="currentColor"
                className="text-zinc-800"
                strokeWidth={1}
              />
              <text x={-8} y={yFor(tick)} textAnchor="end" dominantBaseline="middle" className="fill-zinc-500 text-[10px]">
                {yTickFormat(tick)}
              </text>
            </g>
          ))}

          {mode === "bar"
            ? categories.map((cat, ci) =>
                series.map((s, si) => {
                  const v = values[s.key]?.[ci];
                  if (v == null) return null;
                  const x = groupX(ci) + si * (BAR_WIDTH + BAR_GAP);
                  const y = yFor(Math.max(v, 0));
                  const barHeight = Math.abs(yFor(v) - yFor(0));
                  const opacity = hovered === null || hovered === s.key ? 1 : 0.25;
                  return (
                    <rect
                      key={`${cat}-${s.key}`}
                      x={x}
                      y={y}
                      width={BAR_WIDTH}
                      height={Math.max(barHeight, 0)}
                      fill={s.color}
                      opacity={opacity}
                      rx={2}
                      onMouseEnter={() => setHovered(s.key)}
                      onMouseLeave={() => setHovered(null)}
                    >
                      <title>{`${s.label} — ${cat}: ${yTickFormat(v)}`}</title>
                    </rect>
                  );
                })
              )
            : series.map((s) => {
                const linePoints = categories
                  .map((cat, ci) => {
                    const v = values[s.key]?.[ci];
                    if (v == null) return null;
                    return `${groupX(ci) + groupWidth / 2},${yFor(v)}`;
                  })
                  .filter((p): p is string => p != null)
                  .join(" ");
                const opacity = hovered === null || hovered === s.key ? 1 : 0.25;
                return (
                  <g key={s.key}>
                    {/* Invisible fat hit-area: a 2px visible stroke is too thin to hover reliably. */}
                    <polyline
                      points={linePoints}
                      fill="none"
                      stroke="transparent"
                      strokeWidth={16}
                      onMouseEnter={() => setHovered(s.key)}
                      onMouseLeave={() => setHovered(null)}
                    />
                    <polyline
                      points={linePoints}
                      fill="none"
                      stroke={s.color}
                      strokeWidth={2}
                      opacity={opacity}
                      className="pointer-events-none"
                    />
                    {categories.map((cat, ci) => {
                      const v = values[s.key]?.[ci];
                      if (v == null) return null;
                      return (
                        <circle
                          key={`${s.key}-${cat}`}
                          cx={groupX(ci) + groupWidth / 2}
                          cy={yFor(v)}
                          r={3}
                          fill={s.color}
                          opacity={opacity}
                          onMouseEnter={() => setHovered(s.key)}
                          onMouseLeave={() => setHovered(null)}
                        >
                          <title>{`${s.label} — ${cat}: ${yTickFormat(v)}`}</title>
                        </circle>
                      );
                    })}
                  </g>
                );
              })}

          {categories.map((cat, ci) => (
            <text
              key={cat}
              x={groupX(ci) + groupWidth / 2}
              y={plotHeight + 16}
              textAnchor="middle"
              className="fill-zinc-500 text-[10px]"
            >
              {cat}
            </text>
          ))}
        </g>
      </svg>
    </div>
  );
}

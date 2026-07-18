"use client";

import { useState } from "react";

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
}

const BAR_WIDTH = 14;
const BAR_GAP = 3;
const GROUP_GAP = 20;
const MARGIN = { top: 12, right: 16, bottom: 24, left: 56 };

export function GroupedBarLineChart({ categories, series, values, mode, yTicks, yTickFormat, height = 240 }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  const groupWidth = series.length * BAR_WIDTH + Math.max(0, series.length - 1) * BAR_GAP;
  const plotWidth = categories.length * groupWidth + Math.max(0, categories.length - 1) * GROUP_GAP;
  const plotHeight = height;
  const svgWidth = plotWidth + MARGIN.left + MARGIN.right;
  const svgHeight = plotHeight + MARGIN.top + MARGIN.bottom;
  const scaleMax = yTicks[yTicks.length - 1] || 1;

  const yFor = (v: number) => plotHeight - (v / scaleMax) * plotHeight;
  const groupX = (categoryIndex: number) => categoryIndex * (groupWidth + GROUP_GAP);

  return (
    <div className="space-y-2">
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
                    const barKey = `${cat}-${s.key}`;
                    const x = groupX(ci) + si * (BAR_WIDTH + BAR_GAP);
                    const y = yFor(Math.max(v, 0));
                    const barHeight = Math.abs(yFor(v) - yFor(0));
                    const opacity = hovered === null || hovered === barKey ? 1 : 0.25;
                    return (
                      <rect
                        key={barKey}
                        x={x}
                        y={y}
                        width={BAR_WIDTH}
                        height={Math.max(barHeight, 0)}
                        fill={s.color}
                        opacity={opacity}
                        rx={2}
                        onMouseEnter={() => setHovered(barKey)}
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
                      <polyline points={linePoints} fill="none" stroke={s.color} strokeWidth={2} opacity={opacity} />
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
      <div className="flex flex-wrap gap-3">
        {series.map((s) => (
          <div key={s.key} className="flex items-center gap-1.5 text-xs text-zinc-400">
            <span className="inline-block size-2.5 rounded-full" style={{ backgroundColor: s.color }} />
            {s.label}
          </div>
        ))}
      </div>
    </div>
  );
}

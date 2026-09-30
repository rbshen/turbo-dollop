import type { ChartBarOut, ChartStagePointOut } from "@/lib/api/types";

// Candle colors for the Chart tab's W/4Y "Stage" toggle. Stage 1 Basing / 2 Advance / 3 Top / 4 Decline.
// Legacy/fallback palette -- TickerChart.tsx passes the live-resolved --fathom-stage-* tokens (see
// lib/chartTokens.ts::readChartColors) as buildStageColoredBars' own `palette` argument; this constant is only
// what it falls back to when none is given (this file's own tests, and any other caller with no design-system
// tokens to resolve).
export const WEINSTEIN_STAGE_CANDLE_COLORS: Record<ChartStagePointOut["stage"], string> = {
  base: "#8FD99F",
  advance: "#1B9E3E",
  top: "#E8A020",
  decline: "#E03A3A",
};

// Pure white -- no named design-system token exists for this line (see this session's report), so it stays a
// raw literal by deliberate exception rather than reading from lib/chartTokens.ts.
export const WEINSTEIN_MA_COLOR = "#FFFFFF";

// Bars with per-candle stage colors (body, wick and border). A week with no stage yet (state machine not seeded)
// keeps the chart's default up/down color -- no color keys are set for it.
export type StageColoredBar = ChartBarOut & { color?: string; wickColor?: string; borderColor?: string };

export function buildStageColoredBars(
  bars: ChartBarOut[],
  stages: ChartStagePointOut[],
  palette: Record<ChartStagePointOut["stage"], string> = WEINSTEIN_STAGE_CANDLE_COLORS
): StageColoredBar[] {
  const byTime = new Map(stages.map((s) => [s.time, s.stage]));
  return bars.map((bar) => {
    const stage = byTime.get(bar.time);
    if (!stage) return bar;
    const color = palette[stage];
    return { ...bar, color, wickColor: color, borderColor: color };
  });
}

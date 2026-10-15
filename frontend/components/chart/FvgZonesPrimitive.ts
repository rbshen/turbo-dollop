import type { IChartApi, ISeriesApi, ISeriesPrimitive, IPrimitivePaneRenderer, IPrimitivePaneView, Logical, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import { FVG_EDGE_ALPHA, FVG_FILL_ALPHA, fvgRect, fvgSpan, withAlpha } from "@/lib/chartFvg";
import type { ChartFvgOut } from "@/lib/api/types";

// Draws the Chart tab's fair value gap zones (D·6M): a filled rectangle plus dashed 1px top and bottom edge lines per zone,
// behind the candles (zOrder "bottom"), on the price pane only (attached to the candle series). X comes from
// logicalToCoordinate at the bar EDGES (center +-0.5), y from priceToCoordinate; a zone with a null coordinate is skipped.
// It has no autoscaleInfo, so it never changes the price scale. Overlapping zones are all drawn, no merging.

export interface FvgColors {
  bullish: string;
  bearish: string;
}

export class FvgZonesPrimitive implements ISeriesPrimitive<Time> {
  private zones: ChartFvgOut[] = [];
  private barTimes: string[] = [];
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private requestUpdate: (() => void) | null = null;

  constructor(private colors: FvgColors) {}

  private readonly view: IPrimitivePaneView = {
    zOrder: () => "bottom",
    renderer: (): IPrimitivePaneRenderer | null => ({
      draw: (target) => {
        target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hpr, verticalPixelRatio: vpr }) => {
          const chart = this.chart;
          const series = this.series;
          if (!chart || !series || this.zones.length === 0) return;
          const timeScale = chart.timeScale();
          const lineWidth = Math.max(1, Math.round(vpr));
          ctx.lineWidth = lineWidth;
          ctx.setLineDash([4 * hpr, 3 * hpr]);
          for (const zone of this.zones) {
            const span = fvgSpan(zone, this.barTimes);
            if (!span) continue;
            const rect = fvgRect(
              timeScale.logicalToCoordinate(span.left as Logical),
              timeScale.logicalToCoordinate(span.right as Logical),
              series.priceToCoordinate(zone.top),
              series.priceToCoordinate(zone.bottom)
            );
            if (!rect) continue;
            const base = zone.side === "bullish" ? this.colors.bullish : this.colors.bearish;
            const x = Math.round(rect.x * hpr);
            const w = Math.max(1, Math.round(rect.width * hpr));
            const top = Math.round(rect.y * vpr);
            const bottom = Math.round((rect.y + rect.height) * vpr);
            ctx.fillStyle = withAlpha(base, FVG_FILL_ALPHA);
            ctx.fillRect(x, top, w, Math.max(1, bottom - top));
            ctx.strokeStyle = withAlpha(base, FVG_EDGE_ALPHA);
            const offset = lineWidth % 2 === 1 ? 0.5 : 0;
            ctx.beginPath();
            ctx.moveTo(x, top + offset);
            ctx.lineTo(x + w, top + offset);
            ctx.moveTo(x, bottom + offset);
            ctx.lineTo(x + w, bottom + offset);
            ctx.stroke();
          }
          ctx.setLineDash([]);
        });
      },
    }),
  };

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
    param.requestUpdate();
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  /** `[]` hides every zone (the toggle off). `barTimes` are the chart's bar times, oldest first. */
  setZones(zones: ChartFvgOut[], barTimes: string[]): void {
    this.zones = zones;
    this.barTimes = barTimes;
    this.requestUpdate?.();
  }
}

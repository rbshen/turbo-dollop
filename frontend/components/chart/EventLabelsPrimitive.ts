import type { IChartApi, ISeriesPrimitive, IPrimitivePaneRenderer, IPrimitivePaneView, PrimitiveHoveredItem, SeriesAttachedParameter, Time } from "lightweight-charts";
import { eventLabelCenterY, EVENT_LABEL_FONT_PX, hitTestEventLabels } from "@/lib/chartEventMarkers";
import type { EventLabel } from "@/lib/chartEventMarkers";

// Draws the Chart tab's earnings ("E") / dividend ("D") letters on a fixed row along the price pane's floor.
// A series primitive rather than series markers -- see lib/chartEventMarkers.ts's header for why the built-in
// markers can't produce shape-less, fixed-row, larger letters.
//
// Draws in the pane's own media-pixel space, so the row's position comes from the pane's REAL height
// (`mediaSize.height`) and never from a price scale. One instance per label kind (each has its own toggle):
// `setLabels([])` hides it.

const FONT_FAMILY = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

interface Placed {
  id: string;
  x: number;
  y: number;
}

export class EventLabelsPrimitive implements ISeriesPrimitive<Time> {
  private labels: EventLabel[] = [];
  private chart: IChartApi | null = null;
  private requestUpdate: (() => void) | null = null;
  // Where the labels were last drawn, for hitTest. Recomputed on every draw, so it always matches the screen.
  private placed: Placed[] = [];

  private readonly view: IPrimitivePaneView = {
    // Above the candles and any series markers, so a letter is never hidden behind a candle or arrow.
    zOrder: () => "top",
    renderer: (): IPrimitivePaneRenderer | null => ({
      draw: (target) => {
        target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
          const chart = this.chart;
          const placed: Placed[] = [];
          if (chart && this.labels.length > 0) {
            const timeScale = chart.timeScale();
            ctx.font = `700 ${EVENT_LABEL_FONT_PX}px ${FONT_FAMILY}`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            for (const label of this.labels) {
              const x = timeScale.timeToCoordinate(label.time as Time);
              if (x === null || x < -EVENT_LABEL_FONT_PX || x > mediaSize.width + EVENT_LABEL_FONT_PX) continue;
              const y = eventLabelCenterY(mediaSize.height, label.stackSlot);
              ctx.fillStyle = label.color;
              ctx.fillText(label.text, x, y);
              placed.push({ id: label.id, x, y });
            }
          }
          this.placed = placed;
        });
      },
    }),
  };

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi;
    this.requestUpdate = param.requestUpdate;
    param.requestUpdate();
  }

  detached(): void {
    this.chart = null;
    this.requestUpdate = null;
    this.placed = [];
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    const id = hitTestEventLabels(this.placed, x, y);
    return id === null ? null : { externalId: id, zOrder: "top", hitTestPriority: 2, cursorStyle: "default" };
  }

  setLabels(labels: EventLabel[]): void {
    this.labels = labels;
    this.requestUpdate?.();
  }
}

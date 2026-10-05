import type { ISeriesApi, ISeriesPrimitive, ISeriesPrimitiveAxisView, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import { axisTagHeightPx, formatAxisPrice, nudgeTagYs } from "@/lib/chartAxis";

// Price-axis tags for reference lines that sit so close together that their tags would overlap (the Warren RSI pane's
// 80.81 and 84.75, about 4 px apart). The lines themselves are ordinary dashed price lines at their true levels, drawn
// without a tag; this series primitive draws their tags instead, each at its line's y except where two would collide:
// then the upper tag is nudged up and the lower down by the minimum needed (lib/chartAxis.ts::nudgeTagYs). A tag is
// placed with fixedCoordinate, which the library never moves, so the nudge is exactly ours.
//
// y and text are read at draw time (updateAllViews runs before every draw), so the tags follow autoscale and panning.

export interface LevelTag {
  price: number;
  backColor: string;
  textColor: string;
}

export class LevelTagsPrimitive implements ISeriesPrimitive<Time> {
  private series: ISeriesApi<SeriesType> | null = null;
  private ys: (number | null)[];

  constructor(
    private readonly levels: LevelTag[],
    private readonly fontSize: () => number,
  ) {
    this.ys = levels.map(() => null);
    this.views = levels.map((level, i) => ({
      // Parked far off so automatic placement leaves no gap for it; the label is drawn at fixedCoordinate.
      coordinate: () => -1e6,
      fixedCoordinate: () => this.ys[i] ?? undefined,
      text: () => formatAxisPrice(level.price),
      textColor: () => level.textColor,
      backColor: () => level.backColor,
      visible: () => this.ys[i] !== null,
      tickVisible: () => false,
    }));
  }

  private readonly views: readonly ISeriesPrimitiveAxisView[];

  attached(param: SeriesAttachedParameter<Time>) {
    this.series = param.series;
  }

  detached() {
    this.series = null;
  }

  updateAllViews() {
    const series = this.series;
    if (!series) {
      this.ys = this.levels.map(() => null);
      return;
    }
    const height = series.getPane().getHeight();
    const tag = axisTagHeightPx(this.fontSize());
    this.ys = nudgeTagYs(
      this.levels.map((level) => series.priceToCoordinate(level.price)),
      tag,
      tag / 2,
      Math.max(tag / 2, height - tag / 2),
    );
  }

  priceAxisViews() {
    return this.views;
  }
}

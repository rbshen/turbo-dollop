import type { ISeriesApi, ISeriesPrimitive, ISeriesPrimitiveAxisView, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import { formatAxisPrice } from "@/lib/chartAxis";

// The one tick label of a "clean" Warren sub-pane (Axis option "Clean sub-pane axes"): the price at the vertical middle of
// the pane's visible price axis, drawn on the price axis at exactly that height. A series primitive's axis view rather than a
// regular tick, because the library only labels prices on its own 1/2/2.5/5 ladder, which seldom includes the midpoint.
//
// Both numbers are read at draw time (updateAllViews runs before every draw): y is half the pane's height and the text is the
// price the scale maps to that y, so the label follows autoscale and panning with no bookkeeping. Look is a plain tick label
// (page-colored box, no tick line), colors read live so the Brighter option applies.

export class PaneMidLabelPrimitive implements ISeriesPrimitive<Time> {
  private series: ISeriesApi<SeriesType> | null = null;
  private y = 0;
  private text = "";
  private shown = false;

  constructor(
    private readonly textColor: () => string,
    private readonly backColor: () => string,
  ) {}

  private readonly views: readonly ISeriesPrimitiveAxisView[] = [
    {
      // The label is placed with fixedCoordinate (exact, never nudged); coordinate() is parked far off so automatic
      // placement leaves no gap for it.
      coordinate: () => -1e6,
      fixedCoordinate: () => this.y,
      text: () => this.text,
      textColor: () => this.textColor(),
      backColor: () => this.backColor(),
      visible: () => this.shown,
      tickVisible: () => false,
    },
  ];

  attached(param: SeriesAttachedParameter<Time>) {
    this.series = param.series;
  }

  detached() {
    this.series = null;
  }

  updateAllViews() {
    const series = this.series;
    const height = series ? series.getPane().getHeight() : 0;
    const price = series && height > 0 ? series.coordinateToPrice(height / 2) : null;
    this.shown = price !== null;
    if (price !== null) {
      this.y = height / 2;
      this.text = formatAxisPrice(price);
    }
  }

  priceAxisViews() {
    return this.views;
  }
}

# Fathom Charts

How every chart is coloured, drawn and worded. Companion to `docs/design-system.md`. Decided from a read-only audit of the frontend (two chart libraries, no shared theme, four different greens, found during the design work).

## Two libraries, one set of rules

`lightweight-charts` draws the Chart tab only. `recharts` draws everything else. The rules below apply to both; only the way a token reaches the chart differs (a hex string for `lightweight-charts`, a CSS variable for `recharts`).

## Colour

| The job | Use |
| --- | --- |
| Chart tab candles, indicators, zones, signals, events, stages | The named tokens `chart-up`, `chart-down`, `chart-ema21`, `chart-sma50`, `chart-sma200`, `chart-stoch-k`, `chart-band`, `chart-refline`, `chart-zone-broken-support`, `chart-zone-broken-resistance`, `chart-warren-yellow`, `chart-warren-gray`, `chart-event-earnings`, `chart-event-dividend`, `stage-*`. Values are unchanged from before the redesign, except `chart-warren-yellow` (amber `#f59e0b` to pure yellow `#ffff00`, 2026-10-05); only the names are new. |
| Bars that show a direction (Breadth net new highs, Sector heatmap cells) | `positive` and `negative`. Never the candle pair. |
| A bar or line that is one series (Revenue, ROE, price target) | `series-1` (brand blue). |
| Several series that are not ordered by meaning | `series-1` to `series-5`, in order. Never `warn`, `positive`, `negative` or `brand` under another name. |
| Breadth 20, 50, 200-day lines | `series-3`, `series-2`, `series-1`. Draw order 200, 50, 20 so the most volatile line is on top. |
| P/E history (Ratios tab): stock, sector average, industry average | `series-1`, `series-2`, `series-3`, one shared P/E axis, the "data starts" dashed marker as on the price-target chart. |
| Recommendation Trend (Buy, Outperform, Hold, Underperform, Sell) | Sentiment colours as built: `positive`, `brand`, `warn`, `chart-purple`, `negative`. It is a scale, not a set of series. Unchanged. |
| Total Debt (long-term and short-term) | `series-1` and `chart-orange`. Orange stays reserved for the Debt chart. |

**Candle colours are not verdict colours.** `chart-up` and `chart-down` say the price moved. `positive` and `negative` say a company passed or failed. They stay separate so a rising candle can never read as a Pass.

**Negative bars.** In Historical Trends and Ratio Trends, a bar at or above zero is `series-1` and a bar below zero is `negative`. The rule is by sign only — it never says good or bad, because for CCC, Debt/EBITDA and receivables the higher value is the worse one.

## Getting a colour into the chart

`recharts` draws SVG, so it takes `var(--color-*)` strings and the browser resolves them. `lightweight-charts` draws on a canvas and only accepts plain colour strings. The 18 Chart tab data tokens are authored as hex, so `readChartColors()` reads them at mount. The four chrome tokens (`page`, `text-secondary`, `border-card`, `border-subtle`) are authored as `oklch()`, and Tailwind's build adds a `lab()` override that Safari picks — no browser API turns that back into the `rgb()` format the library requires. So for the canvas chart those four are fixed hex (`#080B11`, `#9499A0`, `#292E36`, `#20242B`) in `lib/chartTokens.ts`. This is safe because Fathom has one dark theme. **If the chrome tokens ever change, `lib/chartTokens.ts` must change with them** — it will not pick the change up automatically.

## Chrome, the same on every chart

- **Background** is `page`.
- **Axis text** `text-secondary`, 12px `figure-sm` mono. **Axis lines and pane separators** `border-card`.
- **Gridlines:** none. Trend bars have no axes at all.
- **Tooltip:** `surface` fill, `border-card` outline, `radius-md`, `shadow-popover`. Labels `text-secondary`, values `text-primary` in mono, always with a sign on a change (+1.26%, −7.49%).
- **Active range or toggle:** `surface-2` fill and `text-primary`, neutral and never brand blue. A choose-one range is a SegmentedControl; an independent overlay is a Switch, or an `outline` `sm` Button with `aria-pressed` where a row of them has no room for switches (the Chart tab's overlay toggles).
- **Legend:** `caption` in `text-secondary`, a 6px dot in the series colour. Non-interactive.

## States

| State | What shows |
| --- | --- |
| Loading | A `surface-2` block in the chart's own shape and height, pulsing. |
| Empty | A `caption` in `text-tertiary` ("No data for this period") inside the chart's own space. A trend tile with no data stays visible with this caption instead of vanishing. |
| Error | One short line in `negative`. |

## Not decided / left as built

Chart geometry (heights, bar gap, corner radius) stays as it was before the redesign: trend bars 64px (32px in the Watchlist), Analyst Ratings 216px, Chart tab 580px main pane and 100px sub-panes.

The Chart tab (candlestick) colour palette was deliberately kept as-is rather than redesigned — see `docs/decisions.md`. The 2H·90D range's three Warren sub-panes add no tokens: RSI `chart-band` (one color on this range; the daily RSI pane is red beyond 30/70), ADX `chart-ema21` (the ADX line alone; +DI/-DI are not plotted), WVF `chart-warren-yellow` (`#FFFF00`, TOS Color.YELLOW; the Warren yellow arrows share it. It was amber `#F59E0B`, which read orange; changed 2026-10-05), reference lines `chart-refline` (all dashed: the Warren thresholds; the classic 30/70 lines are not drawn). On every range the axis text is `#e5e8ec` (the text-primary hex) in the monospace face with a lower price-axis tick density, the sub-panes show no tick labels (only their level-line tags), and the signal arrows carry no text: `docs/specs/chart-tab.md`, "Axis options" and "Signal arrows".

## Dashboard primitives (2026-10-10)

Five small, dependency-free visuals for the Dashboard tab (`docs/specs/dashboard.md`), in `components/charts/`. They are plain `div`/`svg`, no recharts, no `lightweight-charts`, and every colour is a token (never a hex or an `oklch()` literal). **No tooltips**: every figure a visual encodes is also written beside it in text. Sentence case throughout; captions are 12px `text-tertiary`. Each has a `role="img"` and an `aria-label` that says the same thing as the visible text. Every state below is drawn in `/styleguide` ("Dashboard chart primitives"). Single-series bars on the tab still use `MiniBarChart` (thick bars, no axis, hover value); these primitives cover what a bar cannot.

| Primitive | Reads as | Props that matter |
| --- | --- | --- |
| `ThresholdGauge` | One ratio against its pass line and hard limit | `value`, `passLine`, `hardLimit`, `direction` (`ceiling`: lower is safer; `floor`: higher is safer), `format`, `notApplicable` |
| `DivergingBar` | A signed gap around zero, with an "in line" band | `value`, `band`, `scale`, `format`, `stockReturn`, `benchmarkReturn`, `benchmarkLabel` |
| `StageTimeline` | The last 12 months of Weinstein stage, week by week | `weeks`, `since`, `sinceIsLowerBound`, `unavailableReason` |
| `PriceRangeBar` | The price against the fair-value band (0.9x to 1.1x) | `price`, `fairValue`, `bandLow`, `bandHigh`, `unavailableReason` |
| `Sparkline` | A plain line, e.g. the 5-year price | `values`, `startLabel`, `endLabel`, `format` |

Plus one layout helper, `VisualRow`: label and pill on the left, the visual on the right; **below 36rem of its own width (the `sm` breakpoint of a full-width card) the pill and label stack above the visual**. It uses a container query, so it follows the width of the card, not the window.

### Colour rules

The colour of a visual is part of what it says, so the rules are strict:

1. **Neutral by default.** Fills, lines, ticks and tracks are `text-secondary`, `text-tertiary`, `surface-2` and `border-card`. A visual that has nothing to flag draws no colour at all.
2. **Amber only for a breach and for Flagged.** `ThresholdGauge` turns its fill `warn` only when the value is past the pass line, and tints the monitor zone (between the pass line and the hard limit) with `warn` at 20%. The Stuck-check "Flagged" tag is the other amber. Nothing else on the Dashboard is amber. It is the plain `warn` amber, never the `caution` of "Pass with caution", and never a verdict word.
3. **Green and red only on diverging bars and stage tones.** `DivergingBar` is `positive` ahead, `negative` behind, neutral inside the band. `StageTimeline` uses the same tone the `WeinsteinStagePill` uses (`WEINSTEIN_STAGE_TONE`: Advance `positive`, Top `warn`, Decline `negative`, Base neutral), so the strip and the header pill always agree. No other visual uses green or red; in particular `PriceRangeBar` draws undervalued / fair / overvalued in neutral and says it in words (the Valuation pill is the verdict).
4. **Brand blue is the one-series line.** `Sparkline` is `series-1`, like every single-series chart.
5. **Scored and context-not-scored stay visibly apart.** A scored step is drawn with its score and verdict pill beside the visual. The "Why might it be stuck?" visuals (row 8 `DivergingBar`, the margin and ROIC series) sit in their own section headed "Context, not scored", carry no pill and no verdict tone: their only colour is the diverging green/red on a gap, which says ahead or behind a benchmark and never pass or fail.

### Geometry and behaviour

- **ThresholdGauge.** An 8px track (`surface-2`, fully rounded), the fill from the left edge to the value, a 2px tick for each line, the value at the right in 12px mono tabular `text-primary`, and one caption line below in 12px `text-tertiary` naming the lines in words ("Passes at 3.0x or lower · hard limit 4.0x"). `ceiling` and `floor` differ only in which side of the line is safe (and so which side the amber zone sits on): the track always runs from 0 to a scale chosen so both lines and the value fit, and a value past the scale is clamped with a "›" after the label. When `passLine` equals `hardLimit` (REIT gearing, Bank CET1 and NPL) there is one tick and no zone. A null value draws an empty track with "No data"; `notApplicable` replaces the whole visual with the reason in `text-tertiary`.
- **DivergingBar.** A centre axis (`border-card`), the in-line band as a `surface-2` rectangle centred on it, the bar from the axis to the value. The scale is symmetric (`-scale` to `+scale`) and set by the caller so a stack of bars shares one (`divergingScale()` picks it); a bar past the scale is clamped with an end cap. The label is the signed value with the unit, e.g. "+3.1%", titled "ahead of / behind benchmark" in the table that holds it, and the stock's and the benchmark's own returns sit next to it ("stock +12.1% · XLK +9.0%") so a gap cannot be read as a return. Inside the band the bar is neutral and the word is "in line".
- **StageTimeline.** One horizontal strip, 12px tall, one segment per run of equal stage with width proportional to its weeks and a 1px gap between runs. The current stage's start is marked with a tick above the strip and the date written under it ("Since 12 Mar 2026", or "Since at least ..." with the data-starts caveat when the date is a lower bound, as in the header tooltip, `formatWeinsteinSince`). A line of text under the strip names the stages shown. Unavailable (fewer weeks cached than the engine needs): the strip is replaced by the reason in `text-tertiary`.
- **PriceRangeBar.** A track with the fair-value band shaded (`surface-2`, `border-card` edges), a tick at the fair value, and the price as a taller `text-primary` marker with its label above. The captions under the track read "0.9x $90.00", "Fair value $100.00", "1.1x $110.00", and a sentence says where the price sits ("Price is 10.0% below fair value"). The track scale is chosen so the price is always on it. No fair value: the bar is replaced by the reason ("No fair value: no valuation method applies") and the price in words.
- **Sparkline.** An `svg` polyline, 1.5px, `series-1`, `vector-effect: non-scaling-stroke`, no axes, no fill, 40px high; a dot marks the last point; the first and last labels sit under the ends in 12px `text-tertiary`. Under two points it shows "No price history" instead.
- **Narrow width.** Every primitive is fluid (100% of its container, no fixed pixel width) and keeps its captions on their own lines. In a `VisualRow` the label and pill stack above the visual under 36rem.

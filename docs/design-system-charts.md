# Fathom Charts

How every chart is coloured, drawn and worded. Companion to `docs/design-system.md`. Decided from a read-only audit of the frontend (two chart libraries, no shared theme, four different greens, found during the design work).

## Two libraries, one set of rules

`lightweight-charts` draws the Chart tab only. `recharts` draws everything else. The rules below apply to both; only the way a token reaches the chart differs (a hex string for `lightweight-charts`, a CSS variable for `recharts`).

## Colour

| The job | Use |
| --- | --- |
| Chart tab candles, indicators, zones, signals, events, stages | The named tokens `chart-up`, `chart-down`, `chart-ema21`, `chart-sma50`, `chart-sma200`, `chart-stoch-k`, `chart-band`, `chart-refline`, `chart-zone-broken-support`, `chart-zone-broken-resistance`, `chart-warren-yellow`, `chart-warren-gray`, `chart-event-earnings`, `chart-event-dividend`, `stage-*`. Values are unchanged from before the redesign; only the names are new. |
| Bars that show a direction (Breadth net new highs, Sector heatmap cells) | `positive` and `negative`. Never the candle pair. |
| A bar or line that is one series (Revenue, ROE, price target) | `series-1` (brand blue). |
| Several series that are not ordered by meaning | `series-1` to `series-5`, in order. Never `warn`, `positive`, `negative` or `brand` under another name. |
| Breadth 20, 50, 200-day lines | `series-3`, `series-2`, `series-1`. Draw order 200, 50, 20 so the most volatile line is on top. |
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
- **Active range or toggle button:** `surface-2` fill and `text-primary`, like SegmentedControl.
- **Legend:** `caption` in `text-secondary`, a 6px dot in the series colour. Non-interactive.

## States

| State | What shows |
| --- | --- |
| Loading | A `surface-2` block in the chart's own shape and height, pulsing. |
| Empty | A `caption` in `text-tertiary` ("No data for this period") inside the chart's own space. A trend tile with no data stays visible with this caption instead of vanishing. |
| Error | One short line in `negative`. |

## Not decided / left as built

Chart geometry (heights, bar gap, corner radius) stays as it was before the redesign: trend bars 64px (32px in the Watchlist), Analyst Ratings 216px, Chart tab 580px main pane and 100px sub-panes.

The Chart tab (candlestick) colour palette was deliberately kept as-is rather than redesigned — see `docs/decisions.md`.

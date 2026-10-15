# Fathom Charts

How every chart is coloured, drawn and worded. Companion to `docs/design-system.md`. Decided from a read-only audit of the frontend (two chart libraries, no shared theme, four different greens, found during the design work).

## Two libraries, one set of rules

`lightweight-charts` draws the Chart tab only. `recharts` draws everything else. The rules below apply to both; only the way a token reaches the chart differs (a hex string for `lightweight-charts`, a CSS variable for `recharts`).

## Colour

| The job | Use |
| --- | --- |
| Chart tab candles, indicators, zones, signals, events, stages | The named tokens `chart-up`, `chart-down`, `chart-ema21`, `chart-sma50`, `chart-sma200`, `chart-stoch-k`, `chart-band`, `chart-refline`, `chart-zone-broken-support`, `chart-zone-broken-resistance`, `chart-warren-yellow`, `chart-warren-gray`, `chart-event-earnings`, `chart-event-dividend`, `chart-fvg-bullish`, `chart-fvg-bearish`, `stage-*`. Values are unchanged from before the redesign, except `chart-warren-yellow` (amber `#f59e0b` to pure yellow `#ffff00`, 2026-10-05); only the names are new. |
| Bars that show a direction (Breadth net new highs, Sectors page return bars) | `positive` and `negative`. Never the candle pair. |
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
- **Axis text** `text-secondary`, mono (`font-mono`, 13px `text-xs`). **Axis lines and pane separators** `border-card`.
- **Gridlines:** none. Trend bars have no axes at all.
- **Tooltip:** `surface` fill, `border-card` outline, `radius-md`, `shadow-popover`. Labels `text-secondary`, values `text-primary` in mono, always with a sign on a change (+1.26%, −7.49%).
- **Active range or toggle:** `surface-2` fill and `text-primary`, neutral and never brand blue. A choose-one range is a SegmentedControl; an independent overlay is a Switch, or an `outline` `sm` Button with `aria-pressed` where a row of them has no room for switches (the Chart tab's overlay toggles).
- **Legend:** a `text-xs` line (13px) in `text-secondary`, a 6px dot in the series colour. Non-interactive.

## Ranked return bars (Sectors page, 2026-10-14)

A horizontal, sorted, diverging bar chart for one return per category (11 sector ETFs): `components/sectors/SectorBarChart.tsx`, plain CSS (percent-positioned `div`s), not recharts. **Bars are drawn like the Historical Trends bars** (`MiniBarChart`): solid token fill, corner radius 1px (effectively square, not rounded), bar 90% of its row and gap 10% (recharts `barCategoryGap` 10%; 32px rows, 5% inset top and bottom). A label column (mono ticker + name), then the plot: bars grow from a one-pixel `text-tertiary` zero line, `positive` to the right and `negative` to the left, sorted descending, with the signed two-decimal value (`+1.80%`, `-5.93%`, `text-primary`, mono) at the bar's outer end. The plot is inset by a gutter on both sides so a label never clips, longest negative bar included.

**Stacked charts share one zero.** When several of these charts stack, they use one label column width and one plot width, and the 0% line sits at the same x in all of them: the shared zero fraction is the max over the charts of L / (L + R) (L = most negative value's size, R = most positive, 0 if none), clamped to 12%-88% of the plot width; a chart with nothing to draw is ignored. Each chart still has its own scale (percent per unit width), the smallest that fits its bars on both sides of that zero, with round 1/2/5 ticks (`text-secondary` mono labels under the plot, no gridlines). So charts are not comparable to each other in length, only in position of zero. Changing any chart's window recomputes the zero and every scale. A missing value is the label, `n/a` in `text-tertiary` and no bar. No tooltip. Each chart carries its own native `Select` (`short`) above it. Pure helpers in `lib/sectorReturns.ts`; spec docs/specs/sectors.md.

## States

| State | What shows |
| --- | --- |
| Loading | A `surface-2` block in the chart's own shape and height, pulsing. |
| Empty | A `text-xs` line in `text-tertiary` ("No data for this period") inside the chart's own space. A trend tile with no data stays visible with this caption instead of vanishing. |
| Error | One short line in `negative`. |

## Not decided / left as built

Chart geometry (heights, bar gap, corner radius) stays as it was before the redesign: trend bars 64px (32px in the Watchlist), Analyst Ratings 216px, Chart tab 580px main pane and 100px sub-panes.

The fair value gap zones (D·6M, `docs/specs/fvg.md`) have their own pair, `chart-fvg-bullish` `#0891B2` (cyan-600) and `chart-fvg-bearish` `#F472B6` (pink-400), deliberately not the candle green/red. A fill at 14% alpha with dashed 1px edge lines at 58% alpha, behind the candles. The first-choice teal `#14B8A6` was dropped: it sits 5.4 OKLab-distance units (x100) from `chart-up` (emerald `#10B981`), so a bullish zone would read as a rising candle; `#0891B2` is 11.1 or more from every other chart color (nearest: `chart-band` grey 11.1, `chart-ema21` 13.3, `chart-up` 15.9) and `#F472B6` is 15.0 or more (nearest: `chart-down` 15.0, `chart-sma200` 15.4, `chart-zone-broken-resistance` 15.6). Neither is used for any other line or marker.

The Chart tab (candlestick) colour palette was deliberately kept as-is rather than redesigned — see `docs/decisions.md`. The 2H·90D range's three Warren sub-panes add no tokens: RSI `chart-band` (one color on this range; the daily RSI pane is red beyond 30/70), ADX `chart-ema21` (the ADX line alone; +DI/-DI are not plotted), WVF `chart-warren-yellow` (`#FFFF00`, TOS Color.YELLOW; the Warren yellow arrows share it. It was amber `#F59E0B`, which read orange; changed 2026-10-05), reference lines `chart-refline` (all dashed: the Warren thresholds; the classic 30/70 lines are not drawn). On every range the axis text is `#e5e8ec` (the text-primary hex) in the monospace face with a lower price-axis tick density, the sub-panes show no tick labels (only their level-line tags), and the signal arrows carry no text: `docs/specs/chart-tab.md`, "Axis options" and "Signal arrows".

## Series keys in the generated `<style>` (2026-10-13)

`components/ui/chart.tsx` writes one `--color-<key>` custom property per series into a `<style>` element, and the keys of the Segmentation charts are raw FMP segment names. Every key therefore goes through `chartCssKey`: characters outside `[A-Za-z0-9-]` become `_<hex code point>_`, including the underscore itself, so the mapping is stable and two different names can never share a key (`"a_"` and `"a;"` stay different). The chart's own id goes through `chartDomId` (idempotent, `[A-Za-z0-9_-]`), a colour containing `; { } < > " ' \` or a control character is not emitted, and the CSS text is built by the pure `buildChartCss`. No component reads `var(--color-<key>)` today (series colours are passed to Recharts as `fill`); a future reader must use `chartCssKey(key)` for the lookup. Test: `components/ui/chart.test.tsx`.

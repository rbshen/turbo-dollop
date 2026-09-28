# Fathom frontend chart & table audit (2026-09-28)

Read-only inventory of every chart and every table in the Fathom Next.js frontend, done to
inform a chart/table spec for the new design system. No code, config, or data was changed to
produce this document. All paths are relative to `frontend/` unless stated otherwise.

Reference tokens used for color-matching throughout: page `#080B11`, surface `#12161C`,
surface-2 `#1B1F26`, border-subtle `#20242B`, border-card `#292E36`, text-primary `#E5E8EC`,
text-secondary `#9499A0`, text-tertiary `#82868E`, brand `#4A89F2`, positive `#57966E`,
positive-strong `#00D172`, warn `#DCA744`, caution `#C48400`, negative `#F05653`,
chart-purple `#9C84C7`, chart-orange `#E48233`, index-membership `#00978A`. Fonts: Public Sans
(body), Sora (headings), IBM Plex Mono (numbers).

---

## PART 1 — CHARTS

### 1.0 Charting libraries in use

`package.json`: `"lightweight-charts": "5.2.0"`, `"recharts": "^3.8.0"` (resolved `3.8.0`). No
d3, victory, visx, chart.js, nivo, plotly, apexcharts, or highcharts anywhere in the tree.

- **lightweight-charts 5.2.0** — used in exactly one place: the ticker page's **Chart** tab
  (`components/chart/TickerChart.tsx`, `EventLabelsPrimitive.ts`, `lib/chartEventMarkers.ts`,
  `lib/chartWeinstein.ts`, `components/ticker/ChartTab.tsx`). Nowhere else.
- **recharts 3.8.0** — used by 9+ files: the shared wrapper `components/ui/chart.tsx`
  (`ChartContainer`/`ChartTooltip`/`ChartTooltipContent`/`ChartStyle`), the shared generic
  chart primitives `components/charts/{RechartsAreaChart,RechartsStackedChart,RechartsPieChart,
  MiniBarChart,ChartLegend}.tsx`, `components/breadth/MarketBreadthCharts.tsx`,
  `components/analystRatings/PriceTargetTrendChart.tsx` and
  `RatingDistributionTrendChart.tsx`, `components/ticker/InstitutionalOwnershipTab.tsx`
  (shelved, see §1.11), and (Summary tab, out of the originally-named scope but found by the
  library sweep) `components/ticker/SegmentationSection.tsx` /
  `SegmentationSnapshotSection.tsx`.
- **No chart at all**, confirmed by direct file reads: the ticker page's **Analysis** tab
  (Step 1/2/4/5 cards), the **Technical** tab's lens cards, the **Screener** page, the
  **Momentum** page, and (currently) **Growth Rate** anywhere in the app.
- **Sector Heatmap** (`/sectors`) is a hand-built CSS grid — no charting library at all, by
  its own code comment.

There is **no single shared chart theme/config file**. Two unrelated conventions coexist:
lightweight-charts' `TickerChart.tsx` hardcodes ~20 raw hex values in its own local `COLORS`
object (nothing there references a CSS token); every recharts chart instead defines its own
local color constants as `var(--color-*)` strings, inconsistently naming them per-component
(`TARGET_COLOR`, `SMA20_COLOR`, `OWNERSHIP_COLOR`, etc.) with no central chart-palette file.
The one truly shared piece, `components/ui/chart.tsx`'s `ChartTooltipContent`, itself uses
generic shadcn tokens (`bg-background`, `border-border/50`) rather than the app's own
Fathom-named tokens — see §1.13.

---

### 1.1 Chart tab — OHLC candlesticks (`components/chart/TickerChart.tsx` + 5 helper files)

Page: ticker page → **Chart** tab. Library: `lightweight-charts` 5.2.0, one `createChart()`
with 3 stacked panes (price / RSI / Full Stochastic) sharing one time axis.

**What's drawn** (main pane unless noted): candlesticks; EMA(21), SMA(50), SMA(200) lines;
Bollinger Bands(20,2) — upper/lower only, no fill; Liquidity Zone support/resistance lines,
plus "broken zone" lines in distinct colors; earnings ("E") / dividend ("D") event letters via
a custom canvas primitive; Warren signal arrows (Blue/Yellow/Gray × Up/Down) and a BB+RSI
buy-arrow via the library's `createSeriesMarkers`; a Weinstein-stage candle-recolor mode
(weekly view only); RSI(14) and Full Stochastic(5,3,3 EMA) in their own sub-panes with static
70/30 and 80/20 reference lines. **No volume bars exist anywhere in this chart** (confirmed by
grep — no histogram series). **No watermark.**

**Colors — every single one is a raw hex literal**, none reference the app's CSS tokens:

| Element | Value | Notes |
|---|---|---|
| Background | `#09090b` | matches wrapper's `bg-zinc-950` |
| Axis text | `#a1a1aa` | reused as Warren-gray marker |
| Axis/pane-separator border | `#27272a` | |
| Up candle body+wick | `#10b981` | reused for BB+RSI marker, LP active support |
| Down candle body+wick | `#ef4444` | reused for RSI OB/OS highlight, LP active resistance |
| EMA(21) | `#3179F5` | reused as Warren-blue marker |
| SMA(50) | `#4CAF50` | |
| SMA(200) | `#F23645` | **same literal as Stochastic-K**, uncommented (likely coincidental) |
| Bollinger upper & lower (both) | `#808080` | same gray as RSI base and Stochastic-D |
| RSI base / Stochastic-D | `#808080` | |
| Stochastic-K | `#F23645` | |
| Static ref lines (RSI 70/30, Stoch 80/20) | `#52525b` | |
| LP active support / resistance | `#10b981` / `#ef4444` | = candle colors |
| LP broken support / resistance | `#FF9800` / `#E040FB` | matches project docs; reused verbatim by `LiquidityZonesCard` (§2.13) |
| Warren blue / yellow / gray | `#3179F5` / `#f59e0b` / `#a1a1aa` | |
| Earnings "E" / Dividend "D" | `#22d3ee` / `#a78bfa` | cyan-400 / violet-400 equivalents |
| Weinstein stage: base/advance/top/decline | `#8FD99F` / `#1B9E3E` / `#E8A020` / `#E03A3A` | week-candle recolor, W/4Y "Stage" toggle only |
| Weinstein MA overlay | `#FFFFFF` | pure white, only white series on the chart |

Chrome around the canvas is a mix of raw Tailwind and design tokens: the DOM wrapper is
`bg-zinc-950` (raw) + `border-border-card` (token); the event-marker hover tooltip is fully
raw (`border-zinc-700 bg-zinc-900/95 text-zinc-200/400`); the OHLC legend uses raw
`text-zinc-500/300/200` for O/Open/Close but raw Tailwind `emerald-400`/`red-400` (not the
`positive`/`negative` tokens) for High/Low; range/overlay-toggle buttons use a raw
`bg-zinc-700 text-zinc-100` for the active state next to token-based inactive/hover classes;
the Chart tab's own error text is the token `text-negative` — a third distinct "red" inside
one feature (see §1.13).

**Typography**: axis labels `var(--font-mono), ui-monospace, monospace` (IBM Plex Mono), 12px.
Event letters: bold 13px, but a **separately hardcoded** font stack
(`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`) rather than reusing the chart's
own `var(--font-mono)` string. OHLC legend/pane titles use Tailwind's `font-mono` utility
(a third, technically distinct reference to "mono"). RSI/Stoch pane titles are 10px.

**Geometry**: main pane fixed at 580px via `setStretchFactor` (not `setHeight`, deliberately);
RSI/Stoch panes 100px each. No candle-width setting (library auto-computed). All overlay lines
`lineWidth: 1` except none use dashes — active and broken LP lines are both solid, distinguished
by color only. Grid lines are **fully hidden** on both axes (`grid.vertLines/horzLines.visible:
false`) — no gridlines anywhere on this chart.

**Behavior**: crosshair `mode: 1` (a bare numeric literal — Magnet mode — the `CrosshairMode`
enum isn't even imported). Zoom is two discrete buttons stepping a 3-level geometric ladder,
not wheel/pinch (`handleScale: false`); pan bounds computed analytically, not read back from
the live time scale. Tooltip = a custom hit-tested primitive for E/D letters (own hover logic,
placement flips above/left of cursor near edges) plus a plain OHLC legend that always shows the
hovered (or else latest) bar. Loading = a fake pseudo-histogram skeleton
(`bg-zinc-800`/`animate-pulse`). Empty = "No chart data available for {ticker}." Error =
`text-negative` text. Range switch fully remounts the chart (`key={range}`).

**Formatting**: no `priceFormat`/`tickMarkFormatter`/`localization` set anywhere — axis price
and date formatting is 100% library default. The OHLC legend and event tooltips use the app's
own `fmtMoney`/`fmtEventDate` helpers independently of the axis.

---

### 1.2 Historical Trends / Ratio Trends bar charts (`MiniBarChart` + `TrendCardsGrid`)

**Correction to the task's premise**: these bar charts do **not** live on the Analysis tab.
The 4 Analysis-tab cards (Step1Card/Step2Card/Step4Card/Step5Card) contain **zero charts** —
confirmed by direct read, they're all thin wrappers around `components/shared/
AnalysisSectionCard.tsx`, which is score/verdict text + a prose sentence + a collapsible
bulleted `<ul>`, by explicit design ("Analysis-tab cards are deliberately minimal... the same
series/ratios are shown in full on the Financials/Ratios tabs instead" — its own comment).

The real bar charts live on two **sibling tabs**:
- **Financials tab** → `components/ticker/HistoricalTrendsGrid.tsx`: CFO, Net Income,
  Operating Income, Revenue, FCF, Accounts Receivable, CCC, Total Debt (stacked LT+ST).
- **Ratios tab** → `components/ticker/RatioTrendsGrid.tsx`: Gross Margin, Net Margin, ROE,
  ROIC, Current Ratio, Debt/EBITDA, Interest Coverage.
- Also reused, smaller, as the Watchlist table's REV/NI/CFO sparkline columns
  (`components/watchlist/WatchlistTable.tsx`'s `TrendCell`, §2.3).

Both grids are built from `components/charts/TrendCardsGrid.tsx` (card shell) →
`components/charts/MiniBarChart.tsx` (the chart). Type: single-series vertical bar chart, one
bar per fiscal year+TTM; Total Debt is the one **stacked** 2-segment chart in the whole app.

**Confirms the memory-noted house style** — "thick bars, small gap, no axis, hover tooltip w/
signed 2-decimal value" — is real (`MiniBarChart.tsx`'s own comment says so verbatim) but the
"signed" part only actually holds for the percent formatter (`fmtPct`): the money formatter
(`fmtCompactMoney`, used for Revenue/NI/CFO/FCF/AR/Total Debt) shows a bare `-` for negatives
and no `+` for positives; days/ratio formatters are unsigned too. The code comment itself
overstates this.

**Colors**: every single-series bar defaults to `var(--color-brand)` (blue) — **no caller in
this scope ever overrides it**, so Revenue, Net Income, CFO, FCF, AR, CCC, Gross/Net Margin,
ROE, ROIC, Current Ratio, Debt/EBITDA, Interest Coverage, and the Watchlist sparklines are all
the identical brand-blue. **There is no negative-value color at all** — a loss year renders in
the same blue as a profit year, just extending below the zero baseline; sign is legible only
from the tooltip/headline text, never the bar color. The one exception: Total Debt's stacked
chart colors long-term debt `var(--color-brand)` and short-term debt
`var(--color-chart-orange)` — the only place `chart-orange` is used as a chart-series color.
No axis, no gridlines (both `XAxis`/`YAxis` hidden, no `CartesianGrid`). Tooltip container is
the shared `bg-background`/`border-border/50` chrome (see §1.13).

**Geometry**: `height=64` (Financials/Ratios cards) or `32` (Watchlist sparkline);
`barCategoryGap` `10%` default, `15%` in the Watchlist cell; `radius={1}` (near-square
corners, not a pronounced rounded-top look despite "thick bars" framing); no animation.

**Behavior**: hover tooltip only, no crosshair highlight (`cursor={false}`). Loading = a plain
pulsing gray box at the caller level, not the chart's own. Empty = the whole card silently
disappears from the grid (no placeholder) if every value is null.

---

### 1.3 ScoreBadge, SignalBars, CircularScoreBadge, verdict pills — gauge-style graphics

None of these are charts in the library sense — all are plain CSS/text, included per the
task's "score or gauge graphics" instruction.

- **`ScoreBadge`** (`components/step1/ScoreBadge.tsx`) — borderless stacked text (`score` /
  `verdict`), color from the shared 5-tier `lib/tierColor.ts::textClassFor`. **Actually used
  only by `ScreenerCard.tsx`** — none of the 4 Analysis-tab cards import it (they use
  `AnalysisSectionCard`'s own inline score string instead; see §1.13's doc-drift note).
  Bands, confirmed exact: Fail → `text-negative`; Pass-with-caution → `text-caution`;
  score > 90 → `text-positive-strong`; score ≥ 75 → `text-positive`; else (70–74, or any
  sub-75 Pass) → `text-warn`.
- **`CircularScoreBadge`** (`components/overall/CircularScoreBadge.tsx`) — the one genuine
  gauge-*shaped* graphic on the Analysis tab (top of `OverallAssessmentCard`). It is **not**
  an SVG arc/progress ring — just a plain CSS circle (`rounded-full border-2`) with the score
  number inside; no arc fill, no needle, no proportional track.
- **`SignalBars`** (`components/watchlist/SignalBars.tsx`) — 3 fixed CSS bars (ascending
  height, bottom-aligned), used only for the Watchlist table's Moat and Valuation columns.
  Filled-bar color is caller-supplied (`bg-negative`/`bg-positive`/`bg-positive-strong`,
  solid full-opacity, unlike the `/16` translucent badges elsewhere); unfilled bars are always
  `bg-border-subtle`. **Note**: CLAUDE.md documents a `maxBars` prop generalization for a
  5-bar Trend indicator — the live code has no such prop; `SignalBars` is hardcoded to exactly
  3 bars today (see doc-drift, §4).
- **Verdict/status pills** (`MoatPill`, `FairValuePill`, `PerfVsSpyPill`,
  `SpeculativeGrowthPill`, `WeinsteinStagePill`) all share one identical shape convention
  (`rounded-md text-xs font-semibold`, `rounded-md` ≈ 8px — narrower than the card containers'
  `rounded-lg` ≈ 10px, a real small inconsistency), each independently hardcoding the same
  Tailwind string rather than sharing one base component.
- **`lib/tierColor.ts`** is the single shared verdict→color function (`classFor`/
  `textClassFor`/`flatChipClassFor`), used by ScoreBadge, AnalysisSectionCard's inline score,
  CircularScoreBadge, and `OverallAssessmentCard`. It is **not** the same scheme
  `AnalysisSectionCard` uses for its own bullet-text coloring (a simpler 3-tier
  0/`<70`/else scheme) — see §1.13's "verdict coloring" finding for the full picture (4
  distinct status-color schemes coexist on the ticker page alone).

---

### 1.4 Analyst Ratings tab charts

Files: `components/analystRatings/PriceTargetTrendChart.tsx`,
`RatingDistributionTrendChart.tsx`, plus supporting non-chart visuals in the same folder.

- **Price-target-vs-price overlay** (`PriceTargetTrendChart.tsx`): default view is a single
  smoothed area/line of avg. price target (`var(--color-brand)`, gradient fill fading
  0.3→0 opacity); an "Overlay stock price" toggle switches to a 2-line comparison — target
  (`var(--color-brand)`) vs. stock price (`var(--color-chart-1)`) — on **one shared $ axis**,
  never dual-axis. A dashed (`2 3`) reference line marks a data-truncation point. Y-axis is
  fully hidden. Height 216px both modes. Toggle button's active state is
  **hardcoded `bg-zinc-700 text-zinc-100`**, not a token — the same raw pair seen on the
  Chart tab's own toggle buttons (§1.1), while its inactive state right next to it does use
  tokens.
- **Recommendation Trend** (100%-stacked bar, `RatingDistributionTrendChart.tsx` via the
  shared `RechartsStackedChart`): 5 segments (Buy/Outperform/Hold/Underperform/Sell), colored
  `positive`/`brand`/`warn`/`chart-purple`/`negative` — the one place `chart-purple` is used
  as a categorical chart-series color. Hovering a segment dims all others to 25% opacity
  (unique interaction in this scope). Legend is a separate custom `ChartLegend` component
  below the chart, not Recharts' built-in legend, and is non-interactive (no click-to-hide).
- Non-chart but visually chart-adjacent: `PriceTargetRangeSlider` (Low→Avg→High gradient
  track, red→amber→green left-to-right) and `ConsensusBanner` (a stacked proportion bar,
  buy/hold/sell colors) — both plain divs, not Recharts.
- Both use the shared `ChartTooltipContent` chrome (see §1.13).

---

### 1.5 Valuation (Step 3) tab — no chart library at all

Confirmed via grep: **zero imports of recharts/lightweight-charts anywhere in
`components/step3/`.** Two hand-built, plain-div visuals exist instead:

- **`ValuationGauge`** — a horizontal gradient track (`green→amber→red`, i.e.
  `positive→warn→negative`, undervalued-to-overvalued) with a thin **white** vertical tick
  marker (`bg-white`, literal, ringed in `--color-surface`) positioned by a clamped formula.
  Static, no hover/tooltip/animation.
- **P/B mean/SD "bands"** — despite the name, this is a **plain data table** (5 rows, Mean±2SD
  down to Mean-2SD, plus Last Close), not a graphical band chart at all — no positional
  representation of where price sits among the bands.
- **`PriceTargetRangeSlider`** (Analyst Ratings, §1.4) uses the *opposite* gradient stop order
  (red→amber→green, low-to-high) from `ValuationGauge`'s green→amber→red — same 3 tokens,
  reversed sequence, and a solid brand-blue circular marker instead of a white tick — two
  different conventions for visually similar "gradient track + position marker" widgets.

---

### 1.6 Sector Heatmap (`/sectors`)

`components/sectors/SectorHeatmapGrid.tsx` — a plain CSS grid (`role="table"`/`role="cell"`
ARIA emulation via `display: contents`), **not** a charting library, by its own code comment.
11 ETF rows × 7 trailing-return-window columns.

**Color-scale logic** (`lib/sectorHeatmap.ts`): per-**column** scaling — each window's own
largest `|return|` sets that column's intensity ceiling (floored at 1pp so a flat column
doesn't paint noise at full saturation). Tint range 12%–62%, computed as
`color-mix(in oklab, var(--color-X) N%, transparent)`. **Positive cells use
`--color-positive-strong`** (the bright "Strong Pass" green), **negative cells use plain
`--color-negative`** — an asymmetric pairing (there is no "negative-strong" token to match).
Cells below 0.05% render untinted; null cells render "—" in tertiary gray.

**Geometry/typography**: no gridlines, no cell borders (0.25rem grid gap does the visual
separating), `rounded-md` cells, `font-mono` for tickers and values (IBM Plex Mono, matching
the app-wide numeric convention). Sort is single-column click-header (toggles direction on the
same column, resets to descending on a new one) — a third distinct sort UX pattern in the app
(see §2.16).

**Flagged inconsistency**: the page's own footnote still reads "Trailing total return (price
change plus reinvested distributions)" — this contradicts the documented and (per other
agents' cross-check) actual computation, which is price-only/dividend-excluded. A copy/data
mismatch, not a code bug.

---

### 1.7 Market Breadth (`/breadth`, `/breadth/[sector]`)

`components/breadth/MarketBreadthCharts.tsx` + `MarketBreadthStats.tsx`. Library: Recharts
3.8.0, via the shared `ChartContainer`.

**4 stat tiles**, then **two synced panels** (`syncId`), never combined into one dual-axis
chart (explicit design precedent, later reused verbatim by the shelved Institutional
Ownership tab, §1.11):
- **3-line % panel**: 20-day (`var(--color-chart-1)`, green), 50-day (`var(--color-chart-2)`,
  amber — **numerically identical to `--fathom-warn`**), 200-day
  (`var(--color-chart-4)`, blue — **numerically identical to `--fathom-brand`**). Drawn
  200/50/20 order so the most volatile line sits on top. Fixed Y domain 0–100, dashed 50%
  reference line, plus a dashed "Live →" marker at the backfill/live boundary when one exists
  in view. Horizontal gridlines only (`CartesianGrid vertical={false}`).
- **Diverging net-new-highs bar panel**: per-bar `Cell` colored `var(--color-positive)` or
  `var(--color-negative)` by sign (plain, not the "-strong" variant Sector Heatmap uses for
  the same semantic idea). Solid zero reference line (vs. the other panel's dashed 50% line).
- Custom pan (drag, no `<Brush>` — tried and rejected per code comment for breaking
  `syncId` alignment with the bar panel), no zoom. Legend is the same custom, non-interactive
  `ChartLegend` component as Analyst Ratings uses.
- `/breadth/[sector]` sub-pages reuse this same chart code verbatim (deliberate duplication,
  not a shared component, per its own comment) — one raw, non-token color found here:
  `hover:bg-white/5` on the sector-tab strip's inactive state.

---

### 1.8 Momentum (`/momentum`) — no chart of any kind

Confirmed by full file read: `MomentumTable`/`MomentumBanner` render a plain HTML `<table>`
(see §2.4) with no bar chart, sparkline, or heatmap anywhere. The only "gauge" element is a
`MoatPill` badge per row.

---

### 1.9 Watchlist mini-bar sparklines

Covered under §1.2 (`MiniBarChart`) — the REV/NI/CFO columns each render a 32px-tall,
brand-blue-only mini bar chart with no axis, per the shared house style.

---

### 1.10 Technical tab lens cards — no chart library anywhere

Confirmed by grep across all of `components/technical/`: **zero** `recharts`/`<svg>`/
`<canvas>` imports. Trend Structure/BOS is presented on this tab purely as two stat cards
(`LongTermCard`/`NearTermCard`) — the actual swing/BOS/LP visual lines only ever appear on the
separate Chart tab (§1.1). Every card on this tab (`WeinsteinStageCard`, `ReversalCard`,
`TrendContinuationCard`, `BbRsiEntrySignalCard`, `WarrenSignalCard`, `LiquidityZonesCard`) is
built from the shared `ChecklistCard` list primitive (see §2.13) plus colored pills.

The only "chart-like" elements anywhere on this tab: one hand-rolled CSS linear progress bar
(`ReversalCard`'s "freshness" indicator, `bg-brand` fill on a `bg-surface-2` track) and a CSS
"dot timeline" (`DotTimeline`, shared by `ReversalCard`/`TrendContinuationCard` — a row of
colored dots joined by hairlines, no SVG). **SMA 20/50/200 position tracking is not rendered
anywhere on this tab** — the fields exist in the API type but no component reads them (the
Watchlist columns that used to show this were removed 2026-09-06 and never re-surfaced here).

`LiquidityZonesCard` is the one place in this whole scope besides the Chart tab that uses
hardcoded, non-token hex (`#FF9800`/`#E040FB`, see §1.1) — explicitly "kept in sync manually"
with the chart's own values per its own code comment.

---

### 1.11 Institutional Ownership tab — shelved, code intact, has real charts

`components/ticker/InstitutionalOwnershipTab.tsx` is disconnected from the tab bar
(shelved 2026-09-27 per CLAUDE.md) but the file is fully present and was audited as built.
Two stacked Recharts `LineChart` panels (`TrendPanel`, called twice): "Ownership %"
(`var(--color-chart-1)`) and "Holder count" (`var(--color-chart-4)`) — deliberately split,
citing Market Breadth's percent-vs-count precedent. This is the **only** chart in the whole
audit that renders a visible `CartesianGrid` (`var(--color-border-subtle)`, horizontal only)
and the only one with explicit non-default Recharts margins — every other chart in scope
either has no grid or leaves margins at the Recharts default.

---

### 1.12 Segmentation charts (Summary tab — found via the library sweep, not in the original 3 named tab groups)

`components/ticker/SegmentationSection.tsx` (multi-year stacked bar, via the shared
`RechartsStackedChart`) and `SegmentationSnapshotSection.tsx` (single-year donut, via
`RechartsPieChart`), both paired with the shared `ChartLegend`. Donut: `innerRadius="55%"
outerRadius="90%"`, hover dims non-hovered slices to 35% opacity. Neither is on a dedicated
"Segmentation" tab — both live on the Summary tab.

---

### 1.13 Cross-chart summary

**Do "price up/down" colors differ from "pass/fail" colors? Yes, substantially.**

| Green in use | Value | Where |
|---|---|---|
| `#10b981` (raw Tailwind emerald-500) | up-candle, BB+RSI marker, LP active support | Chart tab only |
| `--fathom-positive` `oklch(62% 0.09 155)` | verdict Pass 75-90, Moat "narrow", Valuation "fair" | app-wide badges/text |
| `--fathom-positive-strong` `oklch(75% 0.2 155)` | verdict Strong Pass, Moat "wide", Valuation "undervalued", **and** Sector Heatmap's positive cell fill | app-wide + one chart |
| `--color-chart-1` `oklch(68% 0.15 155)` | Breadth 20-day-SMA line, Institutional Ownership ownership-% line | 2 charts only, a 4th distinct green with no reference-token match |

| Red in use | Value | Where |
|---|---|---|
| `#ef4444` (raw Tailwind red-500) | down-candle, RSI OB/OS highlight, LP active resistance | Chart tab only |
| raw Tailwind `red-400` | OHLC legend "Low" value | Chart tab only — a 3rd red inside the same feature |
| `--fathom-negative` `oklch(66% 0.19 25)` | verdict Fail, Moat "no moat", Valuation "overvalued", Sector Heatmap/Breadth negative fills, Chart tab's own error text | everywhere else |
| raw `text-red-400` | 4 Settings forms' top-level error text | Settings only, should be `text-negative` per every other error message in the app |

| Amber in use | Value | Where |
|---|---|---|
| `--fathom-warn` `oklch(76% 0.13 80)` | Pass 70-74, "Top" Weinstein stage, disclaimer boxes app-wide | everywhere |
| `--fathom-caution` `oklch(66% 0.16 80)` | "Pass with caution" verdict only | narrow, deliberate 2nd amber tier |
| `--color-chart-2` `oklch(76% 0.13 80)` | Breadth 200-day-SMA line | **numerically identical to `--fathom-warn`** — visually indistinguishable from a warn badge despite being an unrelated series |

`--color-chart-4` (Breadth 50-day line, Institutional Ownership holder-count line) is
similarly numerically identical to `--fathom-brand`. So two of the four "chart-N" tokens
duplicate existing semantic tokens exactly, while `chart-1` and `chart-3` don't correspond to
anything in the reference palette at all (`chart-3`, the reserved red slot, is explicitly
never used per Breadth's own code comment, to avoid implying "bad").

**No shared chart theme/config file exists.** The Chart tab (lightweight-charts) is fully
self-contained raw hex; every Recharts chart independently defines its own `var(--color-*)`
constants; the one shared piece (`components/ui/chart.tsx`'s tooltip chrome) uses **generic
shadcn tokens** (`bg-background`, `border-border/50`, `rounded-none`, `shadow-xl`) rather than
the app's own Fathom-named tokens — the dark-theme values happen to numerically coincide with
`--fathom-page`/`--fathom-border-card`, but this means every chart tooltip in the app floats
on the *page* background color, one shade darker than the *card* (`surface`) it sits over, and
is the only place in the whole audit using a visible drop-shadow or square corners.

**Verdict/status coloring is not one scheme — at least 4 coexist**: `lib/tierColor.ts`'s
5-tier scheme (score/verdict-driven, used for badges); `AnalysisSectionCard`'s own simpler
3-tier scheme for bullet text (0 / <70 / else); Step5Card's breach-context sub-bullets
(favorable/unfavorable/not-computable → positive/negative/tertiary-italic); Step3Card's
method-selection trace list (passed/failed/unknown → positive/tertiary/warn).

**Other inconsistencies found**: SMA(200) and Stochastic-K share the identical literal
`#F23645` with no comment noting the reuse (possibly coincidental, unlike every other
documented color reuse in that file); `MiniBarChart` never color-codes negative values despite
`pnlClass`-style sign-coloring being a well-established convention elsewhere in the app; pill
radius (`rounded-md` ≈ 8px) is narrower than card radius (`rounded-lg` ≈ 10px) throughout;
`bg-zinc-700 text-zinc-100` (a raw, off-token gray pair) is independently hardcoded for the
"active" state on both the Chart tab's own range/toggle buttons *and* the Analyst Ratings
overlay toggle — the one small piece of literal duplication across otherwise-unrelated chart
features.

---

## PART 2 — TABLES

### 2.1 Shared table primitive

`components/ui/table.tsx` — a real HTML `<table>` (shadcn-style primitive: `<thead>`/`<tbody>`/
`<tr>`/`<th>`/`<td>`), default header `h-10 px-2 text-left`, default cell `p-2`, default row
`border-b hover:bg-muted/50`. Note the base primitive's own defaults reference **generic
shadcn tokens** (`--border`, `--muted`), not the app's `border-card`/`surface-2` — the
dark-theme values are numerically identical to those tokens, but every consumer that wants an
explicit, named-token hover/border must override it manually (most do; some don't — see §2.16).
Used by: Watchlist, Momentum, Financials, Ratios, MetricsGrid, Analyst Ratings' Recommendation
Details table, Step 3's InputRow/PBBandsTable, Institutional Ownership's Top-Holders table
(shelved), and the historical (now-deleted) Insider Activity transactions table.

Screener and Sector Heatmap deliberately do **not** use this primitive (see below).

---

### 2.2 Screener — cards, confirmed NOT a table

`components/screener/ScreenerCard.tsx` + `app/screener/page.tsx`. No `<table>` anywhere —
each result is a `<Link href="/tickers/{ticker}" target="_blank">` card in a plain CSS grid
(`grid-cols-1 sm:grid-cols-2 xl:grid-cols-3`, 18 cards/page). Card content: ticker + company
name + Overall `ScoreBadge`, company-type/sector chip, a fundamental pill row (Moat/Valuation/
vs-SPY), a separately-grouped technical pill row (Weinstein/Reversal/Pullback), and a 4-column
stat strip (Quote/Mkt Cap/P/E/Beta).

**Sort**: a `<select>` dropdown + Asc/Desc toggle button — not click-on-header (there are no
column headers, since this is cards not a table). **Pagination**: numbered page buttons +
Prev/Next (active page = `bg-brand text-white` — **literal Tailwind white**, the only
non-token color found in Screener). **Empty/loading/error**: plain `<p>` text, no skeleton
component. **Row click**: whole card opens the ticker page in a new tab.

---

### 2.3 Watchlist table — real `<table>`

`components/watchlist/WatchlistTable.tsx`. Real `<table>` via the shared primitive, wrapped in
a `rounded-lg border-border-card bg-surface` card with a `max-h-[70vh] overflow-auto` scrollbox
(a deliberate, commented 2-axis-scroll fix from a same-day CSS bug).

**Columns** (13): Ticker (mono, violet if speculative-growth), Sector, REV/NI/CFO (mini bar
charts, §1.2, not sortable), Moat (`SignalBars`), Value (`SignalBars`), Analysis (flat tier
chip + optional "⚠" for caution), Rating (colored text), Mkt Cap, Beta, P/E (all mono,
right-aligned, sortable), a remove-icon column. Ticker/Sector left-aligned; REV/NI/CFO/Moat/
Value/Analysis center; Mkt Cap/Beta/P/E right.

**Sort**: **click-header, multi-column** (up to 4 rules, cycling append→flip→remove, shown via
a small superscript priority numeral once 2+ rules are active) — the most sophisticated sort
UX of any table in the app, persisted per-watchlist in `localStorage`.

**Colors**: header row explicitly re-applies `hover:bg-surface-2` (named token, overriding the
base primitive's generic default); body rows leave the base primitive's generic
`hover:bg-muted/50` **unoverridden** — a real, if visually-coincidental, inconsistency between
the header and body of the same table. Border: `border-card` (wrapper/header), `border-subtle`
(body rows, lighter). No striping, no row-selected state; "caution" only shows via an inline
glyph, never a row-level tint.

**Behavior**: sticky header inside its own scrollbox; horizontal scroll via `min-w-[1000px]`;
no pagination (capped at 100 tickers); whole row is clickable (`cursor-pointer`) except the
remove-button cell; empty/loading/error are plain bordered/pulsing/red text.

**Formatting**: `fmtCompactMoney` (Mkt Cap), `fmtNumber` (Beta/P-E, 2-decimal).

---

### 2.4 Momentum table — real `<table>`, but styled inconsistently with Watchlist

`components/momentum/MomentumTable.tsx`. Real `<table>` via the shared primitive, but rendered
**with no wrapping card container at all** — no `rounded-lg border bg-surface` div, no
`bg-surface-2` sticky header — unlike Watchlist's own treatment of the same base primitive.

**Columns** (9): Rank (center), Ticker (link, brand-colored), Company, Moat (`MoatPill`
chip variant), 3mo/6mo/12mo/Composite (mono, signed `pnlClass` color), Score (mono, **always
plain tertiary gray, never sign-colored** — the one column inconsistent with the others in
its own table).

**Sort**: **none at all** — fixed by backend rank; no click-header, no dropdown (the only
sortable-data table in the app that isn't sortable). **Row click**: only the Ticker text is a
link — the rest of the row does nothing (unlike Watchlist's fully-clickable row). No sticky
header, no forced horizontal scroll, no pagination (hard-capped to top 10 client-side). Header
row uses the same wording convention (`text-xs font-semibold uppercase tracking-widest
text-text-tertiary`) as Watchlist's, just without the `sticky`/`bg-surface-2` additions.

---

### 2.5 Sector Heatmap grid — ARIA-table CSS grid, not a `<table>`

Covered in full under §1.6 (color logic); as a "table" specifically: `role="table"`/
`role="columnheader"`/`role="row"`/`role="cell"` divs using `display: contents` so each
`role="row"` wrapper's children join the parent grid's column tracks directly. Row-label
column left-aligned, every return-window column right-aligned. **Sortable, single-column**
(click header, direction flips on re-click of the same column). No row-divider borders at all
(only the grid's own gap reveals the page background between cells), no sticky header, no
zebra striping, ticker names deliberately **not** links. Horizontal scroll via `min-w-[44rem]`
on narrow viewports.

---

### 2.6 Market Breadth — confirmed no table

Grep across every `components/breadth/*.tsx` file: zero `<table>`/`role="table"`/grid-of-rows
constructs. It's 4 stat tiles (each its own card) + 2 chart panels (§1.7), nothing tabular.

---

### 2.7 Financials tab statement table

`components/ticker/FinancialsStatementTable.tsx`, real `<table>`. "Metric" column + one column
per period (annual/TTM or quarterly, toggle above the table); label left, all period columns
right-aligned. **Not sortable** (fixed order). Rows group under collapsible section headers
(click to collapse/expand, per-group `useState`, not persisted); ungrouped statements (Income
Statement) have no group headers at all.

**Sticky header AND sticky first column simultaneously** — the only table in the app that
sticks on both axes at once, with a `max-h-[70vh]` vertical scrollbox. Row hover is
**explicitly disabled** (`hover:bg-transparent`, overriding the base primitive's default) — a
third distinct hover convention alongside Watchlist's (token-based header only) and Momentum's
(unoverridden generic default). Values are `font-mono tabular-nums`, right-aligned; emphasized
rows (subtotals) render bold/`text-primary`, others `text-secondary`. Null → em dash. A small
inline "SEC cell-check" trigger button appears next to two specific line items (Income
Taxes/Interest Paid) known to have FMP coverage gaps. Money/share values use `fmtTableNumber`
(no "M" suffix — a one-time "figures in USD millions" caption covers units instead), unlike
the "M"-suffixed `fmtTableMoney` used elsewhere (e.g. §1.2's chart headlines) — a real,
documented formatting split worth knowing before writing a single "money format" table rule.

---

### 2.8 Ratios tab table

`components/ticker/RatiosTable.tsx` — structurally a near-verbatim twin of the Financials
table (same sticky-both-axes behavior, same disabled hover, same group-collapse), differing
only in per-column unit formatting (adds ratio/percent/days formatters) and lacking the
SEC-cell-check buttons and the annual/quarterly toggle (ratios are annual+TTM only, since
quarterly ratios currently 402 on the FMP plan).

---

### 2.9 Analyst Ratings tables/lists

- **Recommendation Details** (`RecommendationDetailsTable.tsx`) — real `<table>`, fixed rows
  (Buy/Outperform/Hold/Underperform/Sell/Mean/Consensus/Target) × time-bucket columns. Sticky
  first column only (no sticky header — short, embedded table). Hover disabled, same as
  Financials/Ratios. A rare **cell-specific tooltip** on just the Consensus/Current cell,
  clarifying it's FMP's live text vs. every other column being Fathom-computed.
- **Current Distribution** (`CurrentDistributionList.tsx`) — explicitly **not** a proportion
  bar by design ("precision matters more than visual proportion" — its own comment): plain
  divider-separated rows, colored swatch + label + count.

---

### 2.10 Valuation (Step 3) tables

- **Input/output rows** (`InputRow`/`ManualInputRow`, `Step3Card.tsx`/
  `ManualCalculationPanel.tsx`) — real, headerless `<table>`. Deliberately **one single shared
  table for an entire method's whole field set** (not several sibling tables), and every label
  cell is forced to 2 lines (blank placeholder sub-line when there's no real note) so every row
  is identically `h-12` by construction — the most detailed anti-layout-drift comment found in
  the whole audit.
- **P/B bands table** (§1.5) — real `<table>` with a header, 5 fixed rows + Last Close, Mean
  row bolded — the only row-emphasis-via-boldness pattern outside the Financials table's own
  `item.emphasis` mechanism.
- A native `<details><summary>` "Method selection reasoning" trace list (the only use of
  native `<details>` in the audit, vs. the `Collapsible` component used everywhere else),
  positive/tertiary/warn colored per passed/failed/unknown step.

---

### 2.11 MetricsGrid (ticker header stat tables)

`components/ticker/MetricsGrid.tsx` — real, headerless `<table>` per stat group, 2-column card
layout. Label `text-xs uppercase text-tertiary`; value `font-mono tabular-nums text-primary`,
right-aligned, with an optional inline "⚠" (outlier flag, `text-warn`) or "ⓘ" (methodology
tooltip) — a different glyph/icon convention than `OutlierWarningNote`'s own bullet-list
(§2.13), for a conceptually similar "flagged metric" idea.

---

### 2.12 Settings pages — a genuinely separate color system

**Major, codebase-wide finding**: every Settings-page component
(`components/settings/*.tsx`) uses **raw Tailwind `zinc-100`…`zinc-950`** (plus stray
`red-400`/`sky-400`/`sky-500`) instead of the app's design tokens used everywhere else. This
is confirmed **deliberate**, not drift — `components/ui/NumberStepper.tsx`'s own comment says
it matches "the form's own Save button... keeps every button on this page visually consistent
with the one the styling report called out as 'styled correctly'". It's a self-consistent
sub-palette, but a real, second color system running alongside the main token set.

- **Data Groups table** (`FmpDataGroupsSection.tsx`) — a hand-rolled bare `<table>` (not the
  shared primitive). Columns: On/Group/State/Last success/Required tier/Feeds. State pill:
  3 of 4 states use real tokens (`live`→positive, `not_on_plan`→warn, `restricted`/
  `failing`→negative) but `cached_only` is a bespoke raw zinc combination with no token
  equivalent.
- **Scheduled Jobs table** (`ScheduledJobsSection.tsx`) — a bare `<table table-fixed>` with an
  explicit `<colgroup>` (the only table in the audit using either). Status dot colors:
  `ok`/`failed`/`overdue` use real tokens, but `unknown`→raw zinc and **`skipped`→
  `bg-sky-500`/`text-sky-400`, a blue with no reference-token equivalent at all** — the only
  semantic status color in the entire app that isn't traceable to any given token.
- **Liquidity Zone / Weinstein / Moat / Discount Rate settings forms** — plain labeled-input
  grids (not tables/lists structurally, though Discount Rate renders one card per region — a
  list-of-cards pattern currently showing exactly one card). All 4 forms' top-level error text
  uses raw `text-red-400`, not the `text-negative` token used for errors everywhere else in
  the app.
- **Saved Screener Filters** (`SavedFiltersBar.tsx`) — the one Settings-adjacent surface that
  **does** use real tokens throughout (`border-input`, `surface`, `surface-2`, `brand`,
  `negative`, `warn`). A custom dropdown popover (not a table), rows with a check-icon for the
  active saved view and an inline delete button that turns solid red on error.

---

### 2.13 Technical tab lists (not tables, but list-like data displays)

- **`ChecklistCard`** (`components/technical/ChecklistCard.tsx`) — the single most-reused list
  pattern on this tab (5 cards). A plain `<ul>` of icon+label+status rows (CheckCircle/XCircle/
  plain dot), a caller-supplied status pill, and a mandatory, always-visible disclaimer footer
  (`border-warn/40 bg-warn/10 text-warn`) — this exact warning-box convention recurs verbatim
  across the whole app (LiquidityZonesCard, OutlierWarningNote, WeinsteinStageCard's pending
  block, Institutional Ownership's stale-data banner) and is one of the few genuinely
  consistent patterns found in this audit. **Note**: numeric values inside `ChecklistCard` rows
  are **not** rendered in `font-mono`, unlike numeric values in every table/other card in the
  app (NearTermCard, LiquidityZonesCard, all real tables) — a real typography inconsistency.
- **`LiquidityZonesCard`** — a `<ul>` zone ladder (not a table), price colored positive/negative
  by support/resistance, a dashed "broken zone" row using the two hardcoded hex colors from
  §1.1/§1.10, and blank placeholder rows to keep ladder height constant regardless of how many
  real zones exist.

---

### 2.14 Institutional Ownership top-holders table (shelved)

`InstitutionalOwnershipTab.tsx`'s `HoldersTable` — real `<table>`, no sort, no sticky header
(short table). **The one table in the entire codebase that keeps a genuine, named-token hover
effect** (`hover:bg-surface-2/50`) rather than disabling hover or leaving the generic default.
QoQ % column is sign-colored via `pnlClass`; Market Value/Shares are compact-formatted mono.

---

### 2.15 Insider Activity — fully deleted, documented from git history only

**Correction to CLAUDE.md**: this feature's frontend code is not "shelved, code left in the
tree" as documented — `git log`/`git show` confirm it was **fully deleted** in commit
`6410970`. Recovered from `6410970~1` purely for historical documentation (none of this exists
in the working tree today): a real `<table>` (`InsiderTransactionsTable.tsx`) with Date/
Insider/Type/Shares/Value/SEC-link columns, type-colored text (buy=positive, sale=negative),
a genuine `hover:bg-surface-2` row hover, a typographic distinction for non-cash-value rows
(smaller sans-serif "no cash value" text instead of the usual mono dollar figure), and a
client-side "Show N more" pagination pattern (the only pagination-within-a-table found
anywhere in the audit, vs. Screener's page-numbered pagination and everything else's
show-everything approach).

---

### 2.16 Cross-table summary

**Real `<table>` vs. cards/grid, by feature**:

| Feature | Structure |
|---|---|
| Screener | Cards (CSS grid of `<Link>`s) |
| Watchlist | Real `<table>`, shared primitive, card-wrapped |
| Momentum | Real `<table>`, shared primitive, **not** card-wrapped |
| Sector Heatmap | ARIA-role CSS grid, not `<table>` |
| Market Breadth | No table at all |
| Financials / Ratios | Real `<table>`, shared primitive, sticky both axes |
| Analyst Ratings (Recommendation Details) | Real `<table>`, shared primitive |
| Valuation (Step 3) | Real `<table>` (headerless input rows + P/B bands) |
| MetricsGrid | Real, headerless `<table>` |
| Settings (Data Groups / Scheduled Jobs) | Bare, hand-rolled `<table>`, **not** the shared primitive, separate zinc palette |
| Institutional Ownership (shelved) | Real `<table>`, shared primitive |
| Insider Activity (deleted) | Was a real `<table>`, shared primitive |

**Row-hover conventions — 4 distinct treatments coexist**:
1. Generic default, unoverridden (`hover:bg-muted/50`) — Momentum.
2. Explicitly re-applied as a named token on the header only, generic default left on the body
   — Watchlist (an internal split within one table).
3. Explicitly disabled (`hover:bg-transparent`) — Financials, Ratios, Recommendation Details,
   Step 3 input rows.
4. Explicitly a named token everywhere (`hover:bg-surface-2[/50]`) — Institutional Ownership
   (shelved), and historically Insider Activity (deleted).

**Sort UX — 4 different patterns, one per table family**: Screener = dropdown + Asc/Desc
button; Watchlist = click-header, multi-column (up to 4 rules); Sector Heatmap = click-header,
single-column; Momentum = no sorting at all.

**Row-click affordance differs per table**: Watchlist's whole `<tr>` is clickable; Momentum
only the Ticker text is a link; Sector Heatmap's ticker is explicitly *not* a link; Screener's
whole card is a link.

**Typography**: IBM Plex Mono (`font-mono tabular-nums`) is the near-universal numeric-cell
convention (Watchlist, Momentum, Sector Heatmap, Financials, Ratios, Analyst Ratings,
MetricsGrid, Institutional Ownership) — the one confirmed exception is `ChecklistCard`'s
generic row renderer (Technical tab cards), which never applies `font-mono` to its numeric
readings. Header cells are consistently `text-xs font-semibold uppercase tracking-widest
text-text-tertiary` everywhere except Settings' bare tables (`text-zinc-500`, no token).

**Container geometry**: `rounded-lg border-border-card bg-surface` is the near-universal card
wrapper; Momentum's table is the one exception (no wrapper at all, sitting on the bare page
background). Pill/badge corner radius (`rounded-md` ≈ 8px) is consistently narrower than card
radius (`rounded-lg` ≈ 10px) app-wide — a small but real inconsistency in the radius scale.

**Formatting reference** (`lib/format.ts`, used identically across every table above): `fmtMoney`
(signed `-` only)/`fmtSignedMoney` (`+`/`-`), `fmtCompactMoney`/`fmtCompactNumber` (K/M/B/T),
`fmtTableMoney` (always ÷1e6, always "M" suffix) vs. `fmtTableNumber` (same, no suffix — used
specifically where the table already captions its own units once), `fmtPct` (signed) vs.
`fmtPlainPct` (unsigned), `fmtRatio` ("12.3x"), `fmtDays`, `fmtNumber`. Every money/number
column in every table reviewed is `font-mono tabular-nums` with zero exceptions found.

---

## 4. Documentation/code drift found (facts for planning purposes, not fixes)

- **CLAUDE.md says Insider Activity is "shelved, code left in the tree"** — it is fully
  deleted from the frontend (git history confirms). Institutional Ownership, by contrast, genuinely
  is shelved-not-deleted, exactly as documented.
- **CLAUDE.md documents a `SignalBars` `maxBars` prop generalization** (for a since-removed
  5-bar Trend indicator) — the current component has no such prop; it is hardcoded to 3 bars.
- **`CircularScoreBadge.tsx`'s own comment claims `ScoreBadge` is "used by the 4 per-step
  Analysis cards"** — false; `ScoreBadge` is used only by `ScreenerCard`.
- **Sector Heatmap's page footnote** ("total return, price change plus reinvested
  distributions") contradicts the documented, price-only/dividend-excluded computation.
- **A "News" tab does not exist anywhere in the frontend** — `useNews.ts` is defined but has
  zero consumers; there is no News UI to audit despite it being a plausible candidate.
- **Growth Rate (Step 2) has no chart or table anywhere in the app** — a prose sentence plus
  2 bullets is the entire UI for it; no per-forward-year analyst-estimate table exists in the
  frontend at all, despite the backend computing full estimate detail for it.

---

*Compiled 2026-09-28 from 6 parallel read-only research passes over `frontend/`. No files were
modified to produce this document.*

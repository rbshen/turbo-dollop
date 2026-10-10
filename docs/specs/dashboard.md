# Dashboard tab (backend read)

A ticker-page tab, key `dashboard`, label "Dashboard" (not `overview`: the ETF page owns that key), planned second after Summary, not shown on the ETF page.
It consolidates the verdicts, the five scored steps with a small visual each, price and valuation, and the "Why might it be stuck?" section (moved here
from the Analysis tab), so the owner does not switch tabs. **Presentation only**: no scoring, threshold, Settings value or snapshot-log change. Built in four
phases: the backend read, the chart primitives (`docs/design-system-charts.md`), the tab, and the move of the stuck card.

## Sources

| Section | Source |
| --- | --- |
| A. Verdict strip (Overall, Valuation, Weinstein stage + since date, 5Y vs SPY) | The header's own hooks and components (`useTickerScore`, `useTickerSummary`, `useTrendAnalysis`; the same pills), so the values always match the header. **No new backend.** |
| B. The five steps (scored) and C. Price and valuation | `GET /api/tickers/{ticker}/dashboard` (below) |
| D. Why might it be stuck? (context, not scored) | Its own lazy `GET /api/tickers/{ticker}/stuck-check`, its own section, no verdict tones, amber only for Flagged |

## `GET /api/tickers/{ticker}/dashboard`

`data/dashboard_data.py::get_dashboard_data`, response `DashboardOut`. **Cache only: no FMP call, nothing written.** It calls steps 1, 2, 4, 5 and the
summary with `cache_only=True` exactly as `compute_ticker_score` does, then reads the stored `TickerScore` row, the manual Moat rating and the
cached daily bars (`read_cached_daily_bars_batch`). A step that raises degrades to an unavailable block; the rest still answer. Refresh and the
Moat save invalidate it with no extra code: both sweep every SWR key starting `/tickers/{ticker}`.

Top level: `applicable` (false with `not_applicable_reason` "Stocks only" for an ETF/fund), `has_data` (false when no profile and no score are cached),
`company_type`, `currency` (the reporting currency of the money series).

Every scored step block (`financials`, `growth`, `profitability`, `debt`) starts with the same head: `score` and `verdict` (the step function's own
cache-only result, stored key such as "Fail") and `stored_score` / `stored_verdict` (the `TickerScore` row's; they differ only while the stored row is
stale, and are null for a ticker with no row). **A verdict is never recomputed here**; the UI draws the words with the existing helpers
(`verdictLabel`, `debtVerdictDisplay`, "May not pass").

| Block | Fields |
| --- | --- |
| `financials` | `series`: last 5 completed fiscal years (TTM dropped) of revenue, net income, CFO. `scored_revenue`, `scored_net_income` (always true), `scored_cfo` and `cfo_exempt_reason` (Bank, Insurance, Property Developer, Commodity Company are scored on revenue and net income only; CFO is still returned, not scored) |
| `growth` | `growth_rate` (the stored analyst-estimate CAGR, percent), `target_analyst_count`, `basis`, base and target fiscal year |
| `moat` | `moat`, `rated`, `multiplier` (not rated = No moat 0.70; Narrow reads the saved setting); `price_series` weekly closes (the last bar of each week, real dates) from the cached daily bars, `price_years_covered`, `price_label` ("5-year price", or "N.N-year price (all the history cached)" when under 4.5 years are cached), `price_unavailable_reason`. **No score or verdict: Moat is a multiplier, not a step** |
| `profitability` | `roe` and `roic`: `years` + `values` (last 5 completed FYs, percent, for context), `scored` (the average the tier read, below), `exempt_reason` (ROIC: Bank, Insurance, Utility, REIT). `cutoffs`: excellent 15, good 12, marginal 8, min-year 8 (`scoring/step4.py`) |
| `debt` | `status` (scored, partial, not_applicable, insufficient_data), `ratios[]` each with `value`, `adjusted_value` (current ratio net of deferred revenue, only when it differs), `tier`, `points`, `excluded`, `direction` (floor/ceiling), `pass_line`, `hard_limit`; `unrescued_breaches`, `pass_with_caution` |
| `fair_value` | `fair_value_price`, `verdict`, `method`, `source`, `price`, `currency`, `band_low` / `band_high` (0.9 / 1.1), `discount_premium_pct`, and when missing `unavailable_reason` (`pass_method`, `insufficient_data`, `no_price`, `not_scored`) + `unavailable_detail` |
| `weinstein` | `weeks[]` (Monday-labelled week, stage) for the last 52 weeks, `stage`, `since_date`, `since_is_lower_bound`, `weeks_available`, `weeks_required`, `ma_label`; unavailable with a reason when fewer than `weeks_required` weeks are cached |

**Scored average (Profitability).** `roe.scored` / `roic.scored` is `scoring/step4.py::scored_ratio_summary`: the same steps in the same order the scorers
run (real points only, the recovery-aware exclusion of an already-recovered early dip, then the spike-robust average that leaves out an anomalous
high year), computed in `get_step4_data` off the exact cleaned series that was scored (so it includes the TTM point and drops periods with missing
equity). Fields: `average`, `minimum`, `points_used`, `points_total`, `recovery_excluded`, `spike_excluded`. ROE's negative-equity branch has no
average (it tiers on net income): `basis` is `negative_equity` and `average` is null. The tier reads the average, not the latest value; the per-year values are context.

**Debt lines come from the scoring code.** `pass_line` / `hard_limit` are `scoring/step5.py` constants: current ratio floor 1.0 / 0.7, Debt/EBITDA ceiling
3.0 / 4.0, debt servicing ceiling 30% / 40% (between the two is the monitor zone: a breach a tiebreaker can still rescue). REIT gearing (ceiling 45%), Bank
CET1 (floor 10%) and NPL (ceiling 5%) have one line only, so `pass_line == hard_limit` and there is no monitor zone (`GEARING_LIMIT_PCT`,
`CET1_FLOOR_PCT`, `NPL_LIMIT_PCT`, named in phase 1 and used by the scorers). Insurance is `not_applicable` ("Debt is not applied to insurers"); a Bank without
deposits (IBKR, HOOD) is `not_applicable`; a Bank missing CET1 or NPL is `partial` (the value it has, null for the other).

**Fair value band.** `band_low = 1 + VALUATION_UNDERVALUED_THRESHOLD` (0.9) and `band_high = 1 + VALUATION_OVERVALUED_THRESHOLD` (1.1) from `scoring/step3.py`: at or under
0.9x fair value reads undervalued, at or over 1.1x overvalued. The price is the summary's price (the cached quote the header uses; the last cached
close when there is none); the reason when there is no fair value comes from the cache-only valuation result (PASS method, or insufficient data).

**Weinstein series.** The production engine (`compute_stage_series` on `resample_to_weekly` of the cached daily bars, the live Weinstein settings,
`since` from the engine's own `_stage_since`), over the same `WEINSTEIN_LOOKBACK_DAYS` (5 years) the nightly job replays, so the last stage equals the
header's unless the settings changed since the last nightly run. `weeks_required` is `WeinsteinParams.min_weeks_required` (40 at the defaults, the
engine's own floor).

## Stuck-check payload, additive fields (phase 1)

The existing rows and figures are unchanged (the old card keeps working). New, on `StuckRowOut`: `series[]` (per-fiscal-year `{label, value}` points, last 5
completed FYs), `returns` and `growth`.

| Row | Added |
| --- | --- |
| 8 Relative strength | `returns`: `sector_etf`, `benchmark` ("SPY"), `band_pp`, and `windows[]` for 1, 3, 6 and 12 months with `stock_pct`, `sector_pct`, `spy_pct` (the SPY 1M and 3M included). Split-adjusted price returns, **no dividends** |
| 9 Margins | `series`: `operating_margin` per FY |
| 10 Growth | `growth`: `cagr_5y`, `sector_median`, `percentile`, `sector_peers`; `series`: `revenue_growth` (year on year) |
| 12 ROIC | `series`: `roic` per FY (null where FMP has no figure) |

Phase 4 removes Price context row 7 and the figures the redesign drops (gross margin, latest-FY growth, growth vs own CAGR).

## The tab (`components/ticker/DashboardTab.tsx`)

Registered in `lib/tickerTabs.ts` as `dashboard`, second after Summary (Summary stays the default; no URL state), lazy-mounted like the other tabs, absent from the
ETF variant, data-group badge `profile_quote`, `fundamentals`, `daily_prices` (`lib/dataGroups.ts::TAB_GROUPS`). A delisted ticker (`/universe` status) gets one plain line
on top. Each section loads and fails on its own.

| Section | Source | What it draws |
| --- | --- | --- |
| A. Verdicts ("As in the header") | `useTickerScore`, `useTickerSummary`, `useTrendAnalysis` and the header's own `AssessmentChipView`, `FairValuePill`, `WeinsteinStagePill`, `PerfVsSpyPill` | Overall, Valuation, Weinstein stage with the since date (and the data-starts caveat when it is a lower bound) as inline text, 5 years vs SPY. A missing piece is a neutral word ("Not scored", "No fair value", "No stage yet", "No data") |
| B. Five steps ("Scored") | `/dashboard` | One row per step with the **stored** score and verdict pill (`lib/dashboard.ts::stepPill`; the live `verdict` of the same payload is never drawn, so the page agrees with the header and the Screener; missing or insufficient_data is the neutral "Not scored"). Financials: three mini bars (revenue, net income, CFO) for 5 completed fiscal years, CFO marked "not scored" for Bank, Insurance, REIT and Commodity. Growth: the rate on a 0-20% `TierScale` with the 5/10/15% lines (from the endpoint) and the analyst count. Economic moat: the type pill ("Not rated" when unset), the multiplier, the 5-year price sparkline with the endpoint's label and span (type only when there is no series). Profitability: ROE and ROIC gauges on the **scored average** against the tier cut-offs (negative-equity ROE shows its basis note, an exempt ROIC its reason). Debt: a gauge per ratio from the endpoint's pass line and hard limit (amber zone between them for Standard and Utility; single-line gauges for Bank CET1 and NPL and REIT gearing; "Not applicable" with the reason for Insurance and a no-deposit bank) |
| C. Price and valuation ("Not part of the score") | the header's summary (price, fair value) + `/dashboard` (band, reasons, stage weeks) | `PriceRangeBar` with the price and fair value of the **header's summary** so it agrees with the valuation pill (the endpoint's cached quote is the fallback only); no fair value says why in plain words. `StageTimeline` for the last 12 months; unavailable shows the reason and the since date only |
| D. Why might it be stuck? ("Context, not scored") | its own `/stuck-check`, mounted when scrolled into view | See `docs/specs/stuck-check.md`. Relative strength as diverging bars (1M, 3M, 6M, 12M against the sector ETF, then SPY, with both returns beside each gap); earnings quality and capital allocation (rows 1, 2, 3, 5 with gauges, a Not flagged or Flagged tag and a meaning line; rows 4 and 6 figures only; the not-applicable reasons as one note); fundamentals trend (operating margin and ROIC mini bars, revenue growth against the sector median with the percentile); footer "Nothing flagged" |

Reused header components keep their native `title` hover text; everything the Dashboard draws itself has none.

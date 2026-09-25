# Full Stochastic divergence vs ThinkOrSwim / TradingView (2026-09-25)

**Status (2026-09-25): fixes 1, 2, 4 implemented -- Stochastic is now 5/3/3 EMA, TOS-parity, zero-range = 0. Fix 3 deferred, fix 5 rejected (keep the live bar). The tables below describe the PRE-fix SMA behaviour.** Original investigation was read-only. Reference = thinkScript `StochasticFull` with the user's live
settings: **K=5, slowing=3, D=3, EXPONENTIAL**; `FastK = c2 != 0 ? c1/c2*100 : 0`; `FullK = EMA(FastK,3)`;
`FullD = EMA(FullK,3)`; classic recursive EMA, alpha = 2/(n+1).

## 1. Implementations found

Exactly **one**. (Grep of backend + frontend for `stoch`.)

| Where | Detail |
|---|---|
| `backend/analysis/trend_structure/stochastic.py:14` `compute_stochastic` | 5 / 3 / 3, **SMA** smoothing (`rolling(3).mean()` twice) |
| `backend/data/chart_data.py:571` | sole caller; computed on the full fetched series, sliced by the visible-window mask (`_stochastic_points`, :285), NaN rows dropped |
| Displayed | Chart tab only, "Full Stochastic (5, 3, 3)" pane under RSI (`TickerChart.tsx:701` `addStochasticSeries`, label :1175; `ChartTab.tsx:163`). Ranges D_6M / D_1Y / D_2Y (daily) and W_4Y (weekly, resampled from FMP long-history dailies). |
| Not used by | Screener, Watchlist, signals (BB+RSI, Warren, LZ), scores. No crossover logic exists anywhere. |
| Frontend | Pure display. `setData(data.stochastic.map(...))`; no recompute, no re-smoothing. Only the 80/20 reference lines are frontend constants. |
| Settings | K/slowing/D/type are module constants; not configurable. |

## 2. Divergences (Fathom vs TOS reference)

| # | Item | Fathom | TOS | Impact |
|---|---|---|---|---|
| a | Periods | 5 / 3 / 3 | 5 / 3 / 3 | **None** (matches) |
| b | **Average type** | **SMA(3)**, SMA(3) | **EMA**(3), EMA(3), alpha 0.5 | **The whole gap.** See §3. |
| c | Smoothing order | ratio then average | ratio then average | None |
| d | Window | rolling(5) incl. current bar, `min_periods`=window; 2y+ history fetched, sliced after compute | incl. current | None. With SMA there is no warm-up dependence at all. |
| e | Zero range | NaN (documented choice in the docstring) | 0 | **0 occurrences** in 5y of AAPL/NVDA/SPY/TECL/KO/ORLY/IBKR, so no measured impact. Latent: pandas `ewm` skips NaN, so once EMA is used a NaN FastK would silently carry the previous value rather than read 0. |
| f | Price basis | All of H/L/C on the same basis (FMP `full`: split- and spin-off-adjusted, not dividend-adjusted; Massive `adjusted=True` / Yahoo `auto_adjust=False` fallbacks are split-only) | TOS: split-adjusted, not dividend-adjusted (TOS default) | None for the user's setup. See §4. |
| g | Source / bars | Chart daily: live FMP -> Massive -> Yahoo, uncached. Latest bar = whatever the provider returns (the chart path, unlike the nightly `SharedBarsCache` path, does not drop a same-day partial bar). Daily bars have no intraday anchoring/extended-hours question. | Completed and live bar | No measurable difference on completed sessions; only relevant intraday if Massive/Yahoo answer with a partial bar. |
| h | Crossover logic | none exists | n/a | n/a |
| i | Frontend recompute | none | n/a | None |

## 3. Measured impact (b)

Reference implementation run on the same cached daily bars (SharedBarsCache "1d", FMP basis, 5y, through 2026-09-24).
Reference EMA = first-value seed. Control: reference with SMA vs Fathom agrees to 7e-14, i.e. the port is faithful
and **SMA-vs-EMA is the only difference**.

Absolute difference in points, Fathom vs reference (max / mean):

| Ticker | K last 60 | K full | D last 60 | D full | First date |diff|>0.5 (K / D) |
|---|---|---|---|---|---|
| AAPL | 16.84 / 5.40 | 20.92 / 5.19 | 16.94 / 6.89 | 18.74 / 5.81 | 2021-10-05 / 2021-10-07 |
| NVDA | 13.57 / 5.74 | 22.10 / 5.39 | 13.82 / 7.03 | 21.83 / 6.02 | same |
| SPY | 14.26 / 6.23 | 20.60 / 5.57 | 13.87 / 6.33 | 20.43 / 5.95 | same |
| TECL | 16.65 / 6.16 | 22.89 / 5.43 | 15.80 / 7.10 | 20.74 / 6.03 | same |
| KO | 15.62 / 5.72 | 19.67 / 4.99 | 14.79 / 5.40 | 17.31 / 5.28 | same |
| ORLY (15:1 split 2025-06) | 16.03 / 5.86 | 20.03 / 5.05 | 15.37 / 5.07 | 18.20 / 5.50 | same |
| IBKR (4:1 split 2025-06) | 15.19 / 5.78 | 21.83 / 4.89 | 16.19 / 5.72 | 21.83 / 5.36 | same |

"First divergence" is simply the first bar where both series exist: they differ essentially from the start.
Typical gap is ~5-7 points mean, up to ~14-23 points on individual bars. Weekly (W_4Y): AAPL K 13.3 max / 4.9 mean,
D 17.7 / 5.5 (last 60); KO K 12.7 / 5.1, D 15.1 / 5.8.

Practical effect: SMA lags the EMA, so Fathom's D is systematically slower and its K crosses D at different bars.
Over the last 250 daily bars: AAPL K/D cross-ups Fathom 33 vs TOS 35 (downs 33 vs 36); NVDA 29 vs 32; SPY 34 vs 37.
Days with K>80 / K<20: AAPL Fathom 55/27 vs TOS 50/16; NVDA 49/37 vs 40/27; SPY 73/14 vs 69/11. So overbought/oversold
readings would also disagree with the user's TOS/TradingView.

### EMA sensitivity (does seeding / warm-up matter?)

Reference re-run, last 60 bars, max |change| vs first-seed / full 5y baseline:

- SMA seed: **0.0** (K and D), all six tickers.
- pandas `ewm(adjust=True)`: **<= 7e-15**.
- History starting 1y back (first-seed or SMA-seed): **0.0**.

Reason: alpha = 0.5, so seed influence decays by half per bar and is gone within ~40 bars (the FastK series
is the only input). **Seeding/warm-up cannot explain any gap**; nor can it be a source of a mismatch after the switch.
(2y-start in Fathom's smallest fetch is still ~500 bars.)

## 4. Price-basis sensitivity (reference EMA 5/3/3, last 60 bars, max / mean)

Yahoo pulled live read-only (`auto_adjust=False`) for this check; nothing written.

- FMP cache vs Yahoo raw split-only, AAPL/SPY: **0.000 / 0.000**. Closes agree to <0.02% over the full window.
  KO and ORLY showed a spurious 17 / 8-point gap on 2026-09-23/24 only, traced to Yahoo missing the 2026-09-22
  bar in that download (rolling windows over different bar sets), not a price difference.
- Yahoo split-only vs dividend-adjusted (H, L, C all scaled): AAPL 0.89 / 0.05, SPY 5.64 / 0.20, KO 13.6 / 0.87 (one
  window-spanning ex-dividend bar; mean under 1 point). ORLY (no dividends) 0.
- Mixed basis (raw H/L with dividend-adjusted close, the bug shape): SPY 24.0 / 12.4, KO 30.5 / 14.1.
  **Fathom does not do this**: all three of H/L/C come from the same provider row in every path. Recorded because
  it would be a large error if a future change adjusted only Close.
- Split ticker: FMP cache vs Yahoo raw for ORLY / IBKR is on the same split-adjusted basis (max close diff 0.012%).
  Spin-off adjustment (FMP-only, see CLAUDE.md "Daily prices: FMP") only affects the ~30 tickers listed there
  and only history before the spin date.

## 5. Eye-check table (5/3/3 EXPONENTIAL; reference values to compare with TOS / TradingView)

Bars from the cache, FMP basis. Latest completed session in cache = 2026-09-24.

**AAPL daily**

| Date | High | Low | Close | FastK | ref FullK | ref FullD | Fathom K | Fathom D |
|---|---|---|---|---|---|---|---|---|
| 2026-09-18 | 338.49 | 332.53 | 336.13 | 76.73 | 80.70 | 80.91 | 82.09 | 83.05 |
| 2026-09-21 | 339.64 | 333.05 | 338.98 | 94.15 | 87.43 | 84.17 | 86.58 | 84.11 |
| 2026-09-22 | 345.34 | 338.75 | 339.75 | 63.13 | 75.28 | 79.72 | 78.00 | 82.22 |
| 2026-09-23 | 341.80 | 335.50 | 337.02 | 45.12 | 60.20 | 69.96 | 67.47 | 77.35 |
| 2026-09-24 | 338.91 | 334.30 | 335.92 | 26.46 | 43.33 | 56.65 | 44.90 | 63.46 |

**SPY daily**

| Date | High | Low | Close | FastK | ref FullK | ref FullD | Fathom K | Fathom D |
|---|---|---|---|---|---|---|---|---|
| 2026-09-18 | 762.00 | 757.97 | 761.69 | 86.54 | 68.78 | 53.69 | 63.51 | 41.97 |
| 2026-09-21 | 774.89 | 766.03 | 773.50 | 94.50 | 81.64 | 67.67 | 86.17 | 62.80 |
| 2026-09-22 | 775.14 | 772.57 | 773.38 | 93.11 | 87.37 | 77.52 | 91.39 | 80.36 |
| 2026-09-23 | 773.05 | 766.50 | 767.81 | 57.31 | 72.34 | 74.93 | 81.64 | 86.40 |
| 2026-09-24 | 768.95 | 763.25 | 767.18 | 53.64 | 62.99 | 68.96 | 68.02 | 80.35 |

If TOS/TradingView's FastK/FullK/FullD for these dates match the "ref" columns, the reference is confirmed and the
only remaining cause is Fathom's SMA. (I had no access to TOS/TradingView to confirm; the user's statement that both
match is the assumption.)

## 6. Proposed fixes, ranked (NOT implemented; awaiting approval)

1. **Switch smoothing to EMA (alpha = 2/(n+1), recursive, adjust=False) in `compute_stochastic`.** Removes 100% of
   the measured gap; seeding is irrelevant (§3), so any seed choice is fine. One function plus its tests
   (`analysis/trend_structure/test_stochastic.py` pins SMA values). Keep 5/3/3 defaults (already the user's setting).
2. **Zero-range -> 0** (TOS parity) before smoothing, so a flat window does not become NaN that EMA would silently skip.
   Zero occurrences today; cheap.
3. **Make K / slowing / D / average type configurable** (Settings, DB-backed like `LiquidityZoneConfig`, or a
   per-chart control). Not needed to match this user's setup once (1) lands; worth it only if the user wants to
   flip to TOS's script defaults (10/10/3 SIMPLE) or experiment. It would also need the chart-tab label
   (`TickerChart.tsx:1175`, `ChartTab.tsx:163`) to become dynamic. Recommend deferring.
4. Label: keep "Full Stochastic (5, 3, 3)" and add "EMA".
5. Optional/low: on the Chart path, drop a same-day partial bar (as `SharedBarsCache` does) so an intraday view
   does not show a moving last Stochastic value that TOS would also show anyway. TOS shows the live bar, so this may
   not be desired; leave as is unless asked.

Not a fix, but worth knowing: a dividend-adjusted feed would move the numbers by roughly 1 point mean (KO), so
"FMP split-only" is the right basis for parity with TOS.

## 7. Cleanup

Throwaway reference/comparison scripts lived only in the session scratchpad and were deleted; no production code,
DB row, or cache was modified (DB opened read-only; Yahoo read live without writing).

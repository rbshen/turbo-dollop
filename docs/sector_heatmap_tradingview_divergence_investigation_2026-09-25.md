# Sector Heatmap vs TradingView GICS index divergence (2026-09-25)

Read-only investigation. No code or data changed.

## Conclusion

**No bug.** Fathom's 3M figures for XLK, XLY, XLB (and the XLE/XLRE controls) reproduce exactly from two independent
sources (FMP direct, Yahoo direct) using the same two dates. The gap to TradingView is a difference between what is
being measured (an ETF vs the GICS index), not a calculation, date, ticker-mapping or adjustment fault.

## 1. Data source per ticker

`data/sector_heatmap_data.py` reads through `clients.shared_bars_cache.get_or_fetch_bars_batch(..., "1d", 730,
auto_adjust=False)`, which routes via `clients/daily_bar_sources.py`. The 5 ETFs have no cached FMP profile, so
`core.tickers.is_us_listed` treats them as US (no dot suffix) -> **FMP `/historical-price-eod/full`** (`daily_prices`
group) first, Massive then Yahoo only as per-ticker fallback.

Evidence it was FMP for all five on the run that produced the 2026-09-24 figures: the `CronRunLog` row
(2026-09-25 03:30 UTC) reads `11/11 funds, 0 still stale after fetch, 0 fell back from FMP (Massive 0, Yahoo 0)`.
So the earlier "excluded from the FMP migration" decision is out of date: since Phase 2 this job is on FMP.

## 2. Adjustment mode

FMP `full` = split- (and spin-off-) adjusted, **not** dividend-adjusted. The heatmap uses the plain `close` column.
Consistent across all 5 tickers; none is an outlier. (No dividend/total-return reconstruction anywhere in the path.)

## 3 & 4. Numbers (window 3M, anchor 2026-09-24, base 2026-06-24; both dates are real sessions, no fallback needed)

| Ticker | Base close | End close | Fathom stored | FMP direct | Yahoo direct (`Close`) | Yahoo `Adj Close` (for reference) | TradingView index |
|---|---|---|---|---|---|---|---|
| XLK | 183.05 | 194.71 | +6.37% | +6.37% | +6.37% | +6.49% | +11.51% (S5INFT) |
| XLY | 115.07 | 110.32 | -4.13% | -4.13% | -4.13% | -3.92% | +0.21% (S5COND) |
| XLB | 51.16 | 49.68 | -2.89% | -2.89% | -2.89% | -2.45% | -6.49% (S5MATR) |
| XLE | 53.57 | 62.60 | +16.86% | +16.86% | +16.86% | +17.55% | +16.67% (SPN) |
| XLRE | 44.51 | 41.65 | -6.43% | -6.43% | -6.43% | -5.64% | -6.38% (S5REAS) |

Closes in Fathom's `SharedBarsCache` match FMP's to the cent. Stored rows: `SectorEtfReturn`, `as_of_date`
2026-09-24, `base_date` 2026-06-24, `computed_at` 2026-09-25 03:30. Cache `max(bar_time)` is 2026-09-24 for all five.

## 5. Per-ticker verdict

- **XLK (-5.1pp vs S5INFT): expected divergence, no bug.** Fathom's number equals the independent price return.
- **XLY (-4.3pp vs S5COND): expected divergence, no bug.**
- **XLB (+3.6pp vs S5MATR): expected divergence, no bug.**
- XLE / XLRE controls: match TradingView within 0.2pp, and match the independent calc.

Dividends do not explain it either: total return would shift these by at most ~0.8pp (XLE/XLRE), nowhere near 4-5pp.

**Why the ETF differs from the index (hypothesis, not verified here):** the Select Sector SPDR funds cap single-name
weights (roughly 20-25% single / 50% for the sum of >4.8% positions), while the S&P 500 GICS sector indices are
uncapped cap-weighted. XLK and XLY are the two sectors where a few mega-caps dominate the index, so capping
redistributes weight to smaller names and the 3M paths separate; Energy and Real Estate have no such concentration and
track closely, which fits the control result. XLB's gap fits the same mechanism (LIN-type dominance) but is the least
obvious. I did not pull constituent weights or index levels to test this, so treat the mechanism as the likely
explanation, not a confirmed one. Also not checked: whether TradingView's S5xxx symbols are price-return (they
normally are).

## Incidental finding (docs, not code)

CLAUDE.md's "Sector Heatmap" section still says Yahoo-only, `Adj Close` total return, 7 windows. Actual current
behaviour: shared cache, FMP-first, plain split-adjusted `close`, 8 windows (1d added). Candidate doc-refresh follow-up.

Scratch scripts were run inline (no files created).

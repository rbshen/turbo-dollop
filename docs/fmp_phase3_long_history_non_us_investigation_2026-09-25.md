# FMP migration Phase 3, Part A — long-history + non-US daily prices (investigation, 2026-09-24/25)

Read-only investigation. No app code, DB write, crontab or toggle was touched. DB access was
`mode=ro`; helper scripts lived in the session scratchpad and were deleted afterwards. **Live FMP
calls: 15**, all per-ticker `/historical-price-eod/full` except two probes (see §3/§4): 11 full-history
calls (AAPL, KO, SPY, CRCL, SPCX, six HKSE names), 2 latency re-measurements at 10y (AAPL, 0005.HK), 1
`/historical-price-eod/dividend-adjusted` (AAPL), 1 `/historical-chart/1week` (AAPL, 404). Yahoo was
called live (yfinance) for parity only. Basis: `main` at cc63fba.

## Executive summary

1. **Scope is smaller than feared.** Remaining Yahoo *daily/weekly* call sites that belong to P3 are
   exactly three: Chart W_4Y (`chart_data.py:168`), the Analyst 10y overlay (`analyst_ratings_data.py:139`)
   and the non-US branch of the shared daily-bar cache (`shared_bars_cache.py:484-485`, plus the non-US
   fall-through in Chart D views). No stray index-symbol consumer exists (`^GSPC` is a stale orphan cache
   row; the Weinstein benchmark is SPY, already FMP).
2. **Non-US universe = 6 HKSE tickers** (0005, 0728, 0857, 0883, 0941, 3988 `.HK`), each with only ~2y
   (495 bars) cached. Symbols work **unchanged** on FMP; prices are HKD (local), which matches how the app
   already treats `quote_currency`. Nightly cost: +6 calls (~6-12 s), +6 more on the Sunday resync.
3. **FMP depth:** every long-lived ticker returns the **newest 5,000 rows (~19.9y, back to Jun–Nov 2006)** —
   the endpoint silently caps at 5,000 rows, it does not 402. Young IPOs return their full life. Full
   20y response ≈ 1.1 MB / ~1.8 s; a 10y request ≈ 0.56 MB / 1.6–2.0 s. Our key returns 10y+ with no
   402/limit (it behaves as Ultimate, as in Phase 0).
4. **There is no weekly endpoint** (`/historical-chart/1week` → 404). W_4Y today is a *native Yahoo
   `1wk`* fetch. Resampling FMP daily with the existing `resample_to_weekly` (W-FRI, shift −4d, first/max/
   min/last/sum) reproduces Yahoo's weekly bars: **522/522 weeks and identical Monday labels for AAPL, KO,
   SPY; open/high/low/close within 0.5% on 99.6–100%; volume 96.7–99.6%**, the only differences being the
   partial current week's volume and tiny volume-print differences.
5. **Parity (daily):** FMP `close` vs Yahoo split-adjusted `Close` over 10y: **100.00% within 0.5% (max 0.08%)**
   for AAPL/KO/SPY. HK vs the existing cache: 99.80–100% within 0.5% (all 6), vs live Yahoo 10y 99.88–100%.
6. **One real behaviour change to decide (Q1):** the Analyst overlay reads Yahoo **`Adj Close` (dividend-
   *and* split-adjusted)**. FMP `full` is split-only. Overlay values change materially for dividend payers
   (KO up to 36%, SPY 17%, AAPL 9% in 2016). FMP's `/historical-price-eod/dividend-adjusted` reproduces
   Yahoo's `Adj Close` to ≤0.08% if we want zero change — but split-only is arguably the *correct* basis for
   comparing against nominal analyst targets.
7. **FMP HK data has phantom holiday/weekend bars** (e.g. 2025-04-18 Good Friday, Sunday 2025-10-26,
   ~28–34 extra bars per 5y on 0857/0883). Yahoo has none. Needs a filter before non-US bars enter the
   cache (weekend drop + flat-copy drop), otherwise SMA/Weinstein windows are contaminated slightly.
8. **Architecture trap:** storing 10y on-demand rows in `SharedBarsCache["1d"]` collides with (a) the weekly
   `prune_old_bars` (keeps 6y of 1d), (b) `_preserved_lookback_days` (ratchets nightly refetch width) and
   (c) the "5y everyone" assumption in the Trend/LZ/breadth jobs. Recommend a **separate table** for long
   history (§9).
9. **Tiers:** long-history US (>5y) = **Premium** (Starter is documented 5y); non-US = **Ultimate**
   (`daily_prices_intl` is already seeded Ultimate/unwired). Neither boundary is observable from our key.
10. **Storage is trivial:** ~249 B/row all-in; on-demand 10y ≈ +0.3 MB/ticker (worst case all 600 tickers
    ≈ +190 MB); HK backfill ≈ +1 MB. VPS: `/` 25 G, 5.1 G free; `fathom.db` 1.28 GB.

---

## 1. Remaining Yahoo inventory (after Phase 2)

`grep` for `yahoo_client`, `yfinance`, `yf.` across non-test code. Only *fetch* sites listed.

| # | file:line | What it fetches | Consumer | Phase |
|---|---|---|---|---|
| 1 | `data/chart_data.py:168` (`_fetch_yahoo_bars`, called from `_fetch_bars`:206) | symbol, `interval="1wk"`, `period="10y"`, `auto_adjust=False`; also daily `1d` 2y/5y as the last fallback for D_6M/D_1Y/D_2Y | Chart tab: **W_4Y always**; D views for non-US or when FMP+Massive both fail | **3** (W_4Y, non-US D) / 6 (US fallback) |
| 2 | `data/analyst_ratings_data.py:139` (`_fetch_price_history`) | symbol, `1d`, `10y`, `auto_adjust=False`, reads **`Adj Close`** | Analyst Ratings "Price Target Trend" overlay | **3** |
| 3 | `clients/daily_bar_sources.py:227` (`YahooDailySource`) | batch, `1d`, period tiers 1mo…10y | (a) non-US tickers, `shared_bars_cache.py:484-485`; (b) Massive→Yahoo fallback for US | **3** (a) / 6 (b) |
| 4 | `clients/shared_bars_cache.py:500` | batch, `60m`, period 2y | Warren, BB+RSI | 4 |
| 5 | `data/chart_events_data.py:175-176` | `get_earnings_dates`, `dividends` | Chart E/D markers, only when FMP `corporate_events` fails/off | 6 |
| 6 | `clients/yahoo_cache.py:137` via `data/ticker_summary.py:152` | symbol, `5d` latest close (`YahooPriceCache`) | Header price when `profile_quote` off (Massive snapshot first) | 6 (plan §4.6) — see note |
| 7 | `pipeline/stale_data_health_check.py:185` | `1mo` `1d`, flagged tickers | Delisted-revival probe | 6 |
| 8 | `pipeline/backfills/backfill_entry_signal_events.py:96` | 60m, manual, already run | one-off | 4 / dead |
| 9 | `clients/technical_sources.py`, `pipeline/nightly_warren_signal_calculation.py:104` | route through #4 | Warren/BB+RSI | 4 |

Not on your list, flagged:
- **Row 6 (price fallback)** is on your P3 wording ("ticker-page price fallback") but is a *quote*, not
  bar history; the phase-0 plan puts it in P6 (replace with last FMP daily close). It only fires when
  `profile_quote` is off, and it uses the US session clock (`yahoo_cache._is_stale`) even for HK symbols.
- **`^GSPC`**: no consumer. Orphan `SharedBarsCache` rows (503, last bar 09-22) from the Yahoo era; the
  benchmark is `SPY` (`weinstein.py:39`). The 11 sector ETFs and SPY are US-routed → already FMP. No
  `^VIX` anywhere. `route_by_source` still documents `^GSPC` as US-by-no-profile.
- `analysis/trend_structure/weinstein.py`, `market_breadth_data.py`, `momentum_data.py`, `sector_heatmap_data.py`
  mention yfinance only in comments; they read `get_or_fetch_bars_batch`.

## 2. Current cached depth (Phase 2 FMP cache)

`SharedBarsCache interval='1d'`: 603 tickers, 736,141 rows. Span per ticker (last − first bar):
**min 0.27y, median 4.99y, max 4.99y**. Histogram (rounded years): 0y×3, 1y×5, 2y×10, 3y×5, 4y×3,
**5y×577**. Median 1,253 bars. So "long history" = anything beyond ~5y. The 26 short ones are young
listings plus the 6 HK names (2y, 495 bars, still Yahoo-sourced, 2024-09-19…2026-09-23).

Consequence for W_4Y: weekly SMA200 needs ~200 weeks (3.85y) of warm-up on top of 4y visible ⇒ ~7.9y
of dailies; the 5y cache cannot serve it, hence the current `10y` fetch. (The Analyst overlay needs
history back to `PriceTargetSnapshot`'s start, 2021-04, i.e. ≤5.5y — the 10y period is generous; a 6y
window would do. Decision Q6.)

## 3. FMP history depth (live, per-ticker)

`/historical-price-eod/full?symbol=X&from=1990-01-01&to=2026-09-24`:

| Symbol | rows | earliest | latest | bytes | latency |
|---|---|---|---|---|---|
| AAPL | **5000** | 2006-11-07 | 2026-09-24 | 1.14 MB | ~1.8 s |
| KO | 5000 | 2006-11-07 | 2026-09-24 | 1.12 MB | ~1.8 s |
| SPY | 5000 | 2006-11-07 | 2026-09-24 | 1.15 MB | ~1.8 s |
| CRCL (IPO 2025-06) | 329 | 2025-06-04 | 2026-09-24 | 74 KB | <1 s |
| SPCX (IPO 2026-06) | 72 | 2026-06-12 | 2026-09-24 | 16 KB | <1 s |
| 0005.HK | 5000 | 2006-06-22 | 2026-09-24 | 1.14 MB | 1.8–2.0 s |
| 0728.HK | 5000 | 2006-06-21 | 2026-09-24 | 1.11 MB | 1.8 s |
| 0857.HK | 5000 | 2007-01-31 | 2026-09-24 | 1.12 MB | 1.8 s |
| 0883.HK | 5000 | 2007-02-08 | 2026-09-24 | 1.13 MB | 2.0 s |
| 0941.HK | 5000 | 2006-06-21 | 2026-09-24 | 1.13 MB | 1.8 s |
| 3988.HK | 5000 | 2006-06-21 | 2026-09-24 | 1.12 MB | 2.0 s |

- **The 5,000-row cap is the finding**: "earliest" is the cap, not the listing date (0728.HK lists in 2004).
  10y+ is safely inside it; 20y+ is not obtainable in one call (would need `to=` paging — not needed).
- No 402/limit on any call. Row fields: `symbol,date,open,high,low,close,volume,change,changePercent,vwap`.
- 10y-window requests (`from=2016-09-25`): AAPL 2,513 rows / 576 KB / 1.56 s; 0005.HK 2,464 rows / 557 KB /
  1.98 s. A cold 5y call is ~1,250 rows / ~285 KB (Phase 2 measured ~88 s for the whole universe).
- The response already includes **today's bar** once the session is closed (run at 16:25 ET); the Phase 2
  `_completed_session()` filter handles the partial-bar case.

## 4. Weekly bars

- **Today:** `chart_data.py:168` fetches Yahoo native `interval="1wk"`, `period="10y"` (RANGE_CONFIG `W_4Y`).
  Daily views are daily bars. Nothing resamples for the chart (Weinstein and LZ *do* resample dailies via
  `weinstein.py::resample_to_weekly`).
- **FMP has no weekly endpoint**: `/historical-chart/1week?symbol=AAPL` → **404** (`[]`), consistent with the
  Liquidity Zone note in CLAUDE.md.
- **Resampling recipe that matches Yahoo exactly:** `resample("W-FRI")` with open=first, high=max, low=min,
  close=last, volume=sum, drop empty weeks, shift labels −4 days (Monday anchor). That is precisely
  `resample_to_weekly` — reuse it, no new code. Partial current week: it is emitted as an in-progress bar
  labelled by that week's Monday, same as Yahoo does. Holiday weeks (Mon closed) are still labelled by the
  Monday, again same as Yahoo.
- **Match vs Yahoo `1wk` (10y, live), FMP-daily resampled:**

| | weeks | O ≤0.5% | H ≤0.5% | L ≤0.5% | C ≤0.5% | Vol ≤0.5% | labels only on one side |
|---|---|---|---|---|---|---|---|
| AAPL | 522 | 99.62 | 100 | 99.81 | 100 | 97.89 | none |
| KO | 522 | 100 | 100 | 100 | 100 | 96.74 | none |
| SPY | 522 | 100 | 100 | 100 | 100 | 99.62 | none |

  Volume misses (1/7/11 weeks) are the partial current week (Yahoo's weekly volume lagged the last daily
  bar: KO 44.2 M vs 61.4 M) and ~0.1–10% consolidated-volume print differences seen in the daily volume
  too. Price fields are equivalent for charting.
- Server-side resample is cheap (5,000 rows). Client-side resampling is not needed and would break the
  server-computed indicators (EMA/SMA/BB/Stochastic are computed on weekly bars server-side).

## 5. Analyst 10y overlay

- **Path:** `GET /api/tickers/{t}/analyst-ratings` (`core/main.py:667`) → `get_analyst_ratings_data`
  → `_fetch_price_history` (`analyst_ratings_data.py:112`): live Yahoo, `period="10y"`, `interval="1d"`,
  `auto_adjust=False`, reads **`Adj Close`** (dividend+split adjusted), no cache; skipped when
  `cache_only`. Values feed `RatingHistoryPoint.price_on_date` via `_price_on_or_before`, only from the
  first real price-target point onward.
- **The "price-target-trend toggle" is the same data path** — there is only this one overlay fetch
  (`price_on_date` per history point); no second price source. The target line itself is FMP
  (`PriceTargetSnapshot`, split-adjusted `adjPriceTarget`).
- **Basis mismatch with FMP `full` (measured, 10y):** `FMP close` vs `Yahoo Adj Close` within 0.5%:
  AAPL 13.7%, KO 0.3%, SPY 2.7%; max difference 9.3% / 36.3% / 17.1%. By contrast
  `FMP /historical-price-eod/dividend-adjusted adjClose` vs Yahoo `Adj Close` (AAPL): 100% within 0.1%
  (max 0.08%). `FMP close` vs Yahoo *split-only* `Close` is the 100% match of §7.
- **Which basis is right?** The docstring says the overlay wants to be comparable to a *split-adjusted*
  target line; a dividend-adjusted price deflates older prices below what traded when the analyst wrote
  the target, so split-only (`full`) is the more faithful comparison and matches the Chart tab. But it is a
  visible change for dividend payers, so it's an explicit decision (Q1). If dividend-adjusted is wanted,
  `/historical-price-eod/dividend-adjusted` is **not in `ENDPOINT_GROUP`** yet — the registry test would fail
  until mapped (return keys are `adjOpen/adjHigh/adjLow/adjClose`).

## 6. Non-US symbol mapping, currency, calendars

- **Universe:** exactly six non-US listings in `TickerScore`/`SharedBarsCache` (all `exchange=HKSE`,
  `currency=HKD`): 0005.HK (HSBC), 0728.HK, 0857.HK, 0883.HK, 0941.HK, 3988.HK. No `.PA`/other suffix
  names are tracked. 585 tickers are USD-quoted (ADRs/OTC included, already US-routed).
- **Symbols:** all six work **unchanged** on FMP `/historical-price-eod/full` (200, 5,000 rows each). No
  mapping table needed. (4-digit zero-padded HK codes are FMP's own format.)
- **Currency:** FMP returns **local HKD prices** (0005.HK close 156.9, 0941.HK 78.9, 3988.HK 6.04 — same
  scale as the cached Yahoo bars, 99–100% within 0.5%). The app keeps bars in the quote currency by design:
  `quote_currency = profile.currency` (`ticker_summary.py:502`); FX only converts *fundamentals* from
  `reportedCurrency` (`step3_data.py::_resolve_fx_rate`). Bar consumers (Weinstein, LZ levels, chart) are
  scale-free or already local. ⇒ no double or missing conversion; **no FX work in P3**.
- **Calendar effects:**
  - **Phantom bars.** FMP HK carries days the exchange was closed: 2025-04-18 (Good Friday) on all six,
    Sunday 2025-10-26 (+ Mon 10-27 copy) on 0005, Sundays 2024-09-22/09-29 on 0883, plus 2016–17 holiday
    bars on 0857/0883 (75/81 FMP-only dates vs Yahoo over 10y). Weekend bars in 20y: 1/0/0/5/0/0. Flat
    OHLC copies in the last 5y: 0857 ≈30, 0883 ≈35, others 2–5 (US control: 0). Yahoo has none. Row counts
    5y: 1,256–1,262 for 0857/0883 vs ~1,228 for the others. Filter proposed: drop `dayofweek>=5` and any
    bar whose OHLC equals the previous bar's (Part B commit 2).
  - **Nightly overlap check (0.5% + Sunday resync)** compares only dates present in both; phantom bars do
    not trigger a false "restated" (verified: all shared-date diffs ≤0.71%). One non-blocking miss:
    0728/0941 2024-01-15 differ 1.6%/1.1% vs *Yahoo* (Yahoo's own print), not vs cache.
  - **Freshness clock is the US session** (`_is_stale`, `_provisional_last_bar_tickers`, `_completed_session`):
    (i) an HK-only holiday leaves the last bar behind the US "completed session", so the ticker reads stale and
    is refetched (1 harmless call/night until the next HK bar) — same "not holiday-aware" limit already
    documented; (ii) `_provisional_last_bar_tickers` uses US close 16:00 ET, so an HK bar fetched between HK
    close (04:00 ET) and 16:10 ET is treated as provisional and refetched — irrelevant for the 03:10 UTC
    cron (= 23:10 ET) but can cause redundant on-demand refetches. (iii) The job runs mid-HK-session
    (03:10 UTC): the HK bar dated *today* is partial and is correctly dropped by the `<= completed_session`
    filter; the previous HK day is complete. All acceptable.
  - Non-US last bar in cache is 2026-09-23 vs FMP 2026-09-24 (HK closed 08:00 UTC) — normal one-run lag.

## 7. Parity

Reference: **live Yahoo, `auto_adjust=False`, 10y** (the US SharedBarsCache is now FMP-sourced since Phase 2, so
the old Yahoo cache is gone for US names) and, for HK, both the existing Yahoo-sourced cache and live Yahoo.

**(a) AAPL / KO / SPY, 10y daily (2,512–2,513 days; FMP has 5,000):**

| | Close ≤0.1% | Close ≤0.5% | max | Open ≤0.5 | High ≤0.5 | Low ≤0.5 | Vol ≤0.5 |
|---|---|---|---|---|---|---|---|
| AAPL | 100 | **100** | 0.08% | 99.80 | 100 | 99.96 | 98.29 |
| KO | 100 | **100** | 0.08% | 99.96 | 99.96 | 100 | 98.61 |
| SPY | 100 | **100** | 0.00% | 100 | 100 | 100 | 99.92 |

Diff causes: none for Close (sub-0.1% rounding). Outlier OHLC: AAPL open 1.07% and low 2.74% on one day each
(single-print differences), KO open 1.19%; volume 27–31 days >1% apart, max 13% (consolidated-tape volume
differs slightly between vendors). No splits/spin-offs inside these 10y windows for these three
(Phase 2's spin-off basis note applies to other tickers, e.g. T/WDC/FDX, which are the ones to check if a
10y overlay/chart is opened on them — Q4).

**(b) HK, full cached window (495 bars each) vs cache — Close ≤0.5%:** 0005 100, 0728 100, 0857 99.80,
0883 99.80, 0941 100, 3988 100 (≤0.1%: 95.6–99.6). Max 0.71% (0883/0857, 2026-02-16, Lunar-New-Year
adjacent). High/Low/Open ≤0.5% 98.8–99.8%; volume 98.4–98.8%. Dates only in FMP: the phantom bars of §6;
dates only in cache: none.
**vs live Yahoo 10y:** Close ≤0.5% 99.88–100% (0728 1.58% on 2024-01-15; 0941 1.08% same day; 3988 0.8% on
2019-04-30; 0883 0.55–0.71% on 2020-12 and 2026-02-16) — isolated single-day print differences.

Overall: closes within 0.5%: **≥99.8% for every sample**, well above the 99% gate; every cluster traced to
(i) sub-0.1% vendor rounding, (ii) HK phantom holiday/weekend bars, (iii) isolated single-day prints.

## 8. Plan tier per new data group

| Proposed group | Feeds | Needed tier | Basis |
|---|---|---|---|
| `daily_prices_long` (US >5y) | Chart W_4Y, Analyst 10y overlay (US-listed) | **Premium** (30y history) | FMP pricing: Starter = "up to five years of historical data", Premium = "up to thirty years" (see Sources); not observable on our key |
| `daily_prices_intl` (already seeded, unwired) | non-US nightly bars + non-US chart/overlay | **Ultimate** | Ultimate adds "global coverage"; Premium = US/UK/Canada (Sources) |
| existing `daily_prices` | US ≤5y | Premium (seeded) | unchanged — note Starter's 5y would also cover it |

- **Our key returns everything (no 402 anywhere)** — 15 calls, incl. 2006-era history and HKSE. So tiers are
  docs-only, as in Phase 0. The same group can be one tier for US and another for non-US: the on-demand chart
  for a non-US ticker must consult `daily_prices_intl` (Ultimate), the US one `daily_prices_long` (Premium).
- Mapping mechanics: `FMPClient.get` maps endpoint→group, so `/historical-price-eod/full` needs an explicit
  `group=` per call for US-nightly / US-long / non-US (the existing `/earnings` and `/quote` override
  pattern, `ENDPOINT_GROUP_OVERRIDES_USED`), plus `PROBE_ENDPOINTS` entries (canary: AAPL for long, `0005.HK`
  for intl) and `STATEMENT_TYPE_GROUP` if a cache key is used.
- FMP also documents a trailing-30-day **bandwidth** limit (Ultimate 150 GB, Premium 50 GB): our nightly
  daily-bar path is ~0.3 MB × 600; Part B adds ≪1 GB/month. Not a concern.

## 9. On-demand design inputs

- **Hook points.** W_4Y: `data/chart_data.py::_fetch_bars` (weekly branch, currently
  `_fetch_yahoo_bars`, lines 203-206) behind `GET /api/tickers/{t}/chart?range=W_4Y`
  (`core/main.py:593`). Overlay: `analyst_ratings_data.py::_fetch_price_history` behind
  `/api/tickers/{t}/analyst-ratings` (`main.py:667`). Both are single-ticker, page-view-scoped.
- **Sync vs background.** A cold fetch is 1.5–2.0 s (10y) — comparable to what Yahoo `1wk 10y` costs today —
  so **synchronous on first request** is acceptable: the page already awaits a live Yahoo call of similar
  size, then every later view is a local read (~ms). Background-fetch would show an empty chart on the
  first view and needs a poll/refresh mechanism: not worth it. The overlay is an optional add-on to an
  already-loaded page; keep it sync but fail-soft (empty overlay, as today).
- **Concurrent first requests.** No single-flight primitive exists in the codebase (`asyncio.Lock` only in
  `FMPClient._pace` and `_Pacer`). Two simultaneous cold opens would issue two FMP calls and both write. Safe
  because writes are an idempotent upsert / replace-in-one-transaction (`_write_rows(replace=True)`); cost is
  one redundant call. Recommend a small per-ticker in-process `asyncio.Lock` dict (cheap) — open Q9.
- **FMP failure / toggle off.** Follow the Phase 2 semantic: group not live → fall through to today's
  Yahoo path (until P6) and label the response `source="yahoo"`; group live but the FMP call errors → same
  fall-through, log type only (not the URL: it embeds the apikey, as `chart_events_data` already notes);
  a cached long row is served *even if the group is off* (cached-only), never wiped. Empty 200 → fall
  through, no cache write. No shrink guard (decided).
- **Where to store — do NOT put 10y in `SharedBarsCache["1d"]`.** Verified hazards: (1)
  `SharedBarsCache.RETENTION_DAYS` keeps 6y of `1d` and `prune_old_bars` (weekly, Sun 1:10) would trim a
  10y row back to 6y, causing a refetch loop; (2) `_preserved_lookback_days` would ratchet every nightly
  refetch/Sunday resync for that ticker to the 10y tier; (3) `tests/test_shared_bars_cache_prune.py` pins the
  6y window against consumer tiers; (4) Trend/LZ/Breadth/Momentum trim per consumer, but would all read a
  wider set. **Recommended: a dedicated table** `LongHistoryBars`-style (PK `ticker, bar_time`, same
  lowercase OHLCV + `fetched_at`), written whole-window by replace, keyed like `SharedBarsCache`, with its own
  prune-exempt status; or, minimum-change alternative, reuse `FundamentalsCache` `historical_price_eod`/`10y`
  (blob JSON, exists as a key, `daily_prices` group mapping already present; 0.5 MB blob/ticker). The table
  is cleaner (queryable window trim, no JSON parse of 2,500 rows per view) — Q5.
- **Staleness convention to reuse.** The close-aware check (`_most_recent_completed_trading_date`; row fresh
  iff its last bar == last completed session, plus the provisional-last-bar rule), **not** a flat TTL —
  exactly the Phase 2 rule; only the *last few* bars need refreshing, so a stale long row is topped up
  incrementally (`from = last_bar − 7d`, 0.5% overlap check, replace on restatement) rather than refetched
  whole.
- **Should the nightly job keep extending long rows?** Recommend **no**: leave them alone at night. A long row
  is topped up lazily on the next view (one small incremental call, sub-second) — zero nightly cost for
  unopened tickers and no coupling to the nightly universe. The 5y nightly rows and the long-history rows
  then overlap on the last 5y; to avoid two copies of the same 1,250 bars, the on-demand fetch could write
  only the *older* segment (bars before the shared cache's first bar) and the read path stitch the two.
  Stitching across two stores is more code/parity risk than +0.3 MB/ticker, so I recommend the simple
  full-copy in the separate table (Q5). Note the split-adjustment restatement risk grows with copies: a
  restatement replaces the nightly row (weekly Sunday resync) but not a stale long row → the incremental
  overlap check on next open catches it (same 0.5% rule).

## 10. Nightly impact for non-US

- **Tracked:** 6 (all HKSE). All in `TickerScore`, so in `load_full_tracked_universe`; only the Trend job
  (3:10) fetches; LZ/Momentum/etc. read the warm cache (LZ scope is W1–W5; check whether any HK name is on
  W1–W5 in Part B).
- **Routing today:** `shared_bars_cache.py:476` `route_by_source` → `non_us_tickers` → plain
  `YahooDailySource` (lines 484-485), never FMP/Massive. `is_non_us_ticker` (dot suffix) also short-circuits
  `chart_data.py:207` and `resolve_daily_bar_source_label`.
- **What changes:** `FMPDailySource` hard-gates on `effective_state("daily_prices")` (line 512); add a
  second instance/flag gated on `daily_prices_intl`, sending non-US through `FMPWithFallback`-style logic
  (FMP intl → Yahoo). `FMPClient.get_historical_price_eod` needs a `group` parameter. The phantom-bar filter
  and calendar behaviour of §6 go in `fmp_rows_to_frame` (or a non-US wrapper).
- **Cost:** +6 `full` calls/night incremental (`from=last−7d`, ~50 KB each), +6 full-window calls on the
  Sunday resync (~285 KB each at 5y): ≈ 6–12 s/night at the paced rate — negligible against the 44–60 s
  Trend run. One-time re-backfill 6 × 5y ≈ 12 s.
- **Consequences to recompute after backfill:** HK Weinstein (needs ≥40 weeks: 2y history already suffices, but
  the 104-week convergence note favours 5y), Liquidity Zones if any HK name is on a watchlist, `TickerScore`
  copies. Sector/US names unaffected.

## 11. Storage

- Measured: `sharedbarscache` table 116.75 MB + autoindex 50.9 MB + ticker index 15.0 MB = **182.7 MB for
  736,141 rows = 248 B/row all-in**. `fathom.db` = **1,279,401,984 B (1.19 GiB)**; `df -h`: `/` 25 G total,
  18 G used, **5.1 G free** (78%); `/tmp` tmpfs 470 MB, 403 MB free. (The 1.2 GB DB is dominated by
  `fundamentalscache` 976 MB, not prices.)
- **On-demand 10y** per ticker: ~2,520 rows × 248 B ≈ **0.62 MB** as a full copy (0.31 MB if only the
  older 5y segment were stored). **Worst case, all ~600 tracked tickers opened once: ≈ 375 MB full copy
  (≈ 190 MB older-segment-only).** Practical usage (a few dozen tickers): < 25 MB. If instead it is a
  `FundamentalsCache` JSON blob: ~0.56 MB/ticker raw (~0.3 MB on disk after SQLite page packing is not
  guaranteed) — similar.
- **HK backfill:** 6 tickers × (1,260 − 495) new rows × 248 B ≈ **1.1 MB**.
- 5.1 G free vs 375 MB worst case: fine, but the existing `backups/*.db.gz` rotation grows with the DB
  (compressed OHLCV ≈ 3–4×), watch `backup_db` disk-full history (2026-08-09 incident) if worst case is
  ever reached.

## 12. Proposed Part B plan and open questions

### Commit-by-commit plan

1. **Group registry (P1 pattern).** Add `daily_prices_long` (Premium, `falls_back=True`, live) and flip
   `daily_prices_intl` live (Ultimate, `falls_back=True`); `FMPClient.get_historical_price_eod(..., group=)`;
   `ENDPOINT_GROUP_OVERRIDES_USED`, `PROBE_ENDPOINTS` (AAPL / 0005.HK canaries), `STATEMENT_TYPE_GROUP` if a
   cache key is used; Settings > Status rows and `feeds` text; registry tests. *Tests:*
   `test_data_groups_registry` additions, effective-state and 402-canary cases per group.
2. **FMP bar cleaning for non-US** in `fmp_rows_to_frame` (or wrapper): drop weekend rows and flat-copy rows.
   *Tests:* fixture built from the real 0005.HK 2025-04-18/2025-10-26 cases; AAPL control unchanged.
3. **Non-US nightly path.** `FMPDailySource` parameterized by group; `shared_bars_cache.py` routes non-US to
   FMP(intl) → Yahoo; `resolve_daily_bar_source_label`; heartbeat message counts. *Tests:* routing matrix
   (US/non-US × group live/off × FMP empty), overlap-check with phantom bars, Sunday force resync.
4. **HK re-backfill + recompute** (`pipeline/backfills/backfill_fmp_daily_bars.py` extended to non-US;
   `--dry-run` first). **Parity gate step:** dry-run compare vs cache, gate ≥99% closes within 0.5%,
   traced diffs written into CLAUDE.md. Then recompute: `nightly_trend_calculation` for the 6 tickers,
   `nightly_liquidity_zone_calculation` (if any is W1–W5), `recompute_ticker_scores`. Verify Weinstein
   stage changes for the six, expect a since-date shift from phantom-bar removal.
5. **Long-history store + on-demand fetch.** New table (or cache key, Q5) + module
   `clients/long_history_bars.py`: close-aware freshness, incremental top-up with overlap check, replace on
   restatement, per-ticker lock, fall-through to Yahoo when the group is off/failing. *Tests:* cold fetch,
   warm read, stale top-up, restatement replace, group off → cached-only/Yahoo, concurrent first request,
   prune-exempt.
6. **Chart W_4Y on FMP.** `_fetch_bars` weekly branch → long-history store → `resample_to_weekly` → trim to
   the range's window; `ChartOut.source` "fmp"; keep Yahoo fallback. *Tests:* resample equals stored Yahoo
   fixture on the 3 tickers; partial current week; non-US (HK) weekly.
7. **Analyst overlay on FMP.** `_fetch_price_history` → long-history store (basis per Q1); non-US works.
   *Tests:* `price_on_date` alignment, basis pinned, off/failed → empty overlay.
8. **Non-US Chart D views** through the intl group (drop the `is_non_us_ticker` Yahoo short-circuit in
   `_fetch_bars`).
9. **Docs + ops:** CLAUDE.md (Daily prices P3 section, parity numbers, the 5,000-row cap, phantom bars),
   OPS_RUNBOOK, `crontab.txt` unchanged (no new job), status text.
   *Recomputes needed after 4 only;* 5–8 need none. No crontab reinstall.

### Open questions for you

1. **Overlay basis:** switch the analyst overlay to FMP split-only `full` (recommended; matches Chart and
   target line; visible change for dividend payers), or use `/historical-price-eod/dividend-adjusted` to
   reproduce Yahoo `Adj Close` (adds an endpoint to the registry)?
2. **Group naming/granularity:** one new group `daily_prices_long` for both US-long consumers, plus reuse of
   seeded `daily_prices_intl` for non-US nightly *and* non-US on-demand? Or separate long/intl-long groups
   (4 in total)?
3. **Tier defaults:** OK to seed `daily_prices_long` at Premium and keep `daily_prices_intl` at Ultimate,
   both "unverified"?
4. **Spin-off basis on 10y views:** accept that a 10y chart/overlay for spin-off tickers (T, WDC, FDX, EXC, …)
   will show the FMP-adjusted history (as in P2), unchanged?
5. **Storage shape:** separate long-history table (recommended), a `FundamentalsCache` blob, or stitching
   an older-only segment onto `SharedBarsCache`? (Prune window/ratchet hazards in §9.)
6. **How deep:** fetch 10y (matches today, ~0.56 MB) or the minimum needed (W_4Y ≈ 8y, overlay ≈ 6y)?
   Cap at the FMP 5,000 rows anyway.
7. **HK phantom bars:** drop weekend + flat-copy bars (recommended), or also apply a market-holiday calendar
   (`holidays-by-exchange`) — more accurate, more code?
8. **Non-US freshness clock:** accept the US-session clock (one harmless redundant call per HK holiday) or
   make freshness exchange-aware for HKSE?
9. **Single-flight lock** for concurrent first opens: add now, or accept one occasional duplicate call?
10. **Non-US on-demand long history**: same table/flow as US (needs Ultimate), or leave HK chart/overlay on
    Yahoo until P6 for fewer moving parts (only 6 tickers)?
11. **Price-fallback quote (row 6)** and delisted probe (row 7): confirmed P6, not P3?

### Sources
- [FMP pricing plans](https://site.financialmodelingprep.com/pricing-plans)
- [How to choose the right FMP plan](https://site.financialmodelingprep.com/insights/platform/how-to-choose-the-right-financial-modeling-prep-plan-for-your-workflow)
- [FMP API review, pricing & limits (2026)](https://www.findmymoat.com/tools/financial-modeling-prep-fmp)

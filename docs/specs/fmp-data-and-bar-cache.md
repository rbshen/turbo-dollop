# FMP data groups and the shared bar cache

FMP is Fathom's sole external data provider (since Phase 6b, 2026-09-26 — Massive and Yahoo were
both fully removed; the removal record is in `docs/archive/claude-md-history-fmp-migration.md`).
This document is the ground-truth reference for which FMP endpoints exist, which data group
gates each one, and the price-bar mechanisms that sit underneath the price groups specifically:
the shared daily/60m bar cache and its close-aware freshness rule (and the bug history behind
it), the daily-price (Phase 2), long-history (Phase 3) and intraday (Phase 4) sources, and
delisted/non-US handling. `CLAUDE.md`'s "Data groups" section carries the current-state
narrative for the per-group toggle system itself; this document is the companion
technical/investigation reference it points to, not a restatement of it.

## Endpoint inventory (ground truth, 2026-09-27 audit)

Every FMP request goes through `FMPClient.get` (`backend/clients/fmp_client.py`) — a repo-wide
search confirmed no FMP call bypasses this client anywhere in the app, `bin/start.sh`'s own AAPL
preflight included. The gate registry is `core/data_groups.py`: `ENDPOINT_GROUP` (endpoint →
group), `ENDPOINT_GROUP_OVERRIDES_USED` (endpoints reached by two groups via an explicit
`group=`), `PROBE_ENDPOINTS` (canary per group), `STATEMENT_TYPE_GROUP` (cache-key gate).
`tests/test_data_groups_registry.py` fails if any FMP endpoint or cached `statement_type` used
in the code is unmapped, so this inventory can't silently drift from the code without CI
noticing — an unmapped endpoint fails closed by design (see `CLAUDE.md`'s "Data groups"
section).

**35 distinct endpoint paths total** (34 fully gated by a single group; `/quote`, `/earnings`,
and `/historical-price-eod/full` are each reached by two groups via an explicit override).

### Multi-group endpoints (the same URL, two purposes)

| Path | Reached by | Resolution |
|---|---|---|
| `/quote` | `get_quote` → `profile_quote`; `get_forex_quote` → `fundamentals` (explicit `group=`) | A `fundamentals`-off state blocks Valuation's FX conversion even though `/quote` is otherwise live under `profile_quote`, and vice versa |
| `/earnings` | `get_earnings` (limit 8) → `fundamentals` (staleness-date lookups); `get_earnings_history` (limit 1000) → `corporate_events` (Chart "E" markers) | Same URL, two purposes and two groups |
| `/historical-price-eod/full` | default → `daily_prices`; `long_history_bars` passes `daily_prices_long` | Split represents history *depth*, not a different endpoint — see "Long-history store" below |
| `sec_company_facts` (**SEC EDGAR, not FMP**) | `clients/sec_edgar.py`, via `get_or_fetch` | Mapped to `fundamentals` in `STATEMENT_TYPE_GROUP` only to preserve the pre-Phase-6 pause behavior — there is no actual FMP endpoint here |

### Groupings that don't fit cleanly (worth a manual tier check, not code errors)

- `/quote`'s FX use sits under `fundamentals`, not `profile_quote`, purely so the Valuation FX
  lookup follows Valuation's own pause behavior — a `<CCY>USD` forex quote may sit in a different
  FMP pricing tier than a stock quote.
- `/earnings` serves both a `limit=8` staleness-date use and a `limit=1000` chart-history use
  under two different groups — tier may differ by `limit`, not verified.
- `/historical-price-eod/full` is split across `daily_prices`/`daily_prices_long` only by
  requested date range, and several `daily_prices` callers omit an explicit `group=` and rely on
  the default.
- `/delisted-companies` is filed under `index_membership` (moved from `corporate_events` 2026-09-27; it's a
  market-wide tracked-ticker-universe check, the same job family as the index scrapers, not per-ticker
  corporate-action data). `/splits` stays in `corporate_events` but currently feeds no chart marker.
- `/search-symbol`, `/search-name`, `/stock-price-change` sit under `profile_quote` ("Profile &
  quote") though search/price-change aren't obviously in the same FMP product tier as
  profile/quote.
- 6 endpoints (`/enterprise-values`, `/financial-growth`, `/key-metrics(-ttm)`, `/ratios(-ttm)`,
  `/analyst-estimates`, `/financial-statement-full-as-reported`) are all lumped under
  `fundamentals` — FMP's own catalogue may split these across tiers; the group's one recorded
  tier covers all 12 endpoints in that group uniformly.
- `/analyst-estimates` sits in `fundamentals`, not `analyst_ratings`, even though it's analyst
  data — it feeds Growth Rate scoring, which is why it's grouped with the fundamentals pause
  behavior instead.
- `/grades-*` and `/price-target-*` (5 endpoints) share one group and tier, but
  `/price-target-news` is only used by a spent one-time backfill script, never a live call path.
- `/nasdaq-constituent` is grouped with S&P/Dow under `index_membership`, but its plan tier may
  differ from the other two; the group canary only tests Dow.

**Confidence notes**: recorded tiers in the live DB are the user's own entries, not
FMP-verified facts — several DB tiers (Starter) are lower than the code's own seed defaults
(Premium), so the seeds can't be trusted as evidence either. Two groups (`news`,
`index_membership`) show no recorded `last_success_at` even though their code paths exist and
run — not investigated further (the news tab may simply not have been viewed since that column
was added; the index scrapers only run on Sundays).

### Unwired, dead, one-shot, or shelved

- **Shelved**: both `/insider-trading/*` endpoints (`insider` group seeded off; the tab itself is
  fully deleted, not just hidden — see `docs/archive/claude-md-history-features.md`, "Insider Activity").
- **One-shot / no live cron caller**: `/price-target-news` (only the spent
  `backfill_price_target_snapshots.py`); the `bulk_refresh_*` and `backfill_fmp_daily_bars.py`
  scripts (they reuse endpoints that are also live elsewhere in the app, so removing them
  wouldn't remove endpoint coverage).
- **Unwired research code**: `analysis/ma_magnet/data.py` calls `/historical-price-eod/full` but
  nothing in production imports it.
- **Fetched but unused downstream**: `/splits` (stored in `CorporateEvent`, no chart marker reads
  it yet). `/financial-statement-full-as-reported` is only exercised for Bank-classified tickers.
- **Seeded group with no endpoint**: none any more — the `extended_hours` (P5) group row was
  removed 2026-09-27 (it never got an endpoint, client method, or call site); see "Extended-hours
  pricing" below for what was tested toward eventually building it.

## The daily-bar cache staleness bug, and its two fixes (2026-09-16 / 2026-09-18)

Two compounding bugs, both in the shared daily-bar caching layer that `data/chart_data.py` and
(at the time) the Liquidity Zone job both read through, were found via a real, reproduced
production symptom (a Chart tab showing the wrong most-recent candle) rather than by inspection
alone.

### Bug 1 — wrong staleness window + colliding cache key (fixed 2026-09-16)

`clients/daily_price_sources.py`'s daily-bar fetch reused `settings.cache_staleness_days` (7
days, meant for slow-changing fundamentals) instead of a window matched to daily-price data's
actual change cadence, **and** hardcoded its cache key to a fixed lookback-years constant
regardless of the caller's actual requested window — so the Chart tab's D_6M/D_1Y/D_2Y/W_4Y
ranges (which need 2y/2y/3y/8y respectively) and the Liquidity Zone job (4y) all collided on one
shared cache row, with whichever caller fetched first each day silently winning for everyone
else. Confirmed live in production: a direct read-only DB query found the large majority of
FMP-sourced Liquidity Zone rows stuck a full trading day behind the most recent close.

**Fix**: a new `Settings.daily_bar_staleness_days` (default 1 day, day-scale rather than
week-scale) replaced `cache_staleness_days` at this one call site; the caller's real
`lookback_years` was threaded into the cache key instead of the fixed constant, so each range
gets its own genuinely isolated cache row.

*Code-vs-history note (verified 2026-09-29):* the symbols this fix touched no longer exist. The
module is now `clients/daily_bar_sources.py` (not `daily_price_sources.py`), and neither
`Settings.daily_bar_staleness_days` nor `_fetch_fmp_daily_bars` remain — the Chart tab bypasses
the cache and every nightly consumer goes through `SharedBarsCache`'s close-aware freshness
(next section), so the rule that survives is "a daily-bar cache key must include the caller's
lookback, and freshness must be close-aware, not a flat TTL." The original before/after evidence
(100 of 103 daily and all 103 weekly Liquidity Zone rows a trading day behind) is archived in
`docs/archive/claude-md-history-technical-signals.md`.

### Bug 2 — a flat TTL still isn't market-close-aware (fixed 2026-09-18, two different ways for two different consumers)

Fixing the TTL's *window* wasn't enough — a flat day-scale TTL still has no concept of *when*
during the trading day it was measured from. A cache row fetched any time before a given trading
day's close still locks in that day's *previous* close as "fresh" for up to the next 24 hours,
which routinely spans past the next session's open. Confirmed live: `fetched_at` on the affected
row was mid-morning, hours before that day's market close — genuinely correct at fetch time, but
stale by the time it mattered, for up to a full day.

**This was fixed two different ways for two different consumers, a deliberate divergence, not an
oversight:**

- **Chart tab**: reverted to a genuinely uncached, on-demand live FMP fetch for its daily ranges
  — bypassing the shared cache entirely for this one feature. Rationale: the tab's own module
  docstring already framed itself as "fully on-demand," and a warm cache bought comparatively
  little against many same-day page views anyway.
- **Liquidity Zone job** (and, later, every other nightly consumer of the shared cache — see
  "Shared bars cache" below): kept the cache — it fetches once per ticker per night regardless,
  so a genuinely-current warm row is real, load-bearing savings there — and instead added a
  **market-close-aware freshness check on top of the existing TTL**: compare the cached series'
  own last bar date against the most recently *completed* trading session (US/Eastern,
  weekday-aware, deliberately not holiday-aware — a market holiday just costs one extra harmless
  refetch), and force a live refetch (ignoring the TTL) whenever the two disagree.

**Confirmed live in production this fix was necessary, not theoretical**: a follow-up
investigation found this exact bug pattern *compounding* for the Liquidity Zone job specifically
— because FMP bars are fetched sequentially per-ticker (no bulk endpoint), and nightly run
durations vary night to night, whether a given ticker's own row read as "stale" on the next run
reduced to a coin-flip on relative run-speed, not anything about whether the cached data was
actually current. Some tickers' rows were found 2-3 nights stale, not just 1.

## The shared bars cache (`SharedBarsCache`, 2026-09-19; FMP-only since Phase 6b)

Once the market-close-aware freshness rule above proved out for the Liquidity Zone job, the same
mechanism was generalized into one shared table (`SharedBarsCache` in `core/models.py`, unique
`(ticker, interval, bar_time)`) read by every nightly bar consumer — Trend/Weinstein, Liquidity
Zones, Warren, BB+RSI, Sector Heatmap, Market Breadth, and Momentum — via
`clients/shared_bars_cache.py::get_or_fetch_bars_batch`. The bars are FMP's (see "Daily prices:
FMP migration (Phase 2)" and "Intraday bars: FMP (Phase 4)" below), raw / non-dividend-adjusted
(`auto_adjust=False`). The Chart tab is deliberately NOT a consumer of this shared table
(variable per-request window; same-day caching not worth it) and fetches live, for the same
reasoning that motivated its own on-demand revert above.

Key mechanics:

- **Key is `(ticker, "1d" | "60m")`** — Warren and BB+RSI both build their "2h" candles from raw
  60m bars, so they share ONE `"60m"` row; Trend and Liquidity Zones share the `"1d"` row.
- **Growth to the max window ever requested.** A request is served from cache only if the row is
  fresh AND its earliest bar reaches back to the caller's `lookback_days`; otherwise it refetches
  at `max(requested, preserved width)`. Preserved width is the stored span snapped DOWN to a
  width tier (`_preserved_lookback_days`) so a narrow consumer's refetch never shrinks a wide row
  and the ever-growing stored span never ratchets the download wider. Tickers are grouped by
  needed period, one fetch pass per distinct period (a 572-ticker Trend run does not re-download
  everyone at 5y because ~100 are also Liquidity Zone tickers). Each consumer gets only its own
  window back. Whichever overlapping job runs first each night does the one live fetch; no
  cron-order assumption exists. Width tiers: daily `1mo/3mo/6mo/1y/2y/5y/10y` (30/90/180/365/730/
  1825/3650 days), 60m `1mo..2y` only (no longer tier — the real 60m history limit is ~730
  calendar days).
- **Freshness is close-aware, never a flat TTL** (`_is_stale`): a row is trusted only if its LAST
  bar matches the most recently completed session for its interval. Daily:
  `_most_recent_completed_trading_date()` (US/Eastern, weekday-aware, NOT holiday-aware). 60m:
  `_most_recent_completed_intraday_bar_start()` — FMP labels bars by start (09:30..15:30, the last
  only 30 min); before 10:30 ET, on weekends, or pre-open it resolves to the prior trading day's
  15:30 bar, so overnight/weekend re-runs are not falsely stale. A mismatch forces a live refetch.
  `force=True` still live-fetches unconditionally.
- **Read path is deliberately not ORM-based.** Freshness/coverage come from one grouped MIN/MAX
  query per batch; the read is one column-only query with the caller's window trimmed in SQL;
  writes are one vectorized executemany upsert per ticker. The first version hydrated every bar
  as an ORM object twice per ticker and measured at minutes per nightly run at Warren's volume
  (~365k rows) — caught by a before/after timing measurement, not by tests.
- **Retention/pruning.** `clients/shared_bars_cache.py::RETENTION_DAYS` keeps **6y of `1d`**
  (6 × 365 days) and **3y of `60m`** (3 × 365 days) bars, trimmed per bar (never whole rows, so a
  survivor's last bar — what freshness reads — is untouched and `min(bar_time)` just moves
  forward to the first survivor) by `prune_old_bars`, run weekly from the existing
  `pipeline.prune_cache` job (Sundays 1:15 AM per `crontab.txt`; no new cron entry, so nothing new for `CRON_JOB_NAMES`)
  and previewable with its `--dry-run`. Windows are chosen against the consumers' real fetch
  tiers: each is >= the widest tier fetched (1d: Liquidity Zones' 4y lookback → the `5y` tier;
  60m: Warren's 730d → `2y`) plus a year of headroom, and BELOW the next tier up (`10y`), so a
  full-grown retained row still snaps down to the tier it was fetched at in
  `_preserved_lookback_days` (no ratchet) and the nightly coverage check never sees a pruned row
  as too narrow. `tests/test_shared_bars_cache_prune.py` pins both invariants against the
  consumers' real `LOOKBACK_DAYS` constants — a new consumer needing more than a window retains
  fails CI instead of refetching its full width every night. The 60m window is deliberately
  wider than any consumer needs: the 60m history that can be fetched is ~730 days deep, so a
  pruned 60m bar can never be re-fetched. Simulated (104 watchlist tickers, 469 Trend-only,
  176 B/row) five years out: unpruned 2.46M rows / ~430 MB vs. pruned 1.47M rows / ~250 MB
  (plateaus; unpruned growth is ~+57 MB/yr forever). A DELETE doesn't shrink the SQLite file —
  the freed pages are reused by later inserts, so it plateaus rather than shrinks; nothing
  VACUUMs it.
- **Trend's computed row is close-aware too.**
  `data/trend_analysis_data.py::get_trend_analysis_data` (the on-demand
  `GET /api/tickers/{t}/trend-analysis` path; the nightly job recomputes every ticker
  unconditionally and has no gate) compares `TrendAnalysis.bars_as_of` (date of the last daily
  bar the row was computed from) with `_most_recent_completed_trading_date()` and recomputes only
  when it is older — or NULL, i.e. a row from before the column existed, which self-heals with
  one recompute. (It previously trusted a stored row on a flat 1-day `computed_at` timer, which
  served a row a full session behind from the 4pm ET close until the next nightly trend run and
  recomputed an unchanged row every weekend day.) `cache_only=True` reads never recompute.
- **Known limits.** Not holiday-aware: a market holiday looks like one missed session and costs
  one extra (harmless) refetch that day — and, for the trend endpoint above, one recompute per
  on-demand read that day.
- **Other technical-signal consumers have no read-time freshness gate.** BB+RSI, Warren and
  Liquidity Zones read cache-only and recompute unconditionally every night; their only timers
  are the 7-day `STALE_AFTER_DAYS` abandonment sweeps (`entry_signal_data.py`,
  `warren_signal_data.py`, `liquidity_zone_data.py`), which are not freshness checks.
- **Verification after a nightly run** (no `sqlite3` CLI on this box; use python):
  `select ticker, interval, min(bar_time), max(bar_time), count(*), max(fetched_at) from
  sharedbarscache group by ticker, interval`. `max(bar_time)` should be the last completed
  session's date at 00:00 for `1d` and that session's 15:30 for `60m`; `min(bar_time)` should be
  ~2y back (`60m`, Warren/BB+RSI), ~2y (`1d`, Trend-only tickers) or ~5y (`1d`, Liquidity Zone
  tickers).

### Downstream ordering: the Screener's copy of technical fields

`compute_ticker_score` copies `weinstein_*` (+ `reversal_status`/`pullback_status`) from
`TrendAnalysis` (written by the 12:05 trend job), `bb_rsi_entry_signal` from the 12:20 BB+RSI job's
row, and `warren_active_signal_kind`/`warren_last_buy_fired_at` from the 12:25 Warren job's rows.
The full-universe recompute (`pipeline.nightly_score_recompute`) therefore runs at **3:25 AM**,
after all three and before the 3:30 backup (cache-only, zero FMP calls, ~30s; Warren is ~2 min
today, ~9 min theoretical worst case). Nothing else depends on that order: the trend job reads
only the shared bars cache and its own universe. The 2:55 fundamentals fetch (since the 2026-09-30 reorder, technical jobs first) scores each
ticker inline after the technical jobs, so it already sees same-night technical fields; the 3:25 sweep
is the backstop for ad-hoc tickers outside the index universe. Pinned by
`tests/test_cron_wiring.py::test_score_recompute_runs_after_every_job_it_copies_from` (and
`JOB_METADATA`'s time label by `test_job_metadata_sort_minutes_match_crontab`). After any night
the trend/BB+RSI/Warren job overruns 3:25, the affected tickers just read a night behind. The
night-behind bug this ordering fixed (2026-09-19) is recorded in
`docs/archive/claude-md-history-technical-signals.md`. Note that editing `crontab.txt` alone
changes nothing on the box — it must be reinstalled from `backend/` (`crontab crontab.txt`) and
`crontab -l` checked against the file.

## Daily prices: FMP migration (Phase 2, 2026-09-24)

FMP `/historical-price-eod/full` (data group `daily_prices`) is the source of the `SharedBarsCache`
`"1d"` bars for **US-listed** tickers, and (since Phases 6a/6b) the only one — formerly
Massive-with-Yahoo-fallback. The migration record (backfill run, parity check, recomputes) is
archived in `docs/archive/claude-md-history-fmp-migration.md`.

- **Basis — read this before comparing prices to another chart.** FMP `full` is split- **and
  spin-off**-adjusted, not dividend-adjusted. For ~30 tickers, pre-spin-off history therefore
  differs from a split-only source (e.g. TradingView) by a constant factor that ends exactly on
  the spin-off date (T +32.5% before 2022-04-11, EXC +40%, WDC +32%, FDX +24%, DHR +13%, O +3.3%,
  plus BDX, J, LEN, ILMN, ZBH, APTV, FLEX, SPGI, CMCSA, HON, IP, TRI). This removes an artificial
  cliff a spin-off leaves in a raw series; it is not a data error. No splits-only FMP endpoint
  exists (`non-split-adjusted` is raw; `dividend-adjusted` is split+dividend).
- **Routing = listing exchange, not domicile** (`core/tickers.py::is_us_listed`, exchange read
  from the cached FMP profile by `clients/daily_bar_sources.py::_profile_exchanges`). The code's
  `US_EXCHANGES` set is NYSE, NASDAQ, AMEX (FMP's name for NYSE Arca ETFs such as SPY), CBOE and
  **OTC** (by decision: CNSWF/EVVTY/SINGY), plus the spelling variants NYSE ARCA/NYSEARCA/ARCA,
  NYSE AMERICAN and BATS; a ticker with no cached profile (the sector ETFs) is US unless its
  symbol has a dot. 54 US-listed tickers have a foreign domicile (ACN, TSM, BABA, NVO, HSBC ...)
  and are US. Delisted-flagged tickers are skipped.
- **Source and toggle** (`clients/daily_bar_sources.py`): `get_daily_bar_source()` returns
  `FMPDailySource`. A ticker FMP returns nothing for (empty 200, error) lands in the
  `unserved_tickers` out-parameter and keeps its cached bars; `daily_prices` off / master off /
  above plan / restricted reports the whole batch unserved — **cache-only, and the daily-bar jobs
  record `skipped`** (Phase 6b). Heartbeat message: `N not served by FMP (cached bars kept)`.
- **Nightly incremental** (only the 12:05 trend job actually fetches; Liquidity Zones/Heatmap/
  Breadth/Momentum read its warm cache): per ticker, one `full?from=<last cached bar - 7d>` call
  (`FMP_OVERLAP_DAYS`). The last cached bar is always overwritten; any EARLIER overlapping close
  that differs from the cache by more than 0.5% (`FMP_OVERLAP_TOLERANCE`) means FMP restated
  history (split / spin-off / symbol reuse) and that ticker is refetched over its full window and
  **replaced** (delete + insert in one transaction, `_write_rows(replace=True)`). No splits
  calendar or bulk endpoint is used (`eod-bulk` etc. are Ultimate). A cache starting within 10
  days of the window start counts as covering it; a young listing (< 5y of history, ~22 tickers)
  is refetched in full each night (cheap: short histories). **The Sunday (UTC) run is a weekly
  full resync**: the trend job passes `force=True` (`WEEKLY_RESYNC_WEEKDAY_UTC`), so every ticker
  is refetched and replaced, closing the sub-0.5% restatement gap. Measured at the time: ~590
  calls, ~62 s at concurrency 10 (`FMP_CONCURRENCY`), paced to 50% (`FMP_RATE_FRACTION`) of the
  plan's documented rate (`FMP_PLAN_REQUESTS_PER_MIN`: Starter 300, Premium 750, Ultimate 3000);
  a full 5y backfill is ~88 s of fetching.
- **Partial bars.** A bar dated after the last completed session is dropped by the FMP source,
  and `shared_bars_cache._provisional_last_bar_tickers` treats a row whose newest write predates
  the close (+10 min, `_CLOSE_SETTLE`) of its last bar's own session as stale — a date-only
  freshness check once kept mid-session bars forever (2026-09-23 15:50 ET incident).
- **Chart tab** D_6M/D_1Y/D_2Y: FMP for every ticker while the group is live; group off or FMP
  failing/empty → an empty chart (Phase 6b). `ChartOut.source` is always `"fmp"`.
- **Backfill script** (`pipeline/backfills/backfill_fmp_daily_bars.py`, run once 2026-09-24):
  replaces each routed ticker's 1d rows with a fresh 5y FMP series; a ticker FMP cannot serve
  keeps its rows; `--dry-run` fetches and compares without writing.
  `backfill_market_breadth --rebuild` replaces `is_backfilled` breadth rows only.

**Parity gate accepted below its own bar, by explicit user decision.** The post-backfill parity
check (592 tickers, ~717k overlapping days) measured 98.14% of days within 0.1% against the
prior cache — under the 99% bar originally set for this migration. The shortfall was fully
traced to five understood, accepted buckets: the spin-off basis change itself; stitched/renamed
symbols now reading as one continuous series under FMP where the old provider had a visible
seam; a handful of confirmed single bad prints in the *old* cache (FMP was independently
verified correct on these); OTC thin-trading vendor differences; and FMP simply carrying more
history for some tickers than the old cache did. The user accepted the gate at 98.14% given
every discrepancy bucket was independently explained, rather than raising the FMP-side match
rate further. Known leftover: **AVB** is not fixed (FMP carries the same 2026-08-17 −64% cliff;
delisted-flagged, left as is).

**FMP silently caps a response at 5,000 rows (~19.9 years) — confirmed, not documented anywhere
by FMP, and no 402.** Relevant to any consumer requesting more than ~20 years of history; not
reachable by the nightly 5-year window, but directly relevant to the long-history store below,
which requests 10 years per ticker (~2,500 rows, ~0.56 MB, 1.6-2.0 s) in a single call and
confirmed it never needs paging at that depth. No paging exists anywhere in the app.

## Long-history store (Phase 3, 2026-09-25) — Chart W_4Y and the Analyst Ratings overlay

Two on-demand, per-ticker consumers need more history than the nightly ~5-year cache carries:
the Chart tab's **W_4Y** range (needs ~7.9 years of daily bars once weekly-SMA200 warm-up is
accounted for) and the Analyst Ratings tab's **10-year price overlay** on the price-target trend
chart. Both are served from a dedicated store, `LongHistoryBars` (PK `(ticker, bar_time)`),
**not** `SharedBarsCache["1d"]` and **not** a `FundamentalsCache` blob.

**Group / tier.** `daily_prices_long` (Premium: FMP documents 30y history on Premium, 5y on
Starter) = history beyond the nightly ~5y, feeding W_4Y and the overlay. Seeded unverified
(docs-only — the key returned 10y+ with no 402). `FMPClient.get_historical_price_eod` takes
`group=` (default `daily_prices`); `/historical-price-eod/full` is in
`ENDPOINT_GROUP_OVERRIDES_USED`; the `PROBE_ENDPOINTS` canary is AAPL over a 2016 window. The
store is `clients/long_history_bars.py::get_long_history`, one full ~10y copy per ticker on the
FMP `full` basis (`from = today - 10y`).

**Why a separate table, not an extension of the shared cache — a real architectural trap,
identified before it was built into, not discovered by breaking it.** Storing a 10-year window
directly in `SharedBarsCache["1d"]` would collide with three of that table's own existing
invariants: its weekly `prune_old_bars` job keeps only 6 years of `1d` bars, which would
immediately trim a 10-year row back down and trigger a permanent refetch loop; its "preserved
width" ratchet logic would widen every future nightly refetch for that ticker to the 10-year
tier, permanently inflating the nightly download for every other consumer sharing that row; and
the retention window is itself pinned by a test against the *nightly* consumers' fetch tiers —
widening it silently for one on-demand feature would break that test's own guarantee for
everyone else. A dedicated table sidesteps all three by construction: nothing nightly reads or
writes it, and nothing prunes it — pinned by tests. Rows are only appended by a top-up or
replaced wholesale (~250 rows/year/ticker, ~0.6 MB/ticker).

**Fill/refresh behavior**: lazily filled per-ticker, single-flight (an in-process lock per
ticker per event loop — an `asyncio.Lock` per (loop, ticker) — so two concurrent first-views of
the same never-yet-cached ticker don't double-fetch).
Cold → a synchronous ~1.6-2.1s full 10-year fetch. Warm and fresh (last bar = the last completed US session AND written after that session's
close + 10 min — the same close-aware rule the shared cache uses) → served with no live call, ~0.07s. Warm and stale → an incremental
top-up (`from = last bar - 7d`) with the same 0.5%-overlap restatement check the nightly job
uses, falling back to a full refetch+replace if history was restated. Group off (or master off / restricted) → an existing row is served as-is (cached-only, never
wiped), no row → `None`. Group live but FMP errors/returns empty → cold: `None`, nothing written;
warm-stale: the existing row is served. Errors log the exception type only (the URL carries the
API key).

**Chart W_4Y basis** (`data/chart_data.py::_fetch_fmp_weekly_bars`): the store's own dailies,
trimmed to 10 years, resampled through the same `weinstein.resample_to_weekly` (W-FRI, shifted to
Monday labels) every other weekly consumer in this app already uses — reused directly, not
reimplemented, since the resampling logic is genuinely data-source-agnostic.
`ChartOut.source="fmp"`; no stored row → an empty chart (Phase 6b). Weekly parity against a
recorded native-weekly reference fixture
(`tests/fixtures/weekly_parity_fmp_daily_vs_native_1wk.json`, kept as that historical record and
still used by `test_chart_weekly_fmp.py`) was verified: identical week-for-week labels, closes
within 0.5% on all 68 weeks, volume >= 90%. The in-progress week is a partial bar labelled by
its Monday. **The Chart tab's "zero persistent caching" has this one exception** (its daily
ranges stay uncached); the store is close-aware, so the 2026-09-18 stale-bar bug cannot recur
here.

**Analyst overlay basis, a real decision, not a default.** The overlay reads the store's FMP
`full` closes — split- (and spin-off-) adjusted, **not** dividend-adjusted — deliberately, not
because a dividend-adjusted endpoint wasn't available. The target line it's compared against
(FMP's own `adjPriceTarget`) is itself split-adjusted but not dividend-adjusted, and an
analyst's target is a nominal price at the time it was issued — a dividend-adjusted close would
deflate every earlier price by dividends paid since, which is the wrong comparison basis for
"was the stock trading near this target when it was issued." This also matches the Chart tab's
own basis, so the two views of the same ticker's price history agree. The overlay reads through
`data/analyst_ratings_data.py::_fetch_price_history`; no stored row → an empty overlay, never an
error. The dividend-adjusted endpoint is deliberately NOT in the endpoint registry. **10y views
therefore show FMP's spin-off-adjusted history** (T, WDC, FDX, EXC ...) — the same accepted basis
as Phase 2's nightly bars; no splits-only endpoint exists.

## Intraday bars: FMP (Phase 4, 2026-09-26)

FMP `/historical-chart/1hour` (data group `intraday_bars`, Premium, seeded unverified) is the
source of the shared **`"60m"`** `SharedBarsCache` rows behind Warren and BB+RSI, for
**US-listed** tickers (non-US tickers get no 60m bars). Both consumers share the rows; neither
engine changed. Since Phase 6b there is no fallback provider: with the group off, the cached rows
keep serving and the Warren/BB+RSI nightly jobs record `skipped`.

- **Basis (checked live 2026-09-26):** split-adjusted, NOT dividend-adjusted — the endpoint has
  no adjustment parameter. IBKR (4:1, Jun 2025) and FAST (2:1, May 2025) pre-split bars are
  consistent with the daily cache (FMP `full`). RTH only, labelled by bar START (09:30..15:30),
  timestamps naive strings in ET, newest first. **Never `extended=true`** (clock-anchored, wrong
  labelling).
- **Client/registry:** `FMPClient.get_historical_chart_1hour` (a literal path — the registry test
  scans for literals), `ENDPOINT_GROUP["/historical-chart/1hour"]`, an AAPL canary in
  `PROBE_ENDPOINTS`.
- **`FMPIntradaySource`** (`clients/daily_bar_sources.py`, same shape as `FMPDailySource`): FULL
  fetch when never cached, narrower than requested, `force`, or the cached rows are not all FMP's;
  otherwise INCREMENTAL `from = last bar - 3d` (`INTRADAY_OVERLAP_DAYS`) with a 0.5% overlap check
  (mismatch = restated history → full refetch + replace). Full fetches page newest-first by moving
  `to` to the oldest bar returned (~9 pages / 730 days), start no later than the cached first
  bar, and never write a partial history on a mid-paging error. Bars after the last completed bar
  are dropped. A ticker FMP does not serve (group off / restricted / error / thin answer) lands in
  the `unserved_tickers` out-parameter and keeps its cached bars.
- **Provenance forces the one-time replace.** `SharedBarsCache.source` (`"fmp"` | NULL; nullable,
  no backfill, only `"60m"` reads it). A ticker whose cached 60m rows are not ALL `"fmp"` — every
  pre-cutover row reads NULL (or the legacy `"yahoo"`) — is fully replaced on its next FMP fetch,
  so FMP bars are never layered on older-provider history. There was no separate backfill script:
  the first nightly run after the cutover did it.
- **Completeness check:** each fetched frame is scanned for sessions with fewer than 7 hourly bars
  (4 on half-days); short sessions are logged per ticker (`FMPIntradaySource.short_sessions`,
  `find_short_sessions`). Log-only — nothing is refetched or dropped.
- **Accepted side effect (reviewed, do not "fix"):** Warren signal dates replayed on FMP bars can
  differ slightly from the previous provider's, because small OHLC differences cross indicator
  thresholds on different bars. No compensating logic exists (measurement archived).
- **Cost:** nightly ~105 calls (one overlapping incremental per ticker); a cold full backfill
  ~945.
- **Not touched:** extended hours (P5), warm-up buffer / history depth / retention.
  `FMPTechnicalSource` is a thin reader of the shared cache.

## Delisted-ticker handling (2026-09-23; detection replaced in Phase 6a)

**TWTR, WBA, EA, AVB, EQR** are the five flagged tickers (TWTR, WBA, EA delisted; AVB and EQR merged
into Vivmark Residential, VMRK, trading from 2026-08-18) and stay in `load_full_tracked_universe`
forever (any ticker that ever got a `TickerScore` row never drops out), so the nightly bar jobs
would re-attempt them every night. **Provenance (corrected 2026-09-30):** all five carry
`delisted_at = 2026-09-24 10:17:02`, written by a manual `stale_data_health_check` run under the
*earlier staleness heuristic* (SharedBarsCache last daily bar more than 30 days old), not by the
`/delisted-companies` sync below — the sync only sets a NULL flag, so it never rewrote them, and
FMP's own delisted date is not stored anywhere.

- **`TickerScore.delisted_at: datetime | None`** (nullable, `_add_missing_columns`-backfilled) is
  set by `pipeline/stale_data_health_check.py::sync_delisted_flags` (weekly, Sundays 1:30 AM) from
  FMP `/delisted-companies` (group `index_membership`). The endpoint's page size is capped at 100
  (~157 pages / ~15.6k rows / ~15.4k unique symbols on 2026-09-26, so ~157 sequential calls a
  week); a tracked ticker listed with a delisted date on/before today is flagged. (An earlier
  version of this section said this was "verified against the live endpoint" for the five tickers
  above; that is not reproducible from cached data and is not what set their flags, see above.)
- **Detection rules.** Absence is never evidence: no flag for an unlisted ticker, and an existing
  flag is **never cleared** (the earlier staleness heuristic, live-probe revival and auto-clear
  are gone). Guards on a hit: a delisted date in the future is a scheduled delisting (ignored); a
  symbol whose cached profile `ipoDate` is after the delisted date is a reused symbol (ignored);
  FMP's `BF.B` matches our `BF-B`. A page error uses what was fetched and reports "delisted list
  incomplete" (paging ties can also drop a row at a page boundary; the weekly rerun catches it).
  **Open decision:** a relisted symbol stays flagged until someone clears `delisted_at` by hand.
- **The nightly bar jobs skip a flagged ticker** via
  `stale_data_health_check.load_delisted_tickers(session)`: Trend, Liquidity Zones and
  `data/momentum_data.py::compute_and_store_momentum_snapshot` drop it from the fetch and compute
  loop, and each summary carries `skipped_delisted_count`. Scoped to the DB-derived universe
  only — the trend job's `--tickers`/`--limit` escape hatch bypasses it. Market Breadth and Sector
  Heatmap need no change (their universes — `IndexConstituent` sp500 and 11 fixed ETFs — never
  contained these).
- **Nothing is ever deleted**: `TickerScore`, `FundamentalsCache`, Watchlist and ticker-page
  history stay intact; the flag stops price-bar re-fetching and (since 2026-09-30) hides the ticker
  from every Screener universe and the Screener's meta count (see overview.md, "Screener excludes
  delisted tickers"). The row itself is still recomputed nightly.

## US-listed tickers only (non-US cleanup, 2026-09-26)

Fathom supports **US-listed tickers only** — the listing venue decides, not domicile: NYSE/NASDAQ
ADRs and OTC names are US (`core/tickers.py::is_us_listed`; see "Routing" under Phase 2 above).
The earlier HK/France expansion is fully shelved. Non-US tickers get no nightly daily or 60m
bars; `route_by_source`/`is_us_listed`/`_profile_exchanges` remain and scope the price-target,
last-close and corporate-events universes.

- **Kept: the general reported→quote FX conversion (Step 3).** 14 US-listed ADRs (ASML, BABA,
  CCEP, CCJ, CNI, EVVTY, FER, MFC, NVO, PDD, RY, SINGY, TME, TSM) report in a non-USD currency but
  quote in USD, so `_resolve_fx_rate` still converts reported→quote (checked against cached
  profiles/income statements, not assumed). Only the HK/FR-specific layer went:
  `SUPPORTED_REGIONS` is now `{"US"}` (an ADR's domicile `country` such as CN/CA/TW redirects to
  the US discount-rate row, as it already did), the `HKD` currency prefix and HK wording are gone,
  and the leftover `HK` `DiscountRateConfig` row was deleted. The multi-region seeding code in
  `helpers/discount_rate_config.py` is generic and kept (tests use a synthetic second region).
- **Ticker search returns US-listed results only** (`data/ticker_search.py`, `is_us_listed` off
  each result's `exchange`), so a non-US ticker can't be added by search. The leveraged-ETP
  ranking stays (it applies to US ETPs too).
- **Screener Country filter removed**: `CountryFilter.tsx`, `TickerScore.country`,
  `SavedScreenerFilter.country`, the exchange→country derivation and the API fields. Both columns
  are dropped from existing DBs by `core/db.py::_OBSOLETE_COLUMNS` at startup.
- **Weekly safety net**: `pipeline.stale_data_health_check` first runs `pipeline/non_us_purge.py`,
  deleting any tracked ticker whose cached profile exchange is not a US venue (or, with no
  profile, whose symbol is dotted) from every table with a `ticker` column. Local-only.
  **Refuses (deletes nothing) if more than 2% of the tracked universe would go**
  (`DEFAULT_MAX_FRACTION = 0.02`) — that signals an exchange-name mismatch in `US_EXCHANGES`, not
  real non-US tickers; the report and heartbeat say "REFUSED".
- Legacy `source="yahoo"` handling in the shared bars cache is behaviour, not a stray reference,
  and stays. The weekly-parity fixture is `weekly_parity_fmp_daily_vs_native_1wk.json` (it still
  pins Monday-anchored weekly resampling). The one-time cleanup script
  (`pipeline/backfills/non_us_cleanup.py`, `--dry-run`, idempotent) and the leftovers sweep are
  recorded in `docs/archive/claude-md-history-fmp-migration.md`.

## Endpoint feasibility work not yet wired into the app

### Extended-hours pricing (P5, unbuilt)

A standalone feasibility test (2026-09-24, no app code touched) confirmed the current FMP plan
*can* support a real pre-market/regular/post-market/overnight "latest price" read, but needs two
endpoints combined, since neither alone covers all four session windows:

- **Pre-market and post-market "latest price"**: `GET /historical-chart/1min?extended=true` —
  an undocumented parameter (found empirically by testing candidate names side-by-side;
  `extended`, not `extendedHours`/`includeExtendedHours`, which are both silently ignored). Take
  the close of the most recent bar. This is the only endpoint confirmed to cover pre-market at
  all — `GET /quote` freezes at the 16:00 ET regular close and never reflects a pre- or
  post-market move, confirmed live side-by-side against real, current post-market prices at the
  same moment.
- **Overnight / weekend / holiday "last known price"**: either the same 1-minute chart's last bar
  of the most recent trading day, or `GET /aftermarket-trade`/`GET /aftermarket-quote`, which
  empirically just stops advancing once the post-market session ends and so already returns the
  correct frozen value with no extra date-math.
- **Regular session (09:30-16:00 ET)**: `GET /quote` is fine and cheaper — only the
  extended-hours behavior is broken, not the regular-hours one.
- **Session-state detection** (which of the four windows applies right now) has no FMP endpoint
  of its own (`is-the-market-open`/`market-hours` both 404; `exchange-market-hours`'s
  `isMarketOpen` only distinguishes regular-open from everything-else) — this needs to be
  computed client-side from wall-clock ET time plus `GET /holidays-by-exchange`, which does
  correctly report full closures and early closes.

**Real, accepted risks, not blockers**: `extended=true` is undocumented and could change or be
removed by FMP without notice, with no plan-tier signal to detect that beyond the bar range
silently shrinking back to regular-hours-only; a genuinely thin-traded ticker can show a
"latest extended-hours price" that's 30-60+ minutes stale relative to the current clock simply
because nothing traded more recently — an accepted, displayable characteristic (show the bar's
own timestamp), not something to engineer around; an early-close trading day's post-market
window starts at the adjusted close, not a fixed 16:00, which `holidays-by-exchange` reports but
which any future session-detection logic would need to combine correctly with wall-clock time
itself.

This remains genuinely unbuilt — there is no endpoint, client method, or call site anywhere in
the app, and the `extended_hours` data group row that had been seeded for it was removed
2026-09-27 (a future build would need to add the group back to `core/data_groups.py::GROUPS`).

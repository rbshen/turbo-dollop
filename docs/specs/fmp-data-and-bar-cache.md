# FMP data groups and the shared bar cache

FMP is Fathom's sole external data provider (since Phase 6b, 2026-09-26 — Massive and Yahoo were
both fully removed; see `CLAUDE.md`'s "Phase 6a"/"Phase 6b" sections for that removal's own
record). This document is the ground-truth reference for which FMP endpoints exist, which data
group gates each one, and the daily-bar caching mechanism (and its bug history) that sits
underneath the price-bar groups specifically. `CLAUDE.md`'s own "Data groups" and "Daily prices:
FMP" sections carry the full current-state narrative for the toggle system and the migration
phases; this document is the companion technical/investigation reference those sections point
to, not a restatement of them.

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
- `/delisted-companies` is filed under `corporate_events` for convenience; it's a market-wide
  reference list, not per-ticker corporate-action data. `/splits` shares that group but currently
  feeds no chart marker.
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
  fully deleted, not just hidden — see `CLAUDE.md`'s "Insider Activity" section).
- **One-shot / no live cron caller**: `/price-target-news` (only the spent
  `backfill_price_target_snapshots.py`); the `bulk_refresh_*` and `backfill_fmp_daily_bars.py`
  scripts (they reuse endpoints that are also live elsewhere in the app, so removing them
  wouldn't remove endpoint coverage).
- **Unwired research code**: `analysis/ma_magnet/data.py` calls `/historical-price-eod/full` but
  nothing in production imports it.
- **Fetched but unused downstream**: `/splits` (stored in `CorporateEvent`, no chart marker reads
  it yet). `/financial-statement-full-as-reported` is only exercised for Bank-classified tickers.
- **Seeded group with no endpoint at all**: `extended_hours` (P5) — see "Extended-hours pricing"
  below for what was tested toward eventually wiring this up.

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
`TrendAnalysis` (written by the 3:10 trend job), `bb_rsi_entry_signal` from the 3:20 BB+RSI job's
row, and `warren_active_signal_kind`/`warren_last_buy_fired_at` from the 3:40 Warren job's rows.
The full-universe recompute (`pipeline.nightly_score_recompute`) therefore runs at **3:50 AM**,
after all three and before the 3:55 backup (cache-only, zero FMP calls, ~30s; Warren is ~2 min
today, ~9 min theoretical worst case). Nothing else depends on that order: the trend job reads
only the shared bars cache and its own universe. The 2:00 fundamentals fetch still scores each
ticker inline, so fundamentals-derived fields are fresh from 2:00; its technical fields are
overwritten by the 3:50 sweep. Pinned by
`tests/test_cron_wiring.py::test_score_recompute_runs_after_every_job_it_copies_from` (and
`JOB_METADATA`'s time label by `test_job_metadata_sort_minutes_match_crontab`). After any night
the trend/BB+RSI/Warren job overruns 3:50, the affected tickers just read a night behind. The
night-behind bug this ordering fixed (2026-09-19) is recorded in
`docs/archive/claude-md-history-technical-signals.md`. Note that editing `crontab.txt` alone
changes nothing on the box — it must be reinstalled from `backend/` (`crontab crontab.txt`) and
`crontab -l` checked against the file.

## Daily prices: FMP migration (Phase 2, 2026-09-24) — basis and parity

The nightly-bar consumers' data source, formerly Massive-with-Yahoo-fallback, moved to
`/historical-price-eod/full` for US-listed tickers.

**Basis change, worth understanding before comparing to another chart.** FMP `full` is split-
**and spin-off**-adjusted, not dividend-adjusted. For roughly 30 tickers, pre-spin-off history
therefore differs from a split-only source (e.g. TradingView) by a constant factor that ends
exactly on the spin-off date — this removes an artificial cliff a spin-off leaves in a raw
series; it is not a data error, and no splits-only FMP endpoint exists to avoid it.

**Parity gate accepted below its own bar, by explicit user decision.** The post-backfill parity
check (592 tickers, ~717k overlapping days) measured 98.14% of days within 0.1% against the
prior cache — under the 99% bar originally set for this migration. The shortfall was fully
traced to five understood, accepted buckets: the spin-off basis change itself; stitched/renamed
symbols now reading as one continuous series under FMP where the old provider had a visible
seam; a handful of confirmed single bad prints in the *old* cache (FMP was independently
verified correct on these); OTC thin-trading vendor differences; and FMP simply carrying more
history for some tickers than the old cache did. The user accepted the gate at 98.14% given
every discrepancy bucket was independently explained, rather than raising the FMP-side match
rate further.

**FMP silently caps a response at 5,000 rows (~19.9 years) — confirmed, not documented anywhere
by FMP.** Relevant to any consumer requesting more than ~20 years of history; not reachable by
the nightly 5-year window, but directly relevant to the long-history store below, which requests
10 years per ticker in a single call and confirmed it never needs paging at that depth.

## Long-history store (Phase 3, 2026-09-25) — Chart W_4Y and the Analyst Ratings overlay

Two on-demand, per-ticker consumers need more history than the nightly ~5-year cache carries:
the Chart tab's **W_4Y** range (needs ~7.9 years of daily bars once weekly-SMA200 warm-up is
accounted for) and the Analyst Ratings tab's **10-year price overlay** on the price-target trend
chart. Both are served from a dedicated store, `LongHistoryBars` (PK `(ticker, bar_time)`),
**not** `SharedBarsCache["1d"]` and **not** a `FundamentalsCache` blob.

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
writes it, and nothing prunes it.

**Fill/refresh behavior**: lazily filled per-ticker, single-flight (an in-process lock per
ticker, so two concurrent first-views of the same never-yet-cached ticker don't double-fetch).
Cold → a synchronous ~1.6-2.1s full 10-year fetch. Warm and fresh (by the same market-close-aware
rule the shared cache uses) → served with no live call, ~0.07s. Warm and stale → an incremental
top-up (`from = last bar - 7d`) with the same 0.5%-overlap restatement check the nightly job
uses, falling back to a full refetch+replace if history was restated. Group off or the FMP call
fails while warm → the existing stored row is served as-is (cached-only, never wiped); group off
or a failure while cold → `None`, nothing written.

**Chart W_4Y basis**: the store's own dailies, trimmed to 10 years, resampled through the same
`weinstein.resample_to_weekly` (W-FRI, shifted to Monday labels) every other weekly consumer in
this app already uses — reused directly, not reimplemented, since the resampling logic is
genuinely data-source-agnostic. Weekly parity against a recorded native-weekly reference fixture
was verified: identical week-for-week labels, closes within 0.5% on every sampled week.

**Analyst overlay basis, a real decision, not a default.** The overlay reads the store's FMP
`full` closes — split- (and spin-off-) adjusted, **not** dividend-adjusted — deliberately, not
because a dividend-adjusted endpoint wasn't available. The target line it's compared against
(FMP's own `adjPriceTarget`) is itself split-adjusted but not dividend-adjusted, and an
analyst's target is a nominal price at the time it was issued — a dividend-adjusted close would
deflate every earlier price by dividends paid since, which is the wrong comparison basis for
"was the stock trading near this target when it was issued." This also matches the Chart tab's
own basis, so the two views of the same ticker's price history agree.

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

This remains genuinely unbuilt — the `extended_hours` data group is seeded but has no endpoint,
client method, or call site anywhere in the app.

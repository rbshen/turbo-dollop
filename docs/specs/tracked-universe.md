# Tracked universe (the nightly ticker set)

Built 2026-10-02 from `docs/tracked-universe-expiry-investigation-2026-10-02.md`. Replaces the 2026-08-06 "index +
ever-viewed + watchlisted" rule, under which a ticker viewed once stayed in every nightly job forever.

## The rule

`data/tracked_universe.py::load_tracked_universe(session, now=None)` is the one definition of which tickers the nightly
and weekly jobs iterate. A ticker is in when it is **not delisted-flagged** and at least one of:

| | Rule | Source |
|---|---|---|
| a | member of the S&P 500, Nasdaq-100 or Dow list | `IndexConstituent` (`index_name` in `sp500`, `dow`, `nasdaq`) |
| b | on **any** watchlist, monitored or not | `WatchlistTicker` |
| c | in `SYSTEM_TICKERS` (the 11 sector ETFs plus SPY) **and already known to the app** | constant, built from `SECTOR_ETFS` and `WEINSTEIN_BENCHMARK_TICKER` |
| d | its page was opened in the last 30 days (`TRACKED_VIEW_WINDOW_DAYS`) | `TickerView.last_viewed_at` |
| e | it carries manual data: a Moat rating, any custom valuation (active or not), or a bank-capital entry | `TickerMoat`, `TickerCustomValuation`, `TickerBankCapitalMetrics` |

Anything else that the app holds data for is **expired**: it stays in the DB with all its data (nothing is ever deleted
by this rule), and drops out of the nightly jobs and the Screener's `all` universe until it is viewed again. The first
matching reason wins and is reported as `delisted`, `index`, `watchlist`, `system`, `manual`, `viewed` or `expired`
(`classify_known_tickers`); the universe, the Screener's hidden count and the verification report all derive from that
one classification.

- **Rule (e) exists because of Monthly Momentum.** Its universe is "tracked tickers with a Moat rating"; without (e) a
  Moat-rated ticker not opened for 30 days would silently leave the next snapshot. A delisted ticker is excluded even if
  it has a Moat (the Momentum job still reports it as `skipped_delisted_count`).
- **Rule (c) is protection, not insertion.** A system ticker the app has never seen is not added to anything, so the rule
  creates no row and no FMP call. **A future ETF momentum universe must be added to `SYSTEM_TICKERS`** (the ETF momentum
  ranking is "investigated, not built", `docs/specs/sector-heatmap.md`). There is a comment at the constant and the
  guard test pins today's membership.
- **A delisted flag always wins** (`TickerScore.delisted_at`), over an index, a watchlist or manual data.

`load_all_known_tickers(session)` is the old wide set: index members, any ticker with a cached FMP *profile* (not any
`FundamentalsCache` ticker: that table also holds FX pairs such as `EURUSD`), any `TickerScore` row, any watchlist entry.
It never expires and includes delisted tickers. It is for the jobs whose point is to see everything: the weekly
non-US purge, the delisted-flag sync, the search fallback while `profile_quote` is off, and the one-off backfills.

## The ETF universe (added 2026-10-02, not wired to any job yet)

Step 2 of the ETFs screener (additive only). `load_tracked_universe` above is **unchanged**: the stock-side jobs still
hold the ETFs (Weinstein, last close, score recompute) until a later cutover step. Nothing reads the functions below
yet; there is no endpoint, table, cron job or write for them.

- **Partition.** `partition_known_tickers(session)` splits the wide known set into (stock side, ETF side) using
  `data/etf_data.py::known_etf_tickers` (a `TickerScore.is_etf` row, or a cached profile with `isEtf`/`isFund`) plus
  `ETF_SEED_TICKERS`. The two sides are disjoint and together hold every known ticker; the ETF side also carries the
  seeds the app has never seen. An ETF is only recognised once its profile or score row exists, so an unopened ETF
  stays on the stock side until it is opened.
- **Seed list.** `ETF_SEED_TICKERS` = SPY + the 11 sector SPDR ETFs, built from `SECTOR_ETFS` (never retyped). A seed
  is in the ETF universe with reason `system` even with no profile row. It is its own constant: `SYSTEM_TICKERS` is
  untouched (it still protects the same tickers on the stock side). Today they have the same members. A future ETF
  momentum universe goes into both while both are live.
- **Rules**, via the same first-match `_classify` as the stock side (shared with `classify_known_tickers`; same
  `TRACKED_VIEW_WINDOW_DAYS`, same delisted flag): `delisted` > `watchlist` > `system` > `viewed` > `expired`. The
  `index` and `manual` reasons do not apply to an ETF (no ETF is an index constituent, and Moat cannot be set on one).
  An ETF on **any** watchlist, monitored or not, never expires while it stays there. "Searched" means "opened": the
  `TickerView` that `GET /api/tickers/{t}/summary` records; search itself writes nothing.
- **Functions.** `classify_etf_tickers` ({ticker: reason}), `load_etf_universe` (sorted, delisted and expired
  removed), `load_expired_etfs`, and `count_hidden_inactive_etfs` (the ETF counterpart of
  `ScreenerMeta.hidden_inactive`; it counts expired ETFs, not table rows, because the ETF read-model does not exist
  yet).
- **Guard.** `tests/test_tracked_universe.py` pins that the stock-side union is unchanged and that the partition is
  exhaustive with no overlap.

## Who uses which

| Expiring `load_tracked_universe` | Wide `load_all_known_tickers` |
|---|---|
| last-close snapshot and price-target snapshot (`load_us_price_target_universe`, minus non-US, delisted, and known ETFs for price targets) | `non_us_purge` and its 2% refusal guard |
| `nightly_trend_calculation` (Weinstein and the bar-cache fill) | `sync_delisted_flags` (a flagged ticker must stay matchable) |
| `nightly_fundamentals_fetch` (minus known ETFs/funds) | the search fallback |
| `nightly_score_recompute`, `recompute_ticker_scores` (and `POST /api/screener/recompute`) | the daily-bar and price-target backfills |
| `monthly_momentum_snapshot` (`data/momentum_data.py`) | |
| `stale_data_health_check`'s staleness report | |
| Screener `GET /api/screener?universe=all` and `/screener/meta` | |

Not on this list because they never used the universe: Liquidity Zones, BB+RSI and Warren (monitored watchlists only),
the Sector Heatmap (11 fixed ETFs) and Market Breadth (`IndexConstituent` sp500). `tests/test_tracked_universe.py` fails
if a job reads the helper from anywhere else, calls the old name `load_full_tracked_universe`, or re-declares the union.

## Recording a view

`TickerView(ticker PRIMARY KEY, last_viewed_at)`. `GET /api/tickers/{t}/summary` calls
`record_ticker_view` after `get_summary` succeeds (a 404 is never recorded). Only ticker pages call that route (the
header, Summary, Chart and Analyst Ratings tabs share one SWR key; the ETF page uses it too); the Watchlist and Screener
do not. One statement, no pre-read, **at most one write per ticker per calendar day**:
`INSERT ... ON CONFLICT(ticker) DO UPDATE SET last_viewed_at = :now WHERE last_viewed_at < :start_of_today`. It never
raises (a DB error is logged, the page is unaffected). A tab left open revalidates and so counts as a view once a day.

## The seed and the 30-day grace

`core/db.py::_seed_ticker_views`, called from `init_db()` (so on every backend start and every cron job's start): when
`TickerView` is **empty**, every ticker the app already held (cached profile, `TickerScore` row, watchlist entry or index
membership, same wide set) gets `last_viewed_at = now`. Once any row exists, a later `init_db()` does nothing, so the
grace dates never move on a restart. No viewed-only ticker can leave the universe before 30 days after the first start on
this code. An empty database seeds nothing.

## What the jobs and pages do for an expired ticker

- Its data, `TickerScore` row, Weinstein row, bars, price-target and momentum history all stay. `prune_cache` (unchanged)
  deletes `FundamentalsCache` rows older than 180 days, so an expired ticker's cache rows go about 210 days after its
  last view; its `TickerScore` row survives and the page re-fetches on demand.
- **Screener, `universe=all`:** the row is hidden (`TickerScore.ticker IN tracked universe`) and `ScreenerMeta.hidden_inactive`
  counts the stock rows hidden; the Screener subtitle shows "N not viewed in 30 days are hidden". Index universes are
  unaffected. Saved views store filters, not results, so they stay valid and simply show fewer rows. Viewing the ticker
  re-adds it at once.
- **Header Assessment chip:** `GET /api/tickers/{t}/score` recomputes live (`cache_only=False`) when the stored row is
  older than 36 hours (`SCORE_STALE_AFTER`), so the first view after a gap never shows a frozen score. Nightly keeps every
  universe member inside that bound. Skipped for an ETF (no chip) and a delisted ticker (frozen on purpose).
- **ETF Overview:** `data/etf_data.py::_warm_daily_bars` fetches and caches the ETF's daily bars when the shared cache holds
  none or is behind the last completed session, so the Trading data block is not empty (about one FMP call, only then; zero
  for an ETF in the universe). On-demand only, never from a nightly job; a failure is swallowed.
- Weinstein on the ticker page already recomputes on demand when stale, and Technical/Chart fetch bars on demand.

## Delisted tickers

A flagged ticker leaves **every** nightly job at once, including the weekly fundamentals refetch (it was the one job that
did not skip delisted tickers). Its data is untouched and its page still renders (the summary route does not read the
flag). The flag is no longer permanent: the weekly `sync_delisted_flags` clears it when **both** the whole delisted list
was read (`complete`) and the ticker is no longer on it as a qualifying hit, **and** a live FMP `/profile` call says
`isActivelyTrading: true` (at most 50 re-checks a run, today 5). An incomplete list, a failed call or an inactive profile
leave the flag. See `docs/specs/fmp-data-and-bar-cache.md`, "Delisted-ticker handling".

## Verifying

`uv run python -m pipeline.tracked_universe_report [--days N]` (read-only, no FMP call, no `init_db`): known and in-universe
counts, counts by reason, `TickerView` row count and first/last grace date, the delisted and expired lists, and the viewed-only
tickers leaving within N days (default 7). See `backend/OPS_RUNBOOK.md`, "Tracked universe".

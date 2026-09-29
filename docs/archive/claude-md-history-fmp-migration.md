# CLAUDE.md history: FMP migration

Verbatim history moved out of the original CLAUDE.md (archived at docs/archive/CLAUDE.original.md). Text is unedited; line ranges refer to that file.

## Phase 6a: Massive removed; FMP last-close, corporate-events and delisted-companies (original lines 3919-3965)

## Phase 6a: Massive removed; FMP last-close, corporate-events and delisted-companies (2026-09-26)

Massive/Polygon is **deleted** (client, `MassiveDailySource`, `massive_enabled`/`massive_api_key`/`massive_base_url`,
the ticker-alias helpers, the one-time Massive backfill, their tests, and `MASSIVE_API_KEY`/unused `EODHD_*`/`APCA_*`
from `backend/.env`). It was confirmed fallback-only beforehand. The last remaining provider after it was removed in
Phase 6b (below), leaving FMP as the only one.

- **Header price** (`data/ticker_summary.py`): a live FMP `/quote` on every view (unchanged). When the
  `profile_quote` group is off **or** the live fetch failed, only `price` is overridden with the last official
  close cached nightly by `pipeline.nightly_last_close_snapshot` (3:15 AM UTC; table `TickerLastClose`, latest-only,
  `data/last_close_data.py`). One `/historical-price-eod/full` call per US-listed tracked ticker (group
  `daily_prices`; skipped with a real `skipped` status while it is off), newest bar on/before the last completed
  session. No cached close -> the stale cached FMP quote price stays. `cache_only` never reads it. The old
  header-price fallback to a second provider is removed.
- **Earnings / dividends / splits cache** (`CorporateEvent` + `CorporateEventFetch`, `data/corporate_events_data.py`,
  `pipeline.nightly_corporate_events`, 3:12 AM UTC): FMP `/earnings` (limit 1000), `/dividends` (limit 2000),
  `/splits` (new `FMPClient.get_splits`, in `corporate_events`), **full-history REPLACE per (ticker, type)** each
  night, so the first run is the backfill (~590 tickers x 3 calls, ~1-2 min, paced to half the plan rate). A failed
  endpoint (or a 200 error body) keeps that type's old rows. `CorporateEventFetch` records the last *successful*
  fetch per (ticker, type) so "fetched, FMP has none" (TSLA dividends) differs from "never fetched". Cadence
  choice: nightly for all three (earnings actuals fill in day to day; splits ride along for one cheap call).
  **Chart tab**: `chart_events_data._fetch_events` reads the cache first (rebuilds FMP-shaped rows and reuses the
  live path's own normalizers, so the marker rules are identical) and only falls through to the live FMP
  path for a ticker whose earnings+dividends were never cached. The cache is served however old, including
  while `corporate_events` is off. (The live path was deleted in Phase 6b.) Splits are stored but no marker reads them yet.
- **Delisted flags** (`pipeline/stale_data_health_check.py::sync_delisted_flags`, weekly Sun 1:30): pages FMP
  `/delisted-companies` (group `corporate_events`; **page size capped at 100, ~157 pages / ~15.6k rows / ~15.4k
  unique symbols on 2026-09-26**, so ~157 sequential calls/week) and sets `TickerScore.delisted_at` for tracked
  tickers listed with a delisted date on/before today. Verified against the live endpoint: all five
  known-delisted tickers (TWTR, WBA, EA, AVB, EQR) are in it and are the only 5 of 591 tracked tickers that are.
  **Absence is never evidence: no flag for an unlisted ticker, and an existing flag is never cleared** (the old
  staleness heuristic, live-probe revival and auto-clear are removed). Guards on a hit: a delisted date in the
  future is a scheduled delisting (ignored); a symbol whose cached profile `ipoDate` is after the delisted date is a
  reused symbol (ignored); FMP's `BF.B` matches our `BF-B`. A page error uses what was fetched and reports
  "delisted list incomplete" (paging ties can also drop a row at a page boundary; the weekly rerun catches it).
  `last_bar_ages_days` (shared_bars_cache) was removed as dead. **Open decision:** a relisted symbol stays
  flagged until someone clears `delisted_at` by hand.
- **Non-US support** was removed in the follow-up section above: non-US tickers get no nightly daily or 60m bars.
  `route_by_source`/`is_us_listed`/`_profile_exchanges` remain (they scope the price-target/last-close/corporate-events
  universes).
- **`^GSPC` cleanup (run 2026-09-26, after `pipeline.backup_db` -> `fathom_20260926_105650.db.gz`):** confirmed
  `WeinsteinSettings.rs_benchmark` is `SPY` and no `weinstein_params_json` names `^GSPC`, then deleted 1,253
  `sharedbarscache` and 510 `yahoopricecache` `^GSPC` rows. `weinsteinBenchmarkLabel` no longer special-cases
  `^GSPC` (a user could still type it into Settings; it now just displays as `^GSPC`). The Yahoo price table was dropped in Phase 6b.
- **To activate:** reinstall the crontab (`crontab crontab.txt` from `backend/`; two new jobs) and restart the
  app (`./bin/stop.sh && ./bin/start.sh`; production build). Ops details: `backend/OPS_RUNBOOK.md`.


## Phase 6b: Yahoo Finance removed entirely (original lines 3966-4036)

## Phase 6b: Yahoo Finance removed entirely (2026-09-26)

Yahoo (`yfinance`) was the last non-FMP market-data source; it had not served a real production ticker
since the 2026-09-24 FMP cutover, but was still wired as a fallback at 9 call sites. All removed. **FMP is
now the only external market-data provider and there is no fallback anywhere** -- when a data group is off
or FMP fails/answers empty, the last cached rows keep serving (nothing is wiped) and features degrade as
below. The sections above were rewritten to describe the FMP-only behavior; this section is the record of the removal.

**Decisions (user-made, final):**
1. **Chart tab daily ranges (D_6M/D_1Y/D_2Y)**: group off, or FMP errors/answers empty -> an **EMPTY chart**
   (`chart_available=False`). No stale-cache substitute, no new caching. W_4Y keeps the long-history store
   (cached-only when `daily_prices_long` is off; empty when there is no stored row). `ChartOut.source` is
   always `"fmp"`. The ticker-page tabs' "not refreshing" badge (`lib/dataGroups.ts::TAB_GROUPS`) now also
   covers `daily_prices`/`daily_prices_long`/`intraday_bars` on the Chart/Technical/Analyst Ratings tabs.
2. **Nightly bar jobs** (Trend, Liquidity Zones, Sector Heatmap, Market Breadth, Momentum -> `daily_prices`;
   Warren, BB+RSI -> `intraday_bars`) report a real **`skipped`** cron status while their group (or the master
   switch) is off, via `core/data_groups.py::job_skip_reason`, instead of "success with N still stale". The
   Momentum job's ordinary "not the first trading day" no-op is unchanged (still a success).
3. **`TechnicalEntrySignal.source`** is always `"fmp"` for new rows; the 34 existing `"yahoo"` rows were
   rewritten (see the cleanup record below). `LiquidityZoneAnalysis.source` (54 legacy `"yahoo"` rows) was
   not touched -- the nightly LZ job overwrites it on its next run. `SharedBarsCache.source` keeps its
   provenance role: legacy NULL/`"yahoo"` 60m rows are still fully replaced on the next FMP fetch.

**What changed, per call site:**
- `clients/yahoo_client.py`, `clients/yahoo_cache.py`, `YahooPriceCache` (model + table), the last references
  in `ticker_summary`/`stale_data_health_check` (their Yahoo paths were already dead after Phase 6a; header
  price = live FMP quote, else the nightly last close), `pipeline/backfills/backfill_entry_signal_events.py` (spent one-time script), and
  `Settings.yahoo_quote_intraday_ttl_seconds` are deleted. `yfinance` is out of `pyproject.toml`/`uv.lock`
  (transitively `requests`, `urllib3`, `pytz`, `soupsieve`, ... too; nothing imported them directly).
- `clients/daily_bar_sources.py`: `YahooDailySource`, `FMPWithFallback` and `FMPIntradayWithFallback` are
  gone. `get_daily_bar_source()` returns `FMPDailySource`; `FMPIntradaySource` is used directly. Both take
  an `unserved_tickers` out-parameter (the whole batch while the group is off). **Renamed:**
  `FallbackTickers`->`UnservedTickers` (no `.yahoo` any more), `describe_fallback`->`describe_unserved`
  (heartbeat text `N not served by FMP (cached bars kept)`), the `fallback_tickers` parameter ->
  `unserved_tickers`, and the job-summary keys `fallback_count`/`fallback_yahoo_count` -> `unserved_count`.
- `clients/shared_bars_cache.py`: `_fetch_yahoo_intraday` and `intraday_source_labels` are gone; every 60m
  write is tagged `source="fmp"`. `_period_for`/the period tiers stay (they pin retention/width logic in
  tests) but no longer drive a fetch. `clients/technical_sources.py`: `YahooTechnicalSource` ->
  `FMPTechnicalSource` (the single reader). `core/tickers.py::resolve_daily_bar_source_label` is deleted
  (jobs write `"fmp"`).
- `data/chart_events_data.py`: the **`CorporateEvent` cache is the sole source** (no live FMP call, no
  Yahoo, no timeout wrapper); an uncached ticker or a read error = no markers (`events_source=None`).
  `data/chart_data.py`, `data/analyst_ratings_data.py`: Yahoo branches removed (see decision 1; the
  overlay is empty with no stored row).
- Data groups: `GroupMeta.falls_back`, `DataGroupOut.falls_back` and the `using_fallback` state were removed
  outright (not set to False) since no group has a fallback. Frontend chip text for an off price group is
  now the plain "Cached only". `DataSourceStatusOut.source` is `Literal["fmp"]`; `data_source_status.py`
  builds only the FMP entry; the Yahoo card, `YAHOO_POWERS` and the "no kill switch" comments are gone
  (`DataSourceCard.tsx` is now unused by the UI but kept). `types.ts`: `events_source: "fmp" | null`,
  `ChartOut.source: "fmp"`.

**One-time data cleanup (run 2026-09-26)**, `pipeline/backfills/phase6b_yahoo_cleanup.py` (has `--dry-run`;
idempotent), after `pipeline.backup_db` -> `backups/fathom_20260926_172754.db.gz`: **34**
`TechnicalEntrySignal` rows `"yahoo"`->`"fmp"`; **2** `DataSourceHealth` rows deleted (`massive` -- Phase 6a had
left it -- and `yahoo`); `DROP TABLE yahoopricecache` (**375,708** rows). A second run changes nothing.

**Tests:** `test_yahoo_client.py`/`test_yahoo_cache.py` deleted; the shared-cache/consumer/prune/chart/overlay/
events/group tests now fake at the FMP source boundary (`_FakeBarSource`/`FakeBars`) instead of `yahoo_client`;
new `test_nightly_jobs_group_skip.py`, `test_phase6b_yahoo_cleanup.py`. `tests/fixtures/
weekly_parity_fmp_daily_vs_yahoo_1wk.json` is kept as the historical FMP-vs-Yahoo weekly parity record (still
used by `test_chart_weekly_fmp.py`). Backend 2,087 tests, frontend 442.

**To activate:** restart the app (`./bin/stop.sh && ./bin/start.sh`; production build) and reinstall the
crontab (`crontab crontab.txt` from `backend/`) -- the crontab.txt change is comments only (no schedule change),
but the file and the installed copy now differ until it is.

**Left in place, deliberately:** `analysis/entry_signal/engine.py::compute_historical_entry_signals` and
`data/entry_signal_data.py::record_historical_entry_signal_events` (their only caller was the deleted backfill;
still unit-tested); the Weinstein/`resample_to_weekly` docstrings that cite Yahoo's native weekly bars as the
validation reference; non-US routing helpers (`route_by_source`, `is_us_listed`).


## Phase 6a follow-up: non-US support removed (2026-09-26) (original lines 3690-3703)

- **Non-US support removed.** Deleted: the `daily_prices_intl` data group (registry, canary,
  `NON_US_CANARY_GROUPS`, 402 non-US canary branch), `drop_phantom_bars`/`PHANTOM_VOLUME_TOLERANCE` and every
  `non_us=` parameter (the filter was only ever applied to non-US series -- US was never filtered, so nothing
  US-facing lost it), the Chart tab's non-US branch (every ticker now uses `daily_prices`),
  `long_history_bars.group_for` (always `daily_prices_long`), the nightly non-US daily-bar fetch
  (`shared_bars_cache` now fetches only the US half of `route_by_source`, as 60m already did), and the
  backfill's `--scope`/parity gate. Kept, deliberately: `route_by_source`/`is_us_listed`/`_profile_exchanges`
  (they scope the price-target/last-close/corporate-events universes and the bar fetches).
  **Consequence:** a non-US ticker viewed later gets a `TickerScore` and fundamentals but no nightly bars; its
  Chart tab works on demand (FMP `daily_prices`, unfiltered), and its long-history/overlay bars come
  from the same group with no phantom filtering. The 6 HKSE tickers were purged from the real DB (see the
  2026-09-26 cleanup record in the commit message/report); nothing prevents a user re-adding one.
  Sections above describing `daily_prices_intl`, phantom bars, `--scope non-us` and the HK backfill are history.


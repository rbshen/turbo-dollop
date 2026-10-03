# Opt-in universe ("Add to Universe") and the wipe job: investigation (2026-10-03)

Phase 1, report only. No code, DB, crontab or config change was made by the investigation itself, and no FMP call. Read-only
queries against `backend/fathom.db`. The build that followed (step 1: registry, candidate logic, dry-run-only wipe job) is in
`docs/decisions.md` (2026-10-03) and `docs/specs/tracked-universe.md` ("Planned: opt-in universe and wipe", not yet active).
FMP call counts and timings for the Add click are estimates from reading the code, not measurements.

**Goal (decided with the owner):** two linked features for stocks and ETFs. (1) A ticker opened for the first time and not
already in the universe works normally but does not join the screeners or nightly jobs; an "Add to Universe" button adds it
(an ETF's `EtfScreenerRow` is written at once, a stock's score is computed at once). (2) A wipe job: a ticker untouched for 30
days is fully cleaned out of the DB unless it is an index member, on a watchlist, a seed ETF, or carries manual data. After a wipe
the ticker has no state, so opening it again shows the Add button again. Wiping must not affect any computation.

## 1. How "touched" works today

- The only writer is `GET /api/tickers/{t}/summary` (`core/main.py`), which calls `data/tracked_universe.py::record_ticker_view`
  after the summary succeeds. `TickerView(ticker PK, last_viewed_at)`: per ticker, at most one write per calendar day.
- Search, the Screener / ETFs / Watchlist pages, watchlist actions, `/score`, `/refresh` and every cron job never touch it. Cron
  jobs call `get_summary` directly, not the route. Only ticker pages call `/summary`; cards and search open the page, and that
  is the touch. The page shell does no server-side fetch, so a Next link prefetch should not touch it (read from the code, not
  verified in a browser). A tab left open can count once a day (the spec says so; the SWR focus-revalidate setting was not checked).

## 2. Inventory of per-ticker data (live row counts, 2026-10-03)

| Table (key) | Rows / tickers | Read by | Shared? | Cleaned today | Class |
|---|---|---|---|---|---|
| `TickerView` (ticker) | 596 / 596 | universe `_classify` | no | never | wipe last (it is the state) |
| `TickerScore` | 605 / 605 | Screener via the universe, Watchlist (live), `known_etf_tickers`, holds `delisted_at` | no | non-US, invalid purge | wipe |
| `EtfScreenerRow` | 19 / 19 | ETFs page via the universe | no | nightly ETF job prunes it | wipe |
| `TrendAnalysis` | 606 / 606 | header pill, score copy, Watchlist | no | none | wipe |
| `TickerLastClose` | 600 / 600 | header price fallback | no | none | wipe |
| `FundamentalsCache` | 14,397 / 614 | all tabs, SPY `price_change`, `etf_info` | seed rows and 7 `forex_rate` keys | `prune_cache` (180 d), non-US | wipe, except seeds and `forex_rate` |
| `SharedBarsCache` | 1,129,251 / 605 | Weinstein, LZ, Breadth, Momentum, Heatmap, ETF | seeds and index | `prune_old_bars` by age | wipe candidates only |
| `LongHistoryBars` | 157,988 / 68 | long chart ranges, price-target chart | no | none | wipe |
| `PriceTargetSnapshot` | 37,924 / 580 | Analyst tab | no | none | wipe (history that cannot be re-created) |
| `CorporateEvent`, `CorporateEventFetch` | 16,649 and 1,746 / 582 | Chart E/D markers | no | 4-year age prune | wipe (its nightly job is disabled) |
| `TechnicalEntrySignal` (240), `TechnicalEntrySignalEvent` (2,257), `WarrenSignalEvent` (2,240), `LiquidityZoneAnalysis` (262) | 100-131 tickers | monitored watchlists only | no | self-clear after 7 days | wipe (a candidate never has them) |
| `NewsCache` (9), `newssentimentcache` (3, no model) | per left | News tab (the latter: nothing) | no | none | wipe |
| `MomentumSnapshot` | 1,222 / 410 | Momentum page | Moat-rated only | none | wipe for orphan cleanup (a Moat protects, so a candidate has none) |
| `SectorEtfReturn` | 880 / 11 | Heatmap | seeds | age prune | keep |
| `IndexConstituent` (635 / 518), `WatchlistTicker` (188 / 135), `TickerMoat` (414), `TickerCustomValuation` (36), `TickerBankCapitalMetrics` (16), `GrowthCatalystNote` (0) | per left | universe protections | no | non-US purge only | protecting |
| `SavedScreenerFilter` | 3 | stores filters, no tickers | no | none | keep |

There are no in-memory per-ticker caches. Logs and backups hold ticker names only.

## 3. Readers that bypass the universe

- **Breadth:** current S&P 500 members only. **Momentum:** Moat-rated tickers in the stock universe; all 410 tickers in
  `MomentumSnapshot` have a Moat, so they are protected. **Sector Heatmap:** the 11 sector ETFs (seeds).
- **SPY benchmark:** SPY is a seed, but the Weinstein `rs_benchmark` is a DB setting (now SPY). Only the constant
  `WEINSTEIN_BENCHMARK_TICKER` was protected, so a changed setting would have left the new benchmark unprotected. The wipe now
  protects the live value too.
- **Price-target trend:** `PriceTargetSnapshot` is read per ticker on the Analyst tab; nothing breaks if rows vanish, the history is lost.
- Nothing else depends on viewed-only tickers.

## 4. Manual data

`load_manual_data_tickers` covered `TickerMoat`, `TickerCustomValuation` (active or not) and `TickerBankCapitalMetrics`. The
Moat has no delete path, so it protects for good. The Step 3 manual calculation is stateless. **Gap found:** `GrowthCatalystNote`
(0 rows) is read by Step 2 but had no write path and was not in the function; it is now (step 1).

## 5. Existing deletion primitives

- `purge_invalid_tickers`: `FundamentalsCache` + `TickerScore` for a confirmed-empty profile. `non_us_purge.purge_tickers`: every
  table with a `ticker` column, no protection list (so not reusable as-is for the wipe). `prune_cache`: age (180 d). `prune_old_bars`:
  global by age (6 y daily, 3 y 60m). **`prune_etf_screener_rows` already hard-deletes `EtfScreenerRow` rows of ETFs outside the
  ETF universe** after each live nightly run. The delisted logic only sets `TickerScore.delisted_at`.
- Foreign keys exist only from `watchlistticker` and `savedscreenerfilter` to `watchlist`, and `PRAGMA foreign_keys` is 0: no cascade,
  deletion order is free for integrity. Delete derived tables first, caches next, `TickerView` last (a half-done wipe stays retryable).

## 6. The ticker page for a not-yet-added ticker

Opening a page today writes `FundamentalsCache`, `SharedBarsCache` bars, `TrendAnalysis` (header pill), a `TickerScore` row (`/score`,
cache-only) and `TickerView`. By code reading, the page works without a `TickerScore` row. Recommendation: leave the page's data path
unchanged; screeners read through the universe join, so a non-added ticker's rows are invisible there. The Chart tab's E/D markers read
only the `CorporateEvent` cache, which `nightly_corporate_events` (disabled since 2026-10-01) does not refill. A never-seen ticker costs one
live profile call; an empty profile is a 404 and writes nothing.

## 7. State model (recommended)

Add nullable `added_at` / `added_source` to `TickerView` (one row per ticker; `init_db` adds nullable columns itself; `record_ticker_view`
only updates `last_viewed_at`). Versus a separate `UniverseMembership` table: two tables to keep consistent, and `kind` is derivable from the
profile. Reasons become `added` (replaces `viewed`), `browsed` (opened, not added), and `expired` becomes "idle > 30 days, awaiting wipe".
The wipe evaluates protections from the raw sets, not from `_classify` reasons (`delisted` is answered first there).

## 8. Add click

- **Stock:** `POST /api/tickers/{t}/universe` (idempotent): profile check, set `added_at`, then `compute_ticker_score(cache_only=False)`
  (what `POST /refresh` already does synchronously). Estimate 10-20 FMP calls, 3-10 s (not measured). Synchronous with a spinner.
- **ETF:** `refresh_etf_screener(tickers=[X])` is reusable: explicit lists bypass the universe and never prune; a live run writes
  `EtfScreenerRow`, `TrendAnalysis`, `TickerLastClose`. Estimate 2-4 calls, 1-3 s. Call it directly, not the pipeline `main()`
  (which calls `configure_logging`/`init_db` inside the running app), and check `group_live` in the endpoint. It skips the write when
  nothing was computed (`_worth_writing`), so the UI must say "appears after tonight's run".
- Stock versus ETF comes from the profile flag `isEtf || isFund`.

## 9. Grandfathering (live DB)

25 tickers are in the universe only through "viewed": 18 stocks (AAP, ACHR, AXTI, BB, BLDR, CNI, ETSY, FLY, IONQ, JOBY, MAN, PARA, RIVN,
SINGY, TAP, TMP, TXG, WCN) and 7 ETFs (GLD, IBIT, QQQ, SMH, SOXX, TECL, TLT). None is expired (the seed stamped 2026-10-02 07:00; real views
on 2026-10-02/03: MAN, GLD, TECL). The migration must mark all 25 as added (`grandfathered`) **before** the classification flips: otherwise 18
stocks leave the Stocks Screener and the nightly jobs, and the 7 ETF rows are hard-deleted at the next live 1:45 run.

## 10. Watchlist, search, UI

Watchlist add counts as a universe add, derived from the `watchlist` reason (no write); the button shows a disabled "In universe · E3". The ETF
page's "Add to watchlist" also puts the ETF on the monitored `ETF` list (LP, BB+RSI, Warren), which is heavier: use distinct labels, and have
that endpoint also write the `EtfScreenerRow` at once. Search is a live FMP query that opens a new tab; nothing changes. Buttons: next to
`AddToWatchlistButton` (stock header) and `EtfWatchlistButton` (ETF header). A Remove button is feasible (clears `added_at`, deletes the
`EtfScreenerRow`; disabled with the reason for index / watchlist / seed / manual); it does not wipe on the spot. After wipes `hidden_inactive`
is about 0: remove the field, `count_hidden_inactive_etfs`, `load_expired_*`, the two subtitle strings, the types and tests.

## 11. Dry run (at investigation time)

Nothing expires before 2026-11-01 07:00 (the 2026-10-02 seed). At day 30 with an empty added set: 25 viewed-only tickers (about 39,350 rows) plus
the 4 unprotected delisted tickers AVB, EQR, TWTR, WBA (4,088 rows) are due; EA (delisted, has a Moat) stays. The five orphans (DXC, VFC, CROX,
ROKU, SNAP) have no `TickerView` row and are adopted, not wiped. Index names in `IndexConstituent`: `sp500` 503, `nasdaq` 102, `dow` 30. The
step-1 build's own live dry run is in the report of that task (and reproduces these numbers: 29 wipes at day 31 with an empty added set, 4 once the
25 are supplied as added).

## 12. Risks

- **Wipe against an open:** the summary route writes cache rows first and `TickerView` last. Touch at the start of the request instead, and re-check
  inside a per-ticker `BEGIN IMMEDIATE` (step 1 does the latter).
- **Locking:** journal mode is `delete`, not WAL: delete per ticker (about 1,200 bars each).
- **Lost history:** `PriceTargetSnapshot` (not verified whether FMP grades history can rebuild it), `CorporateEvent` (not refilled while its job is
  disabled), `FundamentalsCache` periods older than FMP now returns. Weinstein stage-since and momentum history are reproducible or unaffected.
- **Disk:** at investigation time the DB was 1.31 GB with 1.5 GB free (`backup_db` needs 1.25x). The wipe frees pages inside the file but does not shrink it.
- **Backups** keep wiped data for their retention window; a restore resurrects it with the old `TickerView`, and the next wipe removes it again.

## 13. Inconsistencies found (code versus docs)

- `etf-screener.md` L54, `models.py` (`EtfScreenerRow` docstring) and `etf_screener_data.py` L5 say an expired ETF "keeps its row"; `prune_etf_screener_rows`
  and the spec's own "Retention" section delete it.
- "Hidden, not deleted" / "viewing re-adds" / "nothing is ever deleted": see the list in `docs/specs/tracked-universe.md`, "Planned: opt-in universe and wipe"
  (updated by the classification-flip step).
- The runbook's verify counts are stale (`viewed 27`, `system 3`, 595 tickers); rule lettering differs between `tracked-universe.md` (a-d), `decisions.md` (a-e)
  and a docstring that said "(e)"; the runbook still mentions the `^GSPC` benchmark.
- `newssentimentcache` exists in the DB with no model: it is a leftover of the Alpha Vantage News-Sentiment feature (added 68dc559, removed c81e9b6).

## 14. Open decisions (ranked at the time)

1. Whether browsing (Screener/ETFs page use) should count as a touch for added tickers. **Decided 2026-10-03: added tickers never expire by the 30-day rule.**
2. Grandfathering: all 25 (recommended). 3. Remove button (recommended). 4. Watchlist add = implicit universe add (recommended; decided).
5. Delisted tickers: the same rule (decided). 6. Accept loss of `PriceTargetSnapshot` / `CorporateEvent` history on wipe. 7. Stock Add sync versus background.
8. Orphans with no `TickerView`: adopt first (decided). 9. Protect the live `rs_benchmark` (decided).

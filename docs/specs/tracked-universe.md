# Tracked universe (the opt-in ticker set)

Built 2026-10-02 from `docs/tracked-universe-expiry-investigation-2026-10-02.md`, which replaced the 2026-08-06 "index + ever-viewed +
watchlisted" rule (a ticker viewed once stayed in every nightly job forever). **Made opt-in 2026-10-03** (the classification flip, from
`docs/universe-add-wipe-investigation-2026-10-03.md`): a page view no longer admits a ticker; the owner adds it. The one part of that design not
active is the **wipe**: `pipeline/wipe_untouched_tickers.py` exists but is dry-run only, `--apply` is locked and nothing schedules it.

## The rule

`data/tracked_universe.py::classify_known_tickers` / `classify_etf_tickers` give every known ticker ONE reason, the **first match** in this order
(`_reason_for`, one pure function shared by the bulk classification and the single-ticker `classify_one` that backs the status API):

| # | Reason | Meaning | In the universe? |
|---|---|---|---|
| 1 | `delisted` | flagged `TickerScore.delisted_at` | **no**: out of every universe and every job, wins over everything below |
| 2 | `index` | member of the S&P 500, Nasdaq-100 or Dow list (`IndexConstituent`, `INDEX_NAMES`) | yes (protected) |
| 3 | `watchlist` | on **any** watchlist, monitored or not (`WatchlistTicker`) | yes (protected) |
| 4 | `system` | a seed ETF (`ETF_SEED_TICKERS`), `WEINSTEIN_BENCHMARK_TICKER`, or the live `rs_benchmark` setting | yes (protected) |
| 5 | `manual` | owner-entered data: a Moat, any custom valuation (active or not), a bank-capital entry, a growth-catalyst note (`ticker_data_registry.MANUAL_DATA_MODELS`) | yes (protected) |
| 6 | `added` | `TickerView.added_at` set (the Add API, or the 2026-10-03 grandfather backfill) | yes, **at any idle age**; leaves only through Remove |
| 7 | `browsed` | has a `TickerView` row, last opened within 30 days (`TRACKED_VIEW_WINDOW_DAYS`), not added | **no** |
| 8 | `expired` | same, but idle for MORE than 30 days (exactly 30 is still browsed) | **no**, awaiting the wipe |
| 9 | `untracked` | known, unprotected, not added, **no `TickerView` row** (e.g. a stock that left an index) | **no**; the wipe job adopts it |

A ticker is **in** the universe through `index`, `watchlist`, `system`, `manual` or `added` only; `OUT_OF_UNIVERSE` = `delisted`, `browsed`, `expired`,
`untracked`. Browsed, expired and untracked tickers keep all their data (the classification deletes nothing); they drop out of the nightly jobs and
the Screener's `all` universe (an ETF's `EtfScreenerRow` is deleted by the 1:45 job, as for any ETF outside the ETF universe). **Opening a ticker's page
records a view (the "last touch" the wipe reads) but never admits it.** Rule 5 exists because Monthly Momentum is "Moat-rated tracked tickers"; a
delisted ticker is excluded even if it has a Moat (the Momentum job still reports it as `skipped_delisted_count`).

`load_all_known_tickers(session)` is the wide set: index members, any ticker with a cached FMP *profile* (not any `FundamentalsCache` ticker: that table also
holds FX pairs such as `EURUSD`), any `TickerScore` row, any watchlist entry. It never expires and includes delisted tickers. It is for the jobs whose point is
to see everything: the weekly non-US purge, the delisted-flag sync, the search fallback while `profile_quote` is off, and the one-off backfills. A ticker the
app holds none of those rows for (a Moat on a never-fetched ticker) is in no universe whatever protections it carries.

- **A future ETF momentum universe must be added to `ETF_SEED_TICKERS`**; protection on the ETF side creates no row and no FMP call for an unseen ticker.

## The ETF universe

`partition_known_tickers(session)` splits the wide known set into (stock side, ETF side) using `data/etf_data.py::known_etf_tickers` (a `TickerScore.is_etf`
row, or a cached profile with `isEtf`/`isFund`) plus `ETF_SEED_TICKERS`. The sides are disjoint and together hold every known ticker; the ETF side also
carries the seeds the app has never seen. An ETF is only recognised once its profile or score row exists, so an unopened ETF stays on the stock side until it
is opened. The ETF side uses the same first-match rule minus `index` and `manual` (neither can apply to a fund). `ETF_SEED_TICKERS` = SPY + the 11 sector
SPDR ETFs, built from `SECTOR_ETFS`.

`load_tracked_universe` (the stock side) and `load_etf_universe` are read by the screeners (`GET /api/screener`, `/api/etf-screener`), the nightly jobs
(`pipeline/nightly_etf_screener.py` at 1:45 AM owns the ETFs: it also writes their `TrendAnalysis` and `TickerLastClose`), `stale_data_health_check` and
`tracked_universe_report`; see [ETFs screener](etf-screener.md). `tests/test_tracked_universe.py` pins that the stock universe holds no ETF, that the
sides are exhaustive with no overlap, and that `SYSTEM_TICKERS` is gone.

## Who uses which

| Expiring `load_tracked_universe` | Wide `load_all_known_tickers` |
|---|---|
| last-close snapshot and price-target snapshot (`load_us_price_target_universe`, minus non-US and delisted; the known-ETF filter is a belt-and-braces guard) | `non_us_purge` and its 2% refusal guard |
| `nightly_trend_calculation` (Weinstein and the bar-cache fill) | `sync_delisted_flags` (a flagged ticker must stay matchable) |
| `nightly_fundamentals_fetch` (minus known ETFs/funds) | the search fallback |
| `nightly_score_recompute`, `recompute_ticker_scores` (and `POST /api/screener/recompute`) | the daily-bar and price-target backfills |
| `monthly_momentum_snapshot` (`data/momentum_data.py`) | |
| `stale_data_health_check`'s stock staleness report (the ETF side is reported separately from `load_etf_universe`) | |
| Screener `GET /api/screener?universe=all` and `/screener/meta` | |

Not on this list because they never used the universe: Liquidity Zones, BB+RSI and Warren (monitored watchlists only), the Sector Heatmap (11 fixed ETFs) and
Market Breadth (`IndexConstituent` sp500). `tests/test_tracked_universe.py` fails if a job reads the helper from anywhere else, calls a removed name, or
re-declares the union.

## State and recording a view

`TickerView(ticker PK, last_viewed_at, added_at, added_source)`.

- **`last_viewed_at`, the touch.** Written by `GET /api/tickers/{t}/summary` only (the ticker page; the header, Summary, Chart and Analyst Ratings tabs and the
  ETF page share one SWR key; the Watchlist and Screener do not). A ticker that already has a row is touched at the **start** of the request
  (`touch_existing_ticker_view`, one `UPDATE ... WHERE last_viewed_at < start_of_today`), so a wipe cannot catch a ticker mid-open; a ticker with no row gets
  one after the summary succeeds (`record_ticker_view`, `INSERT ... ON CONFLICT DO UPDATE`), so an invalid symbol never creates a row. At most one write per
  ticker per calendar day; neither ever raises (a DB error is logged, the page is unaffected); a tab left open revalidates and so counts once a day.
- **`added_at` / `added_source`** (`'user'` | `'grandfathered'`, both nullable): set by the Add API, cleared only by Remove. `record_ticker_view` and the touch
  never write them; a watchlist change never writes them.
- **The seed.** `core/db.py::_seed_ticker_views`, called from `init_db()`: when `TickerView` is **empty**, every existing ticker (cached profile, `TickerScore`
  row, watchlist entry or index membership) gets `last_viewed_at = now`. Once any row exists a later `init_db()` does nothing. It was the 2026-10-02 migration; with
  the opt-in rule a seeded view admits nobody.
- **Grandfathering (done 2026-10-03).** `pipeline/grandfather_universe.py` marked the 25 tickers that were in the universe only through the old `viewed` reason
  (18 stocks, 7 ETFs) as added, source `grandfathered`, in one transaction, after a pre-write snapshot. The script was removed at the flip: the reason it selected
  on no longer exists, and running that rule now would admit every browsed ticker.

## What the jobs and pages do for a ticker outside the universe

- Its data, `TickerScore` row, Weinstein row, bars, price-target and momentum history all stay until the wipe. `prune_cache` (unchanged) deletes
  `FundamentalsCache` rows older than 180 days, so a browsed/expired ticker's cache rows go about 210 days after its last view.
- **Screener, `universe=all`:** `TickerScore.ticker IN tracked universe`, so a browsed or expired ticker is simply not listed; there is no hidden count (the
  `hidden_inactive` fields were removed with the flip). Index universes are unaffected. Saved views store filters, not results, so they stay valid and simply show
  fewer rows. **ETFs page:** rows of ETFs in `load_etf_universe` only; the 1:45 job deletes the rest (`prune_etf_screener_rows`).
- **Header Assessment chip:** `GET /api/tickers/{t}/score` recomputes live (`cache_only=False`) when the stored row is older than 36 hours
  (`SCORE_STALE_AFTER`), so the first view after a gap never shows a frozen score. Skipped for an ETF (no chip) and a delisted ticker (frozen on purpose).
- **ETF Overview:** `data/etf_data.py::_warm_daily_bars` fetches and caches the ETF's daily bars when the shared cache holds none or is behind the last completed
  session (about one FMP call, only then; zero for an ETF in the universe). On-demand only, never from a nightly job; a failure is swallowed.
- Weinstein on the ticker page already recomputes on demand when stale, and Technical/Chart fetch bars on demand.
- **Opening a ticker never adds it.** Until the owner clicks Add (or POSTs `/universe`, or puts it on a watchlist) a newly opened ticker works on its page but is in
  no screener and no nightly job.

## Delisted tickers

A flagged ticker leaves **every** nightly job at once, including the weekly fundamentals refetch. Its data is untouched until a wipe and its page still renders (the
summary route does not read the flag). The flag is not permanent: the weekly `sync_delisted_flags` clears it when **both** the whole delisted list was read
(`complete`) and the ticker is no longer on it as a qualifying hit, **and** a live FMP `/profile` call says `isActivelyTrading: true` (at most 50 re-checks a run,
today 5). A delisted ticker follows the wipe rule like any other (idle > 30 days, unprotected, not added) but is classified `delisted`, not `expired`. See
`docs/specs/fmp-data-and-bar-cache.md`, "Delisted-ticker handling".

## The wipe (built, locked, unscheduled)

A ticker is wiped when its last touch (`TickerView.last_viewed_at`) is more than 30 days old AND it has no protection AND it is not added. Protections are read
from the RAW sets, never from the classification reasons (`delisted` wins first there, so a delisted watchlisted ticker would look unprotected): any index name in
`IndexConstituent` (wider than the three that admit a ticker), any watchlist, a seed / the benchmark constant / the live `rs_benchmark`, manual data, and the added
set. A ticker with stored data but no `TickerView` row and no protection (`untracked`) is never wiped blind: it is **adopted** (`last_viewed_at` stamped now,
logged) and becomes eligible 30 days later. `classify_wipe_candidates(session, now, added, tickers)` returns per ticker `wipe` / `adopt` / `protected` /
`not due` / `ignored`; `tests/test_tracked_universe.py` pins, over a generated matrix (protection x added x idle x delisted), that `expired` is exactly a wipe
candidate, `added` is never one, `untracked` is the adoption case, and the wipe candidates are `expired` plus the delisted tickers that are also unprotected, not
added and idle.

- `data/ticker_data_registry.py`: every table with a per-ticker key, classified WIPE (with the deletion order, `TickerView` last), PROTECTING (`IndexConstituent`,
  `WatchlistTicker`, `TickerMoat`, `TickerCustomValuation`, `TickerBankCapitalMetrics`, `GrowthCatalystNote`) or KEEP (`SectorEtfReturn`). `newssentimentcache` (a leftover
  of the removed Alpha Vantage feature, no model) is registered by name with its own DDL. `FundamentalsCache` rows with `statement_type = 'forex_rate'` are never
  touched. `unclassified_ticker_tables(engine)` is the guard: `tests/test_ticker_data_registry.py` fails when a table with a ticker-like column is not classified,
  and `--apply` refuses on one.
- `pipeline/wipe_untouched_tickers.py` (manual, **not registered**: no crontab line, no `CRON_JOB_NAMES`/cadence/metadata entry, no heartbeat). Dry run is the
  default (read-only connection, no `init_db`, no log file, adopts nothing). `--apply` is locked behind `FATHOM_ALLOW_WIPE_APPLY=1`; it runs one `BEGIN IMMEDIATE`
  transaction per ticker, re-checks the decision inside it, deletes in registry order, adopts per the rule. `--tickers`, `--limit` (wipes oldest touch first, then
  adoptions). **Still to do before the lock is released:** (the Add/Remove buttons are built, step 3b), a fresh backup with the disk check, a first `--apply --limit` on a handful of
  tickers, then the cron registration after the nightly reschedule. With the real added set the live dry run reads: 0 wipe today, the 25 grandfathered tickers protected
  by `added`, and at 2026-11-03 only AVB, EQR, TWTR, WBA (4,088 rows) plus the 5 adoptions (CROX, DXC, ROKU, SNAP, VFC).

## API (`/api/tickers/{t}/universe`)

Three routes (`core/main.py`; logic in `data/universe_membership.py`; shapes in `core/schemas.py`: `UniverseStatusOut`, `UniverseAddOut`, `UniverseRemoveOut`). The
ticker is normalized like every other route. `in_universe` and `classification` come from `classify_one`, the single-ticker twin of the classification the universes
use, so **the status cannot disagree with `load_tracked_universe` / `load_etf_universe`** (pinned by a test over a state matrix). `state` is derived from the
protections and `added_at`:

| State | Meaning | `can_add` | `can_remove` |
|---|---|---|---|
| `protected` | at least one protection (`reasons` non-empty; `added_at` may also be set) | false | false |
| `added` | `added_at` set, no protection | false | true |
| `browsed` | neither (the classification reason may be `browsed`, `expired` or `untracked`) | `not delisted` and (profile not cached, or US-listed) | false |

`in_universe` is false for a delisted ticker even when protected or added (`delisted` wins first), and for a protected ticker the app holds no profile, score, index or
watchlist row for (`classification: null`). A ticker under an index name outside `INDEX_NAMES` reads `state: protected` (it is never wiped) but `in_universe: false`.

- **`GET`**: cache-only, zero FMP calls, no write, never touches `TickerView`. Returns `ticker`, `kind` (`stock` / `etf` / null when no profile or score row is cached),
  `in_universe`, `classification`, `state`, `reasons` (`index:<name>`, `watchlist:<list name>`, `seed`, `benchmark`, `rs_benchmark`, `manual:moat` / `custom_valuation` /
  `bank_capital` / `growth_note`), `can_add`, `can_remove`, `added_at`, `added_source`, `delisted`. A never-seen ticker reads `kind: null`, `browsed`, `can_add: true`
  (POST fetches its profile).
- **`POST`** (Add, idempotent): profile cached-first (a ticker just opened costs 0 calls; a never-seen one costs one live profile call; an empty profile is a 404 and
  writes nothing; the profile group off with nothing cached is a 503) -> non-US rejected (400, the existing `is_us_listed` rule on the profile `exchange`) -> delisted
  rejected (409) -> protected or already added: no-op, `changed: false`, no write -> otherwise ensure a `TickerView` row (created with `last_viewed_at = now` when missing,
  an existing value kept), set `added_at` (naive UTC) and `added_source = 'user'`, **COMMIT**, and only then the immediate compute; a failed compute never undoes the add.
  Kind comes from the profile (`isEtf` or `isFund`), never from the client.
  - **Stock:** a live `compute_ticker_score(cache_only=False)`, the call `POST /refresh` makes. It runs Steps 1/2/4/5, the summary and speculative growth, each through
    the cache, so the cost is whatever the opened page has not cached yet (estimate 10-20 FMP calls, 3-10 s; `fmp_calls` is null because `FMPClient` keeps no per-request
    counter). `fundamentals` group off: a cache-only compute (zero calls) and `score_computed: false`, `reason: "fundamentals_group_off"`. A raise or no data: still
    success, `score_computed: false`, `reason: "failed"` / `"no_data"`, `error` (apikey redacted).
  - **ETF:** `refresh_etf_screener(tickers=[X])` (about 2-4 calls, 1-3 s), skipped while `daily_prices` is off (`row_written: false`, `reason: "daily_prices_group_off"`).
    Nothing computed: `row_written: false`, `reason: "no_data"`, "appears after tonight's run". A raise: `reason: "failed"`.
- **`DELETE`** (Remove): 409 with the reasons while any protection applies (a protected + added ticker too); a 200 no-op (`changed: false`) when not added; otherwise clears
  `added_at` / `added_source`, never `last_viewed_at`. The ticker is out of the universe at once (`browsed`, or `expired` when idle). An ETF's `EtfScreenerRow` is deleted
  (and the 1:45 job would prune it anyway); a stock's `TickerScore` and all else stay for the wipe.
- **A watchlist add writes nothing for a stock and no `added_at` for anyone.** A ticker added, then watchlisted, then unlisted keeps its added state (`protected` while
  listed, `added` again after); one only ever watchlisted falls back to `browsed`. An ETF watchlist add (the ETF list endpoint, the generic add, the bulk add) writes the
  ETF's card at once through `ensure_etf_screener_rows` (best effort, never fails the add; see [ETFs screener](etf-screener.md)).

## Frontend (step 3b, 2026-10-03; simplified the same day)

One shared flow, `components/ticker/UniverseControl.tsx`, used by **both** `TickerHeader` (stock) and `EtfHeader` (ETF). `useUniverseControl(ticker)` returns two nodes:
`control` (a single button or nothing) goes first in the header's action cluster, before the watchlist button (`AddToWatchlistButton` / `EtfWatchlistButton`) and
`RefreshButton`; `note` (the success note / error line) goes **under** the cluster, never in the row. Types are in `lib/api/types.ts` (`UniverseStatusOut`,
`UniverseAddOut`, `UniverseRemoveOut`, matching `core/schemas.py`); the hook and the actions are `lib/hooks/useUniverse.ts` (`useUniverseStatus`, `addToUniverse`,
`removeFromUniverse`); the display rule is `lib/universe.ts` (`universeAction`). `UniverseControlView` stacks the two for the styleguide, which draws each state from a
mock status.

**What it shows** (the same for stock and ETF; decided from the GET response only; "in the universe" is gated on `in_universe`, never on `state`). There is **no
"In universe" label and no reasons label**: a protected ticker's membership already shows in the header (the index chip), and the first version's long label
("In universe · Dow, Nasdaq-100, S&P 500, Watchlist E1, ...") pushed the Watchlist and Refresh buttons onto a second row.

| Status | Shows |
|---|---|
| `state` browsed, `can_add` | outline button "Add to Universe" |
| `state` added, `can_remove`, `in_universe` | ghost button "Remove from Universe" (inline two-step confirm: "Remove from Universe?" + Confirm + Cancel, no modal); the button itself is the indicator |
| anything else: protected (any), delisted (any state), browsed with `can_add` false (non-US), `kind` null, status loading or failed | **nothing**, and never an error banner for a failed status request |

**Header layout.** Row 1 of both headers is `flex items-start justify-between` with **no `flex-wrap`**: the title block is `min-w-0 flex-1` (the part that wraps or shrinks), and the
actions are a right-hand column `shrink-0 flex-col items-end` holding the cluster (`flex flex-nowrap items-center gap-2 whitespace-nowrap`) and, below it, the note. Before
3b the row was `flex-wrap` with a `shrink-0` cluster: fine for two short buttons, but a wider cluster could not fit beside the title and wrapped to a second row. A header
test pins these classes for both headers.

**Add** (`POST`): the button shows "Adding…" and is disabled for the duration (a stock 3-10 s, an ETF 1-3 s); the rest of the page is not blocked. On success a stock with
`score_computed: false` shows one line under the cluster, the response's `message` (it names the cause: fundamentals group off, compute failed, not enough data), falling back to "Added. The
score will be filled in by the nightly run."; an ETF with `row_written: false` shows "Added. The card appears after tonight's run."; otherwise no note. On error (400 non-US,
404 empty profile, 409 delisted, 503 profile group off) the plain `detail` shows under the action cluster, no SWR key is touched and the status is unchanged.
**Remove** (`DELETE`): Confirm -> "Removing…". A 409 (a protection appeared, e.g. the ticker was put on a watchlist in another tab) shows the message (under the cluster) and revalidates the status
key, so the Remove button disappears (the ticker is now protected).

**SWR keys revalidated after a successful Add or Remove** (`isUniverseAffectedKey`, one `mutate(predicate)`): `/tickers/{t}/universe`, `/tickers/{t}/score`, every key
starting `/screener` (the Stocks Screener sweep `RecomputeButton` also makes), the ETFs screener's `/etf-screener` and `/etf-screener/meta` (exact keys: they deliberately
sit outside the `/screener` prefix, see `useEtfScreener.ts`), `/watchlists`, and each `/watchlists/{id}/rows`. The ETF saved views key (`/etf-screener/filters`) and other
tickers' keys are untouched. The status hook is a plain `useApiResource` (SWR defaults): the GET is cache-only, so neither the read nor its revalidation touches
`TickerView` or FMP.

## Verifying

`uv run python -m pipeline.tracked_universe_report [--days N]` (read-only, no FMP call, no `init_db`): known and in-universe counts, counts by reason, `TickerView` row
count and first/last date, the delisted and expired lists, and the browsed tickers that become expired within N days (default 7). See `backend/OPS_RUNBOOK.md`,
"Tracked universe". Live on 2026-10-03 after the flip: 586 known stocks (581 in the universe: index 518, manual 32, added 18, watchlist 13; 5 delisted), 19 ETFs (all in:
system 12, added 7).

# ETFs screener: read-model, endpoints, refresh job and page (steps 3 to 5 of the build)

Built 2026-10-02 from the ETFs screener investigation. Backend: the table, a write helper, two read endpoints,
a stock/ETF `kind` on saved views (step 3) and the refresh job code (step 4); frontend: the `/etfs` page (step 5). **The job is REGISTERED (step 6, 2026-10-03)**: daily at
**1:45 AM** in `crontab.txt`, in `CRON_JOB_NAMES`, `_EXPECTED_CADENCE_HOURS` (36 h, the shared daily value) and
`JOB_METADATA`, after Warren (ends by ~1:31) and before the planned corporate-events slot (1:50), fundamentals (2:00), the
recompute and the backup (`tests/test_cron_wiring.py::test_etf_screener_runs_after_its_inputs_with_room_on_both_sides`).
The frontend page (step 5) is built, see "Frontend" below. The cutover that took ETFs out of the stock-side jobs (step 7) is done, see "Cutover" at the end.

The ETF universe (which ETFs are in) is `data/tracked_universe.py::load_etf_universe`, see
[Tracked universe](tracked-universe.md), "The ETF universe". The ETF page itself is [ETF page](etf-page.md).

## The table: `EtfScreenerRow` (`core/models.py`)

One row per ETF, `ticker` is the key. A dedicated table; `TickerScore` was deliberately not widened (an ETF has none of
its fundamentals, and it needs fund fields `TickerScore` has no column for). **Every value column is nullable**: a row is
filled in pieces by different sources.

| Group | Columns | Source (for the step-4 job) |
|---|---|---|
| Identity | `ticker`, `name` | `/etf/info` `name` (or the profile `companyName`) |
| Fund facts | `asset_class`, `expense_ratio`, `aum` | `/etf/info` `assetClass`, `expenseRatio`, `assetsUnderManagement` (AUM from here, never the profile `marketCap`) |
| Quote | `last_price`, `pct_change_1d` | cached daily bars (last close; last two closes) |
| Technicals | `beta`, `return_1y`, `vs_spy_1y` | profile `beta` (raw); `compute_window_returns` 1Y on bars; the ETF's 1Y minus SPY's 1Y, in percentage points |
| Weinstein | `weinstein_stage`, `weinstein_stage_since_date`, `weinstein_stage_since_is_lower_bound`, `weinstein_ma_slope_pct`, `weinstein_vs_ma_pct`, `weinstein_pending_direction` | `TrendAnalysis`, the same fields `TickerScore` copies |
| Signals | `bb_rsi_entry_signal`, `warren_active_signal_kind`, `warren_last_buy_fired_at` | `TechnicalEntrySignal`; only ever set for an ETF on a monitored watchlist (the `ETF` list is one) |
| Bookkeeping | `as_of_date`, `info_updated_at`, `updated_at` | the price session date; FMP's `/etf/info` `updatedAt`; stamped on every write |

**Why these technicals:** they are exactly what the Stocks Screener's Technical section filters on and sorts by, minus
what has no meaning for a fund. Kept: Beta, the relative-performance filter (5Y vs SPY becomes **1Y vs SPY**: a fund's
history is short and the user asked for 1Y), Weinstein stage (the stage filter, its "Pending" option, "stage since" sort
and the pill's tooltip lines), and the Warren / BB+RSI filters and the Warren recency sort. Dropped: scores, P/E, growth,
Moat, valuation, speculative growth, market cap (AUM replaces it), sector and company type (FMP reports every ETF as
"Financial Services"; `asset_class` replaces them).

**Units.** `expense_ratio`, `pct_change_1d`, `return_1y`, `vs_spy_1y` and the two Weinstein percentages are percent
numbers (`0.09` means 0.09%, as `/etf/info` reports the expense ratio and `/stock-price-change` the returns), not
fractions.

## Write helper: `data/etf_screener_data.py::upsert_etf_screener_row(session, ticker, now=None, **fields)`

Creates the row or updates **only the columns passed**; every other column keeps its stored value, so the job can fill a
row from several sources without one blanking another. A column passed as `None` is set to `None` on purpose.
`updated_at` is always stamped; `ticker` is normalised. An unknown column (or the key / `updated_at`) raises `ValueError`
before anything is written (`WRITABLE_FIELDS`). One statement, `INSERT ... ON CONFLICT(ticker) DO UPDATE`.

## Endpoints (`core/main.py`)

Not under `/api/screener`, and the frontend SWR keys must be `/etf-screener...`, so the Moat / Valuation / Bank-capital
`mutate("/screener")` calls and the Recompute button's `startsWith("/screener")` sweep never refresh ETF data. The
stock endpoints (`/api/screener`, `/meta`, `/recompute`, `/filters`) are untouched.

- **`GET /api/etf-screener`** -> `list[EtfScreenerRowOut]`, sorted by ticker. Only rows whose ticker is in
  `load_etf_universe` (a join on the universe): an ETF outside it (browsed, expired, removed or delisted) is not returned,
  and its row is **deleted** by the next successful live nightly run (see "Retention"); adding it again (the Add API) writes
  its row at once. A seed (SPY or a sector SPDR) is returned as soon as it has a row, profile or no. Empty table -> `[]`.
- **`GET /api/etf-screener/meta`** -> `EtfScreenerMeta`: `total_etfs` (ETFs in the universe, with or without a row),
  `row_count` (rows returned; `total_etfs - row_count` is the "X of Y" gap; the `hidden_inactive` count was removed with the
  2026-10-03 opt-in flip), `asset_classes` (distinct non-null values among the returned rows, sorted) and `ranges`
  (min/max for `expense_ratio`, `aum`, `last_price`, `pct_change_1d`, `beta`, `return_1y`, `vs_spy_1y`; all keys always
  present, `null`/`null` when no value; `beta` is the post-rule value).

### Beta is equity-only

The row stores FMP's raw beta; the endpoint returns `beta: null` unless `asset_class` is equity
(`data/etf_data.py::is_equity_asset_class`, the one definition, also used by the ETF page's sector weights and Trading
data block). The `assetClass` values in the live `/etf/info` cache (2026-10-02, 10 ETFs) are **Equity** (7),
**Fixed Income** (1), **Commodities** (1) and **Alternatives** (1). **Equity means exactly `Equity`** (case and
surrounding spaces ignored); `None`, an empty string and any value FMP adds later (for example "Multi-Asset") are not
equity, so Beta stays hidden rather than guessed. The meta `beta` range is computed after the rule. Reason: a bond fund's
beta against equities is meaningless (TLT reads 2.4).

## Saved views: `SavedScreenerFilter.kind`

`kind` is `"stock"` (default) or `"etf"`; a name is unique **per kind** (`UNIQUE(name, kind)`), so a stock view and an ETF
view can share a name. `GET /api/screener/filters`, `PUT /api/screener/filters/{name}` and
`DELETE /api/screener/filters/{name}` take an optional `?kind=` query parameter defaulting to `stock` (any other value is
a 422); with no parameter they behave exactly as before. `SavedScreenerFilterOut` gained a `kind` field. Deleting a
watchlist still removes every view that references it, whatever its kind.

## Frontend: the ETFs page (step 5)

Route `/etfs` (`app/etfs/page.tsx`, tab title "ETFs"), second item of the top nav (Stocks, **ETFs**, Watchlist, ...). The
Stocks Screener's nav label and heading were renamed in the same change: "Screener" -> "Stocks", page heading and tab title
"Stocks Screener"; the route stays `/screener` and `/` still redirects to it. The page is the Stocks page's shell
(header, Sort row, sidebar plus 3-column card grid, 18 per page, saved views, Reset) with client-side filtering, sorting
and paging over `GET /api/etf-screener`. No universe selector, no Recompute button; the Watchlist filter is never dimmed
and lists every watchlist (ETF and E1-E5 included). The header's "Add to watchlist" adds the filtered tickers, as on the
Stocks page.

- **Data and keys.** `lib/hooks/useEtfScreener.ts` (`/etf-screener`, `/etf-screener/meta`) and
  `lib/hooks/useSavedEtfFilters.ts` (key `/etf-screener/filters`, request `/screener/filters?kind=etf`). **No ETF SWR key
  starts with `/screener`**, so the Moat / Valuation / Bank-capital `mutate("/screener")` calls and the Recompute sweep
  never refresh ETF data (`lib/hooks/useEtfScreener.test.tsx` pins it). The stock saved-views hook is unchanged (key
  `/screener/filters`, no `kind`).
- **Sidebar**, in order: **Watchlist**, **Fundamental** (Asset class multi-select from `meta.asset_classes`; ranges
  Expense ratio %, Quote USD, 1D change %, AUM USD with the `500M` / `2B` suffixes), **Technical** (Beta; 1Y vs SPY in
  percentage points; Weinstein stage with "Pending"; Warren entry (2h); BB + RSI entry (2h) with the monitored-lists
  caption). Section titles are the Stocks page's singular "Fundamental" / "Technical". "Quote" is the price range, as on the
  Stocks page, plus a separate 1D change range. The `return_1y` column has no filter or sort (not on the Stocks page).
- **Sort options:** AUM (default, descending), Expense ratio, Quote, 1D change, Beta, 1Y vs SPY, Warren signal recency,
  Weinstein: stage since. Nulls last in both directions.
- **Null rule.** An active range excludes a row whose value is null, as on the Stocks page. That includes Beta: it is null
  for a non-equity fund (the backend's rule, not re-applied on the client), so a Beta range drops those funds; the card shows
  a dash. The meta `ranges` are not used by the page.
- **Card** (`components/etf-screener/EtfScreenerCard.tsx`): ticker, name, asset class badge, Weinstein pill, then Quote, 1D,
  AUM, Exp. ratio, 1Y vs SPY ("+3.5 pp"), Beta. The whole card is a link to `/tickers/X`, `target="_blank"` (the same
  inline new-tab pattern as `ScreenerCard`; the nav's background-tab click replay is nav-only).
- **States.** Zero rows: "ETF data hasn't been loaded yet. It is filled by the nightly ETF job." (until the job's first run). Rows but no match: "No ETFs match the current filters." Subtitle: "X of `total_etfs` ETFs", then "— N match the
  current filters" (no hidden-ticker note since the opt-in flip), or the watchlist flavour as on the Stocks page.
- **Shared vs twin.** Shared as they were or parameterized: `SortControls` (an `options` prop, default the stock list),
  `SavedFiltersBarView` (generic over universe, sort field, filter state and saved row; the stock `SavedFiltersBar` and the new
  `SavedEtfFiltersBar` wrap it), `WatchlistFilters`, `CollapsibleFilterSection`, `Pagination`, `MultiSelectDropdown`,
  `RangeField`, `Checkbox`, `AddToWatchlistButton`, `WeinsteinStagePill`, and in `lib/screenerFilters.ts` the range test
  (`inRange`), counting rule (`countActiveIn`) and null-last sort (`sortRows`) that the stock functions now call. ETF twins
  (bound to the ETF row or state): `EtfScreenerCard`, `EtfFundamentalFilters`, `EtfTechnicalFilters`
  (`components/etf-screener/`) and `lib/etfScreenerFilters.ts` (state, filter, sort).
- Tests: `app/etfs/page.test.tsx`, `components/etf-screener/*.test.tsx`, `lib/etfScreenerFilters.test.ts`,
  `lib/hooks/useEtfScreener.test.tsx`, the nav tests in `components/nav/TopNav.test.tsx`.

## How the schema reaches the live DB

Both changes apply automatically in `core/db.py::init_db()`, which runs on every backend start (`bin/start.sh` calls it
explicitly before the servers, and the FastAPI lifespan calls it) and at the start of every cron job. Nothing is run by
hand and nothing needs a separate deploy step beyond restarting the backend on the new code.

- **`etfscreenerrow`** is a new table: `create_all` creates it, empty.
- **`savedscreenerfilter`** needs a rebuild, not just a column. The live table was created with `UNIQUE(name)` as a table
  constraint, which SQLite cannot drop, and `_add_missing_columns` can only add a nullable column. So
  `_migrate_saved_filter_kind` (runs after `create_all`, before `_add_missing_columns`) renames the old table, creates the
  new one from the model, copies every row with `kind = 'stock'` (ids, timestamps, `watchlist_id` kept), drops the old
  table, all in one explicit transaction (a failure rolls back and leaves the old table untouched). It is idempotent: it
  recognises the new constraint name in the table's DDL and does nothing on a fresh or already-migrated database. The live
  table holds 3 views (ids 5, 8, 9), so the rebuild is instant. Existing views keep working as stock views.
- Tests: `tests/test_db_migrations.py` (rebuild, idempotence, rollback, uniqueness per kind),
  `tests/test_saved_screener_filters.py`, `tests/test_etf_screener.py`.

## The refresh job (step 4)

Code: `data/etf_screener_refresh.py::refresh_etf_screener(tickers=None, *, cache_only=False, dry_run=False)`; entry point
`pipeline/nightly_etf_screener.py` (`uv run python -m pipeline.nightly_etf_screener [--tickers ..] [--cache-only]
[--dry-run]`). For each ticker in `load_etf_universe` it computes the row's fields and writes them through
`upsert_etf_screener_row`. Every source is an existing path; nothing is reimplemented.

**Rows are also written outside the nightly run (opt-in universe, step 3a, 2026-10-03).** Both call `refresh_etf_screener(tickers=[...])`
directly (an explicit list bypasses the universe and never prunes; not the pipeline `main()`, which calls `configure_logging`/`init_db`),
gated on the `daily_prices` group like the job: (1) `POST /api/tickers/{t}/universe` (Add) writes the new ETF's row at once (about 2-4 FMP
calls: one bars batch, one last close, `/etf/info` when not cached; the profile is already cached from the open); (2) an ETF **watchlist add**
(`POST /api/tickers/{t}/etf-watchlist`, the generic add, the bulk add) writes the row for each ETF that has none (cached profile or score row
says ETF; at most 5 per request, one call, best effort: a failure is logged and never fails or delays the add beyond that call). A write that
computes nothing (`_worth_writing`) leaves no row; the response says so and the card appears after the next nightly run. `DELETE
/api/tickers/{t}/universe` (Remove) deletes the ETF's row; until the classification flip a recently viewed ETF is still in `load_etf_universe`
by the old rule, so the 1:45 job can rebuild it. See `docs/specs/tracked-universe.md`, "API".
The ETF page header's **Add to Universe / Remove from Universe** control (step 3b, `components/ticker/UniverseControl.tsx`, shared with the stock header; shown only as Add for a browsed ETF or Remove for an added one, never for a protected seed ETF) calls those two routes; after either it revalidates `/etf-screener` and `/etf-screener/meta` (exact keys, outside the `/screener` prefix) so an open ETFs page picks up the new or removed card. An Add whose card was not written shows "Added. The card appears after tonight's run." See `docs/specs/tracked-universe.md`, "Frontend".

| Field(s) | Source |
|---|---|
| `last_price`, `pct_change_1d`, `as_of_date` | the shared daily-bar cache: one `get_or_fetch_bars_batch` (5 years, `auto_adjust=False`, the same call the Weinstein job makes; a current wide cache makes no FMP call), then `read_cached_completed_daily_bars` per ticker (completed sessions only, the provisional-bar rule applies). Split-adjusted close, no dividend adjustment. `pct_change_1d` is the last two bars; `as_of_date` is the newest bar's date |
| `return_1y` | `scoring/etf_returns.py::compute_window_returns`, window `1y`, anchored on the ETF's newest bar (None for a fund younger than a year or a newest bar more than 5 days stale) |
| `vs_spy_1y` | `return_1y` minus SPY's 1Y return from the same bars, **percentage points**. SPY must have a bar on the ETF's own `as_of_date` (the same window); otherwise it is left unset and logged. SPY itself reads 0.0 |
| `asset_class`, `expense_ratio`, `aum`, `info_updated_at` | `/etf/info` through `data/etf_data.py::load_etf_info` (`get_or_fetch`, 1-day TTL `etf_info_staleness_days`; the `etf_info` group toggle and the 402 safety net apply; off or failing = the cached row is served). `info_updated_at` is `updatedAt` as naive UTC. AUM is `assetsUnderManagement`, never the profile's `marketCap` |
| `name`, `beta` | the cached profile (30-day TTL `profile_staleness_days`). `beta` is stored **raw** (the equity-only rule is applied on read); a beta of 0 or NaN is FMP's "unknown" and is not stored. `name` is the profile's `companyName`; `/etf/info`'s `name` is used only when the profile has none and did not fail |
| `weinstein_*` (stage, since_date, is_lower_bound, ma_slope_pct, vs_ma_pct, pending_direction) | the pure engines `compute_weinstein_stage` / `compute_weinstein_pending` on the ETF's cached bars with the live Settings > Weinstein parameters and the configured RS benchmark's bars (default SPY); a missing benchmark degrades the RS fields inside the engine, not the stage. Computed **once** per ETF (`data/trend_analysis_data.py::compute_weinstein_results`); the same result is also stored to the ETF's `TrendAnalysis` row on a live run (step 7, see "Other tables the job writes"), so the two always agree |
| `bb_rsi_entry_signal`, `warren_active_signal_kind`, `warren_last_buy_fired_at` | **read, not computed**: from `TechnicalEntrySignal` (`bb_rsi`/`warren`) and `WarrenSignalEvent` through `is_entry_signal_active`, `warren_active_up_kind`, `last_buy_signal_fired_at`, the helpers `data/ticker_score.py` uses. The monitored-watchlist jobs produce them for tickers on `E<n>` lists and the `ETF` list; any other ETF has no row, so these are None. Not copied from `TickerScore` |

### Null and partial-write rules

- Only fields **computed successfully this run** are passed to the upsert, so a source that failed, or has nothing, never
  overwrites a stored value with NULL (one ETF's `/etf/info` outage keeps its last asset class, expense ratio and AUM;
  a run with no bars keeps the last price and returns). A fund too young for a 1Y return, a seed with no cached info, a
  stage that could not be determined: those columns are simply not written.
- **Exception: the three signal fields** are a deterministic local read, so "no signal row" is a real answer and is
  written as NULL (a signal that ended is cleared). But a run whose only computed fields are those never **creates** a row
  (a seed with nothing cached stays row-less); it may update a row that exists.
- One source raising (bars, Weinstein, signals, `/etf/info`, profile) costs only its own fields and is recorded in that
  ETF's `errors`; one ETF raising (for example the upsert) is logged and the run continues. `failed` counts ETFs with
  any error. The pipeline entry point applies `core.cron_health.check_failure_threshold` (all failed, or >= 5% of >= 25).
- Seeds the app has never opened (the nine sector SPDRs today) get a first-time fetch through the same paths (profile,
  `/etf/info`, bars), which also caches their profile, so they are known ETFs from then on.
- A fresh cache makes no FMP call: `/etf/info` (1 day), profile (30 days), bars (the shared cache's own freshness rule).

### Modes

- **Live** (default): fetches what is stale, writes rows, then prunes. Skipped (a real `skipped` cron status) while the
  `daily_prices` group is off (`job_skip_reason`); `etf_info` / `profile_quote` off serve cached rows.
### Other tables the job writes (step 7, Phase A, 2026-10-03)

A **live** run also writes, for every ETF it processes, the two rows the stock-side jobs used to provide:
- **`TrendAnalysis`**, from the one Weinstein computation above, through `store_weinstein_results` (the store half of
  `compute_and_store_from_frames`, which now calls the same two functions). Written only when a stage was determined (the stock
  job writes a NULL stage; this job leaves the previous row alone). A store failure is that ETF's `trend_analysis` error and
  costs only that table.
- **`TickerLastClose`**, through `data/last_close_data.py::refresh_last_closes` (one `/historical-price-eod/full` call per ETF, the same
  completed-session rule). A failed ETF keeps its stored close and is recorded as that ETF's `last_close` error.
- The weekly full bar resync (Sunday UTC, the stock-side bar job's rule) is also done for the ETFs' own bars (`force_resync`).
`cache_only` and `dry_run` write **neither** (`cache_only` still writes `EtfScreenerRow` rows, as before; it has no network to
fetch a last close with). The run summary gains `trend_written` and `last_close_written`, also in the cron message.

- **`cache_only`**: no bar fetch, no `/etf/info` or profile call (stale cached rows are used as they are): no network
  call at all. Still writes rows, and never prunes.
- **`dry_run`**: computes and returns everything (the summary's `results`, per ETF: `fields`, `notes`, `errors`), writes
  no `EtfScreenerRow` and prunes nothing (`would_prune` reports the count). It does **not** stop the normal read-through
  caches from filling when it is not also `cache_only`; **`--cache-only --dry-run` is the run that writes nothing at
  all**, and the CLI then skips `init_db()` and the log file, so it can run against the real database read-only.
- `cron_heartbeat("pipeline.nightly_etf_screener")` is in the `__main__` block (matching its `CRON_JOB_NAMES` entry) and is used for a real run only; `--cache-only` /
  `--dry-run` write no `CronRunLog` row.

### Retention

After a **successful live run** (not `cache_only`, not `dry_run`, no explicit `--tickers`), `EtfScreenerRow` rows for
tickers no longer in `load_etf_universe` (browsed, expired, removed, delisted, or not an ETF) are **deleted**, genuinely
(`prune_etf_screener_rows`; the ETF read-model is the one place where leaving the universe already deletes). A run counts as successful when the batch bar fetch did not raise **and** the failure
threshold was not breached (the same rule the heartbeat applies); otherwise nothing is pruned. Re-opening such an ETF does
not bring it back (a view admits nobody): adding it does, and the Add API writes its row at once.

### Registration (step 6, done 2026-10-03)

- `crontab.txt`: a daily line `... -m pipeline.nightly_etf_screener >> .../logs/nightly_etf_screener_cron.log 2>&1`, then
  `crontab crontab.txt` from `backend/` and `crontab -l` checked against the file. Slot: after the Weinstein/bar-cache
  job (it reads the bars that job fills and rides the same incremental fetch), after LP, BB+RSI and Warren (it reads
  their output for the signal fields), and before the score recompute and backup; the exact minute is the schedule
  rework's call (about 1-2 minutes for 20 ETFs, dominated by pacing).
- `core/cron_health.py`: `"pipeline.nightly_etf_screener"` in `CRON_JOB_NAMES`, a `_EXPECTED_CADENCE_HOURS` entry (24),
  a `JOB_METADATA` entry (display name, description, expected time).
- `tests/test_cron_wiring.py` may need the new job added to its ordering assertions (the chain-order list, and
  "after the jobs it copies from"), and `backend/OPS_RUNBOOK.md` the job's row.

## Cutover (step 7, done 2026-10-03): ETFs leave the stock-side jobs

Done in two commits: phase A (additive: the ETF job also writes `TrendAnalysis` and `TickerLastClose`, ran live and verified
against a before-snapshot) and phase B (the switch). Record of what the stock-side jobs provided for an ETF and what replaced it:

| Provided by | What it gave an ETF | Now |
|---|---|---|
| `nightly_trend_calculation` (1:05) | the 5-year daily bars in the shared cache, the `TrendAnalysis` row, the Sunday full resync | The ETF job fetches its own bars (one batch, same cache, Sunday `force_resync`) and writes `TrendAnalysis` from the one Weinstein computation shared with `EtfScreenerRow`. SPY's bars still ride along in the stock job's batch (the RS benchmark, independent of the universe) |
| `nightly_last_close_snapshot` (1:00) | `TickerLastClose` | The ETF job writes it through `refresh_last_closes` |
| `nightly_score_recompute` (3:25) | the ETF `TickerScore` row | **Frozen, left in place** (the 1:45 job and the cutover never delete it; the locked wipe would, with the rest of an unadded, unprotected ETF idle past 30 days). Nothing reads it for the ETF screener; the Watchlist re-derives an ETF row live (`compute_ticker_score(cache_only=True)`, stage from `TrendAnalysis`, price from `TickerLastClose`); `known_etf_tickers` still finds an ETF through its profile or that old row. **Since 2026-10-04 no ETF page load rewrites the row:** `GET /score` computes the same response but calls `compute_ticker_score(persist_etf=False)`, so an ETF gets no new `TickerScore` row (a browsed ETF is recognised from its cached profile) and a frozen one is not touched; a stock is upserted as before. (The Watchlist's live per-row compute and the Add path still call it with the default and can still write an ETF row; that is unchanged.) |
| `stale_data_health_check`, `tracked_universe_report` | the ETFs in the stock reports | Stock figures exclude ETFs; both reports have a separate ETF side |
| Sector Heatmap, Market Breadth | nothing (own lists, own fetches) | unaffected. The Heatmap (1:35) now does the 11 sector ETFs' bar fetch itself (they used to arrive warm from 1:05); the ETF job (1:45) then reads them warm |
| `nightly_fundamentals_fetch`, `nightly_price_target_snapshot`, Monthly Momentum | nothing (already skipped ETFs) | unaffected (the known-ETF filters remain as a belt-and-braces guard) |

`SYSTEM_TICKERS` was retired (`ETF_SEED_TICKERS` has the same members and no other consumer existed). The pin test that said the
stock universe was "unchanged" was rewritten on purpose to pin the stock-only behavior. (`ScreenerMeta.hidden_inactive` and `count_hidden_inactive_etfs`
were removed with the 2026-10-03 opt-in flip.) An unopened ETF the app
has never seen has no profile or score row, so it stays on the stock side until it is opened.

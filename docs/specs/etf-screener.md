# ETFs screener: read-model and endpoints (step 3 of the build)

Built 2026-10-02 from the ETFs screener investigation. **Backend data layer only**: the table, a write helper, two read
endpoints and a stock/ETF `kind` on saved views. Not built yet: the nightly ETF job that fills the table (step 4), the
frontend page, and the cutover that takes ETFs out of the stock-side jobs. Until the job exists the table is empty and
`GET /api/etf-screener` returns `[]`.

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
  `load_etf_universe` (a join on the universe): an expired ETF keeps its row but is not returned, and a re-view brings it
  back. A seed (SPY or a sector SPDR) is returned as soon as it has a row, profile or no. Empty table -> `[]`.
- **`GET /api/etf-screener/meta`** -> `EtfScreenerMeta`: `total_etfs` (ETFs in the universe, with or without a row),
  `row_count` (rows returned; `total_etfs - row_count` is the "X of Y" gap), `hidden_inactive`
  (`count_hidden_inactive_etfs`), `asset_classes` (distinct non-null values among the returned rows, sorted) and `ranges`
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

## For the step-4 job

- Write through `upsert_etf_screener_row`; pass only what the run computed. Iterate `load_etf_universe`.
- Weinstein / signal fields are copied from `TrendAnalysis` / `TechnicalEntrySignal` (the ETFs are still in the stock-side
  Weinstein job until the cutover, so those rows exist; after the cutover the ETF job must compute or take them).
- Store `beta` raw; do not apply the equity rule at write time.
- Seeds the app has never opened (nine sector SPDRs) have no profile or `/etf/info` yet: the job must fetch them.

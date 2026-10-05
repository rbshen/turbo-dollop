# Momentum (stocks and ETFs)

A monthly 3/6/12-month price-momentum ranking, price-only and independent of Step 1-5 / Overall Assessment scoring.
Two rankings share one engine, one job and one anchor rule: **stocks** (`MomentumSnapshot`, the `/momentum` page) and
**ETFs** (`EtfMomentumSnapshot`, `GET /api/momentum/etf`; backend and `/momentum` table built 2026-10-05).
The Sector Heatmap is a separate feature ([Sector Heatmap](sector-heatmap.md)).

## Signal

`scoring/momentum.py::compute_momentum_ranking` (pure, no DB/HTTP), unchanged for both rankings:

- Trailing returns over 3, 6 and 12 months from the anchor date, each `close(anchor) / close(anchor - N months) - 1`,
  where each close is the last bar on or before the date (raw returns, no skip-month).
- `composite_score` = simple average of the three. Rank 1 = highest composite; ties break by ticker (ascending).
- **Drop rules** (never imputed): a ticker is left out when it has no bar on or before the anchor, or no bar on or
  before any of the three lookback dates (under ~12 months of history). Dropped tickers are counted, not stored.
- `return_1w` (anchor - 7 days) and `return_1mo` are informational columns shown beside the ranking; never part of the
  composite or rank, and `None` (not a drop) when the fund lacks a bar that far back.
- **Basis: split-adjusted close, price only** (FMP daily bars through the shared bars cache,
  `auto_adjust=False`), not dividend-adjusted. The Sector Heatmap made the same call: the app is used for options
  trading, not for holding the underlying. For ETFs this understates income-heavy funds (bond, covered-call, high-yield
  equity) against total return; it matters little for the growth funds that tend to top the table.

## Universe

- **Stocks:** `load_tracked_universe` filtered to tickers with a Moat rating, not delisted and not an ETF/fund.
  The stock `moat` is stored in the snapshot (the rating at compute time).
- **ETFs:** `data/tracked_universe.py::load_etf_universe` (the same set as the ETFs screener: seed ETFs, any
  watchlist, ETFs the owner added; not browsed/expired/untracked/delisted). The universe is **frozen per snapshot**: it is
  read once when the snapshot is computed, and a later change never rewrites a stored month. No Moat column.
  Because the ranked set is the ETF universe itself, no `ETF_SEED_TICKERS` addition is needed (docs/decisions.md,
  2026-10-05); an ETF that leaves the universe is simply not in later snapshots.
- **Leveraged and inverse funds are included** (SOXL, TECL, TQQQ ...). They are in the ETF universe, the ranking
  does not filter them, and they often take the top places on a 3/6/12-month return composite. Read the table with that
  in mind; there is no leverage flag yet.

## Anchor rules and the job

`pipeline/monthly_momentum_snapshot.py`, cron `50 2 1-5 * *`. It tries on days 1-5 and runs only on the first NYSE
trading day of the month (`helpers/trading_calendar.py::resolve_month_end_anchor`), anchoring to the **last trading day
before it**, i.e. the prior month-end close. Every other day is a successful no-op.

Order: the same anchor gate and `daily_prices` group-off skip (one `skipped` cron status for the whole run), then the
stock pass, then the ETF pass. Both passes always run; if either raises, the job fails (the first error is re-raised, the
other logged), so neither can hide behind the other. Message: `stocks N/M, ETFs X/Y, K still stale after fetch, ...`.
No separate cron line or `CRON_JOB_NAMES` entry: the ETF pass is part of the existing job.

Manual / backfill flags (`--force-anchor YYYY-MM-DD` bypasses the first-trading-day gate):

- `--etf-only` runs only the ETF pass.
- `--cached-bars-only` (needs `--etf-only`) reads the shared bars cache with no FMP call and no cache write
  (`clients/shared_bars_cache.py::read_cached_daily_bars_batch`); because nothing is fetched it also bypasses the group
  gate. Used for backfills such as `--force-anchor 2026-08-31 --etf-only --cached-bars-only`. The run still writes a
  `CronRunLog` row (the heartbeat wraps every CLI run), so it becomes the job's "last run" in Settings.

## Storage

- `MomentumSnapshot` (stocks) and `EtfMomentumSnapshot` (ETFs): one row per ticker per `as_of_date`, the **full**
  ranking, append-only across dates. `as_of_date` is the anchor (a month-end trading day); `computed_at` is the real run
  time. Returns are fractions (0.12 = +12%).
- **Idempotent per `as_of_date`**: a re-run deletes and re-inserts only that date's rows of its own table, in one
  transaction. The ETF pass never touches `MomentumSnapshot`.
- `company_name` and `last_price` are joined at request time (stocks: `TickerScore`; ETFs: `EtfScreenerRow.name`,
  `TickerLastClose` for both), not stored.
- `EtfMomentumSnapshot` is `KEEP` in `data/ticker_data_registry.py`: it is a frozen history of past rankings, so the wipe
  does not delete a wiped ETF's rows out of past months.

## Endpoints

- `GET /api/momentum?period=current|previous` — the full stock ranking (`MomentumOut`, with `moat`, `overall_score`).
- `GET /api/momentum/etf?period=current|previous` — the **top 5** ETFs only (`EtfMomentumOut`; rows are
  `EtfMomentumRowOut`: no moat, no overall score, no currency), plus `total_ranked`, the size of the stored ranking.
  The full ranking stays in the table.
- Both read stored snapshots, never compute, and return an empty body (`as_of_date: null`, no rows), never an error,
  when no matching snapshot exists.

### "Previous" month

`data/momentum_data.py::previous_snapshot_date`, used by both endpoints: **current** = the snapshot with the latest
`as_of_date`; **previous** = the latest snapshot whose `as_of_date` falls in a calendar month **earlier than the
current snapshot's month**. A second snapshot in the current month (a mid-month manual run) is never "previous".
(Before 2026-10-05 the stock endpoint took the second-newest date, which resolved to 2026-09-23, a manual snapshot
anchored mid-September, instead of 2026-08-31.)

## Caveats

- **Backfills use today's universe.** An ETF snapshot computed for a past anchor ranks the ETFs in the universe *now*,
  so it is not point-in-time: funds added since, or since removed from the universe, differ from what a run on that
  date would have ranked, and the 2026-08-31 and 2026-09-30 ETF snapshots were backfilled this way (cached bars only).
  Real month-end runs freeze their own universe.
- A backfill is limited by what the bars cache holds (the 12-month lookback needs ~13 months of daily bars); a fund
  without them is dropped, not imputed.
- Price-only and leveraged-fund inclusion: see Signal and Universe.

## Frontend (`/momentum`)

- **Layout.** `app/momentum/page.tsx`: the page title "Momentum", then two `MomentumSection`s, **Stock** (the existing table) and
  **ETF** (below it), then the one-line "Ad hoc external research" disclaimer. There is no page-level period toggle and no
  page-level "As of" subtitle: each section carries its own.
- **Section title style.** The design system's `Section` family (hairline above, `h2` at `text-sm font-semibold text-text-primary`,
  sentence case), the same title the Settings and ETF Overview sections use. `Section` has no actions slot, so
  `MomentumSection` renders `Section` untitled and draws the identical `h2` itself, in a header row with the period toggle on the
  right and the section's "As of ... · Computed ..." caption (`text-xs text-text-secondary`) under the title. The `Section` is a
  `role="region"` labelled by its title.
- **`components/momentum/MomentumSection.tsx`.** Props: `title`, `useData` (a module-level hook, `useMomentum` or
  `useEtfMomentum`), `topN`, `showMoatAndScore` (default true), `footnote`. It owns its own `period` state, the `This month |
  Previous month` `SegmentedControl` (`aria-label` "<title> period"), the data call, the pulsing skeleton (`topN` rows, `colSpan`
  = the table's column count), the empty text ("No snapshot yet ..." / "No previous month's snapshot available yet.") and the
  error text ("Failed to load <title> Momentum data."). The two sections are fully independent: each toggle refetches only its own
  endpoint and an error in one never shows in the other.
- **Rows shown.** Stock `topN` 10 (the endpoint returns the full ranking, the page slices); ETF `topN` 5 (the endpoint already
  returns the top 5; the slice is a guard). There is no "top N of M" note, so `total_ranked` is typed (`EtfMomentumOut`) but not
  displayed.
- **Hooks and types.** `lib/hooks/useMomentum.ts`: `useMomentum` (unchanged) and `useEtfMomentum` (`GET /api/momentum/etf?period=`).
  `lib/api/types.ts`: `EtfMomentumRowOut`, `EtfMomentumOut` (with `total_ranked`); the stock types are unchanged.
- **`MomentumTable`.** Rows are `MomentumTableRow` (an ETF row plus optional `moat`, `overall_score`, `quote_currency`, so a stock
  row or an ETF row both fit). Prop `showMoatAndScore` (default `true`): `false` hides the Moat and Score columns (9 columns instead
  of 11). Rank, Ticker (company name below it), Last, 1 w, 1 mo, 3 mo, 6 mo, 12 mo and Composite are identical for both; a missing
  quote currency (always the case for an ETF) formats as USD. The ETF section passes `false`.
- **Footnotes.** Stock section: the Moat point-in-time caveat only (today's Moat classification is the filter). ETF section:
  price-only basis (split-adjusted, no dividends), leveraged funds included, and the previous-month ranking uses today's ETF
  universe, not point-in-time (see Caveats). Neither footnote appears in the other section.
- **Not changed:** `/styleguide`, the backend, CLAUDE.md. Tests: `app/momentum/page.test.tsx`, `components/momentum/MomentumTable.test.tsx`.

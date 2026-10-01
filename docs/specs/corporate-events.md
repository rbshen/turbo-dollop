# Corporate events cache (earnings, dividends, splits)

An FMP-backed local cache of earnings dates, dividends and splits (`data/corporate_events_data.py`, tables
`CorporateEvent` and `CorporateEventFetch`). All three FMP endpoints (`/earnings`, `/dividends`, `/splits`)
belong to the `corporate_events` data group; with the group off, readers serve the cached rows however old
(see `CLAUDE.md`'s data-groups section). The only current consumer is the Chart tab's E/D markers
(`data/chart_events_data.py`, see `docs/specs/chart-tab.md`). Splits are stored for completeness; no chart
marker reads them yet.

## Refresh job

**Disabled 2026-10-01 pending investigation** (about 1,165 FMP calls per run at 406-527 requests/min, over Starter's
300/min; see `docs/decisions.md`). The cron line is commented out and the job is listed in
`core/cron_health.py::DISABLED_CRON_JOBS`; the code, tables and rows are untouched and the cache serves as-is.
What degrades while it is off: the Chart tab's E/D markers are the cache's **only** reader (the next-earnings date,
the scores and the fundamentals jobs read the separate `earnings`/`latest` row in `FundamentalsCache`, group
`fundamentals`, and are unaffected). Nothing fetches on demand, so (1) a company that reports after the last run (the
2026-10-01 02:47 refresh) gets no new "E" marker, because a marker needs back-filled actuals (as of 10-01: 2 tickers
report within 7 days, 25 within 14, about 300 within 30, about 530 within 60); (2) a dividend declared after that run has
no "D" marker (441 dividend payers; 70 had a future ex-date row cached, 371 did not); (3) a ticker never cached, such as
anything first opened after 10-01 02:47 (the ETFs GLD, IBIT, QQQ, SMH, SOXX, XLK, XLV), has no markers at all until
`uv run python -m pipeline.nightly_corporate_events --tickers X,Y` is run for it (2 calls per ticker, plus 1 for splits
when due). No retention prune runs either, which is harmless. To re-enable, see `backend/OPS_RUNBOOK.md`.

`pipeline/nightly_corporate_events.py` (cron 2:45 AM server time when enabled; registered in `core/cron_health.py`).
Earnings and dividends refresh nightly. Splits refresh **weekly** (`SPLITS_REFRESH_DAYS = 6`, via
`splits_due`): a ticker's splits are due when never fetched, or last successfully fetched at least 6 days
ago. The check is judged off `CorporateEventFetch`, not the weekday, so a missed run self-heals the next
night (6 rather than 7 so a nightly run's few seconds of drift never skips the weekly slot). The first run
is the backfill. This cut the nightly calls per ticker from 3 to 2: ~1,770 to ~1,180 on an ordinary night,
and ~1,770 on the weekly splits night. The run summary carries `fmp_calls` and `pruned`.

The universe is every US-listed tracked ticker, the same universe as the price-target and last-close jobs
(`nightly_price_target_snapshot.load_us_price_target_universe`, scoped by `route_by_source` /
`is_us_listed` / `_profile_exchanges`, which were kept deliberately after the non-US removal). That is ~590
tickers x 2 calls, paced to half the plan's documented rate (~1-2 min). A failed endpoint keeps that
ticker's previous rows for that type. The job is skipped (a real `skipped` cron status) while the
`corporate_events` group is not live, and the cache then serves as-is. Manual runs:
`uv run python -m pipeline.nightly_corporate_events [--tickers AAPL,TSLA]`.

## Upsert, never delete-and-replace

`upsert_events` writes by the natural key `(ticker, event_type, event_date)`: new events are inserted,
existing ones updated in place, and **a stored row is never removed because FMP's response omitted it**.
This matters for a plan downgrade (Starter/Premium return ~1y of history where Ultimate returns everything);
a delete-and-replace would silently wipe older cached history. `CorporateEventFetch.row_count` is the
**stored** count after the upsert. A successful refresh also stamps `CorporateEventFetch`, which is what
lets the reader tell "fetched, FMP has none" (TSLA pays no dividend) from "never fetched". FMP returns the
whole history as long as `limit` is large enough (`EARNINGS_LIMIT` 1000, `DIVIDENDS_LIMIT` 2000; e.g. AAPL
has 165 earnings rows back to 1985 and 92 dividends). The regression test is
`test_a_narrower_second_response_never_deletes_cached_rows`.

## 4-year trailing retention

`RETENTION_DAYS = 365 * 4` and `prune_old_events`, run at the end of every `nightly_corporate_events` run.
Incoming rows older than the cutoff are not stored either. Retention is by **event** date (not fetch date),
applies to all three types, is independent of FMP and the plan, and keeps a row exactly on the cutoff. It
**equals the Chart tab's longest view** (`RANGE_CONFIG["W_4Y"]["visible_days"]` = 365 * 4 = 1460, pinned by
`test_retention_matches_the_chart_tabs_longest_view`). The chart drops events before its first visible bar
anyway (`_marker_bar_time`), so the cap removes nothing any range can show.

## Reader

`read_cached_chart_events` rebuilds FMP-shaped rows from the table and reuses `chart_events_data`'s own
normalizers, applying the marker rules: real-actuals-only earnings, split-adjusted dividend amounts, no zero
amounts. Only the deliberate `prune_old_events` housekeeping ever deletes rows.

## Non-US tickers

Non-US support was removed in Phase 6a/6b. A non-US ticker viewed later gets a `TickerScore` and
fundamentals but no nightly bars. Its Chart tab works on demand (FMP `daily_prices`, unfiltered), and its
long-history/overlay bars come from the same group with no phantom-bar filtering. Nothing prevents a user
re-adding one.

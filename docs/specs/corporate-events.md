# Corporate events cache (earnings, dividends, splits)

An FMP-backed local cache of earnings dates, dividends and splits (`data/corporate_events_data.py`, tables
`CorporateEvent` and `CorporateEventFetch`). All three FMP endpoints (`/earnings`, `/dividends`, `/splits`)
belong to the `corporate_events` data group; with the group off, readers serve the cached rows however old
(see `CLAUDE.md`'s data-groups section). The only current consumer is the Chart tab's E/D markers
(`data/chart_events_data.py`, see `docs/specs/chart-tab.md`). Splits are stored for completeness; no chart
marker reads them yet.

## Refresh job

**Weekly since 2026-10-14: Saturdays 6:00 AM server time (UTC)** (`0 6 * * 6`, 2:00 PM Saturday in Hong Kong), registered as a
weekly job in `core/cron_health.py` (`JOB_METADATA` "Sat 6:00 AM", expected every 8 days like the other weekly jobs, so the
Scheduled Jobs page never reads it overdue on a non-run day). It was nightly at 2:45 until it was disabled on 2026-10-01
(about 1,165 FMP calls per run at 406-527 requests/min, over Starter's 300/min); `docs/decisions.md` 2026-10-14 records why it is
weekly: the cache's **only** reader is the Chart tab's E/D markers (the next-earnings date, the scores and the fundamentals jobs
read the separate `earnings`/`latest` row in `FundamentalsCache`, group `fundamentals`, and do not depend on this job), so a marker
that appears up to a week late costs nothing. What a week of staleness means: a company that reports after a run gets its "E" marker
at the next run (a marker needs back-filled actuals anyway), a newly declared dividend gets its "D" marker at the next run, and a
ticker first opened between runs has no markers until the next Saturday, or until
`uv run python -m pipeline.nightly_corporate_events --tickers X,Y` is run for it (3 calls per ticker).

**Cost and window.** Every call asks for the ticker's **full history** (`EARNINGS_LIMIT` 1000, `DIVIDENDS_LIMIT` 2000, all splits), not a date
window, so no event can fall between two weekly runs and a run after two weeks of downtime costs exactly what a normal one does. About 582
US-listed tracked tickers x 3 calls = ~1,750 calls per run (splits are due on every weekly run: they are due when never fetched or last
fetched at least `SPLITS_REFRESH_DAYS` = 6 days ago, and runs are 7 days apart). The job paces ticker starts itself at half the plan's rate
(`FMP_PLAN_REQUESTS_PER_MIN` x `FMP_RATE_FRACTION`, 150 calls/min on Starter), so a run is about 12 minutes (about 20 at ~1,000 tickers); it
overlaps no other FMP job (Saturday 6:00 is two and a half hours after the last nightly FMP job, price-target, ends at ~3:20, and 18 hours
before the next one, the Sunday 12:30 AM stale-data check). `crontab.txt` carries the reasoning next to the line.

`pipeline/nightly_corporate_events.py` (the name is historical; registered in `core/cron_health.py`). The check for splits is judged off
`CorporateEventFetch`, not the weekday; the first run is the backfill. The run summary carries `fmp_calls` and `pruned`.

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
This matters for a plan downgrade (FMP's *calendar* endpoints are limited to a short window on lower plans; the per-symbol endpoints used here were measured on a Starter key on 2026-10-14 and still returned the whole history: 40 earnings rows, 92 dividends back to 1987, 5 splits for AAPL);
a delete-and-replace would silently wipe older cached history. `CorporateEventFetch.row_count` is the
**stored** count after the upsert. A successful refresh also stamps `CorporateEventFetch`, which is what
lets the reader tell "fetched, FMP has none" (TSLA pays no dividend) from "never fetched". FMP returns the
whole history as long as `limit` is large enough (`EARNINGS_LIMIT` 1000, `DIVIDENDS_LIMIT` 2000; e.g. AAPL
has 165 earnings rows back to 1985 and 92 dividends). The regression test is
`test_a_narrower_second_response_never_deletes_cached_rows`. Re-verified 2026-10-02 against the history-protection work
(`docs/specs/fmp-data-and-bar-cache.md`): an empty, error or shorter answer deletes nothing, and the 4-year prune removes by event
date only; this store needed no change.

## 4-year trailing retention

`RETENTION_DAYS = 365 * 4` and `prune_old_events`, run at the end of every `nightly_corporate_events` (weekly) run.
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

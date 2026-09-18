# Chart Tab Missing 09-17 Bar — Investigation — 2026-09-18

Investigation only, no code changes. Root cause: **a rolling 24-hour cache TTL that has no
concept of market close** — not upstream data lag, not a holiday/weekend false assumption,
and not a timezone/date-filtering bug in `chart_data.py` itself. FMP already has the
2026-09-17 daily bar; the app's own `FundamentalsCache` is just serving a snapshot taken
*before* that bar existed, and the "fully on-demand, no cache" framing in `chart_data.py`'s
own module docstring is accurate about not adding a *new* persistence layer, but the pre-existing
FMP cache it deliberately reuses turns out to have a real staleness gap this feature inherited
silently.

## 1. The Chart tab is not "fully on-demand" on the FMP branch — this is documented, not hidden

`data/chart_data.py`'s own docstring (point 2) is explicit: on the FMP branch, `_fetch_bars`
calls `clients.daily_price_sources.FMPDailyBarSource`, which goes through the app's ordinary
`get_or_fetch`-backed `FundamentalsCache` — reused as-is, not bypassed. So "on-demand" only ever
meant "no *new* table/cron was built for this feature," not "this always makes a live FMP call."
This much is working as designed and as documented.

The cache key is `(ticker, "historical_price_eod", f"{lookback_years}y")`, gated by
`Settings.daily_bar_staleness_days` (default **1**, i.e. 1 day) — this is the exact setting
CLAUDE.md's "Shared FMP daily-bar cache" entry (2026-09-16) introduced to fix the *previous*
bug in this same code path (wrong staleness window borrowed from `cache_staleness_days`, and a
colliding cache key across callers). That fix was real and correct for what it targeted — but it
left the staleness *mechanism* itself unchanged: `core/cache.py::get_or_fetch` is a flat

```python
if row and now - row.fetched_at < timedelta(days=staleness_days):
    return json.loads(row.raw_json)
```

with `staleness_days=1`. This is a rolling 24-hour window measured from the moment of the last
fetch, with **no awareness of market close time** at all — it doesn't matter whether the row was
fetched at 7am or 11pm, "fresh" always just means "less than 24h old."

The 4 ranges map to 3 distinct cache keys (confirmed by reading `RANGE_CONFIG` in
`chart_data.py`):

| Range | `fmp_lookback_years` | cache key |
|---|---|---|
| D_6M | 2 | `"2y"` |
| D_1Y | 2 | `"2y"` (shares D_6M's row) |
| D_2Y | 3 | `"3y"` |
| W_4Y | 8 | `"8y"` (fetched daily, resampled locally — FMP has no weekly endpoint) |

## 2. Confirmed live: FMP already has the 2026-09-17 bar

Direct, read-only call to `fmp_client.get_historical_price_eod("AAPL", "2026-09-10", "2026-09-18")`
(no DB session involved, nothing written) returned:

```
dates: ['2026-09-10', '2026-09-11', '2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17']
```

So this rules out upstream data lag and a market-holiday false assumption outright — the bar
exists upstream right now, sitting in real time (~8+ hours after the 09-17 US market close, at
the moment this was checked: system clock `2026-09-18 04:12 UTC`).

## 3. Confirmed in the real DB: AAPL's own cache row explains the exact symptom

Pulled directly from `backend/fathom.db`'s `fundamentalscache` table:

| Field | Value |
|---|---|
| `ticker` | AAPL |
| `period` (cache key) | `2y` (serves D_6M **and** D_1Y) |
| `fetched_at` | `2026-09-17 11:19:24` |
| last date in `raw_json` | `2026-09-16` |

`fetched_at` (11:19 UTC = 07:19 ET) is **before** the 2026-09-17 US market close (20:00 UTC /
16:00 ET) — so when this row was written, 09-17's bar genuinely didn't exist upstream yet, and
the fetch correctly cached a series ending 09-16. That part isn't a bug.

The bug is what happens next: `now` at investigation time was `2026-09-18 04:12 UTC`, only
~17 hours after `fetched_at` — still inside the 24-hour TTL (which doesn't clear until
`2026-09-18 11:19 UTC`). So `get_or_fetch` keeps returning this same pre-close snapshot on every
Chart tab load until the rolling window happens to expire — which, depending on exactly when the
original fetch landed, can span past the next trading day's open and well into the next viewing
session. This exactly reproduces the reported symptom: "most recent candle shown is 2026-09-16"
on 2026-09-18.

This confirms the mechanism directly, not by inference: the row is real, its `fetched_at`
timestamp is real, and the live FMP call above proves the data it's missing is already available
upstream — the gap is purely the local cache's TTL logic, not anything the FMP call itself did
wrong.

## 4. Not a timezone/date-cutoff bug in the fetch or filtering logic

Checked specifically per the investigation ask:

- `FMPDailyBarSource.get_daily_bars` computes `to_date = date.today()` (server wall-clock,
  which runs in UTC on this box) purely to build the FMP request's `from`/`to` query-string
  bounds. Since UTC's calendar date is always equal to or ahead of US Eastern's, this can never
  cause the request window to exclude a real ET trading day — it can only ever ask for slightly
  more range than strictly needed, never less. Not the cause here, and not a real bug on its own.
- `chart_data.py::get_chart_data`'s `visible_start`/`mask` logic only applies a **lower** bound
  (`bars_df.index >= visible_start`, trimming old history for the visible window) — there's no
  upper-bound trimming anywhere that could be clipping off the most recent bar. Read the full
  function; confirmed no such logic exists.
- So the date-range/filtering code itself is clean. The missing bar never reaches
  `chart_data.py` at all in this case — it's absent from the DataFrame before `_fetch_bars`
  even returns, because `get_or_fetch` handed back the cached (pre-close) `raw_json` without
  calling `fetch_fn` at all.

## 5. Scope: reproducible across all 4 ranges, not just D_6M/D_1Y

Query against the real DB, checking every `2y`/`3y`/`8y` `historical_price_eod` row that is
currently inside its 24h TTL (i.e. would NOT trigger a live refetch right now) and whose cached
series still ends before 09-17:

| Cache key | Ranges served | Total rows | Currently exhibiting the bug (fresh-per-TTL but missing 09-17) |
|---|---|---|---|
| `2y` | D_6M, D_1Y | 44 | **25** |
| `3y` | D_2Y | 7 | **2** |
| `8y` | W_4Y | 18 | **7** |

All affected rows share the same shape: `fetched_at` between 07:19 and 11:48 UTC on 2026-09-17
(i.e. the morning, before that day's close), still short of their 24h expiry as of the time of
this check (`04:12 UTC` on 09-18). Examples beyond AAPL: MU, MSFT, GOOGL, AVGO, MS, CDNS (`2y`);
APH, AVGO (`3y`); AVGO, AMAT, NVDA, AMD, HWM, ASML (`8y`).

**This confirms all 4 ranges are structurally vulnerable to the same bug** — it isn't scoped to
particular ranges by design, only by request-timing coincidence: whichever range/ticker
combination happens to get its first fetch-of-the-day before market close gets its cache row
"poisoned" with a pre-close snapshot for up to the next 24 hours. AAPL's D_2Y/W_4Y (`3y`/`8y`)
don't currently have a cached row at all, so their *next* load would live-fetch and correctly
pick up 09-17 — but that's incidental (no one has loaded AAPL's D_2Y/W_4Y today yet), not evidence
those ranges are immune. The 3y/8y rows that *do* exist (other tickers) show the identical
failure shape.

Separately confirmed this is self-healing but recurring: the `3y`/`8y` rows still dated
2026-09-16 (from the *previous* day's pre-close fetches) have already aged out of their 24h
window as of this check and would live-refetch on next load — i.e. this isn't a permanently
stuck cache, it's a **daily-recurring race** between "first request of the day" (often morning,
pre-close) and "market close" that reproduces for whichever tickers/ranges get requested early
enough each trading day.

## Bottom line

One root cause: `daily_bar_staleness_days` (1 day) is a flat rolling TTL with no market-close
awareness, layered under `daily_price_sources.py`'s FMP-backed cache that `chart_data.py`
deliberately (and correctly, per its own docs) reuses. A cache row fetched any time before a
given trading day's close locks in that day's *previous* close as "fresh" for up to the next 24
hours — which routinely spans past the next session's open, hiding the newest bar from the Chart
tab (and, by the same mechanism, from Liquidity Zone detection, which shares this exact cache) until
the window happens to expire on its own. Confirmed via: (1) a live FMP call proving 09-17's bar
is already available upstream, (2) AAPL's real cached row's `fetched_at`/content matching the
exact reported symptom, (3) a full-table scan showing 34 rows across all three cache keys (2y/3y/8y
— i.e. all 4 Chart-tab ranges) currently exhibiting the same failure shape, all from pre-close
morning fetches.

### Proposed fix (not implemented — awaiting go-ahead)

Anchor freshness to market close instead of (or in addition to) a flat TTL: treat a cached daily-bar
row as stale if the most recent US trading session's close has occurred since `fetched_at`, not just
"less than 24h old." Options to weigh:
1. Compute the most recent completed trading-day close (US/Eastern, accounting for weekends —
   holidays are a secondary, lower-value refinement) and compare against `fetched_at` directly,
   independent of `daily_bar_staleness_days`.
2. Simpler/cheaper approximation: compare the cached series' own **last bar date** against
   today's US/Eastern date — if the last cached bar isn't from the most recent completed session,
   treat as stale regardless of `fetched_at` age. This piggybacks on data already in the cached
   payload rather than needing a trading-calendar dependency, at the cost of one extra
   deserialize-and-peek before the existing TTL check.
Either approach should also be considered for the Liquidity Zone job's own `4y` key, which shares
the identical `get_or_fetch`/`daily_bar_staleness_days` mechanism and is subject to the same race.

**Update (2026-09-18, same day): a different fix was implemented instead**, per direct
instruction — rather than building market-close-aware staleness logic into the shared cache, the
Chart tab's FMP branch was reverted to a genuinely uncached, on-demand live fetch (bypassing
`daily_price_sources.py`/`FundamentalsCache` entirely for this feature only). See CLAUDE.md's
"Chart tab reverted to zero-cache on-demand fetch (2026-09-18)" section for the change itself.
Liquidity Zone detection was deliberately left on the cached path described above and remains
subject to this exact bug — options 1/2 above are still the live proposal if/when that gets
revisited.

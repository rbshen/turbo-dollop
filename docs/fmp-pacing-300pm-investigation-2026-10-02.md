# FMP request pacing for a 300-per-minute plan: investigation (2026-10-02)

Phase 1, report only. No code, DB or cron change was made. Sources: the code, `docs/specs/fmp-data-and-bar-cache.md`,
`docs/decisions.md`, `backend/OPS_RUNBOOK.md`, `backend/crontab.txt`, read-only queries against `backend/fathom.db`, and
the per-request `httpx` INFO lines in `backend/logs/*.log` (every FMP request is logged with a timestamp, so real
per-minute rates could be computed rather than inferred). Plan facts from FMP's own site could not be fetched (HTTP 403,
as `fmp-data-and-bar-cache.md` already records); where this report quotes FMP plan contents it says so and marks them
**unverified** (third-party summaries only).

## Summary

1. **The "440 per minute combined" figure is the configured ceiling, not what was measured.** Fundamentals and
   price-target are sequential (one request at a time, about 1 s each), so each runs at about **58-61 requests/min** whatever the
   220 cap says. Their measured combined peak on 2026-10-01 (02:55-03:45 overlap) was **122/min**.
2. **The jobs that really exceed 300/min use `_Pacer` + concurrency 10**, and they do so because the plan
   in the DB is still `Ultimate`: `nightly_last_close_snapshot` (peak 390-565/min), `nightly_trend_calculation` (364-523/min),
   `nightly_corporate_events` (404-565/min; disabled); BB+RSI is lower (136-254/min) and a 1-minute Warren burst. All ran alone, so
   nothing 429'd (no 429 appears in any retained log). These read `FMP_PLAN_REQUESTS_PER_MIN[fmp_plan] * 0.5`
   already, so **flipping the plan setting to Starter alone drops them to a 150/min start-rate** (Ultimate: 1,500/min).
   Nothing else reads the plan.
3. **Nothing is shared across processes**, and the web backend has no pacing at all (`min_request_interval = 0`). On Starter,
   two jobs that overlap, or one job plus a cold ticker page open, can exceed 300/min even with every job inside its own limit.
4. **Downgrade risk is bigger than pacing.** With the recorded tiers, `index_membership`, `daily_prices_long` and
   `institutional_ownership` go "above plan" the moment the plan is set to Starter. Separately, `intraday_bars` is recorded
   Starter in the DB but Premium in code/spec, and a third-party summary says Starter has annual-only fundamentals, which the
   app's quarterly calls would break. See section 4.
5. **Proposal:** one cross-process rolling-window limiter (a small SQLite file), in `FMPClient._send`, with 80% safety
   (240/min), a 20% interactive reserve, per-lane fair share, Retry-After-aware backoff with a shared cooldown, and a
   throttled-wait metric. Estimated size: **medium** (about 1-1.5 days with tests and docs). The nightly window still fits; corporate
   events can return at 1:50 AM at about 6 minutes a run (about 9 on the weekly splits night).

## 1. Every FMP call site, by process type

All live calls funnel through `FMPClient.get` -> `_send` (`clients/fmp_client.py`), so there is one choke point. Common
behavior at that choke point:

- **Pacing:** only `min_request_interval` (default 0.0; a per-process singleton `fmp_client`; an `asyncio.Lock` spaces request
  starts). `_Pacer` (`clients/daily_bar_sources.py`) is a second, separate start-spacer used by three jobs; it does not know
  about other requests.
- **429:** up to 2 retries (`RATE_LIMIT_MAX_RETRIES`), each after a fixed **65 s** sleep (`RATE_LIMIT_RETRY_BACKOFF_SECONDS`),
  no jitter, **`Retry-After` is not read**. Each attempt increments `request_count`. After the retries the 429 raises
  `httpx.HTTPStatusError`; call sites catch `httpx.HTTPError` (`safe_fetch` returns `{}`, the bar sources keep cached bars).
  A 429 never marks a group and no other process hears about it.
- **402:** `_handle_plan_restriction` sends one **extra** canary request (same endpoint, symbol swapped for AAPL, SPY for
  `/etf/info`) through `_send`; only if the canary also 402s is the whole group marked `plan_restricted`. A symbol-scoped 402
  therefore costs 2 calls. Weekly `reprobe_restricted_groups` also goes through `_send`.
- **Group gate:** an off / above-plan / restricted group raises `FMPGroupDisabledError` before any network call.

### 1a. Cron jobs (server time = UTC; times are the installed crontab)

Calls and rates are from the `httpx` lines of the last six nights (2026-09-27 to 10-02). "Peak/min" is the busiest clock
minute. Observed rate for the sequential jobs is latency-bound, so their configured cap never binds.

| Job (slot) | Pacing today | Calls per run | Observed peak/min | 429 / 402 |
|---|---|---|---|---|
| `nightly_last_close_snapshot` (1:00) | `_Pacer` at plan x 0.5 (**1,500/min on Ultimate**), 10 concurrent | 581-589 (1 per US ticker, 10-day window) | **390-565** | common path; none seen |
| `nightly_trend_calculation` (1:05) | `FMPDailySource`: same `_Pacer`, 10 concurrent | 576-586 (one incremental call per ticker nightly; Sunday UTC `full_refresh` is the same count with 5-year bodies; a restated ticker adds 1) | **364-523** | common path |
| `nightly_liquidity_zone_calculation` (1:15) | none of its own; reads shared bars cache, `get_or_fetch_bars_batch` | 3 | 3 | n/a |
| `nightly_entry_signal_calculation` BB+RSI (1:20) | `FMPIntradaySource`: `_Pacer` plan x 0.5, 10 concurrent, paginated | 136-348 (105 tickers; first-time widening pages up to 40 per ticker) | **136-254** | common path |
| `nightly_warren_signal_calculation` (1:25) | same `FMPIntradaySource` | 16-43 (bars are warm from BB+RSI) | 16-43 | common path |
| `nightly_sector_heatmap` (1:35) | shared bars cache | 9-11 | 11 | n/a |
| `nightly_market_breadth` (1:40) | shared bars cache | 4 warm; a self-heal run (after a failed 1:05) is about 503 calls | 4 | common path |
| `nightly_corporate_events` (**disabled**, planned 1:50) | `_Pacer` per ticker START at average calls/ticker, plan x 0.5, 10 concurrent | 1,162-1,165; 1,740 on the weekly splits night | **404-565** (2-4 active minutes) | common path |
| `nightly_fundamentals_fetch` (2:00) | `min_request_interval = 60/220` hardcoded (`TARGET_REQUESTS_PER_MINUTE`), **sequential per ticker** | 5-250 typical, 2,626 on 2026-10-01 (cache-expiry wave, 44.5 min), about 7,000 cold | **46-61** | common path; 402s on dotted/non-US symbols (see section 4) |
| `monthly_momentum_snapshot` (2:50, days 1-5) | none; shared bars cache | 4 | 4 | n/a |
| `nightly_price_target_snapshot` (3:10) | `min_request_interval = 60/220` hardcoded, **sequential** | 581-590 (91 on 10-02 after a warm cache), 1-day staleness | **54-62** | HTTP 200 empties are "no_data", not errors |
| `nightly_score_recompute` (3:25), `backup_db` (3:30) | none | **0** (cache-only) | 0 | n/a |
| Sunday 12:00 / 12:05 / 12:10 index list refreshes | none | 1 each (the 224-call Nasdaq line on 09-26 was a manual run) | 1 | common path |
| Sunday 12:30 `stale_data_health_check` | none; sequential paging | about 158 (`/delisted-companies`, 100 rows/page) + one probe per `plan_restricted` group | 61 | common path |
| Sunday 12:15-12:25, 12:35 (`prune_cache`, `rotate_logs`, audit, `purge_invalid_tickers`) | n/a | 0 | 0 | n/a |

Nightly total on a typical night: about 2,100-2,600 calls (last close 589 + bars 586 + intraday about 250 + price-target 590 +
fundamentals 60-250 + small ones), plus 1,165 if corporate events returns.

### 1b. Web backend (uvicorn, one process; `fmp_client` with no pacing)

- **Ticker page open** (`/summary`, step1-5, financials, ratios, segmentation, analyst-ratings, chart, etf-overview ... each its
  own request from SWR, in parallel): a fully cold stock is about **27-35 FMP calls** (AAPL holds 27 distinct cache keys). Warm
  (inside `cache_staleness_days` = 7) it is zero, so most page views are free. The quote is force-fetched on every summary view:
  1 call per view.
- **Refresh button** (`POST /refresh`): clears the ticker's cache, then `compute_ticker_score(cache_only=False)`: about 25-30
  calls back to back, no pacing.
- **Ticker search:** 2 calls (`/search-symbol`, `/search-name`) per 300 ms-debounced keystroke pause, **uncached, ungated by
  any limiter**.
- **Watchlist rows:** one `grades_consensus` per cold ticker, `_LIVE_FETCH_CONCURRENCY = 8`: a 100-ticker cold list is a burst of
  up to 100 calls in seconds. Real lists today are 14-50 tickers, mostly warm.
- **Chart / long history / ETF:** `get_historical_price_eod` per range (daily_prices or daily_prices_long), `/etf/info` per
  ETF view, `/historical-price-eod/full` for `last_close`-style header tiles.
- **Observed load:** interactive minutes in the DB (cache rows written per minute outside 00:00-03:59) peak at 35 on normal
  days, 232 and 204 on one burst (2026-09-22 21:34-21:35, a bulk action). Typical page open: 18-35.
- **429 / 402:** the same `_send` path. A 429 would sleep the request 65 s twice, holding the HTTP request open.
- The web process is also where the **Settings plan edit** calls `reprobe_restricted_groups` (`core/main.py:195`).

### 1c. One-off scripts

`pipeline/backfills/bulk_refresh_*.py` (3), `backfill_price_target_snapshots.py`: hardcoded 220/min via
`min_request_interval`, sequential, measured 54-64/min; `backfill_fmp_daily_bars.py`: peak 360/min (2026-09-24, Ultimate);
`pipeline/refresh.py`, `pipeline/recompute_ticker_scores.py`, `pipeline/data_groups.py probe/reprobe`, and any `--tickers` manual
run of a nightly job share the paths above. Nothing coordinates with a running cron job or the web app. `analysis/ma_magnet/`
calls FMP but is unwired.

## 2. Where the plan and its limit live today

- **The plan:** `DataGroupGlobal.fmp_plan` (DB, singleton row `default`; currently **`Ultimate`**), edited at Settings > FMP data
  groups (`PUT /api/config/data-groups/plan`, `core/data_groups.py::set_fmp_plan`); values `TIERS = Starter/Premium/Ultimate`.
- **Per-group required tiers:** `DataGroupSetting.required_tier` (DB, user editable), seeded from `GROUPS[...].default_tier`.
- **Who reads the plan:** (a) `effective_state` (tier gating: required tier above plan = group off), and (b) four pacing
  call sites via `clients/daily_bar_sources.py::FMP_PLAN_REQUESTS_PER_MIN = {"Starter": 300, "Premium": 750, "Ultimate": 3000}` and
  `FMP_RATE_FRACTION = 0.5`: `FMPDailySource`, `FMPIntradaySource`, `last_close_data.refresh_last_closes` and
  `nightly_corporate_events.refresh_all` (all `_Pacer` users). Unknown plan falls back to 300.
- **Hardcoded, plan-blind:** `TARGET_REQUESTS_PER_MINUTE = 220` in `nightly_fundamentals_fetch`, `nightly_price_target_snapshot` and
  the four backfills; `FMP_CONCURRENCY = 10`; `RATE_LIMIT_*` in the client; the web app has no limit at all.
- No safety fraction, interactive reserve, per-job budget, or cross-process state exists anywhere. FMP's own limit is documented in
  `fmp_client.py` only as an empirical "300-600/min rolling window, recovering about 65-70 s after a 429".

## 3. Worst-case overlaps under the current schedule

Cron times are not changed by this task. "Plan-Starter, no limiter" means the DB plan flipped to Starter and nothing else
changed (the `_Pacer` family drops to 150/min; fundamentals and price-target stay about 60/min).

| Window | Jobs | Peak today (Ultimate) | Peak at Starter, no limiter | Verdict |
|---|---|---|---|---|
| 1:00-1:05 | last close, then trend (starts 5 min later) | each alone, 390-565/min | last close 589/150 = **3.9 min** (ends about 1:04), then trend; **1 minute margin**. A 429 backoff (65 s) or a slow night overlaps them: 150 + 150 = **300** | marginal |
| 1:05-1:15 | trend (about 3.9 min fetch + compute, ends about 1:10) | alone | 150 | ok |
| 1:20-1:25 | BB+RSI, then Warren | BB+RSI 136-254, Warren 16-43, no overlap (BB+RSI ends about 1:22) | BB+RSI 150 for about 2.3 min | ok |
| 1:40 | Market Breadth warm 4 calls; self-heal 503 | 4 / about 500 | 150 | ok |
| 1:50-2:00 | corporate events (if re-enabled) | 400-565 | 1,165/150 = **7.8 min**, splits night 1,740/150 = **11.6 min, ends 2:01.6** | overlaps fundamentals start: 150 + 60 = 210 |
| 2:00-3:04 | fundamentals (sequential) | 46-61 | 46-61 | ok alone |
| 2:50 (days 1-5) | momentum, 4 calls, during fundamentals | +4 | +4 | negligible |
| 3:10-3:20 | price-target while fundamentals still runs only if it ran past 3:10 (worst seen 64.5 min ends 3:04) | measured combined 122 on 10-01 | 60 + 60 = 120 (ceiling by config 440 is never reached) | ok; a 120-minute cold run would overlap |
| Sunday 12:00-12:33 | 3 list refreshes (1 call each), `stale_data_health_check` 158 pages at about 55/min | 61 | 61 | ok |
| Sunday 1:05 | trend `full_refresh` of 586 tickers, same call count, 5-year bodies | 364-523 | 150 | ok |
| **Interactive anywhere** | cold page open 27-35 calls in a few seconds; refresh 25-30; watchlist cold burst up to 100; search 2 per pause | unlimited | **any of these during a job**: job (<=150-220) + burst (30-100 in seconds) can top 300 inside one rolling minute | **the real gap** |

Conclusion: at Starter the nightly schedule is safe only because jobs mostly run alone and the plan-aware pacer drops to 150/min.
That protection is accidental (it depends on how long each job runs), covers only four of the code paths, and does nothing for
interactive traffic or for a manual run started while a cron job is active.

## 4. Downgrade readiness: every enabled group and its recorded tier

Recorded values are from the live DB (2026-10-02 06:40). Source of "needs": this repo's own history and, where marked
**3P**, search-result summaries of FMP's pricing page (third-party, **unverified**; FMP's pages 403 to the app's fetcher).
Never observed on this key: an endpoint-wide 402 (every real 402 in the retained logs, 2,626 lines including rotated archives, is symbol-scoped:
`0941.HK` x about 20 endpoints, `BRK.B` and `BF.B` statements, all on Ultimate). The one endpoint-wide restriction on record is that
the three constituent endpoints returned 402 before this key moved to Ultimate on 2026-09-15 (`refresh_sp500_list.py` docstring);
the plan the key was on before is not recorded in the repo.

| Group (enabled) | Recorded tier (code seed) | Above Starter? | Breaks after downgrade | Fallback |
|---|---|---|---|---|
| `fundamentals` (on) | Starter (Starter) | no, **but see note A** | Steps 1-5, Valuation, Screener scores, nightly fundamentals, `/financial-statement-full-as-reported` (banks) | none |
| `profile_quote` (on) | Starter | no | header, search, Refresh | tracked-ticker search; last cached close |
| `analyst_ratings` (on) | Starter | no (unverified, note B) | Ratings tab, price-target snapshot | cached |
| `segmentation` (on) | Starter | no | segmentation card | cached |
| `corporate_events` (on, job disabled) | Starter | no | E/D chart markers (frozen cache already) | cached |
| `daily_prices` (on) | Starter | no; the 5-year nightly window equals Starter's documented 5-year cap (**3P**) | Weinstein, LP, heatmap, breadth, momentum, chart daily, last close | none (cache-only, jobs `skipped`) |
| **`index_membership` (on)** | **Premium** (Premium) | **YES** | S&P 500 / Dow / Nasdaq-100 weekly refresh jobs become `skipped`; `IndexConstituent` freezes (Screener universe, Market Breadth's 503, the nightly universe); `/delisted-companies` sync in `stale_data_health_check` skips, so no new delisted flags | **none in code**: the Wikipedia scrapers were removed 2026-09-15 (in git history); the stale-last-bar delisted heuristic was replaced in Phase 6a |
| **`daily_prices_long` (on)** | **Premium** (Premium) | **YES** | Chart W_4Y range and the Analyst Ratings 10-year overlay stop fetching; `LongHistoryBars` (119,146 rows) is served frozen; new tickers have none | cached only; could fall back to the 5-year daily cache (roughly 3 years of weekly after warm-up) |
| **`intraday_bars` (on)** | **Starter in the DB, Premium in the code seed and in `fmp-data-and-bar-cache.md`** | **conflict; likely above Starter (3P: intraday charts are a Premium feature)** | BB+RSI and Warren jobs `skipped`; "60m" cache (381,731 rows, 108 tickers) frozen; chart entry-signal markers stop updating. If the DB's Starter is wrong and the group stays "live", the first 402 canary confirms and marks the group `plan_restricted`: same outcome | **none** (Yahoo removed in P6b) |
| `etf_info` (on) | Starter (Starter, owner's value, not FMP-verified) | unknown (3P: ETF holdings are Ultimate; `/etf/info` not stated) | ETF page Overview, ETF watchlist columns: "unavailable" | none |
| `institutional_ownership` (**on in DB**, code seeds it off) | Ultimate | **YES** (3P: 13F is Ultimate) | already shelved; auto "above plan" off. No live feature | n/a |
| `news` (**on in DB**, code seeds it off; never succeeded) | Starter | no | shelved tab | n/a |
| (stale row) `insider` | n/a | n/a | row left in `datagroupsetting` (enabled 0); harmless | delete |

**Note A (largest unknown): quarterly fundamentals.** A third-party summary lists Starter as "annual fundamentals and ratios".
The app calls `period=quarter` for income, cash flow and balance sheet in Steps 1, 3, 4, 5, Financials and Ratios
(`TOTAL_QUARTERS_NEEDED`), and TTM metrics. If Starter 402s `period=quarter`, `_handle_plan_restriction`'s canary (same endpoint,
same `period=quarter`, symbol AAPL) would confirm it and **mark the entire `fundamentals` group `plan_restricted`**, switching off
annual fetches too (the group is coarser than FMP's gating). The weekly reprobe uses `/income-statement?period=annual&limit=1`, which
passes, so the group would flap back on weekly and off again on the next quarterly call. Mitigation is to verify before
downgrading (section 4 checklist), not code.

**Note B:** `/price-target-*`, `/grades-historical`, `/analyst-estimates`, `/enterprise-values`, `/key-metrics-ttm` tiers are
unrecorded and unobserved; each sits in a group recorded Starter.

**Gate behavior to know:** a group whose recorded tier exceeds the plan is refused before any network call (so "above plan" is never
probed and never discovered wrong); a group recorded too low is discovered only by a real 402 plus a confirming canary.

### Bandwidth and daily caps: what the code knows, what to verify

The code knows nothing about bandwidth or a per-day cap (no counter, no constant). **3P (unverified): Starter 20 GB over a
rolling 30 days** (Premium 50 GB, Ultimate 150 GB); FMP is described as metering bandwidth, not calls. My estimate from the cached
payload sizes (`FundamentalsCache.raw_json` averages: statements 13-20 KB, ratios 11 KB, key-metrics 9 KB, EOD full-history up to
2.5 MB) and call counts, order of magnitude only: weekly Sunday full resync of 586 five-year bar series about 100-150 MB;
corporate events (`/earnings` limit 1000 + `/dividends` limit 2000, no incremental) about 20-35 MB per night, about 0.6-1 GB
per 30 days; a cache-expiry wave of 2,600 fundamentals calls about 30 MB; typical nights a few MB; intraday full widenings about
0.7 MB per ticker; interactive cold opens about 0.3 MB each. **Total roughly 1.5-3 GB per 30 days against 20 GB**: comfortable if the
figure is right, but nothing in the app measures it.

**Verify on FMP's site before downgrading** (a checklist, in priority order):

1. Starter's per-minute limit counting rules: rolling or calendar minute, and whether 402, 429 and empty-200 responses count.
2. Starter bandwidth cap (20 GB / 30 days?), what happens at the cap (429, 402, throttle, or overage), and whether a daily call cap exists.
3. **Quarterly statements and ratios on Starter** (`period=quarter`), the 5-year history limit on statements (the app asks
   `limit=10` annual), `/key-metrics-ttm`, `/ratios-ttm`, `/enterprise-values`, `/financial-growth`, `/analyst-estimates`,
   `/financial-statement-full-as-reported`.
4. `/historical-chart/1hour` (intraday) tier.
5. `/sp500-constituent`, `/dowjones-constituent`, `/nasdaq-constituent`, `/delisted-companies` tier.
6. `/etf/info` tier; `/price-target-consensus`, `/price-target-summary`, `/grades-consensus`, `/grades-historical` tier.
7. `/historical-price-eod/full` depth on Starter (5 years exactly: the nightly window asks `today - 1825 d`) and long-history 10-year
   calls (clipped silently or 402).
8. Whether 429 responses carry `Retry-After`; the real 402 body shape (never captured on this key).
9. When a plan change takes effect (immediately or at renewal).

## 5. Proposal

### 5.1 Design

**One limiter, one choke point.** A new `clients/fmp_limiter.py`, called from `FMPClient._send` before each attempt (so 429 retries
and 402 canaries are counted; every existing call site and `FMPClient(...)` instance is covered; `_Pacer`'s start-spacing stays only
for concurrency shape, no longer for rate).

- **State:** a dedicated small SQLite file, `backend/fmp_limiter.db` (WAL, not `fathom.db`: avoids its write lock, the test
  write-guard in `conftest.py`, and the 1 GB backup). Table `fmp_calls(ts REAL, lane TEXT)` plus a one-row `cooldown_until`.
  Cross-process atomicity by `BEGIN IMMEDIATE`; no third-party dependency. About 1 ms per call at 200 calls/min.
- **Algorithm:** rolling 60-second window (FMP recovered about 65-70 s after a 429, so a rolling window matches the evidence better than a
  token bucket). To send: in one transaction, delete rows older than 60 s, count the rest; if under the cap, insert and go; else sleep until the
  oldest row ages out (plus 20-50 ms jitter) and retry. Waits are `await asyncio.sleep` between short sync transactions (no thread
  blocking the event loop).
- **Limit source:** the existing `DataGroupGlobal.fmp_plan` through one `fmp_plan_limit()` (replaces `FMP_PLAN_REQUESTS_PER_MIN` and
  `FMP_RATE_FRACTION`). Constants: `FMP_SAFETY_FRACTION = 0.8` -> **240/min on Starter**, `FMP_INTERACTIVE_RESERVE_FRACTION = 0.2` -> **48/min**.
  No new DB column. (Adding columns to `DataGroupGlobal` would need a manual ALTER; SQLModel `create_all` does not alter existing
  tables. If the owner wants the safety/reserve editable in Settings later, use a new table.)
- **Lanes and reserve:** a `contextvar` lane set per process: `web` (set at FastAPI startup), `<job name>` (set by `cron_heartbeat`), `adhoc`
  (default for any other script). Rules: a **web** call proceeds while the window total is under **240**; a **job/adhoc** call proceeds only
  while the window total is under **240 - 48 = 192**. So a page view never queues behind jobs (there are always at least 48 free
  slots), and jobs cannot eat the reserve. A web burst over 240 does wait: that is the point of the cap.
- **Per-job budget / fairness:** a lane's share of the 192 job slots is `max(60, 192 / active_job_lanes)`, where active = a lane with a row
  in the last 60 s; a lane alone gets all 192. A job may also declare its own ceiling (`lane_cap`) below that. This stops one long job
  starving another, and two overlapping jobs never sum past 192. No slot is ever idle if only one lane is active.
- **429 handling:** honor `Retry-After` (seconds or HTTP-date), else exponential backoff 5 s -> 10 s -> 20 s -> 40 s with jitter, up to 4
  attempts (replacing the fixed 2 x 65 s). On any 429, write `cooldown_until = now + wait` to the limiter file so **every process
  pauses**, not only the one that was hit, and the window total is treated as full. 429s counted as a metric. 402 behavior unchanged
  (canary and group marking), but the canary and probes take limiter slots.
- **Fail-safe:** if the limiter file cannot be opened or locked, log once and **fail open to an in-process 50%-of-effective pacer**
  (never block the nightly chain on a limiter fault, never remove all pacing).
- **Metrics:** (a) per-run, in the cron heartbeat message (shows on Scheduled Jobs today): `calls`, `throttled waits N / total wait s`, `429s`;
  (b) a `FmpUsageMinute(lane, minute, calls, throttled_s, throttle_waits, rate_limited)` table in the limiter file, 7-day retention, so
  "peak per minute per lane" is a query rather than a log reconstruction like this report; (c) a limiter log line at INFO when a wait exceeds
  5 s. A Scheduled Jobs page column or a Settings card is optional and a separate frontend task.
- **Per-job adaptation:** delete the `TARGET_REQUESTS_PER_MINUTE = 220` / `min_request_interval` setup from fundamentals, price-target and
  the four backfills (the limiter paces them; they keep their sequential shape). `FMPDailySource`, `FMPIntradaySource`, `last_close_data`,
  `nightly_corporate_events` keep `FMP_CONCURRENCY` and `_Pacer` only as the concurrency/shape control and drop the plan-rate arithmetic. The
  weekly splits night and the 5-year Sunday resync need no special case.

### 5.2 Estimated runtimes at the new pace

Jobs share 192/min when alone (the cap each could use alone; a job that is already slower than the cap is unchanged).

| Job | Calls (typical / worst seen) | Today (Ultimate, measured) | New pace (192/min cap) | Fits its slot? |
|---|---|---|---|---|
| last close (1:00) | 589 | 1.3 min | **3.1 min** (call time) | ends about 1:04, 1 min before 1:05 (limiter makes an overlap safe, not fast) |
| trend + bars (1:05) | 586 (Sunday same count) | 1.6-3.7 min | **about 4-5 min** (3.1 fetch + non-fetch compute) | ends about 1:10, window to 1:15 |
| LP / sector / breadth | 3 / 11 / 4 (503 on self-heal = 2.6 min) | seconds | unchanged | yes |
| BB+RSI (1:20) | 136-348 | 0.8-2.1 min | **1.1-1.8 min fetch**, total <= about 3 min | yes (5-min window) |
| Warren (1:25) | 16-43 | 1.7-1.9 min | unchanged | yes |
| corporate events | 1,165 / 1,740 | 2.2 min | **6.1 min / 9.1 min** (4.9 / 7.3 min if allowed the full 240) | at 1:50, ends about 1:56 / about 1:59 |
| fundamentals (2:00) | 60-250 / 2,626 / about 7,000 | 1.8 min / 44.5 min / 64.5 worst | **unchanged** (latency-bound at about 59/min, far under 192) | yes |
| price-target (3:10) | 590 | 9.7-10.2 min | **unchanged** (about 58/min) | yes |
| momentum, scrapers, `stale_data_health_check`, backfills | 4 / 1 / 158 / many | seconds-3 min | unchanged | yes |
| score recompute, backup | 0 | unchanged | unchanged | yes |

**Nightly window:** total about 2,100-2,600 calls, and the only jobs the limiter slows are the three burst-style ones, adding about 2 + 2
minutes in the 1:00-1:10 block. Everything still ends by about 1:10 (chain through 1:45 as planned), fundamentals 2:00-2:05 typical.

**Corporate events:** can return **at 1:50 AM as already planned** (needs the `JOB_METADATA` update, `DISABLED_CRON_JOBS` removal and
`crontab crontab.txt`; none done here). **Cost per run at the new pace:** 1,165 calls = **6.1 min** on a normal night, 1,740 calls =
**9.1 min** on the weekly splits night, about 20-35 MB of bandwidth, 6.5% (normal) to 9.7% (splits) of one hour's 18,000-call budget at
300/min. The splits night ends about 1:59 against fundamentals at 2:00: tight but safe (fundamentals starts mostly with cache hits at
about 60/min, and the limiter caps the sum). Options if the owner wants more margin: give this job `lane_cap = 240` (4.9 / 7.3 min; a
reserve is pointless at 1:50 AM), or fetch only tickers whose earnings or dividend calendar could have changed (not designed here).
`/earnings limit=1000` and `/dividends limit=2000` per ticker per night are 2 calls and the bulk of the bandwidth, and are full-history
replaces by design.

**Sunday and momentum:** unchanged and untouched by the cap.

### 5.3 Size per area

| Area | Size | Notes |
|---|---|---|
| Limiter module (`clients/fmp_limiter.py`) + `FMPClient._send` hook + lane contextvar | **M** | SQLite window, reserve, fair share, cooldown, fail-open |
| Plan limit helper, remove `FMP_PLAN_REQUESTS_PER_MIN`/`FMP_RATE_FRACTION` use | **S** | one function; 4 consumers |
| 429 policy (Retry-After, backoff, shared cooldown) | **S** | replaces two constants |
| Per-job adaptation (fundamentals, price-target, 4 backfills, 4 `_Pacer` users, `cron_heartbeat` lane) | **S-M** | mostly deletions |
| Metrics (`FmpUsageMinute`, heartbeat message, log line) | **S** (backend), +**M** for any Scheduled Jobs page column | page work is separate and skips `/styleguide` |
| Tests, including a **multi-process** concurrent test | **M** | below |
| Docs: `fmp-data-and-bar-cache.md`, `OPS_RUNBOOK.md`, `CLAUDE.md`, `decisions.md`, crontab comments | **S** | |
| **Total** | **M, about 1-1.5 days** | |

### 5.4 Tests (Phase 2)

Unit: window arithmetic with an injected clock; reserve (job blocked at 192, web allowed to 240); fair share with two lanes;
Retry-After in seconds and HTTP-date; shared cooldown; fail-open. **Concurrent multi-process:** spawn N `multiprocessing` workers
(job and web lanes) against one temp limiter file with a fake transport, fire a few hundred requests, and assert no rolling 60 s
window exceeds 240 (and that web lane calls never wait behind job calls past one slot). Conftest: an autouse fixture must point the
limiter at a per-test temp file or disable it; otherwise the existing `MockTransport` suites would write the real file and sleep.

### 5.5 Risks

- **The limit is counted by FMP, not by us:** a second client using the same key (another machine, a notebook, `options_tracker` if it
  shares the key) is invisible to a local limiter. Verify no other consumer shares the key.
- **Quarterly-statement and intraday tiers (section 4) are plan problems, not pacing problems**; the limiter does not fix them.
- **Fail-open vs fail-closed:** chosen fail-open with a reduced in-process pace; a wedged limiter must not stall the nightly chain.
- **Event-loop blocking:** the SQLite transaction is synchronous (about 1 ms); acceptable at this volume; use short transactions only.
- **`uvicorn --reload` (dev)** restarts the web process; the limiter file survives, rows age out in 60 s.
- **Clock:** the window uses wall time (`time.time`), single host, so no cross-process monotonic problem; an NTP step could skew one minute.
- **A tight 1:00 -> 1:05 handoff** and the 1:50 -> 2:00 corporate-events tail are schedule facts; the limiter makes any overlap safe but
  cannot make the jobs shorter. Flagged, no cron change here.
- **Interaction:** `docs/tracked-universe-expiry-investigation-2026-10-02.md` (a pending design) would shrink nightly universes and
  therefore call counts and bandwidth; independent of this work.

### 5.6 Conflicts with `docs/specs/` and existing tests

- `fmp-data-and-bar-cache.md` ("paced to 50% (`FMP_RATE_FRACTION`) of the plan's documented rate", the per-group tier tables, the
  `intraday_bars` "Premium" statement vs the DB's Starter) needs rewriting; `CLAUDE.md` data-source and nightly sections too.
- `crontab.txt` comments ("At ~60 req/min observed (220 cap)", the corporate-events "406-527 requests/min" slot note) and
  `OPS_RUNBOOK.md` corporate-events re-enable steps need updating once the limiter exists; `docs/decisions.md` gets a new entry that
  supersedes the 2026-10-01 corporate-events reasoning (the cause was `plan x 0.5` read from an Ultimate plan, not only concurrency).
- Existing tests pin the old mechanism and change: `tests/test_nightly_fundamentals_fetch.py:257`,
  `tests/test_bulk_refresh_ratios_ttm.py:112`, `tests/test_bulk_refresh_step4_annual.py:128` (`min_request_interval == 60/TARGET_...`),
  `tests/test_fmp_client.py` pacing and 429 tests (`RATE_LIMIT_RETRY_BACKOFF_SECONDS`), `tests/test_debt_metrics.py` comments about the 65 s sleep,
  `tests/test_fmp_plan_detection.py`. `test_cron_wiring.py` and `test_data_groups_registry.py` are unaffected.
- The full test suite is not required for this report (docs only); for Phase 2 only the files above, the new limiter tests and the
  data-groups/cron-wiring suites are needed.

### 5.7 Decisions for the owner before Phase 2

1. Confirm the safety (80%) and interactive reserve (20%) numbers, or choose others.
2. Confirm the downgrade facts in the section 4 checklist (especially quarterly statements, intraday, constituents). They decide whether
   `fundamentals`/`intraday_bars` should be `plan_restricted`-proof or the downgrade should wait; no limiter work changes them.
3. Set `intraday_bars` recorded tier to match reality (DB Starter vs seed/spec Premium).
4. Whether corporate events returns at 1:50 with the 192 cap (ends about 1:56 / 1:59) or with a 240 job cap (about 1:55 / 1:58).
5. Whether to restore a constituent-list fallback (Wikipedia scraper from git) in case `index_membership` stays above Starter.

Sources for the third-party plan facts (unverified, from search summaries): [FMP pricing, as summarised on fitgap](https://us.fitgap.com/products/financial-modeling-prep),
[FMP "how to choose the right plan"](https://site.financialmodelingprep.com/de/insights/platform/how-to-choose-the-right-financial-modeling-prep-plan-for-your-workflow),
[FMP pricing docs page (403 to the app's fetcher)](https://site.financialmodelingprep.com/de/developer/docs/pricing).

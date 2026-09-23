# Market breadth nightly job failure — investigation (2026-09-23)

Investigation only. No code was changed. All queries were run read-only against the real
`fathom.db` (`uv run python` one-liners) or via the actual `pipeline.nightly_market_breadth`
entry point itself (safe/idempotent — see "Live re-run" below); no scratch files were left
behind.

## What happened

The 3:35 AM `pipeline.nightly_market_breadth` cron run on 2026-09-23 failed and wrote **no**
`MarketBreadthSnapshot` rows for any universe (neither `sp500` nor any of the 11
`sector:<ETF>` rows) for the 2026-09-22 session.

Exact error (from `logs/nightly_market_breadth_cron.log` and `CronRunLog.error_summary`):

```
data.market_breadth_data.InsufficientCoverageError: Market breadth: only 6/503 constituents
(1.2%) have a bar on 2026-09-22, below the 97% coverage gate -- not saving a skewed row.
Missing: ['A', 'ABBV', 'ABNB', 'ABT', 'ACGL', 'ADBE', 'ADI', 'ADM', 'ADP', 'ADSK', 'AEE',
'AEP', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG', 'AKAM', 'ALB', 'ALGN', 'ALL', 'ALLE', 'AMAT',
'AMCR', 'AMD'] ...
```

## Step 1 — Evidence

- **Log/cron-health**: `CronRunLog` shows 2026-09-22's run (`03:35:03` → `03:35:09`) as
  `success` (502/503, `HUBB` excluded); 2026-09-23's run (`03:35:03` → `03:35:51`) as
  `failure` with the `InsufficientCoverageError` above. `get_cron_health()` reports
  `health_status='failed'` for `pipeline.nightly_market_breadth`, `last_success_at=
  2026-09-22 03:35:09`, matching the log exactly.
- **Live crontab vs `crontab.txt`**: `crontab -l` is **byte-identical** to
  `backend/crontab.txt`. Schedule, script path, working directory, and log redirect are all
  correct — not a deployment/cron-install problem.
- **`MarketBreadthSnapshot` query** (last ~10 sessions, `universe='sp500'`): the newest row
  is `2026-09-21` (written by the 2026-09-22 run, 502/503 coverage, `stale_excluded=1`).
  **2026-09-22 has no row in any universe** — confirmed for `sp500` and spot-checked for
  `sector:XLK`/`sector:XLF`/`sector:XLE`, all stuck at `2026-09-21`. Every sector row is
  necessarily missing too: the `sp500`-level gate raises *before* `_process_sectors` is ever
  called (`data/market_breadth_data.py::compute_and_store_market_breadth`), so a refused
  sp500 gate currently blocks all 11 sector rows for that night even though, in principle, an
  individual sector's own (more permissive) gate is checked independently once reached. Not
  relevant to root-causing *this* incident (coverage was catastrophically low nearly
  everywhere, not concentrated in one sector — see below), but worth flagging as a latent
  design gap for a future incident where only one sector is affected.
- **Upstream trend job (3:10 AM)**: ran and completed successfully the same night —
  "Processed: 583. Failed: 2" (`TWTR`, `WBA`, both long-delisted, expected/every-night
  failures — confirmed via `logs/nightly_trend_calculation_cron.log` history going back to
  2026-08-22, these two fail every single night). The trend job is not implicated: it ran
  fine and reused the same `SharedBarsCache`.
- **`SharedBarsCache` state**: directly queried `max(bar_time)` per ticker for
  `interval='1d'`. Of 583 tickers with daily bars, **560 top out at `2026-09-21`** and only
  **20 reach `2026-09-22`** (10 S&P 500 names — `AAPL, ACN, CELH, FTNT, MSFT, NKE, PARA,
  PLTR, TXG` — plus `^GSPC` and 9 HK/OTC watchlist tickers not in the S&P 500 universe at
  all). The 10 fresh S&P 500 names' `fetched_at` timestamps cluster **21:25–22:20 UTC on
  2026-09-22** (17:25–18:20 ET, roughly 1.5–2.5h after the 4pm ET close) — well before the
  3:10 AM UTC trend job even ran, almost certainly from live ticker-page views that evening
  (`data/trend_analysis_data.py`'s close-aware on-demand recompute), not from any cron job
  (no cron entry fires in that UTC window).
- **System resources**: `free -h` shows `939Mi` total RAM, `75Mi` free, `228Mi` available,
  `2.2Gi`/`4.5Gi` swap in use — this VPS is under real memory pressure right now, consistent
  with its documented history of OOM kills. `df -h /` shows `75%` used, `5.8G` free — **not**
  the ~94%-full state flagged as a known past risk; disk is not implicated this time.
  **`dmesg`/`journalctl -k` could not be checked**: this session has no passwordless `sudo`
  and `journalctl` without elevated group membership shows no kernel/OOM entries at all
  ("Hint: You are currently not seeing messages from other users and the system"). This is a
  genuine gap in the evidence — see "What I could not verify" below — but it does not change
  the root-cause finding, which is independently and directly confirmed by live data below.

### The direct, reproducible cause

A live, ad-hoc `yahoo_client.get_history(...)` call just now (2026-09-23 ~03:50–03:55 UTC,
i.e. **~12 hours after** the 2026-09-22 4pm ET close) for the 10 sample tickers still stuck
in `SharedBarsCache`, and independently for a random sample of 14 unrelated large caps
(`GOOGL, JPM, XOM, PG, HD, KO, TSLA, V, WMT, JNJ, CAT, GE, LMT, NEE`), shows **every one of
them still has no usable 2026-09-22 bar**, live, right now. Inspecting the *raw* `yfinance`
response before our own `dropna(subset=["Close"])` filter (`clients/yahoo_client.py`) shows
why:

```
Ticker            MSFT                                            AAPL
Price             Open   High   Low     Close  Adj Close   ...    Open    High    Low     Close  Adj Close
2026-09-21   494.95  501.87  491.33  501.61    501.61      ...  335.28  339.64  333.05  338.98  338.98
2026-09-22   507.52  508.50  493.65     NaN       NaN      ...  340.33  345.34  338.75     NaN      NaN
```

Yahoo Finance is returning **Open/High/Low/Volume for 2026-09-22 but `Close`/`Adj Close` are
both `NaN`** — the session's closing print simply has not been published/settled on Yahoo's
side yet, for the large majority of tickers, even ~12 hours after the US market closed.
`yahoo_client.get_history`'s `df.dropna(subset=["Close"])` is doing exactly what it should —
refusing to treat an unpublished close as real data — so those 497 tickers correctly have no
2026-09-22 row in `SharedBarsCache` at all after the trend job's fetch, and `MIN_COVERAGE`
correctly refused to write a `MarketBreadthSnapshot` row built from 6/503 real values.

This is **not** a structural once-a-night timing gap (the identical 3:35 AM UTC cron slot
completed with 502/503 coverage the night before, for the 2026-09-21 session), and it is
**not** concentrated in one sector (the 10 tickers that did get fresh data — via live page
views hours *before* any cron job ran — span at least 5 different GICS sectors: XLK, XLY,
XLP, XLC, XLV). It reads as a one-off Yahoo Finance data-publication delay/glitch specific to
the 2026-09-22 session, still unresolved as of this investigation.

## Step 2 — Root cause classification

**(c) Upstream dependency — Yahoo Finance had not published a valid closing price for
~497/503 S&P 500 constituents as of both the nightly fetch and this investigation, ~12 hours
after market close.**

**The coverage gate tripped correctly — this is the gate working as designed, not a false
alarm.** `MIN_COVERAGE = 0.97` exists specifically so a partial/degraded upstream response
doesn't get silently written as a plausible-looking but skewed breadth row (see
`data/market_breadth_data.py`'s own module docstring). At 1.2% coverage there is no
reasonable threshold under which this row should have been trusted.

No code bug was found in the new sector-level logic (`7c63d87`, 2026-09-22) — the traceback
shows the exception is raised at the `sp500`-level gate, *before* `_process_sectors` is ever
reached, so the sector feature is not implicated in this failure at all. `_gate_rule`,
`coverage_ok`, `_resolve_anchor`, and `get_or_fetch_bars_batch`'s staleness/fetch logic were
all read and behave exactly as documented; the missing-tickers list is consistent with a
genuine, broad Close/Adj Close data gap, not a query or schema bug.

## Step 3 — Fix

**No code fix.** Per the process rules, this is environmental (an upstream vendor data-
publication delay, not something under this app's control) and the only mechanism involved —
`clients/yahoo_client.py::get_history` and `clients/shared_bars_cache.py`'s freshness check —
is shared by every other technical job (trend structure, Weinstein, BB+RSI, Warren, Liquidity
Zones, sector heatmap). Changing it to work around one night's data gap would touch all of
them for a problem that isn't in our code.

**Live re-run confirms no fix is currently possible.** Manually re-ran
`uv run python -m pipeline.nightly_market_breadth` at 2026-09-23 03:55 UTC — it failed
**identically** (`only 6/503 constituents (1.2%) have a bar on 2026-09-22`), confirming
Yahoo still hadn't published the data at that time. This was a safe, idempotent operation
(the job's own self-healing design — no code or config was touched) and wrote nothing new to
`MarketBreadthSnapshot`; it only added two more rows to the append-only `MarketBreadthGateLog`
audit trail, which is exactly what that table exists to record.

**No dates were repaired.** 2026-09-22 remains missing for `sp500` and all 11 `sector:<ETF>`
universes. The job is designed to self-heal automatically: `SharedBarsCache`'s close-aware
staleness check (`_is_stale`) will keep treating every one of the 497 affected tickers as
stale until their last cached bar reaches the most recently completed session, so the very
next successful fetch — whether tonight's 3:10 AM trend job, tonight's 3:35 AM breadth job,
or a manual re-run once Yahoo has actually published 2026-09-22's closes — will pick up both
2026-09-22 and 2026-09-23 in one pass and backfill the gap without any intervention.

No tests were added (there is no code bug to add a regression test for — the coverage gate
already has direct test coverage for exactly this "insufficient coverage → raise, write
nothing" behavior in `tests/test_market_breadth_data.py`). Full backend test suite was not
run since nothing was changed.

## What I could not verify

- **OOM kills around 03:10–03:35 UTC**: could not check `dmesg`/`journalctl -k` — this
  session has no passwordless `sudo` and the unprivileged `journalctl` view shows no
  kernel-level messages at all. `free -h` shows this VPS genuinely low on free memory right
  now (`75Mi` free / `228Mi` available, `2.2Gi` swap in use out of `4.5Gi`), consistent with
  its documented OOM history, but I have no direct evidence an OOM kill happened *during*
  last night's run specifically, and the root cause is independently confirmed without it
  (Close/Adj Close NaN at the raw Yahoo response level, reproduced live and on an unrelated
  ticker sample, hours after the original failure). **If you want this fully ruled out**,
  someone with `sudo` access should check `journalctl -k --since "2026-09-22 22:30" --until
  "2026-09-23 04:00" | grep -i oom` directly.
- Whether tonight's/an eventual re-run actually recovers 2026-09-22 (and 2026-09-23) — this
  depends on Yahoo publishing the data, on their own timeline, which is outside this app's
  visibility. Worth a manual spot-check of `MarketBreadthSnapshot` (or the cron-health
  Status page) in the next day or two.

## Recommendation

No action needed beyond monitoring. The job's built-in self-heal design should close the gap
on its own once Yahoo's data settles — most likely at tonight's 3:10/3:35 AM run, possibly
later if this Yahoo-side delay is unusually long. If `sp500` is still missing 2026-09-22
after 2–3 more nightly runs, that would be worth a fresh look (at that point it would no
longer look like a one-off glitch). Separately, and not urgent: the sp500-gate-blocks-all-
sectors short-circuit noted in Step 1 is a real (if here harmless) design gap worth a look
next time sector-level breadth work is touched, in case a future failure is concentrated in
one sector rather than universe-wide like this one.

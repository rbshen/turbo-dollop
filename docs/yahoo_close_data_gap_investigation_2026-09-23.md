# Yahoo Sep-22 Close data gap — follow-up investigation (2026-09-23)

Investigation only, no code changes. Follow-up to `docs/market_breadth_failure_2026-09-23.md`
(same root cause, same day), triggered by: the breadth job failing identically on a manual
re-run well after the original failure, casting doubt on that doc's "self-heals once Yahoo
publishes" framing. This doc (a) confirms the re-run is doing real work, not reading stale
cache, (b) sizes the gap directly against `SharedBarsCache`, (c) reproduces the NaN live
across several call shapes and checks yfinance's issue tracker, (d) traces what the *other*
four Yahoo-sourced nightly jobs do with the same gap — which turns out to be the more
consequential finding — and (e) explains how the ~10-20 tickers that did get a real 2026-09-22
close got it.

## 1. Does a manual re-run actually re-fetch, or just re-read cache?

**It re-fetches live, every time, for every ticker still missing 2026-09-22.**
`get_or_fetch_bars_batch` (`clients/shared_bars_cache.py`) stales a ticker via:

```python
stale = _is_stale(last_bar, interval, now)   # last_bar.date() < _most_recent_completed_trading_date(now)
insufficient = first_bar.date() > needed_start
if stale or insufficient:
    to_fetch[t] = max(lookback_days, existing_width_days)
```

For any ticker whose cached `SharedBarsCache` row still tops out at 2026-09-21, `last_bar.date()
(09-21) < _most_recent_completed_trading_date(now) (09-22)` is `True` — so it's added to
`to_fetch` and a live `yahoo_client.get_history(...)` call is issued for it. This is confirmed
directly in `MarketBreadthGateLog` (append-only, one row per check, never skipped):

| checked_at (UTC) | with_bar/503 | passed |
|---|---|---|
| 2026-09-23 03:35:51 | 6 | False |
| 2026-09-23 03:56:21 | 6 | False |
| 2026-09-23 05:38:08 | 7 | False |

Three independent gate checks ~20 min to ~2h apart, each preceded by a real `get_or_fetch_bars_batch`
call that re-attempted every stale ticker. `HUBB`'s `SharedBarsCache.fetched_at` is
`2026-09-23 05:37:21` — one minute before the 05:38:08 gate check — direct proof that a live
Yahoo call happened at that moment and, for that one ticker, finally got a real close.

The only tickers a re-run does *not* re-fetch are the ~20 that already have a real 2026-09-22
bar (their `last_bar.date() == _most_recent_completed_trading_date()`, so `_is_stale` is
`False`) — those are served from cache, correctly, since re-fetching them would be wasted work.

**So the prior doc's implicit assumption — "the mechanism will self-heal on its own, just keep
checking" — was correct about the *mechanism* (it never stops trying) but wrong about the
*timeline*: three real attempts spread over ~2 hours produced essentially zero improvement
(6 → 6 → 7 of 503).**

## 2. What does `SharedBarsCache` currently hold for 2026-09-22?

Queried directly (`interval='1d'`, `bar_time` grouped by date), at 2026-09-23 ~05:43 UTC
(~9h43m after the 2026-09-22 20:00 UTC / 4pm ET close):

- **583 distinct tickers** have any `1d` bars at all.
- **21 rows** exist with `bar_time = 2026-09-22`. **All 21 have a real, non-NULL `close`** —
  there is no NULL-close row anywhere in the table. This matters: the gap is not "row present,
  close NULL" — it's "row absent entirely." `yahoo_client.get_history`'s
  `df.dropna(subset=["Close"])` strips the NaN-close row out of the returned frame *before*
  `_write_rows` ever sees it, so a ticker stuck on Yahoo's gap simply never gets a 2026-09-22
  row written — its most recent row stays 2026-09-21, unchanged, indefinitely, with **no
  distinguishing marker anywhere in the DB** between "never tried" and "tried and Yahoo has no
  Close yet."
- Latest-bar-per-ticker distribution: **559 tickers stuck at 2026-09-21**, **21 reaching
  2026-09-22**, and 2 further outliers (2026-08-24, 2026-08-04, 2026-08-21 — long-stale/likely
  delisted tickers, unrelated to this incident).
- Of the 21 at 2026-09-22: 9 HK/OTC tickers (`0005.HK`, `0728.HK`, `0857.HK`, `0883.HK`,
  `0941.HK`, `3988.HK`, `CNSWF`, `EVVTY`, `SINGY`) plus `^GSPC` — all `fetched_at` either
  `2026-09-22 03:10:04` or `2026-09-23 03:10:04` (i.e. from the 3:10 AM trend-job batch itself —
  HK markets close on their own local session well before the US close, so their "Sep 22" bar
  was never subject to the US-close data gap at all). The remaining 11 (`AAPL, ACN, CELH, FTNT,
  HUBB, MSFT, NKE, PARA, PLTR, TECL, TXG`) are the ones answered in §5 below.

`MarketBreadthGateLog`'s own `missing_tickers_json` sample (`A, ABBV, ABNB, ABT, ACGL, ADBE,
ADI, ADM, ADP, ADSK, ...`) matches this exactly.

## 3. Live reproduction right now, plus variations

Ran directly against real Yahoo Finance (not mocked), yfinance **1.6.0** installed.

**Exact batch shape the jobs use** (`period="2y"`, `interval="1d"`, `auto_adjust=False`,
`group_by="ticker"`, multi-ticker) for `A, ABBV, ABT, ADBE, ADI, GOOGL, JPM, XOM, AAPL, MSFT,
PLTR` — **every one** returns 2026-09-21 as its last row via `yahoo_client.get_history` (which
internally drops the NaN-close row). Inspecting the *raw* `yf.download` output before that
dropna step shows why — the 2026-09-22 row is there, with real `Open`/`High`/`Low`/`Volume`,
`Close`/`Adj Close` both `NaN`:

```
A     2026-09-22  Open 163.08  High 167.59  Low 161.04  Close NaN  Adj Close NaN  Volume 3780872
AAPL  2026-09-22  Open 340.33  High 345.34  Low 338.75  Close NaN  Adj Close NaN  Volume 40599377
JPM   2026-09-22  Open 352.00  High 352.10  Low 337.30  Close NaN  Adj Close NaN  Volume 11403647
```

**Variations tried:**

| Variation | Result |
|---|---|
| `period="5d"` instead of `"2y"` | Same — 2026-09-22 row present, `Close`/`Adj Close` NaN |
| `yf.Ticker("AAPL").history(period="5d", auto_adjust=False)` (single-ticker path, not batch) | **Same NaN** — this is not a batch-size artifact |
| `yf.Ticker("AAPL").history(period="5d", auto_adjust=True)` | **Worse** — `Open`/`High`/`Low` also become NaN (adjustment math is a function of Close, so a NaN Close poisons the whole adjusted row). Not a viable workaround. |

**No period, no single-vs-batch call shape, and no `auto_adjust` setting gets a real
2026-09-22 close right now.** This directly rules out "it's a batch-download quirk, call
single-ticker instead" as a fix.

**Re-run instability, not monotonic settling.** `AAPL`'s own `SharedBarsCache` row already
holds a real 2026-09-22 close (339.75, `fetched_at 2026-09-22 21:58:51`, ~1h58m after close) —
but a fresh, direct query for `AAPL` **right now** (~9h43m after close) returns `NaN` for the
exact same date, both via `yf.download` and `yf.Ticker().history()`. Yahoo's answer for this
one historical daily bar was real ~2 hours after close and is NaN ~9.7 hours after close, from
the same process, same code. That's not consistent with a value that simply "hasn't been
published yet and is waiting to arrive" — it's consistent with an upstream value that
*flapped* (real → missing again), which the prior doc's "self-heals on its own timeline"
framing didn't anticipate and can't fully explain.

**Known yfinance issues checked** (via GitHub search): the closest match,
[ranaroussi/yfinance#2177](https://github.com/ranaroussi/yfinance/issues/2177) ("NaN on the
last Close for some tickers if using Tickers function with more than one ticker"), was closed
**not planned** by the maintainer, and its root cause was a *date-alignment* mismatch across
tickers with different last-available dates when merged into one multi-ticker frame — not our
case (same ticker, same date present, `Open`/`High`/`Low`/`Volume` populated, only `Close`/
`Adj Close` NaN — and reproduced on a genuinely single-ticker call, where no cross-ticker
alignment is even possible). No open or closed yfinance issue matches "NaN Close only, other
OHLC fields populated, single ticker" as a *library* bug; the general consensus across the
issues surveyed (`#515`, `#626`, `#134`) is that this shape is Yahoo's own backend not having
finished computing/publishing the official close for that session at request time — i.e. **not
a yfinance 1.6.0 regression, a live upstream data-availability issue**, consistent with the
prior doc's classification, but the flap evidence above means "wait and it'll appear and stay"
is not a fully safe assumption.

## 4. What do the other Yahoo-sourced jobs do with the same gap? (the more important finding)

All four other Yahoo/`SharedBarsCache`-sourced nightly jobs hit the **exact same gap** tonight
(same `interval="1d"` cache, same `dropna`), but none of them have a coverage gate like
breadth's — and `CronRunLog` shows all three checked below as **`success`** for their
2026-09-23 runs, despite operating on 2026-09-21 data for the large majority of tickers:

| Job | 2026-09-23 run | `CronRunLog.status` | Actual data currency |
|---|---|---|---|
| `nightly_trend_calculation` (3:10 AM) | 03:10:03 → 03:11:37 | **success** | 560/579 `TrendAnalysis` rows have `bars_as_of = 2026-09-21`; only 19 reached `2026-09-22` |
| `nightly_liquidity_zone_calculation` (3:25 AM) | 03:25:03 → 03:25:17 | **success** | `LiquidityZoneAnalysis.as_of` maxes at 2026-09-22, but only 4 rows reached it (out of the ~98 W1–W5 union) |
| `nightly_sector_heatmap` (3:30 AM) | 03:30:03 → 03:30:05 | **success** | `SectorEtfReturn.as_of_date` maxes at **2026-09-21** — 100% stuck, for all 11 ETFs, all 8 windows |
| `nightly_market_breadth` (3:35 AM) | 03:35:03 → 03:35:51 | **failure** | Correctly refused to write anything |

**`TrendAnalysis` is the clearest example of silent staleness.** A sampled row (`GWW`):
`computed_at = 2026-09-23 03:11:12` (looks like it ran fresh last night — because it did),
`bars_as_of = 2026-09-21` (the actual data is one session old). `bars_as_of` is the exact field
`data/trend_analysis_data.py::_is_row_stale` uses internally to correctly detect this row as
stale on the next read — but **`bars_as_of` is never included in `TrendAnalysisOut`**
(`core/schemas.py`) and is never referenced by any frontend component (`WeinsteinStageCard`,
`SummaryStrip`, `TickerHeader`, `BbRsiEntrySignalCard`, `WarrenSignalCard`,
`LiquidityZonesCard` all show `computed_at` only — confirmed by grep, none reference
`bars_as_of`). So a user looking at Weinstein Stage / Trend state / Liquidity Zones on the
Technical tab tonight sees a "computed [fresh timestamp]" caption with **no visible indication**
that the underlying price data is a session behind. The correctness mechanism exists
(`bars_as_of`, `_is_row_stale`) but only gates *internal* recompute decisions — it was never
wired to *surface* staleness to a viewer.

`nightly_sector_heatmap` is 100% stuck (not just partially) because its 11-ticker ETF batch
(`XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB, XLRE, XLC`) apparently hit the same Close-not-yet-
published gap for literally every one of the 11 funds — consistent with this being a broad,
not ticker-specific Yahoo issue tonight, not something concentrated in small-cap/illiquid names.

**Market Breadth is, ironically, the only one of the five that is currently *correct*** — it's
the only job with an explicit coverage gate, so it's the only one that visibly failed instead of
silently serving a stale-but-confident-looking result. The other four "succeeded" only because
nothing checks whether the data they computed on actually advanced.

## 5. How did the ~11 successful tickers get a real 2026-09-22 close?

`AAPL, ACN, CELH, FTNT, HUBB, MSFT, NKE, PARA, PLTR, TECL, TXG` — their `SharedBarsCache.fetched_at`
timestamps are scattered individually through the evening (`21:25:02`, `21:25:20`, `21:25:57`,
`21:26:03`, `21:37:22`, `21:58:51`, `22:00:29`, `22:01:25`, `22:20:31` UTC on 09-22, plus `TXG` at
`15:25:02` UTC — mid-session, likely an earlier on-demand view — and `HUBB` at `05:37:21` UTC on
09-23, the manual re-run just now). These are **not** one batch call (no single shared
timestamp) and none of them line up with a cron job's own start time (3:10/3:25/3:30/3:35/3:40
AM UTC). This is the signature of **individual, on-demand single-ticker fetches** —
`data/trend_analysis_data.py::compute_and_store_trend_analysis`, called from the standalone
`GET /api/tickers/{ticker}/trend-analysis` endpoint whenever someone views that ticker's
Technical tab — each landing at whatever moment that specific page happened to be viewed.

The *code path* is not meaningfully different from the batch job's (§3 already showed
single-ticker calls hit the identical NaN right now) — the difference is purely **timing**:
these ~11 tickers happened to be viewed individually in the roughly 1.5–2.5h window after the
4pm ET close, and at that specific moment Yahoo's backend already had a real close for those
specific symbols, while the 3:10/3:35 AM batch runs (7–11h later) hit a state where most symbols
still didn't (or, per the AAPL flap in §3, no longer did). There is nothing about "on-demand vs.
batch" or "single-ticker vs. multi-ticker" that reliably avoids the gap — it's incidental timing
against a moving, apparently non-monotonic upstream target.

## Root cause, plain terms

Yahoo Finance's own backend had not (and, per the flap evidence, may not reliably) published a
finalized `Close`/`Adj Close` for the 2026-09-22 session for the large majority of S&P 500
constituents, for an unusually long window (still true ~9.7h after close, with no measurable
improvement across three checks spanning ~2 hours, and at least one ticker — AAPL — observed to
have had a real value earlier in the evening that a fresh query no longer reproduces). This is
an upstream data-provider issue, not a bug in Fathom's code — `yahoo_client.get_history`'s
`dropna(subset=["Close"])` and `SharedBarsCache`'s close-aware staleness check are both behaving
exactly as designed, correctly refusing to treat a partial/unsettled bar as real. **The actual
gap in Fathom's own design is not "why is Yahoo slow" (out of this app's control) — it's "why
did four of the five jobs sharing this exact same data problem report `success` and show no
visible staleness indicator, while only Market Breadth caught it."**

## Other features affected (silently stale, tonight)

- **Trend Analysis / Weinstein Stage** (ticker Technical tab): 560/579 tickers running one
  session behind, `computed_at` looks fresh, `bars_as_of` (the field that would reveal this) is
  not exposed anywhere in the API or UI.
- **Liquidity Zones**: only 4/~98 W1–W5 tickers reached 2026-09-22; the rest are a session
  behind, same "looks fresh" `computed_at`-only display.
- **Sector Heatmap**: 100% stuck at 2026-09-21 for all 11 sectors, all 8 return windows —
  `nightly_sector_heatmap` reported `success`.
- **Warren / BB+RSI**: not checked in this pass — they read the `"60m"` `SharedBarsCache` row,
  a different interval from the `"1d"` gap investigated here, so they are very likely
  unaffected by *this specific* incident, but they'd be exposed to the identical silent-success
  pattern if Yahoo ever had an equivalent gap on 60m bars. Worth checking in a follow-up if this
  recurs.
- **Chart tab**: not affected right now — `FMP_ENABLED=true` in this deployment, so the Chart
  tab's default price source is FMP's direct, uncached call (`data/chart_data.py::
  _fetch_fmp_bars`), not Yahoo/`SharedBarsCache` at all. If FMP were ever paused, its Yahoo
  fallback goes through the same `yahoo_client.get_history` and would silently show whatever
  the last real cached day is (no crash, no NaN candle — the same dropna protection — just one
  day behind with no on-screen indication).

## Fix options

**1. (Contained to breadth) Push `nightly_market_breadth`'s cron time later**, e.g. from 3:35
AM UTC to something like 8–9 AM UTC (~12–13h after the US close, well past the typical
settlement window). Pure `crontab.txt` + `cron_health.py` schedule-metadata change, no shared
code touched. Trade-off: delays the breadth page's own "as of" date update each morning for
users who check it early; per the flap evidence above, not a *guaranteed* fix (Yahoo's
publication delay this specific night has already exceeded what "later" would obviously fix,
and there's no proof waiting monotonically resolves it) — but it's the cheapest, lowest-risk
mitigation and matches the times FMP-based jobs already run at.

**2. (Contained to breadth) Distinguish "provider not ready yet" from "job broken" in the
alerting, not the data.** Keep the 97% write gate exactly as-is (never write a skewed row), but
change `InsufficientCoverageError` to only escalate to a `cron_heartbeat` failure if the *prior
successful* snapshot is also older than some threshold (e.g. 36–48h) — otherwise log a warning
and exit cleanly. Contained to `data/market_breadth_data.py`/`pipeline/nightly_market_breadth.py`.
Trade-off: reduces alert noise on a slow-provider night, but also reduces visibility if this
turns out to be a genuine, longer outage worth escalating sooner — needs a deliberately-chosen
threshold, not a rubber stamp.

**3. (Cross-cutting, larger blast radius — touches shared code and every Yahoo-sourced job's
schema/frontend) Surface data recency, not just compute recency, for every technical feature.**
Expose `bars_as_of` on `TrendAnalysisOut` (and the equivalent field for Liquidity Zones/Sector
Heatmap, if they don't already track one) so the frontend can show "data as of 2026-09-21"
distinctly from "computed 2026-09-23 03:11" — closing the exact gap `bars_as_of` was built to
solve internally but was never wired out to a viewer. This is the most correct long-term fix for
the *actual* problem this investigation surfaced (silent staleness across 3 of 5 jobs), but it's
schema + shared-code + multiple frontend components, materially bigger than what's needed to
address Market Breadth's own (already-correct) failure mode.

**Recommendation**: do (1) and (2) together for Market Breadth specifically — cheap, contained,
no shared-code risk, and stops the false "job broken" read on a night that's genuinely an
upstream delay. Treat (3) as a separate, explicitly-scoped follow-up — it's the more important
finding of this investigation (four jobs silently reporting `success` on stale data is a bigger
exposure than one job loudly failing), but it's shared code touching Trend/Weinstein/Liquidity
Zones/Sector Heatmap's schemas and several frontend components, and deserves its own review
rather than being folded into a breadth-only fix.

## What I could not verify

Same as the prior doc — no `sudo`/`journalctl -k` access to rule out an OOM kill during the
3:10–3:35 AM window; not relevant here since the root cause is independently confirmed at the
raw-Yahoo-response level, reproduced live, hours after any such event would have mattered.
Whether tomorrow night's run recovers 2026-09-22 fully is unknown and outside this app's
control — worth a spot-check of `MarketBreadthSnapshot`/`SectorEtfReturn`/`TrendAnalysis.
bars_as_of` distribution in the next day or two.

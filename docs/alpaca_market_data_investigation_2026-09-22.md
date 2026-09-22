# Alpaca Market Data API (free/Basic tier) — feasibility investigation (2026-09-22)

Investigation only. No code, schema, or crontab was changed. No scratch scripts were left behind
(all checks below were plain read-only `grep`/`sqlite3` queries, not saved to disk). Alpaca-specific
facts are from Alpaca's own docs/support pages via web search (no live Alpaca account/API key
available in this sandbox to verify directly — flagged per-claim below where that matters).

**Update (2026-09-22, same day): a live paper-trading data-only key became available and resolved the
three items this originally left as "needs a live key" (see section 7) — most importantly, an
undocumented intraday page-size cap that makes Warren's nightly shape materially more expensive under
Alpaca than this original pass could have known. Sections 1–6 below are otherwise unchanged from the
no-key pass and are kept as the original investigation's reasoning, not restated.**

## Summary

Six independent features read Yahoo Finance today, all added between 2026-08-23 and 2026-09-21 and
already unified behind two thin adapters (`clients/yahoo_client.py`, `clients/shared_bars_cache.py`).
That consolidation is exactly what makes an Alpaca evaluation tractable: almost every call site goes
through one of two functions, not six bespoke fetches.

Alpaca's free tier would plausibly cover the **daily/weekly bar consumers** (Chart, Trend/Weinstein,
Liquidity Zones, Sector Heatmap, Momentum, Market Breadth) with no material gap, and its 60-minute-bar
history is a genuine *improvement* over Yahoo's for the two intraday consumers (Warren, BB+RSI) — Yahoo
caps 60m history at ~730 days; Alpaca's minute/hour bars reach back to 2016, which would materially help
Warren's documented leading-edge-noise problem (the write-side buffer/cleanup work from 2026-09-19).
The two hard blockers are (1) no index-symbol support — `^GSPC` needs a substitute, and SPY is a
low-risk one, already precedented elsewhere in this codebase — and (2) no non-US-listing coverage,
which matters only if a user adds a foreign-primary-listed ticker to a watchlist (not confirmed to be
in active use today, but structurally always possible via typeahead search). Chart's W_4Y range
already fetches back to ~2016 for SMA200 warm-up, right at Alpaca's own stated data-start boundary —
this is the one place a swap would have zero headroom, not comfortable margin.

Nothing here recommends a design — see section 6 for three candidates and their tradeoffs.

## 1. Every current Yahoo Finance call site

All six technical-analysis features below moved to Yahoo-only (regardless of `FMP_ENABLED`) between
2026-08-23 and 2026-09-18, per CLAUDE.md's "Trend structure analysis" / "Liquidity Zone detection" /
"Warren RSI/ADX/WVF" sections and the "Shared Yahoo bars cache" consolidation on 2026-09-19. Two client
modules now cover almost everything:

- **`clients/yahoo_client.py`** — the only module that actually calls `yfinance`. Three methods:
  `get_history` (batch OHLCV, used by everything below), `get_dividends`, `get_earnings_dates` (both
  single-ticker, used only by Chart's event markers).
- **`clients/shared_bars_cache.py`** — cache-first wrapper around `get_history`, one table
  (`SharedBarsCache`, keyed `(ticker, interval, bar_time)`) serving every `"1d"`/`"60m"` consumer with
  a growing-window + close-aware-freshness check (see CLAUDE.md's "Shared Yahoo bars cache" section for
  the full mechanism). This is the module that would absorb most of an Alpaca swap.

| Call site | Cadence | Interval fetched | Lookback | Native weekly, or local resample? |
|---|---|---|---|---|
| **Chart tab** (`data/chart_data.py`) | On-demand, every page load, zero caching (deliberately reverted 2026-09-18) | `1d` (D_6M/1Y/2Y), `1wk` (W_4Y) | 2y/2y/5y/**10y** (yahoo_period, snapped up for SMA200 warm-up) | **Native** `"1wk"` — confirmed bit-identical to local resampling, fetched directly for speed/simplicity |
| **Chart tab event markers** (`data/chart_events_data.py`) | On-demand, only as Yahoo *fallback* (FMP is primary while `FMP_ENABLED`) | dividends (`Ticker.dividends`), earnings (`Ticker.get_earnings_dates`) | full history / 40 rows | n/a |
| **Weinstein Stage / Trend-BOS** (`pipeline/nightly_trend_calculation.py`, `data/trend_analysis_data.py`) | Nightly 3:10 AM, full tracked universe (~572) + on-demand single-ticker endpoint | `1d` | 730d (2y) | **Local resample** (`weinstein.py::resample_to_weekly`), confirmed bit-identical to native — chosen to avoid a second fetch |
| **Weinstein Mansfield RS benchmark** (same job) | Same | `1d`, `^GSPC` rides in the same batch call | 730d | resampled |
| **Liquidity Zones** (`pipeline/nightly_liquidity_zone_calculation.py`, `data/liquidity_zone_data.py`) | Nightly 3:25 AM, W1–W5 watchlist union (~100) | `1d` | **1460d (4y)** | Local resample for Weekly timeframe |
| **Warren signal** (`pipeline/nightly_warren_signal_calculation.py`) | Nightly 3:40 AM, W1–W5 union, **full replay from scratch every run** | `60m` (resampled locally to 2h sessions) | 730d (2y — Yahoo's own ceiling) | n/a (intraday only) |
| **BB+RSI signal** (`pipeline/nightly_entry_signal_calculation.py`, via `clients/technical_sources.py`) | Nightly 3:20 AM, W1–W5 union, evaluates only the latest day | `60m` (shares Warren's cache row) | 60d | n/a |
| **Momentum** (`data/momentum_data.py`) | Monthly, Moat-rated universe | `1d` (own direct `yahoo_client.get_history` call, **not** through the shared cache — uses `auto_adjust=True`, the one consumer still on split/dividend-adjusted closes) | 2y | n/a |
| **Sector Heatmap** (`data/sector_heatmap_data.py`) | Nightly 3:30 AM, fixed 11 SPDR ETFs | `1d` (own direct call, `auto_adjust=False`, reads `Adj Close` explicitly for total return) | 2y | n/a |
| **Market Breadth** (`pipeline/nightly_market_breadth.py`, `data/market_breadth_data.py`) | Nightly 3:35 AM, full S&P 500 (~503), reuses Trend's warm cache when it ran first | `1d` (shared cache) | 730d | n/a (needs 252-bar/SMA200 eligibility per ticker) |
| **Price/Quote fallback** (`data/ticker_summary.py`, `clients/yahoo_cache.py`) | On-demand, only while `FMP_ENABLED=false` | `1d` | 5d | n/a (own small cache table, `YahooPriceCache`, now session-aware — see section 5) |
| **ma_magnet** (`analysis/ma_magnet/`) | Unwired research script | — | — | **Not a Yahoo consumer at all** — reuses the FMP client/cache, confirmed via its own `run.py` docstring and a grep of `analysis/ma_magnet/data.py` |

## 2. Would Alpaca's free/Basic tier cover each site's actual needs?

Checked against Alpaca's public docs/support pages (not verified against a live key in this sandbox —
flagged where that matters):

- **Fields used**: every site above reads plain OHLCV. Alpaca's `/v2/stocks/bars` returns exactly that
  (o/h/l/c/v plus trade/VWAP fields nothing here needs). No gap.
- **Depth needed vs. depth available**: the deepest reach is Chart's W_4Y range, `yahoo_period="10y"`
  (fetched for SMA200-on-weekly warm-up, not because 10y is displayed — `visible_days` is only 4y).
  That's back to roughly 2016. **Alpaca's own historical data starts at 2016 for both minute and daily
  bars** (confirmed via Alpaca's own support FAQ, "Does Alpaca Data API have data prior to 2016?", and
  a corroborating community-forum thread titled "Cannot get daily bars before 2016") — so this is the
  one site with **zero headroom**, not comfortable margin, if it ever needs to fetch wider. Every other
  site's lookback (730d–1460d) sits well inside that boundary.
- **Intraday depth is a net *improvement*, not just parity**: Yahoo's 60m-interval history is capped at
  ~730 days (confirmed empirically in this app's own BB+RSI backfill investigation, referenced
  throughout CLAUDE.md). Alpaca's minute/hour bars reach back to **2016** — roughly 7x deeper. This
  directly bears on Warren's own documented problem
  (CLAUDE.md's "Write-side warm-up buffer" entry, 2026-09-19): the reason Warren needs a 180-day write-side
  discard buffer at all is that its state machine bootstraps from a blank slate at the start of
  whatever window it's given, and Yahoo can only ever give it 2 years. A ~9-10 year Alpaca window would
  let the bootstrap-inaccuracy region (empirically ~0% error past 300 days into the replay, per that
  memory) sit almost entirely before the window even starts, likely shrinking or eliminating the
  buffer/cleanup mechanism — a genuine design win, not just a swap, though it would need its own
  re-validation (the 180d/300d figures were measured against Yahoo-length windows and shouldn't be
  assumed to transfer unchanged).
- **Rate limit (200 req/min)**: Alpaca's stock-bars endpoint supports a multi-symbol `symbols=` query
  param (comma-separated), similar in spirit to `yfinance`'s batch download, but responses are paginated
  via `next_page_token` when a request's bar count exceeds the page limit. The nightly jobs' actual
  request counts under Alpaca's pagination shape (e.g., Market Breadth's 503 tickers × 730 daily bars,
  or Warren's ~100 tickers × 730 days of 60m bars — roughly 3,500 bars/ticker) were **not measurable
  without a live key** in this sandbox; this is the one item that genuinely needs a hands-on trial
  against a real free-tier key before any implementation estimate can be trusted. 200 req/min is
  generous for the batch-once-per-night shape every consumer already uses, but the exact call count per
  job is an open question, not a confirmed non-issue.
- **IEX vs. SIP feed**: the free tier serves IEX-sourced data (~2.5% of consolidated US volume) for
  real-time/recent quotes; the paid SIP feed (consolidated, 100% of volume) requires a subscription.
  Every consumer above reads only bar closes/OHLCV for technical analysis, not live quotes or trade-by-
  trade data, so IEX-vs-SIP divergence on daily/60m bar aggregates is expected to be small — this
  wasn't independently measured here (no live key) and would be worth a spot-check (e.g., compare
  Alpaca IEX daily closes against Yahoo/FMP for a sample of liquid names) before trusting it blindly for
  the Warren/BB+RSI threshold-crossing logic, which is sensitive to exact values (see CLAUDE.md's own
  note on why Wilder-seeded RSI was re-implemented for Warren specifically because "the state machine
  depends on exact-value threshold crossings").

## 3. `^GSPC` substitute for the Weinstein Mansfield RS benchmark

**Confirmed: Alpaca has no index-symbol support.** `^GSPC` (and `^IXIC`/`^DJI`/`^RUT`) are Yahoo-specific
pseudo-tickers; Alpaca only serves tradable equity/ETF symbols. A substitute is required — SPY is the
obvious one, and this codebase already treats SPY as the market benchmark elsewhere
(`data/ticker_summary.py::_resolve_perf_vs_spy`, the existing "5Y vs SPY" pill, sourced from FMP).

**Checked whether the substitution would meaningfully change Weinstein's own output**: Mansfield RS
(`analysis/trend_structure/weinstein.py`) computes `rs_ratio = ticker_close / benchmark_close`, then
`(rs_ratio.iloc[-1] / smoothed_rs_ratio - 1) * 100`. This is a **level-invariant ratio computation** —
SPY trading at ~1/10th of `^GSPC`'s index level scales `rs_ratio` by a constant factor that cancels out
identically in both the numerator and the smoothing term, so the pure price-level difference has no
effect. The two remaining, genuinely real differences are (a) `^GSPC` is a pure price index (no dividend
reinvestment) and this app already fetches SPY with `auto_adjust=False`, i.e. raw/unadjusted close —
so SPY's raw price series tracks `^GSPC`'s price movements almost exactly, not SPY's total-return
series; and (b) SPY's own expense ratio (~9bps/yr) and minor tracking error versus the index. Both are
small enough that Mansfield RS's own gate (`rs_ok = mansfield_rs is None or mansfield_rs > 0.0`, a bare
sign check) is very unlikely to flip on the substitution — not independently re-validated against real
history in this pass, but the mechanism gives no reason to expect a meaningful change.

## 4. Non-US-equity coverage

**Confirmed: Alpaca (a US broker-dealer's data API) has no HK/France/non-US-primary-listing coverage.**
It serves US-listed equities/ETFs only — including US-listed ADRs of foreign companies (HSBC, TSM, NVO,
ASML, ARM, BABA, TME — all already tracked in this app per the Screener's `Country=US` note in
CLAUDE.md), since an ADR trades as an ordinary US-ticker symbol. What it cannot serve is a
foreign-*primary*-listed symbol (e.g. Yahoo-style `0700.HK`, `MC.PA`).

This app's tracked universe (S&P 500 + Dow scrape) has no such tickers today — `core/tickers.py`'s
`normalize_ticker` only special-cases `BRK.B`/`BF.B`. But every Yahoo-sourced technical feature above
operates on **any ticker a user reaches**, not just the tracked universe:

- **Chart tab and the standalone Trend Analysis endpoint** — on-demand, any ticker viewable on the
  ticker page, including one found via typeahead search, which (per `core/tickers.py`'s own docstring)
  "queries FMP's entire live ticker universe," not just the tracked set.
- **Liquidity Zones / Warren / BB+RSI nightly jobs** — scoped to the W1–W5 watchlist union, which a user
  can populate with any ticker, foreign-primary-listed or not.
- **Weinstein/Trend nightly job and Market Breadth** — scoped to the full tracked universe / S&P 500
  scrape respectively, so not exposed to this in practice today.

No evidence was found (via a filesystem/repo check; DB inspection wasn't possible in this pass — see
note below) that an HK/France-primary-listed ticker is actually on a live watchlist today, only that the
mechanism (typeahead search + W1–W5 watchlists) makes it structurally possible at any time with no
guard rail. **A full swap to Alpaca-only would silently break Chart/technical-analysis features for any
such ticker a user adds**, whereas today's Yahoo-only design would still serve it.

## 5. The YahooPriceCache staleness/coverage bug — status

**Already fixed, not open.** Two related but distinct bugs existed in this area and both are closed as
of 2026-09-19 (per CLAUDE.md's "Shared Yahoo bars cache" section):

1. The **coverage**-blind bug (a cache row could be time-fresh but too narrow for a wider request) was
   the original motivation for `clients/shared_bars_cache.py` itself — it now grows to the maximum
   window any consumer has ever requested and forces a live refetch whenever a row's *last bar* doesn't
   match the most recently completed session, not on a flat timer.
2. `YahooPriceCache`'s own flat 1-day TTL (the Price/Quote fallback's cache, now the *only* remaining
   consumer of that table) was replaced 2026-09-19 with a market-session-aware check
   (`clients/yahoo_cache.py::_is_stale`) — fresh only briefly while the session is open, fresh through
   the close/weekend once a post-close fetch lands.

**What this means for an Alpaca swap**: there is no pre-existing bug to "sidestep" or "inherit" at this
point — whichever caching layer sits in front of Alpaca would need to **replicate** two already-solved
properties (growing-window coverage + close-aware freshness, not a flat TTL) rather than fix anything
new. That's a real implementation cost (this mechanism took several rounds to get right, per CLAUDE.md's
own history of the bug chain that led here), but it's a known, already-solved problem, not an open risk.
One new wrinkle Alpaca introduces: its own market-calendar/session-close semantics would need checking
against `_most_recent_completed_trading_date`'s Eastern-time, weekday-only (not holiday-aware) logic —
not expected to differ, since both are keyed to the same US equity market clock, but not verified here.

## 6. Candidate designs (not recommending one)

**A. Full replace, scoped to US-listed tickers only.** Point `shared_bars_cache.py` and
`yahoo_client.py`-equivalent calls at Alpaca; keep Yahoo (or drop foreign-ticker support outright) as an
explicit fallback path only for whatever `normalize_ticker`/search flags as non-US-primary. *Pro*:
single source of truth for the vast majority of traffic, deeper intraday history (helps Warren), one
rate-limit budget to reason about. *Con*: needs an explicit US-vs-foreign gate somewhere upstream (none
exists today — FMP's own profile data, already fetched for every ticker, likely has the exchange/country
field to drive it), plus a parallel caching-layer rewrite (section 5) and a real historical-parity
spot-check before trusting Warren/BB+RSI's exact-threshold logic on IEX-sourced bars.

**B. Alpaca-primary, Yahoo-fallback.** Try Alpaca first at every call site; fall back to the existing
Yahoo path on a missing/foreign symbol or an Alpaca error. *Pro*: no upfront foreign-ticker gate needed,
lowest regression risk, deeper intraday history still available for the common case. *Con*: two data
sources now live in every technical feature permanently (this app's `FMP_ENABLED`-fallback precedent
shows this pattern works, but it's a second one to maintain, test, and reason about for drift — e.g. two
sources disagreeing slightly on a bar close feeding Warren's exact-value RSI thresholds, the same class
of divergence risk noted in section 2).

**C. Leave as-is (Yahoo-only), revisit only if Yahoo itself becomes unreliable.** *Pro*: zero migration
risk, zero new rate-limit/auth surface, the existing shared-cache design is already mature and
well-tested (35+ dedicated tests across the consumers touched in section 1). *Con*: forgoes Alpaca's
real intraday-depth advantage for Warren, and leaves Yahoo (an unauthenticated, no-SLA endpoint,
explicitly called out in `clients/yahoo_client.py`'s own docstring as having no kill-switch "because
nothing in this app's design asks for one") as the sole dependency for six production features.

Flagging back for a decision — no design chosen here.

## Not verified in this pass (needs a live Alpaca key or a browser)

- Actual free-tier request counts per nightly job under Alpaca's pagination shape (section 2).
- IEX-vs-SIP/vs-Yahoo bar-level divergence on real symbols.
- Whether Alpaca's multi-symbol `bars` endpoint has an undocumented symbol-count cap per request
  (would change the "one batch call per night" shape this app's design leans on throughout).

## 7. Live-key trial (2026-09-22) — resolving the three items above

A real paper-trading data-only Alpaca key (`APCA_API_KEY_ID`/`APCA_API_SECRET_KEY`, now in
`backend/.env`) made this section possible. All calls below hit `data.alpaca.markets/v2/stocks/bars`
(and, for the symbol-count probe only, the read-only `paper-api.alpaca.markets/v2/assets` listing) with
`feed=iex` — the free-tier default; the paid `sip` feed was not tested (not available on this key).
Nothing trading/order-related was touched. A throwaway script drove all of this and was deleted before
finishing, per instructions — every number below is from its actual output, not estimated.

Sample: `MSFT`, `JNJ`, `XOM`, `SPY` (S&P 500 names not on any watchlist) + one representative ticker
from each of the five `W1`–`W5` watchlists (`AAPL`, `AMAT`, `AMD`, `COHR`, `AAOI`), queried live from
the real DB — 9 tickers total. **The live `W1`–`W5` union is 104 tickers today** (this section's own
direct measurement — CLAUDE.md's Warren-section timing note says "98," measured on a different day; the
watchlists have grown slightly since).

### 7.1 Price divergence vs. cached Yahoo bars

**Clean match, small idiosyncratic per-bar noise — not a systematic offset, and no gaps.** Every one of
the 9 sample tickers had a real Alpaca bar for every date/week being compared (zero missing dates), so
"occasional gaps" is ruled out as a real pattern. What remains is small, non-systematic per-bar noise:

| Ticker | Daily mean\|diff%\| | Daily max\|diff%\| (date) | Daily *signed* mean diff% | Weekly mean\|diff%\| | Weekly max\|diff%\| |
|---|---|---|---|---|---|
| MSFT | 0.034% | 0.349% (06-26) | −0.008% | 0.097% | 1.258% |
| JNJ | 0.028% | 0.170% (07-16) | −0.0002% | 0.024% | 0.118% |
| XOM | 0.035% | 0.214% (09-18) | −0.010% | 0.069% | 0.755% |
| SPY | 0.013% | 0.132% (06-25) | −0.006% | 0.015% | 0.088% |
| AAPL | 0.039% | **0.870%** (06-26) | −0.016% | 0.109% | 1.258% |
| AMAT | 0.046% | 0.453% (06-26) | −0.010% | 0.063% | 0.453% |
| AMD | 0.061% | **1.338%** (08-04) | −0.001% | 0.054% | 0.505% |
| COHR | 0.032% | 0.147% (06-26) | −0.013% | 0.204% | **4.224%** |
| AAOI | 0.044% | 0.125% (07-23) | +0.009% | 0.148% | 2.866% |

(62 overlapping trading days per ticker, trailing ~90 calendar days; 26 overlapping weeks, trailing
~180 days; daily close-to-close, Alpaca `1Day`/`1Week` vs. the exact cached `SharedBarsCache` Yahoo
row for the same date/week — weekly uses Alpaca's native `1Week` bar against this app's own
`resample_to_weekly` applied to the cached Yahoo daily frame, i.e. the real code path, not a synthetic
resample.)

Daily divergence is essentially a coin flip in direction (Alpaca lower on 45–63% of days per ticker,
signed mean within ±0.016% of zero for every ticker) — this is IEX-sampling noise (IEX is ~2.5% of
consolidated volume; its own last print before the close can differ slightly from the officially
reported consolidated closing price Yahoo/FMP report), not a directional discount or premium the way a
stale-quote or adjustment-methodology bug would produce. Four of the nine tickers (MSFT, AAPL, AMAT,
COHR) share their single worst daily divergence on the *same* date (2026-06-26) — a market-wide
volatile session amplifying IEX's thin-sample noise across many names at once is the likely explanation,
not investigated further. AMD's isolated 1.338% (08-04) and COHR's isolated 4.224% weekly divergence
are the two largest single-point outliers in the sample; neither recurs on adjacent dates for that
ticker, consistent with one-off noise rather than a drift. **Bottom line for Warren/BB+RSI's
exact-value threshold logic** (flagged as a real risk in section 2 above): daily/weekly divergence this
small is very unlikely to matter on its own, but this trial did not test 60m-bar-level divergence
specifically (see 7.2 for why — the pagination cost made a like-for-like 60m comparison impractical to
also run), so that specific risk (checked against RSI(14)'s exact 12/30/70/80.81/84.75 thresholds) is
still not directly measured.

### 7.2 Real call counts per nightly-job shape — the actual bottleneck is NOT the 200/min rate limit

**The 200 req/min cap is real** (confirmed via the `X-Ratelimit-Limit: 200` / `X-Ratelimit-Remaining`
response headers on every call) **but was never the binding constraint in this trial** — no call in any
test here came close to 200/min, including a 278-call burst. The actual constraint is an **undocumented,
timeframe-dependent per-page bar cap** that has nothing to do with the `limit` query parameter:

- **Daily (`1Day`) bars: ~9,600–9,900 bars/page**, regardless of symbol count. A 503-ticker S&P 500
  batch × 730 days needed exactly **26 pages/calls** (250,553 bars total, 47.6s, 0 missing symbols) — a
  59-symbol sanity check earlier in this trial landed at the same ~9,850 bars/page. **This means
  Trend/Weinstein, Liquidity Zones, Sector Heatmap, and Market Breadth — every daily-bar consumer — would
  cost a trivial 1–26 calls/night under Alpaca**, comfortably inside the rate limit and roughly the same
  wall-clock cost as today's single Yahoo batch call. No regression risk found here.
- **Intraday (`1Hour`, the closest analog to this app's `60m`) bars: only ~190–255 bars/page**, confirmed
  by directly varying the `limit` param (50/100 are honored exactly; 500/1000/5000/10000 all plateau at
  the identical ~186-count page for a fixed date range) — the server silently caps the page far below
  whatever `limit` is requested, and this cap is **not mentioned anywhere in Alpaca's public docs**.
  Single-symbol loop: MSFT needed 19 pages (3,768 bars) and JNJ 16 pages (3,481 bars) for a 730-day
  window — **~17.5 pages/ticker average**. A 20-ticker multi-symbol batch of real `W1`–`W5` names needed
  **278 pages for 70,832 bars (255 bars/page)** — only ~20% fewer calls than 20 separate single-symbol
  loops would need (20 × 17.5 ≈ 350), because **the page cap applies to the total bar volume across all
  symbols in the request, not per symbol** — multi-symbol batching does not multiply page yield the way
  it does for daily bars.
- **Extrapolated to the full 104-ticker `W1`–`W5` union, a single full 730-day/60m pull costs roughly
  1,450–1,820 calls** (multi-symbol vs. single-symbol-loop strategy, respectively — the two converge
  because both are bound by the same total bar volume). Measured real-world throughput (288.6s for 278
  calls in the 20-ticker batch; 16.05s for 19 calls in the single-symbol MSFT loop) extrapolates to
  **roughly 25 minutes of continuous fetching either way** — not from hitting the rate limit, but from
  the sheer number of small pages needed. **Warren's design replays its full 730-day window from
  scratch every night** (CLAUDE.md's own "genuinely sequential state machine" section), so this ~25
  minute cost would recur every night, not just once on a historical backfill — a severe regression
  against the currently-measured ~99s Yahoo single-batch-call figure for the same 98–104-ticker scope
  (CLAUDE.md's "Measured, not assumed" entry), and would already overflow Warren's existing ~15-minute
  cron allocation (3:40–3:55 AM) on its own. If the `W1`–`W5` union ever grew toward its documented
  500-ticker cap (5 × 100), this scales roughly linearly toward **~2 hours** — a non-starter for the
  current full-replay-every-night design as-is.
- BB+RSI's own shape (60-day lookback, evaluates only the latest day) was not separately re-measured —
  it needs far fewer bars per ticker than Warren's 730-day pull, so it sits well inside a 200-call
  budget by the same per-page arithmetic; not confirmed with a live measurement in this pass.

**This is the central, load-bearing finding of this trial**: the free tier's 200 req/min limit, called
out as the open question in section 2, turns out to be comfortably sufficient on its own — the real,
previously-unknown cost driver is the ~200-bar intraday page cap, which only a live key could have
surfaced (nothing in Alpaca's docs mentions it). It changes the calculus specifically for Warren (and,
to a lesser and unmeasured extent, BB+RSI) — it does not affect the daily-bar consumers at all.

### 7.3 Multi-symbol request behavior at scale — no hard symbol-count cap; pagination, not truncation

Tested with real, valid, currently-tradable NYSE/NASDAQ symbols pulled live from Alpaca's own
`/v2/assets` listing (7,998 candidates) — a scale far beyond anything this app would ever request in one
call (Market Breadth's 503 is the largest real consumer).

| Symbols requested | Status | Symbols returned | Paginated? |
|---|---|---|---|
| 500 | 200 | 500 | no |
| 1,000 | 200 | 1,000 | no |
| 2,000 | 200 | 1,997 | no |
| 5,000 | 200 | 4,971 | no |
| 7,998 | 200 | 6,106 (page 1); **7,924 of 7,998 across both pages** | yes — `next_page_token` present |

**No hard "N symbols max" rejection and no silent truncation at any tested scale.** Past a certain
total-bar-volume threshold for the requested window (here, a single day — so effectively "past a certain
symbol count," but driven by the same bar-volume mechanism as 7.2, not a distinct symbol-count check),
the response pages exactly like a normal date-range pagination: following `next_page_token` recovered
7,924 of the 7,998 requested symbols (the remaining 74 had no trade that specific day — confirmed by
full pagination, not lost to a cap). **The one real way to lose data silently would be an unhandled
`next_page_token`** — a caller that only reads page 1 without checking for it would see a partial,
plausible-looking result (exactly what page 1 of the 7,998-symbol test looked like in isolation: 6,106
symbols, no error) with no indication anything is missing.

One separate, sharp-edged finding surfaced while building the symbol list for this test: **an invalid
symbol anywhere in a multi-symbol request fails the entire call with a 400**, not a per-symbol omission —
`{"message": "invalid symbol: BF-B"}` for the whole request. Class-share tickers need Alpaca's dot
notation (`BF.B`, `BRK.B`); this app's own `-`-based normalization (`BF-B`, `BRK-B`, per
`core/tickers.py`) and a `/`-based guess (`BF/B`) both fail. Any full-universe batch call (e.g. Market
Breadth's S&P 500 sweep) would need this translation — a small, mechanical adapter-layer detail, not a
blocker, but confirmed here with a live 400 rather than assumed.

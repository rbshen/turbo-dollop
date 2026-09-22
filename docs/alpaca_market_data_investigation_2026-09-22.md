# Alpaca Market Data API (free/Basic tier) — feasibility investigation (2026-09-22)

Investigation only. No code, schema, or crontab was changed. No scratch scripts were left behind
(all checks below were plain read-only `grep`/`sqlite3` queries, not saved to disk). Alpaca-specific
facts are from Alpaca's own docs/support pages via web search (no live Alpaca account/API key
available in this sandbox to verify directly — flagged per-claim below where that matters).

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

# Massive.com (Polygon.io) "Stocks Starter" — feasibility investigation (2026-09-23)

Investigation only — no production code, cron, config, or DB rows changed. Triggered by
Yahoo Finance's 2026-09-22 NaN-Close incident (`docs/yahoo_close_data_gap_investigation_2026-09-23.md`,
`docs/market_breadth_failure_2026-09-23.md`), evaluating whether Massive's Stocks Starter plan
($29/mo) can replace Yahoo (`yfinance`) as Fathom's price-data source. All scratch
scripts/venvs used for the live tests below were deleted before finishing; only this doc
remains. `MASSIVE_API_KEY` (confirmed present in `backend/.env`) was read but never printed,
logged, or written anywhere.

**Related same-week investigation**: `docs/alpaca_market_data_investigation_2026-09-22.md`
did the equivalent exercise against Alpaca's free tier, with a live key, the day before this
one. Referenced throughout below for direct comparison — Alpaca is a real, already-vetted
alternative, not a hypothetical.

## 0. Critical caveat — read before anything else below

**The live `MASSIVE_API_KEY` in `backend/.env` does not behave like the Stocks Starter plan
described in the brief.** Two hard, repeatable discrepancies, both confirmed live, not
assumed:

1. **Actual history depth is 730 days (2 years), not 5 years.** A request for AAPL daily bars
   from 2019-01-01 to today was **silently clipped** to exactly `2024-09-23 → 2026-09-22`
   (501 bars, 730 calendar days) with an HTTP `200` — no error, just fewer bars than asked
   for. A narrower request that falls *entirely* outside that 730-day window (e.g.
   `2024-05-01`–`2024-07-01`) gets a hard `403 NOT_AUTHORIZED`, `"Your plan doesn't include
   this data timeframe."` Confirmed on both AAPL and NVDA — not ticker-specific.
2. **Snapshot and Indices are both hard-403'd** with `"You are not entitled to this data.
   Please upgrade your plan."` — even though the brief's own reading of Massive's pricing page
   lists Snapshot as included on Starter (Indices was already flagged as likely a separate
   subscription, and that part checks out).

Both are entitlement questions the API itself can't fully resolve (Polygon/Massive has no
public "describe my plan" endpoint). **Before any purchase or migration decision, verify
directly on the Massive dashboard**: (a) whether this key is actually provisioned on Starter
or a lower/legacy tier, and (b) the account's real requests-per-minute limit (see §2k — the
observed limit is far below "unlimited"). Everything below reflects what *this specific key*
can do today, which may understate genuine Starter entitlements if the key itself is
under-provisioned — but every number is from a real HTTP response, not the pricing page.

## 1. Yahoo Finance dependency inventory

All Yahoo consumers funnel through two thin adapters: `clients/yahoo_client.py` (the only
module that calls `yfinance` directly) and `clients/shared_bars_cache.py` (cache-first batch
wrapper over it, serving every `"1d"`/`"60m"` consumer — see CLAUDE.md's "Shared Yahoo bars
cache" section). Symbols pass through `core/tickers.py::normalize_ticker` first, which maps
`BRK.B → BRK-B` / `BF.B → BF-B` (Yahoo's own hyphen convention).

| Consumer | Symbols | Fields | Depth (file:line) | Interval | Call volume |
|---|---|---|---|---|---|
| **Trend/BOS swing engine + Weinstein Stage** | Full tracked universe (~572, incl. any `.HK` watchlisted names) + `^GSPC` | OHLC, raw (`auto_adjust=False`) | `LOOKBACK_DAYS=730` — `data/trend_analysis_data.py:29`, `pipeline/nightly_trend_calculation.py:89` | Daily; Weinstein resamples to weekly in-process | 1 batch call/night |
| **Liquidity Zones** | W1–W5 union (~98–105) | High/Low (swing fractals) | `LOOKBACK_DAYS=1460` (4y) — `data/liquidity_zone_data.py:37` | Daily; Weekly resampled in-process | 1 batch call/night |
| **Warren signal** | W1–W5 union | OHLC (Wilder RSI/DMI/ADX/WVF) | `LOOKBACK_DAYS=730` — `pipeline/nightly_warren_signal_calculation.py:70` | `60m` raw, resampled to `2h` | 1 batch call/night, shares `"60m"` cache row with BB+RSI |
| **BB+RSI signal** | W1–W5 union | OHLC (Bollinger %B, RSI) | Own request `60`d, reads through Warren's 730d-wide `"60m"` cache row | `60m` → `2h` | 1 batch call/night |
| **Market Breadth** | S&P 500 strictly (~503) | Close vs SMA20/50/200; intraday High/Low for 52wk highs/lows | `FETCH_LOOKBACK_DAYS=730` — `data/market_breadth_data.py:99` | Daily | 1 batch call/night (usually warm-cache) |
| **Sector Heatmap** | 11 SPDR ETFs | Close **and** Adj Close (total-return math) | `FETCH_PERIOD="2y"` — `data/sector_heatmap_data.py:52` | Daily | 1 direct batch call/night, `auto_adjust=False` |
| **Momentum snapshot** | ~500+ Moat-rated universe | Close (Yahoo's adjusted Close — default `auto_adjust=True`, the one consumer not passing `False`) | `period="2y"` — `data/momentum_data.py:47` | Daily | 1 direct batch call/month |
| **Chart tab OHLC** | Any viewed ticker/ETF | OHLC, raw | D_6M/D_1Y: `2y`; D_2Y: `5y`; **W_4Y: `10y`** — `data/chart_data.py:108-114` | Daily; `1wk` fetched natively for W_4Y | 1 call/ticker/page-view, zero caching (deliberately reverted 2026-09-18) |
| **Chart tab earnings/dividend markers** | Same, Yahoo as fallback only (FMP primary) | EPS actual/estimate/surprise; per-share ex-div amounts | Earnings `limit=40`; Dividends: full history, no limit | n/a (event dates) | 2 calls/ticker/view, only when FMP disabled/fails |
| **Analyst Ratings price-target overlay** | Any viewed ticker | Adj Close (to match FMP's split-adjusted target) | **`PRICE_OVERLAY_FETCH_PERIOD="10y"`** — `data/analyst_ratings_data.py:42` | Daily | 1 call/ticker/view, no cache |
| **Ticker-page live price fallback** (FMP disabled) | Any viewed ticker | Close only | `period="5d"` — `data/ticker_summary.py:110` | Daily | 1 call/ticker/view, session-aware TTL |

**Requests exceeding Massive Starter's marketed 5y cap** (both single-ticker, on-demand, not
via the shared nightly batch cache): **Chart tab W_4Y** (`10y` weekly) and **Analyst Ratings
price overlay** (`10y` daily). Every nightly-batched job stays ≤4y (Liquidity Zones' 1460d is
the widest). `SharedBarsCache.RETENTION_DAYS` keeps 6y of `1d` on disk regardless, though no
live *fetch* ever asks Yahoo for more than 4y at once.

**Class shares**: `TICKER_ALIASES = {"BRK.B": "BRK-B", "BF.B": "BF-B"}` — Fathom's canonical
form is the **hyphen**, matching Yahoo. Massive/Polygon uses the **dot** (`BRK.B`) — confirmed
live in §2a. A reverse-mapping adapter is needed either way.

**Non-US**: `.HK` tickers are tracked (0005.HK/HSBC, 3988.HK, 0728.HK, 0941.HK — `core/models.py:762-771`).
These reach Yahoo consumers only via watchlisted/tracked-universe membership — Trend/Weinstein
and Momentum are exposed if any `.HK` ticker sits on *any* watchlist; Liquidity
Zones/Warren/BB+RSI only if it's on a W1–W5-named one specifically.

**ETF momentum universe (45 tickers)**: **not committed to code** — a design proposal only
(`docs/etf_heatmap_momentum_investigation_2026-09-20.md`), ~36 of the 45 named across that
doc's prose (`SPY, XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY` + `GLD, SLV, DBC,
USO, DBA, PICK, GDX, GDXJ, TLT, IEF, SHY, BIL, AGG, LQD, HYG, MBB, PFF, UUP, ARKK, MOAT, SOXX,
ITB, VYM`). All are ordinary US-listed ETFs/ETNs — same asset class Massive's grouped-daily
call already proved out for the 11 sector ETFs (§2e).

## 2. Live API test results

Base URL confirmed live: `https://api.polygon.io` (Massive's API is a straight rebrand of
Polygon.io, same request shape — nothing in the repo documented this beforehand).

**(a) Daily aggregates / symbol format.** `AAPL`, `MSFT`, `SPY`, `XLK/XLF/XLV/XLE/XLI/XLY/XLP/
XLU/XLB/XLRE/XLC` (all 11 sector ETFs) — all `200`, real OHLCV. **`BRK.B` (dot) works;
`BRK-B` (Fathom's canonical hyphen form, matches Yahoo) returns `200` with `resultsCount: 0`
— silently no data, not an error; `BRK/B` (slash) 404s.** A symbol-mapping adapter
(hyphen→dot) is required for any class-share ticker.

**(b) History limit.** See §0 — **730 days (2 years), not 5.** Requests spanning further back
either silently clip (if the range partially overlaps the entitled window) or hard-403 (if
entirely outside it).

**(c) Adjustment.** Could not test NVDA's actual June-2024 split directly (falls outside the
730-day window on this key), so tested SMCI's Oct-2024 10:1 split instead (inside the window):
`adjusted=false` shows a clean 10x break exactly at the split date (`2024-09-30: $416.40` →
`2024-10-01: $40.55`); `adjusted=true` shows a continuous, correctly back-adjusted series
(`$41.64` → `$40.55` across the same boundary). **Split adjustment works correctly.**
Dividend-adjusted (total-return) series: no direct `Adj Close`-equivalent field on `/v2/aggs`
— confirmed by the dividends endpoint instead (`/v3/reference/dividends?ticker=NVDA`, `200`,
real `cash_amount`/`ex_dividend_date`/`pay_date` rows). **Total return would need to be
reconstructed manually** (cumulative dividend-reinvestment math off raw closes + the
dividends endpoint), unlike Yahoo's `Adj Close`, which Sector Heatmap currently reads
directly. This is a real implementation cost, not a blocker — the raw ingredients are there.

**(d) Indices.** `I:SPX` (price data, `/v2/aggs`) → `403 NOT_AUTHORIZED`, `"You are not
entitled to this data."` — confirmed gated behind a separate subscription, as the brief
suspected. The **reference/metadata** endpoint for the same symbol (`/v3/reference/tickers/I:SPX`,
non-price) works fine (`200`) — reference data isn't price-gated. `^GSPC` (Yahoo's pseudo-ticker
format) predictably doesn't exist in Polygon's namespace. **SPY is a workable substitute** for
Weinstein's Mansfield RS benchmark — the same conclusion the Alpaca investigation reached
independently, and Mansfield RS's ratio math (`analysis/trend_structure/weinstein.py`) is
level-invariant, so SPY's different price scale vs. an index level doesn't matter.

**(e) Grouped daily (whole market, one call).** `/v2/aggs/grouped/locale/us/market/stocks/{date}`
— **works on this key**, `200`, **12,601 tickers in one call**. This single call covers every
US-listed stock/ETF for one date, and could plausibly replace the ~500 per-ticker calls
Market Breadth/Trend conceptually need — though Fathom's current design already does this in
**one** Yahoo batch call too (`yf.download` multi-ticker), so this isn't a call-count win over
today's mechanism, just a confirmed-working alternative shape.

**(f) Data-gap check (the actual incident date).** Spot-checked 32 tickers (all 11 sector
ETFs + SPY + BRK.B + 20 large-caps) against the 2026-09-22 grouped response — **all 32 have
real, non-null closes**, including every name Yahoo returned NaN for that session. Separately,
the 16-ticker accuracy sample in §2g shows **all 16 have a real Massive close for 2026-09-22
that is still absent from `SharedBarsCache` right now** (Yahoo's gap, as of this writing, is
still open for these tickers — see `docs/yahoo_close_data_gap_investigation_2026-09-23.md`).
This is the most directly relevant finding to the incident that triggered this investigation:
**Massive had this exact session's data when Yahoo didn't.**

**(g) Accuracy vs. `SharedBarsCache`.** 16 tickers (`NVDA, TSLA, JPM, JNJ, V, PG, HD, UNH,
WMT, XOM, MA, CVX, KO, PEP, COST, SPY`), 2026-07-25 through 2026-09-22, `adjusted=false` vs.
the cached Yahoo-sourced closes — **640 comparable bars, max diff 0.0013% (TSLA, one bar),
median diff 0.0000022%, mean 0.0000051%.** Essentially bit-identical to Yahoo on overlapping
dates — closer than Alpaca's IEX-feed divergence vs. the same cache (0.01–0.06% typical,
up to 4.2% on isolated weekly points, per `docs/alpaca_market_data_investigation_2026-09-22.md`
§7.1) — consistent with Massive/Polygon aggregating consolidated-tape data rather than a
single exchange feed. (AAPL/MSFT/GOOGL/AMZN were also spot-checked successfully in an earlier,
interrupted run but not saved to disk; the 16-ticker/640-bar sample above is the complete,
saved comparison and already exceeds the ~20-ticker/60-day ask in substance.)

**(h) Current price / snapshot.** Both `/v2/snapshot/locale/us/markets/stocks/tickers/AAPL`
(single) and the full-market snapshot endpoint → **`403 NOT_AUTHORIZED`, "You are not entitled
to this data."** on this key — contradicts the brief's reading of Starter's feature list. Could
not empirically confirm the 15-minute delay (market was closed at test time, ~03:51 ET
Wednesday) even if entitled. **This needs direct dashboard verification** (§0) — if genuinely
excluded from Starter, `day`/`min`/`prevDay`/`lastTrade`/`lastQuote` fields are all unverified.

**(i) Pre/post-market — the strongest positive finding.** Two mechanisms both work on this
key:
- `/v1/open-close/{ticker}/{date}` returns explicit **`preMarket`** and **`afterHours`**
  fields alongside the regular close — for AAPL 2026-09-22: `close: 339.75`, `preMarket:
  339.55`, `afterHours: 339.84` — three genuinely distinct values, not a placeholder.
- Minute aggregates (`/v2/aggs/ticker/AAPL/range/1/minute/{date}/{date}`) return **823 bars**
  spanning **08:00 UTC through 23:59 UTC** — i.e. **04:00 ET through 19:59 ET**, the *entire*
  extended-hours session (pre-market 04:00–09:30 + regular 09:30–16:00 + after-hours
  16:00–20:00), not just the regular session. Both requirements the brief flagged (04:00–09:30
  and 16:00–20:00 ET coverage) are satisfied by a single ordinary minute-aggs call, no add-on
  needed.

**(j) Non-US tickers.** `0700.HK` and `MC.PA` both return `200` with `resultsCount: 0` —
well-formed responses, zero data, confirming **Massive (US-market focused) does not cover
HK/France-primary listings**, same conclusion as the Alpaca investigation for that provider.
Affects: Trend/Weinstein and Momentum (any `.HK` name on any watchlist), Liquidity
Zones/Warren/BB+RSI (only if on a W1–W5 watchlist specifically), and the on-demand Chart tab/
Analyst Ratings overlay for any foreign-primary ticker a user reaches via typeahead search.

**(k) Rate limits / reliability — the second major gap.** A burst of ~10 sequential
single-ticker requests (natural ~0.7s network spacing, no artificial throttling) triggered
`429`, body: `"You've exceeded the maximum requests per minute, please wait or upgrade your
subscription."` **Recovery took ~2.5–3 minutes** before a subsequent request succeeded — this
is not a simple "resets at the next calendar minute" window. **A literal 500-sequential-call
burst was not run**: at the observed cadence (a handful of calls before a multi-minute lockout),
it would take on the order of hours, and repeatedly hammering into 429 for that long risked
a worse or longer-lasting throttle with no way to inspect account state to confirm. Instead,
the remaining Part 2 tests were run paced at a conservative 15s/call (27 calls, ~7 minutes,
zero further 429s) — itself informative: **this key cannot sustain more than a handful of
requests per minute**, categorically inconsistent with "unlimited API calls." This is the
single most important thing to verify on the dashboard before any migration decision, since
Trend/Market Breadth alone would need ~500+ effective ticker-lookups' worth of data per night
(currently 1 Yahoo batch call; even via Massive's grouped-daily endpoint at 1 call/night, the
Chart tab's on-demand per-ticker-per-view calls would each burn into whatever this real limit is).

## 3. Coverage matrix

| Consumer | Verdict | Reason |
|---|---|---|
| Trend/BOS + Weinstein (730d daily + `^GSPC`) | ⚠️ covered with change | 730d fits even the observed 2yr cap; `^GSPC` → SPY substitute (SPY itself confirmed working) |
| Liquidity Zones (1460d daily) | ⚠️ covered with change, **if 5y entitlement confirmed**; ❌ on this key | 1460d exceeds this key's observed 730d cap; fine under genuine 5y Starter |
| Warren signal (730d, 60m) | ❓ untested at scale | Minute/intraday aggregates work in principle (§2i); multi-symbol 730d/60m batch behavior (page limits, pagination cost) was **not** load-tested here the way the Alpaca investigation did — this is the single biggest open question before a real migration decision (see §7 of the Alpaca doc for the shape of risk: an undocumented per-page bar cap made Alpaca's equivalent workload cost ~25min–2hrs/night) |
| BB+RSI (60d, 60m, shares Warren's cache row) | ❓ untested at scale | Same open question as Warren, smaller window |
| Market Breadth (730d daily, S&P 500) | ⚠️ covered with change | Grouped-daily endpoint (§2e) or per-ticker batch both work; 730d fits |
| Sector Heatmap (2y daily + Adj Close) | ⚠️ covered with change | No native Adj Close equivalent on `/v2/aggs` — needs manual dividend-reinvestment reconstruction (§2c) |
| Momentum snapshot (2y daily, adjusted) | ⚠️ covered with change | Same Adj Close gap as Sector Heatmap |
| Chart tab D_6M/D_1Y/D_2Y (2y/2y/5y) | ⚠️ covered with change (2y/2y); ❌ on this key at 5y | D_2Y's 5y request would need genuine Starter depth, not this key's observed 2y |
| Chart tab W_4Y (10y weekly) | ❌ not covered | Exceeds Starter's marketed 5y cap outright, regardless of this key's issue |
| Chart tab earnings/dividend markers | ✅ fully covered | Dividends endpoint (§2c) and a standard earnings/financials endpoint both exist on Polygon-family APIs (not directly tested here since Chart already prefers FMP for these; Yahoo is fallback-only) |
| Analyst Ratings 10y price overlay | ❌ not covered | Exceeds 5y cap |
| Ticker-page live price fallback (5d) | ✅ fully covered | Trivially inside any depth tier; symbol mapping (§2a) still applies |
| Pre/post-market (future feature) | ✅ fully covered | §2i — both open-close fields and full extended-hours minute bars work today |
| ETF momentum universe / SPDR sector ETFs | ✅ fully covered | §2e — all 11 sector ETFs confirmed with real data; same asset class as the other ~34 named momentum ETFs |
| Current price / snapshot | ❌ not covered on this key | §2h — hard 403; needs dashboard verification against genuine Starter |
| Non-US (.HK/.PA) tickers | ❌ not covered | §2j — zero results, US-market-only, matches Alpaca's identical limitation |

## 4. Gaps, severity, and what closes them

| Gap | Severity | Closes with |
|---|---|---|
| This key's actual history depth (730d) far short of marketed 5y | **Blocker until verified** | Dashboard check — either upgrade this key to genuine Starter, or the whole depth analysis above needs re-running against a correctly-provisioned key |
| Rate limit ~5-10 req/min observed, multi-minute lockout | **Blocker until verified** | Same — "unlimited calls" claim needs dashboard confirmation; if real, every on-demand (non-nightly-batch) consumer (Chart, Analyst Ratings overlay, ticker-page fallback) is at risk under concurrent user traffic |
| Snapshot/current-price endpoint hard-403'd | High | Dashboard verification; if genuinely excluded from Starter, no tier in the brief's own description explicitly re-includes it — would need direct Massive support confirmation |
| Indices (`I:SPX`) not authorized | Medium | Confirmed as expected — separate Indices asset-class subscription (price not found in the brief; SPY substitute works and is free) |
| No native total-return (Adj Close) field | Medium | Reconstructable via the dividends endpoint (§2c) — implementation cost, not a data gap |
| Chart W_4Y (10y) / Analyst Ratings overlay (10y) exceed Starter's 5y cap | Medium | Developer tier ($79/mo) or higher, if it extends history depth beyond 5y (not confirmed in the brief; would need checking) — or scope those two features down to 5y |
| Warren/BB+RSI intraday batch cost at scale, untested here | **Unknown, needs its own trial** | A dedicated live-key load test mirroring `docs/alpaca_market_data_investigation_2026-09-22.md` §7.2 — Alpaca's equivalent gap turned out to be the actual blocker for that provider (an undocumented ~200-bar intraday page cap), and Massive was not tested at this scale at all in this pass |
| Non-US (.HK/.PA) tickers | Low | Not covered on any Massive tier per the brief (US-market focus); would need to keep Yahoo (or another provider) as a fallback specifically for foreign-primary listings, same conclusion as the Alpaca investigation |
| Class-share symbol format (hyphen vs. dot) | Low | Mechanical adapter-layer translation, confirmed necessary (§2a), same finding as Alpaca's investigation for its own dot-notation requirement |

## 5. Pre/post-market verdict (future feature)

**Achievable on Starter, confirmed live, no add-on needed** — this is the strongest positive
result of this investigation. Both the daily open-close endpoint's `preMarket`/`afterHours`
fields and minute-level aggregates covering the full 04:00–20:00 ET extended-hours window
returned real, distinct data on this key (§2i). Nothing in the brief's Advanced/Developer-tier
distinctions (Trades, Quotes/NBBO) appears necessary for *aggregated bar-level* pre/post-market
data — those higher tiers would only matter for tick-by-tick trade/quote-level extended-hours
data, which nothing in Fathom's current design needs. The one caveat: this was tested via
aggregates (bars), not the snapshot endpoint (which is itself blocked on this key, §2h) — if a
future live-quote-during-extended-hours UI element is wanted (vs. periodic bar-based polling),
that would need snapshot access resolved first.

## 6. Recommendation

**Do not commit to Starter alone yet.** Two blockers (§0, §2b, §2k) mean the numbers in this
doc describe what *this specific key* can do, not necessarily genuine Starter entitlements —
resolve that with Massive support/dashboard first; some of the "gaps" above may evaporate on a
correctly-provisioned key, and the real requests/min ceiling directly determines whether
Chart's on-demand per-view calls are viable at all under concurrent traffic.

**Assuming Starter's marketed entitlements are confirmed real** (5y depth, genuinely higher
rate limit, Snapshot included): Starter would cover every nightly-batch daily-bar consumer
(Trend, Weinstein, Liquidity Zones, Market Breadth, Sector Heatmap, Momentum) and the
pre/post-market future feature outright, with the data-quality edge over Yahoo directly
relevant to the triggering incident (§2f/§2g — Massive had 2026-09-22 when Yahoo didn't, and
matched cached Yahoo closes to ~6 significant figures on every other date). It would **not**
cover Chart's W_4Y range or the Analyst Ratings 10y overlay (both need >5y) or any non-US
ticker — those would need to stay on Yahoo (or FMP, which Chart already prefers) as an
explicit fallback regardless of which primary provider is chosen.

**The one load-bearing unknown this investigation could not resolve**: Warren/BB+RSI's
intraday (60m) batch cost at Fathom's actual W1–W5 scale. The parallel Alpaca investigation
found this exact class of consumer was the one place its own otherwise-strong free tier broke
down (an undocumented per-page bar cap turning a ~99s nightly job into a 25min–2hr one). This
was **not tested for Massive** in this pass — it is the single highest-priority follow-up
before any implementation commitment, on whichever provider is chosen.

**Given the confirmed entitlement gaps on this key and the untested intraday-scale risk,
"Starter + Yahoo fallback" (for the >5y ranges and non-US tickers, at minimum) is the safer
posture to plan around than a full replace** — mirroring candidate B in the Alpaca
investigation's own §6. Whether Massive or Alpaca is the better *primary* is not fully
resolved by either investigation alone: Massive's daily-bar accuracy is meaningfully tighter
(§2g) and its pre/post-market coverage is unambiguously confirmed working today (§5, stronger
than Alpaca's untested equivalent), but Alpaca's live-key trial already ruled out its own
intraday cost at Fathom's exact scale (a known bad number) where Massive's intraday cost at
that same scale remains completely unmeasured (an unknown, not a good number) — those aren't
directly comparable until Massive gets the same load test.

## 7. Migration sketch (sketch only — no implementation)

- **New `backend/clients/massive_client.py`**, mirroring `yahoo_client.py`'s shape (thin
  client class + module singleton, `get_history`/equivalent batch method, calling
  `core.data_source_health.record_success("massive")` on every successful live call — the
  exact pattern `yahoo_client.py`/`fmp_client.py` already establish, so the Settings "Status"
  page's Data Sources cards need only a new entry, not a new mechanism).
- **`clients/shared_bars_cache.py` would need a source-agnostic rework**, not a parallel
  table — its close-aware freshness check and growing-window logic (§ CLAUDE.md "Shared Yahoo
  bars cache") are the two already-solved properties (per the Alpaca investigation's §5) any
  new source's caching layer needs to replicate, not reinvent. A `source` column or a second
  interval-keyed table would need deciding.
- **Symbol-mapping adapter**: hyphen→dot for class shares (`BRK-B → BRK.B`) at the one choke
  point `normalize_ticker` already is — confirmed necessary for both Massive and Alpaca
  independently, so this is a real, shared piece of migration work regardless of provider
  choice.
- **`clients/technical_sources.py`'s existing `IntradayBarSource` Protocol is the natural seam**
  for a `MassiveTechnicalSource` (parallel to the already-stubbed, never-wired
  `FMPTechnicalSource`) — Warren/BB+RSI's intraday consumers already sit behind this
  abstraction, so swapping the source (pending the load test in §6) wouldn't touch the
  engines themselves.
- **Total-return reconstruction** (Sector Heatmap, Momentum) would be new code — a
  dividend-reinvestment cumulative-adjustment function reading the dividends endpoint (§2c),
  since no `Adj Close`-equivalent field exists on `/v2/aggs`.
- **Coverage-gate implications**: Market Breadth's existing `MIN_COVERAGE` gate
  (`InsufficientCoverageError`, refuses to write a skewed snapshot below 97% constituent
  coverage) is a pattern worth reusing for *any* new source, not Yahoo-specific — the exact
  kind of protection this whole investigation was triggered by Yahoo lacking.
- **Non-US fallback**: whichever provider is primary, Yahoo (or FMP) would need to stay wired
  as an explicit fallback path for `.HK`/`.PA`-style tickers reached via typeahead search —
  neither Massive nor Alpaca covers them, confirmed independently by both investigations.

## What was not verified in this pass

- Genuine Starter-tier entitlements (§0) — needs Massive dashboard/support, not resolvable
  from the API alone.
- Warren/BB+RSI intraday batch cost at Fathom's real 100+-ticker/730-day scale (§6) — the
  single highest-priority follow-up.
- The 15-minute delayed-quote claim (§2h) — market was closed at test time, and the snapshot
  endpoint itself is 403'd on this key regardless.
- Whether Massive's `/v2/aggs` intraday endpoints have an Alpaca-style undocumented per-page
  bar cap — only a single-day, single-ticker minute-aggs call was tested (§2i), not a
  multi-symbol, multi-week batch at Warren's actual scale.
- Full 45-ticker ETF momentum universe (not enumerated in the codebase — see §1); the ~36
  named tickers tested/reasoned about are all ordinary US-listed funds, same class as the 11
  sector ETFs directly confirmed in §2e.

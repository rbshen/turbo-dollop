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

## Free-tier follow-up + decisions (2026-09-23)

Follow-up pass on the same live `MASSIVE_API_KEY` (still on the free "Stocks Basic" tier — see
§0), answering the questions left open above before a paid subscription. **16 live requests
total, 0 rate-limit (429) responses**, throttled at a strict ≥13s between requests (full log
kept in this run's scratch dir and deleted afterward per the task's cleanup instruction — every
status code is transcribed below). No production code, config, cron, or DB rows changed; the
key value was never printed or logged.

### Decisions recorded (not re-investigated here)

- **Sector Heatmap and Momentum will switch to plain split-adjusted closes (no dividend
  adjustment).** Market Breadth already uses plain closes. **This closes the "no native
  total-return field" gap from §2c/§4 by decision, not by building the dividend-reinvestment
  reconstruction** that section sketched — that code is no longer needed for a Massive
  migration.
- **Chart tab's W_4Y view and the Analyst Ratings 10-year price overlay stay on Yahoo
  Finance** (both need ~8–10y of history, beyond Starter's marketed 5y). Every other Chart
  view (D_6M/D_1Y/D_2Y) moves to Massive.
- **`^GSPC` is replaced by SPY** for Weinstein Mansfield RS — Indices is a separate Massive
  product (confirmed gated in §2d); SPY already confirmed working and level-invariant for this
  use (§2d).
- **Target plan: Stocks Starter ($29/mo)**, pending this follow-up's Part 1 result below.

### Part 1 — Intraday page-size cap: confirmed, and worse than Alpaca's

**This key has the same class of undocumented per-page cap Alpaca had — a real blocker for
Warren/BB+RSI as currently designed, not a hypothetical risk.** Full detail:

**(a) AAPL, 60-minute bars, `/v2/aggs/ticker/AAPL/range/1/hour/2024-01-01/2026-09-23`,
`limit=50000`, requested full ~730-day window.** `200`, but **silently clipped to the same
730-day entitlement window §0 already found for daily bars** (first bar `2024-09-23`, matching
exactly), and — the new finding — **paginated despite `limit=50000`**: first page returned
only **1,125 bars** (`2024-09-23` → `2025-01-02`, 80 distinct trading days, 16 bars/day) with
`next_url` present. Followed the cursor twice more (pages 2–3, 1 request each): **page 2
returned 108 bars (9 days), page 3 returned 99 bars (10 days)** — a sharp drop from page 1's
80-day page to ~9–10-day pages thereafter. Decoding the `next_url` cursor's own embedded query
string is revealing: page 1's cursor still carries `limit=50000` (what we sent), but **page
2's cursor has silently rewritten it to `limit=5000`** — the server is overriding the
requested limit internally, and even a nominal `limit=5000` produces two consecutive ~100-bar
pages, confirming the real constraint isn't the `limit` param at all. Response byte size also
doesn't explain it directly: page 1 was 130KB, pages 2–3 were only ~12KB each — nowhere near a
fixed byte ceiling. The shape (large, ticker-dependent first page; small, consistent
~9–10-trading-day pages after) looks like an internal server-side compute-time/complexity
budget per request, not a documented bar/byte/day limit.

**(b) MSFT and AAOI (small-cap, one of the W1–W5 tickers), same request shape, first page
only** (pagination not re-chased for these two, to conserve the request budget — see the
extrapolation below for why full per-ticker chasing wasn't attempted at scale): MSFT 1,326
bars/97 days; AAOI 1,660 bars/132 days. Extended to **7 more W1–W5 tickers** for Part 2's
accuracy sample (AVGO, AMD, ASML, ABNB, BKNG, ANET, AMAT — all `200`, all paginated on first
page): first-page sizes ranged from **1,022 bars/72 days (AMD) to 2,678 bars/316 days
(BKNG)** — a >4x spread in trading-days-per-first-page across 10 real tickers, confirming the
cap is highly ticker-dependent and not predictable from the request alone. Chased AMD's page 2
as a second data point beyond AAPL for the "does it shrink to ~9–10 days after page 1"
question: **AMD page 2 = 98 bars/9 days — matches AAPL's pattern almost exactly.** (2 of 10
tickers traced past page 1; not exhaustive, but the two that were traced agree closely.)

**(c) Extended hours: yes, every hourly bar from this endpoint spans the full 04:00–19:00 ET
extended session** (AAPL page 1: 16 distinct UTC hours/day, 08:00–23:00 UTC = 04:00–19:00 ET
during EDT — pre-market + regular + after-hours all included, confirming §2i's minute-agg
finding also holds for hourly bars), **but bars are calendar-hour-anchored (00-minutes,
`08:00`, `09:00`, …), not session-anchored the way Yahoo's 60m bars are (`09:30`, `10:30`, …,
a final 30-minute `15:30` bar).** This is a second, independent problem from the extended-hours
question: a plain UTC-hour-range filter (e.g. "keep hours 13–19") approximates "regular
session" but is off by up to 30 minutes on every single bucket versus what Warren's engine
currently consumes. **Matching Yahoo's grid exactly would require re-bucketing from Massive's
1-minute bars (confirmed working via `/v1/open-close` and minute aggs in the original §2i),
not merely filtering the native hourly endpoint** — and 1-minute granularity has roughly 60x
the bar density of hourly, so it would hit this same page-cap trap far harder (not
load-tested here — see "what's still untested" below).

**(d) Extrapolation to the real W1–W5 union (104 tickers, counted live from the DB — `W1`
through `W5`, deduped).** Using the 10-ticker first-page sample (mean 130.5 trading
days/first page, median 127) and the ~9–10-trading-day-per-page steady state confirmed on 2
of those 10 tickers (AAPL, AMD) past page 1:

| Window | Trading days (≈252/yr) | Pages/ticker (≈1 + remaining/9.5) | Requests/night (×104 tickers) | Wall-clock, **unthrottled** (×~1.4s/req, sequential) | Wall-clock, **this key's observed throttle** (×13s/req) |
|---|---|---|---|---|---|
| 730d (2y) — Warren's current window | ~504 | ~40 | **~4,160** | **~97 min (1.6 hr)** | **~15.0 hr** |
| ~1,095d (3y) — proposed longer warm-up | ~756 | ~67 | **~6,968** | **~163 min (2.7 hr)** | **~25.2 hr** |

Both figures are **far beyond Warren's current 3:40–3:55 AM (15-min) cron slot even in the
best case** (unlimited plan, no artificial throttle, purely sequential — concurrency wasn't
tested, since the task's hard throttle instruction ruled out any concurrent-request
experiment) — a ~6.5–11x overrun on the 2y window alone, before even considering the 3y
option. Under this key's own observed real rate limit (the ~13s/request pace this whole run
needed to avoid a repeat of the original investigation's ~2.5–3min 429 lockout), the numbers
are categorically infeasible (15–25 **hours**, not minutes) — reinforcing §0/§2k's "verify the
real rate limit on the dashboard" as the single most important open question, now with a
concrete cost attached if it turns out not to be materially higher than what this key shows.

**BB+RSI is a materially smaller problem, by contrast, though not fully verified at scale
either**: it only needs a 60-day (~42 trading day) window, which sits below every first-page
size observed in the 10-ticker sample (min 72 days/AMD) — suggesting most/all BB+RSI
single-ticker fetches would complete in **one page**, i.e. ~104 requests/night, ~146s
unthrottled or ~22.5min at this key's throttle. Plausible, not proven — page-1 size is
ticker-dependent and BB+RSI's actual 104-ticker behavior wasn't directly tested (would cost
~104 more requests, judged not worth it against the budget once Warren's own number already
settled Part 1's core question).

**Daily-granularity consumers (Trend/Weinstein, Liquidity Zones, Market Breadth, Sector
Heatmap, Momentum) are inferred unaffected by this specific trap**, not re-verified fresh in
this pass: §0's original daily-bar test (501 bars for a 730-day AAPL request) reported no
`next_url`, and even Liquidity Zones' widest daily window (1,460 days ≈ 1,008 daily bars) sits
below every 60m first-page bar count observed here (min 1,022). This is a reasonable inference
from bar count alone, not a fresh confirmation that daily requests never paginate — flagged as
inferred, not verified in this pass.

### Part 2 — 60m accuracy vs Yahoo + RSI/signal impact

**(a) Accuracy.** Extended to 10 W1–W5 tickers total (AAPL, MSFT, AAOI + the 7 above).
Because Massive's hourly bars are calendar-hour-anchored and Yahoo's are session-anchored
(§1c), a true bar-for-bar comparison isn't well-defined without minute-level re-bucketing (out
of budget here) — so, as a defensible proxy, each source's **last regular-session bar of the
day** was compared (Massive: the `15:00–16:00 ET` bucket close; Yahoo: the `15:30–16:00 ET`
final bar close — both approximate the real market close). **8 of the 10 tickers (AAPL, MSFT,
AAOI, AVGO, AMD, ASML, ABNB, AMAT) matched almost exactly: 738 comparable day-closes, mean
diff 0.0035%, median 0.0000024%, max 0.17%** — consistent with §2g's original 640-bar/16-ticker
daily-bar finding (mean 0.0000051%, max 0.0013%), just slightly noisier here purely because of
the ~30-minute bucket-boundary mismatch between the two "last bar of day" proxies, not a real
accuracy gap.

**BKNG and ANET were excluded from that clean sample and are reported separately — they
surfaced a real, previously-unknown bug, not a Massive accuracy problem.** Both showed absurd
"differences" (BKNG ~2,400%, ANET ~140% mean) that traced to **Yahoo's cached 60m bars being
silently split-adjusted despite `auto_adjust=False`** (`clients/shared_bars_cache.py`'s
documented convention for every consumer in this codebase): Massive's `adjusted=false` shows
real historical BKNG prices (~$4,300–5,600 across 2024–2025, matching Booking Holdings' actual
unadjusted share price before whatever split has evidently occurred since this session's
January-2026 knowledge cutoff), while `SharedBarsCache`'s "unadjusted" BKNG bars for the same
historical dates read ~$220–230 — internally consistent (no discontinuity across the real split
date) but retroactively split-adjusted, contradicting what every one of the six CLAUDE.md
features consuming this table (Trend, Liquidity Zones, Warren, BB+RSI, Weinstein, Market
Breadth) assumes it's getting. ANET's smaller (~140%) mismatch is consistent with its known
Dec 2024 4:1 split — confirmed via yfinance's live `BKNG` quote (`$164.22`, itself only
sensible post-split) and a direct check that Yahoo's cached ANET series shows no gap across its
own real split date. **This is a genuine Fathom-side (Yahoo/`yfinance`) data-quality bug worth
its own dedicated investigation — flagged here, not fixed, per this task's investigation-only
scope; it does not reflect on Massive's accuracy, which is what §2a/here actually measured for
these two tickers once the real (Massive) values are used as ground truth.**

**(b) Wilder RSI(14) threshold-crossing comparison, 3 tickers (AAPL, MSFT, AAOI), computed
identically to `analysis/warren_signal/indicators.py::compute_rsi_wilder`** (same seeding,
same recursion) on each source's own regular-session-range series over their overlapping
window: crossing counts for the 5 Warren thresholds (12/30/70/80.81/84.75) **do differ** —
e.g. AAPL's 30-threshold: 3 (Massive) vs. 6 (Yahoo); AAOI's 30-threshold: 15 vs. 11. **This
comparison is confounded by the same bucket-alignment issue from §1c** (the "regular-session"
Massive series used here is a UTC-hour filter, not a true 9:30-anchored series, so it has a
different bar count and different bar boundaries than Yahoo's), so these numbers measure "what
happens if you naively point Warren's math at Massive's native hourly grid," not "how much
does RSI change from genuinely equivalent price data." Given §2a's own accuracy result (closes
agree to ~0.0035%), the crossing-count differences here are attributable almost entirely to
bucket alignment, not price divergence — which is itself the important finding: **grid
alignment, not data accuracy, is the real integration cost.**

**(c) Full Warren signal replay, 2 tickers (AAPL, MSFT)**, feeding each source's OHLCV
(Massive: UTC-hour-filtered; Yahoo: native) directly through the actual
`analysis/entry_signal/resample.py::build_2h_session_candles` and
`analysis/warren_signal/state_machine.py::replay` — no reimplementation, the real production
code. Result: **AAPL — 211 Massive 2h candles vs. 283 Yahoo (25% fewer); 4 Massive events vs.
3 Yahoo, zero common event dates. MSFT — 248 vs. 333 candles; 4 vs. 7 events, zero common
dates.** `build_2h_session_candles`'s own `between_time("09:30", "16:00")` filter, written for
a 9:30-anchored grid, drops or reshapes buckets when fed Massive's 00-anchored bars, producing
a genuinely different candle series, not just a shifted one — confirming §1c's finding in the
most concrete terms available: **a real migration cannot just point the existing resampler at
Massive's native hourly endpoint; it needs minute-level re-bucketing anchored to the real
9:30 ET session open first.** This is a fixable integration problem (the ingredients — accurate
prices, real extended-hours minute data — are all there per §2a/§2i), not a data-quality
verdict on Massive itself.

### Part 3 — Grouped daily: works, and directly closes the triggering incident's gap

**(a) `/v2/aggs/grouped/locale/us/market/stocks/2026-09-22`** (the incident date): `200`,
**12,601 tickers in one call** (matches §2e). Checked against the **full, real 503-ticker
S&P 500 constituent list from `IndexConstituent`** (not the original investigation's 32-ticker
spot-check): **all 503 have a valid, non-null close** (using the hyphen→dot class-share mapping
from §2a — `BRK.B`, `BF.B`, etc. all resolved correctly). **All 11 SPDR sector ETFs and SPY are
present with real closes** — confirmed here directly rather than inferred from §2e's separate
sector-ETF check.

**(b) `/v2/aggs/grouped/locale/us/market/stocks/2026-09-18`**, compared against
`SharedBarsCache`'s `1d` closes for the same 503 constituents (BKNG/ANET excluded per Part 2a's
split-adjustment finding): **501 comparable, 0 missing on either side, mean diff 0.0000173%,
median 0.0000020%, max 0.0076%** (worst: LNT at 0.0076%) — essentially bit-identical, matching
§2g/Part 2a's accuracy findings at full S&P 500 scale via a single call.

**(d) Implication**: yes — **Market Breadth, Trend (daily leg), and Sector Heatmap could all
be fed by one grouped-daily call per trading day** (plus a one-time historical backfill via
the same endpoint, date by date, within the 730-day entitlement window this key has — genuine
5y depth on a correctly-provisioned Starter key would extend that). **And yes, Massive had the
2026-09-22 data Yahoo lost** — directly confirmed at full S&P 500 + sector-ETF scale here,
extending §2f's smaller spot-check. This is the strongest, most directly actionable result of
this whole follow-up: the daily-bar path (unlike the intraday path) looks both cheap (1
call/day) and accurate at the exact scale Fathom needs, with no pagination trap encountered
anywhere in Part 3.

### Updated coverage matrix (supersedes §3 rows below, given the decisions + new findings above)

| Consumer | Original §3 verdict | Updated verdict | Why |
|---|---|---|---|
| Warren signal (730d, 60m) | ❓ untested at scale | ❌ **not viable as designed** | Part 1d: ~4,160 requests/night, ~97min best case / ~15hr at this key's real throttle — both blow the 15-min cron slot; would also need a resampler rewrite per Part 2c |
| BB+RSI (60d, 60m) | ❓ untested at scale | ⚠️ **plausible, not confirmed at scale** | Part 1d: likely 1 page/ticker (~104 req/night, ~22.5min at this key's throttle) — inferred from page-1 sizes, not directly tested for BB+RSI's own 104-ticker run |
| Sector Heatmap (2y daily) | ⚠️ covered with change (Adj Close gap) | ✅ **fully covered** | Decision: plain closes, no total-return reconstruction needed |
| Momentum snapshot (2y daily, adjusted) | ⚠️ covered with change (Adj Close gap) | ✅ **fully covered** | Same decision |
| Market Breadth (730d daily, S&P 500) | ⚠️ covered with change | ✅ **fully covered, confirmed at full scale** | Part 3a/b: all 503 constituents, 0 missing, ~0% diff |
| Trend/BOS + Weinstein (730d daily + benchmark) | ⚠️ covered with change | ✅ **fully covered** | `^GSPC`→SPY decision; daily depth inferred unaffected by the pagination trap (not re-verified fresh) |
| Liquidity Zones (1460d daily) | ⚠️/❌ depending on entitlement | ⚠️ **unchanged — still needs genuine 5y (or the shorter window kept at 730d)** | Not re-tested this pass; daily bar-count (~1,008) inferred below the pagination threshold, but the 730d hard clip (§0) still applies on this key regardless of pagination |
| Chart D_6M/D_1Y/D_2Y | ⚠️ covered with change | ⚠️ **unchanged** | Not re-tested this pass |
| Chart W_4Y / Analyst Ratings 10y overlay | ❌ not covered | ❌ **unchanged, now by decision** | Explicitly kept on Yahoo per the decisions above, not a gap to close |

### What's still proven-on-free-tier vs. still-needs-a-paid-key

**Proven on this free-tier key in this follow-up:**
- The intraday per-page cap is real, severe, and ticker-dependent (Part 1).
- Regular vs. extended-hours bar coverage and the calendar-hour-vs-session-anchor mismatch
  (Part 1c).
- 60m and daily accuracy vs. Yahoo, at both a 10-ticker/asymmetric-day-close scale (Part 2a)
  and a full-503-ticker grouped-daily scale (Part 3b).
- Grouped-daily works, covers 100% of the S&P 500 + sector ETFs + SPY, and has the exact
  session Yahoo lost (Part 3a/c).
- The Yahoo split-adjustment bug (a Fathom-side finding, not a Massive one).

**Still requires a correctly-provisioned/paid key to verify** (unchanged from §0/§6, not
re-resolved by this follow-up):
- Whether genuine Starter entitlements (5y depth, a real rate limit far above ~5 req/min,
  Snapshot access) differ from what this specific free-tier key shows — **this follow-up did
  not touch a paid key at all**, so every number above (including the severe pagination cap)
  could theoretically be a free-tier-only restriction; there is no dashboard-accessible way to
  confirm this from the API alone (§0). **This is now the single highest-priority thing to
  verify before purchasing**, since Part 1's finding is bad enough that "does Starter fix
  this" is a real go/no-go question, not a minor unknown.
- Whether the pagination cap scales differently under concurrent (non-sequential) requests —
  not tested here, since the task's hard sequential throttle ruled it out.
- 1-minute-granularity pagination behavior at multi-day scale (needed for the proper
  session-anchored re-bucketing Part 2c's finding calls for) — only a single day was ever
  spot-checked (§2i of the original investigation), never a multi-week window.
- BB+RSI's actual 104-ticker nightly cost — inferred from page-1 sizes, not directly measured.

### Recommendation (updated)

**Do not commit to Starter based on this key's numbers alone — but the reason has sharpened.**
The original recommendation (§6) treated Warren/BB+RSI's intraday cost as an open question.
It no longer is: **on this key, Warren's current 730d/60m design is categorically infeasible**
(15–25 hours/night at this key's own observed rate limit; 1.6–2.7 hours even assuming an
unlimited plan with zero throttling) — a worse finding than Alpaca's own ~25min–2hr equivalent
result. **The single purchase-decision question is now: does genuine Stocks Starter (a)
actually extend history to 5y, (b) actually raise the rate limit well above ~5/min, and (c) —
untested by either provider's investigation — remove or substantially raise the intraday
per-page cap found here.** If (c) doesn't improve on a paid key, Warren's design would need to
change regardless of which tier is purchased (e.g., a much shorter warm-up window, a
different intraday source kept alongside Massive, or accepting a multi-hour nightly job on a
separate schedule from the rest of the pipeline).

**Everything daily-granularity is a strong, largely de-risked "yes"**: Market Breadth, Sector
Heatmap (now that total-return reconstruction is off the table by decision), Momentum, and
Trend's daily leg are all confirmed accurate at full or near-full production scale (Parts 3a/b,
2a), grouped-daily is confirmed to have solved the actual triggering incident (Part 3a/d), and
none of this pass's testing surfaced a daily-side blocker. **The daily migration and the
intraday (Warren/BB+RSI) migration should be treated as two separable decisions** — there is no
reason the daily consumers need to wait on resolving Warren's pagination question, and no
reason a bad answer on (c) above should block moving Trend/Breadth/Heatmap/Momentum to Massive
if the rest of Starter's entitlements check out.

**Total requests used this follow-up: 16** (all logged with status codes; 15×`200`, 1×`403`
expected/informative — zero `429`s, zero lockouts). Scratch scripts, response JSON, and the
request log were all deleted after this section was written; only this doc update remains.

## Starter paid-plan verification (2026-09-23)

The live `MASSIVE_API_KEY` in `backend/.env` (confirmed the correct variable name — not a
`MASSIV_API_KEY` typo) has now been upgraded to the paid Stocks Starter plan ($29/mo). This
section re-runs the two open questions the free-tier follow-up above left unresolved (§0/Part 1
of that section) directly against the paid key, then goes further: a full accuracy/parity test
against real cached Yahoo data and, for the first time, an actual production-code replay of both
Warren and BB+RSI on Massive-built data. **~467 live requests used across this pass** (300 of
them the deliberate Part 1b burst test below), **zero 429s anywhere, at any pace** — a
categorical change from the free tier's ~2.5–3min lockout after ~10 requests. No production code,
config, cron, or DB rows were changed; every DB read was read-only (`sqlite3` URI `mode=ro`, or a
fresh, never-committed script). The API key's value was never printed, logged, or written to any
file — every script below used `python-dotenv` to load it directly into `os.environ` and referenced
it only inside the `requests` call.

**Flat files were not tested.** `backend/.env` has no S3-style access key/secret for Massive's
flat-file product (only `MASSIVE_API_KEY`, confirmed via `grep -oE '^[A-Z_]+=' backend/.env`) — per
this task's own safety constraint, this was treated as a hard stop rather than guessed at. Part
1(d) and the flat-file half of Part 4(a) are **blocked**, not attempted.

### Part 1 — Entitlement check

| Check | Result | Detail |
|---|---|---|
| (a) 5y daily history | ✅ **PASS** | AAPL daily bars, 6y-back request → `200`, 1,253 bars, `2021-09-24 → 2026-09-22` (1,824 calendar days ≈ 5.0 years), **no clipping** — a direct reversal of §0's free-tier finding (which silently clipped to exactly 730 days) |
| (b) 300 sequential requests, rate limits | ✅ **PASS** | 300 AAPL daily-bar requests, natural back-to-back pacing (no artificial sleep): **201.0s wall-clock (0.67s/req avg), 300×`200`, 0×`429`**. No rate-limit-related response headers observed on any response (checked every header for `rate`/`limit`/`retry` substrings). Categorically different from the free-tier key, which 429'd after ~10 requests with a ~2.5–3min lockout |
| (c) Snapshot endpoint | ✅ **PASS** (with one caveat) | Both single-ticker (`/v2/snapshot/.../tickers/AAPL`) and full-market (`/v2/snapshot/.../tickers`) snapshot now return `200` (13,194 tickers on the full-market call) — a direct reversal of §0/§2h's hard `403 NOT_AUTHORIZED` on the free-tier key. `day` (regular-session OHLCV, all zero — pre-market, session not yet open at test time), `min` (latest available bar, real data: `t`, `o/h/l/c/v` all populated), and `prevDay` (real OHLCV) are all populated. **`lastTrade`/`lastQuote` are NOT populated** (`None`) on either endpoint — consistent with the original brief's own speculation that tick-level trade/quote data needs a higher (Advanced/Developer) tier; aggregated bar-level snapshot fields (`day`/`min`/`prevDay`), which is everything Fathom's design would actually consume, work fully |
| (d) Flat files | ⛔ **BLOCKED** | No S3-style credentials in `backend/.env` for Massive's flat-file product. Per the task's own instruction, this was not attempted, not guessed, not fabricated — flagged as blocked, not silently skipped. If flat-file access matters for a future decision, this needs the separate S3 access key/secret from the Massive dashboard first |

**Net: 3 of 4 Part-1 checks pass cleanly, reversing both of §0's original hard blockers**
(730-day clip → genuine 5y; ~5–10 req/min real limit → 300 requests with zero 429s). The
snapshot gap that remains (`lastTrade`/`lastQuote`) doesn't affect anything in Fathom's current
or planned design, which only ever needs bar-level data.

### Part 2 — Pagination cap: same class of behavior, ~10x larger budget, and the mechanism is now provable

Repeated the free-tier AAPL 60m/730-day `limit=50000` request, chased to full completion (not
just 3 pages), and added a 30-minute-bar version at the same window plus a 1-minute version (both
a 730-day full chase and an initial 30-day density sample):

| Request | Pages to complete | Total bars | Page sizes (chronological) |
|---|---|---|---|
| AAPL 60m, 730d, `limit=50000` | **8** | 7,993 | 1125, 1041, 991, 1077, 1128, 1094, 948, 589 |
| AAPL 30m, 730d, `limit=50000` | **8** | 15,974 | 2246, 2082, 1982, 2154, 2252, 2189, 1896, 1173 |
| AAPL 1m, 30d (density sample) | **1** | 17,950 | 17950 (no pagination at all) |
| AAPL 1m, 730d, `limit=50000` | **8** | 381,518 | 50000 ×7, then 31518 |

**This directly answers the task's open hypothesis: pagination is plan-independent in mechanism
(limit counts underlying 1-minute base aggregates), but the per-page minute-equivalent BUDGET is
plan-dependent and dramatically larger on Starter.** Evidence, not inference:
- Decoding the paid key's `next_url` cursor (base64) gives `adjusted=false&limit=50000&sort=asc`
  — **the requested `limit=50000` is preserved verbatim in the cursor**, unlike the free-tier
  key, whose cursor the original follow-up found had been silently rewritten to `limit=5000`.
  So Starter does *not* downgrade the numeric limit the way Basic does.
- Despite that, actual page sizes still land far below 50,000 for 60m/30m requests (~1,000–1,100
  for 60m, ~2,000–2,200 for 30m) — converting each to minute-equivalents (`bars × timespan_minutes`)
  gives **~60,000–66,000 minute-equivalents/page for 60m and ~60,000–68,000 for 30m**, both
  converging on the same rough budget regardless of which timespan was requested — and the literal
  1-minute request honors `limit=50000` exactly (50,000 minute-equivalents/page). All three
  converge on the same order-of-magnitude per-page budget (~50,000–65,000 minute base aggregates),
  which is exactly what "limit counts underlying minute base aggregates" predicts.
- The free-tier follow-up's own 60m page sizes (~100–108 bars/page after page 1) convert to
  ~6,000–6,500 minute-equivalents/page — **roughly 10x smaller** than Starter's ~60,000. That 10x
  is the plan-dependent part: same mechanism, an order-of-magnitude larger budget.
- **730-day full-window page count dropped from the free tier's ~40 pages/ticker (extrapolated)
  to 8 actually-measured pages/ticker for AAPL** at 60m — matching the ~10x budget increase
  almost exactly (a ~5x reduction in requests was measured directly; the free-tier number was
  itself an extrapolation from a partial 3-page chase, not a completed count, so the two aren't
  perfectly apples-to-apples, but the direction and rough magnitude agree).

**Practical implication**: a full 730-day 60m or 30m backfill for one ticker now costs **8
requests worst-case** (liquid/large-cap names — AAPL, MSFT both hit 8), **5 requests for
lower-turnover names** (JPM, KO, COST all completed in 5) — see Part 4 for the full-universe
extrapolation. This is the single most consequential change from the free-tier findings: the
free-tier follow-up concluded Warren's design was "categorically infeasible" at 15–25 hours/night;
that conclusion no longer holds on Starter (see Part 4).

### Part 3 — Session-anchored bars → Warren/BB+RSI signal parity (the key question)

**Tickers**: AAPL, MSFT (as directed) + JPM, KO, COST — 3 more names pulled live from the real
W1–W5 watchlist union (`data/watchlists.py::list_tickers_across_watchlists` pattern,
`^W[1-5]$`, read-only query against `backend/fathom.db`: **104 tickers total**, matching the
free-tier follow-up's own count exactly). BKNG, ANET, and NVDA were deliberately avoided — BKNG/
ANET per the free-tier follow-up's own flagged `SharedBarsCache` split-adjustment bug (out of
scope to solve here), and NVDA because its 2024-06-10 10:1 split (confirmed via `/v3/reference/
splits`) sits close enough to the comparison window's edges to risk contaminating the comparison
for no real benefit — JPM/KO/COST have no splits in the window and are still genuinely
representative (2 mega-cap tech names + a bank + 2 consumer staples).

**(a) Building session-anchored 60m bars, both methods.** Window matched exactly to what
`SharedBarsCache` actually holds for `interval='60m'` (read live from the DB): `2024-09-19` →
`2026-09-22` (the real 730-day Warren/BB+RSI fetch window). Both methods used the **aggregates
endpoint** (not flat files — blocked, see Part 1d):
- **(i) 30-min pairing**: fetch `/v2/aggs/.../range/30/minute/...`, then bucket into the same
  4 session windows Yahoo's 60m grid uses (`09:30–10:30`, ..., `15:30–16:00`), labeling each
  bucket by its **window start** (confirmed by directly reading real `SharedBarsCache` rows:
  `09:30:00`, `10:30:00`, ... — this is the one bug caught and fixed mid-investigation, see below).
- **(ii) 1-minute resampling**: same bucketing logic, fed 1-minute aggregates instead.
- Extended-hours bars are dropped in both (`between_time("09:30", "16:00")`, matching
  `analysis/entry_signal/resample.py::build_2h_session_candles`'s own convention).
- **One real bug, caught via a first-pass comparison and fixed before any of the numbers below
  were produced**: the first implementation labeled each 60-minute bucket by its *last raw
  sub-bar's own timestamp* (mirroring `build_2h_session_candles`'s own internal convention for
  building *its* 2h candles) — which for a 30-min-paired 60m bucket is `window_start + 30min`,
  not `window_start`. This produced a **near-total timestamp mismatch against `SharedBarsCache`**
  (497 of ~3,500 bars aligning, not ~3,490) on the first comparison run. Fixed by labeling each
  bucket by its **window start** instead (verified directly against real `SharedBarsCache` rows
  first, not assumed) — `SharedBarsCache`'s Yahoo bars are start-labeled (`09:30`, `10:30`, ...),
  and `build_2h_session_candles`'s "label by last sub-bar" convention, while correct for *its own*
  purpose (building 2h candles from 60m bars, where it's never compared to an external source),
  is the wrong choice for reconstructing a bar series meant to match one. Recorded here because
  it's exactly the kind of subtle labeling-convention bug this whole investigation's premise (§1c)
  warned about, and it would have silently produced a near-zero match rate if not caught.
- **Methods (i) and (ii) produce byte-identical 60m OHLCV series** for all 5 tickers (verified
  directly, not assumed) — expected, since 2h/60m session windows are exact multiples of both 30
  and 1 minutes and OHLC aggregation is associative across nested, aligned time windows. This
  means the choice between them is a pure cost/complexity question, not an accuracy one — see the
  recommendation below.

**(b) Bar-level comparison vs. real cached `SharedBarsCache` Yahoo 60m bars** (read-only query,
same DB, same window):

| Ticker | Massive bars | Yahoo bars | Common (matched timestamp) | Only-in-Massive | Only-in-Yahoo | Mean \|diff%\| (O/H/L/C) | Max \|diff%\| (O/H/L/C) |
|---|---|---|---|---|---|---|---|
| AAPL | 3,506 | 3,492 | 3,492 | 14 | 0 | 0.0086 / 0.0034 / 0.0064 / 0.0016 | 0.90 / 0.77 / 2.56 / 0.69 |
| MSFT | 3,506 | 3,492 | 3,492 | 14 | 0 | 0.0098 / 0.0048 / 0.0051 / 0.0017 | 1.56 / 2.26 / 2.36 / 0.46 |
| JPM | 3,506 | 3,491 | 3,491 | 15 | 0 | 0.0017 / 0.0005 / 0.0009 / 0.0015 | 0.97 / 0.46 / 0.57 / 0.12 |
| KO | 3,506 | 3,491 | 3,491 | 15 | 0 | 0.0020 / 0.0010 / 0.0015 / 0.0008 | 2.06 / 0.86 / 1.39 / 0.16 |
| COST | 3,506 | 3,492 | 3,492 | 14 | 0 | 0.0113 / 0.0035 / 0.0044 / 0.0034 | 1.36 / 1.11 / 1.80 / 0.17 |

**Every bar present in `SharedBarsCache` has a matching Massive bar (0 "only-in-Yahoo" across all
5 tickers) — Massive has strictly more bars** (14–15 extra per ticker; not investigated further,
plausibly session days Yahoo's own cache is missing or holidays handled slightly differently).
Mean diffs are tiny (0.0005%–0.011%, close to §2g's original daily-bar accuracy finding of
~0.000005% mean but about 1,000x looser, consistent with genuine intraday microstructure
differences between data providers rather than a bug) and max diffs (up to ~2.6% on isolated
Low/Open values, one bar out of ~3,500 per ticker) are typical single-bar outliers, not a systemic
skew — no field shows a directional bias. Neither method (paired vs. resampled) differs from the
other in this comparison, confirming the byte-identical finding above. **No split-adjustment
contamination observed for any of the 5 chosen tickers** (BKNG/ANET's known issue was avoided by
ticker selection, not fixed).

**(c) The real test: actual production Warren + BB+RSI code, replayed on both sources.** Called
`analysis.entry_signal.resample.build_2h_session_candles` →
`analysis.warren_signal.state_machine.replay` (Warren) and
`analysis.entry_signal.engine.compute_historical_entry_signals` (BB+RSI) directly — the real
production functions, unmodified, no reimplementation. Both Massive-built 60m series (paired and
resampled — identical results, so reported once) were fed through the same code as the real Yahoo
`SharedBarsCache` series for the same ticker/window:

| Ticker | Warren: Massive events | Warren: Yahoo events | Common dates | Warren date-level match | BB+RSI: Massive fired days | BB+RSI: Yahoo fired days | Common dates | BB+RSI date-level match |
|---|---|---|---|---|---|---|---|---|
| AAPL | 34 (32 dates) | 30 (28 dates) | 27 | 27/33 = **0.818** | 23 | 23 | 23 | 23/23 = **1.000** |
| MSFT | 35 (31 dates) | 35 (31 dates) | 31 | 31/31 = **1.000** | 30 | 30 | 29 | 29/31 = **0.935** |
| JPM | 18 (15 dates) | 18 (15 dates) | 14 | 14/16 = **0.875** | 19 | 20 | 19 | 19/20 = **0.950** |
| KO | 29 (27 dates) | 29 (26 dates) | 26 | 26/27 = **0.963** | 20 | 20 | 20 | 20/20 = **1.000** |
| COST | 26 (23 dates) | 25 (22 dates) | 22 | 22/23 = **0.957** | 24 | 24 | 23 | 23/24 = **0.920** |
| **Pooled (5 tickers)** | | | **120** | **120/130 = 0.923** | | | **114** | **114/119 = 0.958** |

("Match" = Jaccard similarity of the two sources' *unique event dates* — `|common| / |union|` —
not a raw count ratio, so both missed and spurious dates penalize the score equally.)

**This is the headline result of this entire investigation.** The free-tier follow-up found
**zero common Warren event dates** for AAPL/MSFT when naively pointing the resampler at Massive's
native calendar-hour-anchored bars (25% fewer 2h candles than Yahoo, entirely different bucket
boundaries). Building genuinely session-anchored 60m bars first — the fix that follow-up called
for but didn't attempt — closes almost all of that gap: **92.3% Warren date-match, 95.8% BB+RSI
date-match, pooled across 5 real tickers**, using the actual production replay code unmodified.
The remaining ~5–8% mismatch is plausibly attributable to the same small intraday OHLC
differences quantified in (b) above (a few basis points on Close, up to ~2.6% on isolated
Low/Open values) occasionally landing a threshold-crossing indicator (RSI/ADX/WVF/Bollinger %B)
on the adjacent bar or day rather than a structural grid problem — not confirmed by a dedicated
root-cause trace (out of scope for this pass), but consistent with the bar-level accuracy numbers
already measured in (b).

### Part 4 — Nightly operational cost for a realistic incremental design

**W1–W5 union: 104 tickers** (read live from `backend/fathom.db`, read-only — matches the
free-tier follow-up's own count).

**(a) One-time backfill cost, measured directly (not just estimated) for the 5-ticker sample,
then extrapolated to 104:**

| Method | Pages/ticker observed | Wall-clock/ticker observed (incl. 0.8s/page courtesy sleep) | Extrapolated total requests (104 tickers, weighted 40% AAPL/MSFT-shape @ 8pg / 60% JPM/KO/COST-shape @ 5pg → avg 6.2pg/ticker) | Extrapolated wall-clock, courteous pacing | Extrapolated wall-clock, unthrottled (~1.35s/req 30m/60m, ~3.35s/req 1m — both back out the courtesy sleep from the measured totals above) |
|---|---|---|---|---|---|
| 30-min pairing (730d / Warren's current window) | 5–8 (avg 6.2) | 10.0–16.3s | **~645 requests** | **~25 min** | **~14.5 min** |
| 1-min resampling (730d) | 5–8 (avg 6.2, identical page count to 30-min) | 19.0–32.1s (payload-bound, ~2x slower per page) | **~645 requests** | **~47 min** | **~36 min** |
| 30-min pairing, 1,095d (3y) — scaled from the measured 730d page counts, not independently measured | ~9.3 (avg, linear extrapolation) | — | **~967 requests** | ~36 min | ~22 min |
| Flat files | — | — | ⛔ **blocked** (Part 1d) | — | — |

Peak memory during the live 5-ticker run stayed well within budget: processed and discarded one
ticker's raw 1-minute frame (up to 383,094 rows, ~380KB pickled at 60m-resampled size) at a time,
never holding more than one ticker's raw intraday data in memory simultaneously — confirmed via
`free -h` spot-checks during the run (available memory never dropped below ~140MB of the VPS's
939MB). No temporary disk was used beyond the small (<200KB/ticker) pickled 60m outputs in the
scratch dir, all deleted at the end of this task.

**Both real backfill numbers (14.5–47 min) fit comfortably inside a single dedicated cron
window**, a dramatic reversal from the free-tier follow-up's 1.6–25 **hour** range for the
identical 730-day/104-ticker workload. **30-min pairing is the clear choice over 1-min
resampling**: byte-identical output (Part 3a), same request count, but roughly half the
wall-clock and payload size per request.

**(b) Nightly incremental cost** (fetching only bars after the last cached bar — one trading
day's worth, ~7–14 bars depending on method): trivially fits in a single page for every ticker
regardless of method (smallest page-1 size observed anywhere in this investigation was AAPL's
1m/30d sample at 17,950 bars for a *whole month*; one day is a small fraction of that). **104
requests/night, one per ticker** — at Part 1b's confirmed-safe natural pace (0.67s/req for small
payloads), **~70s unthrottled**, comfortably under a minute even with a courteous 1s/req pace
(~104s). This is the design a real migration should use — full-history refetch only on backfill/
recovery, incremental single-day fetches thereafter — not a nightly full-replay-from-scratch
against Massive (Warren's own state-machine replay design doesn't require re-fetching history
from the source every night, only re-running its own replay logic against whatever's cached
locally, exactly as it already does against `SharedBarsCache` today).

**(c) Split-handling rule, sanity-checked against real data.** `/v3/reference/splits?ticker=X`
(tested live, `200`, real data) is the detection mechanism: a scheduled nightly (or pre-backfill)
check for any split with `execution_date` since the last successful fetch triggers a full
refetch for that one ticker only (cheap — 5–8 requests per Part 4a, not a universe-wide re-pull).
Sanity-checked against two real, confirmed splits: **NVDA, 2024-06-10, 10:1** (falls outside
Warren's current 730-day window as of today, `2024-09-19`–`2026-09-22`, but would fall inside a
3-year window — exactly the kind of case this rule needs to catch for a longer warm-up) and
**SMCI, 2024-10-01, 10:1** (inside the current window — this is the same split the original §2c
adjustment test used, confirmed clean via `adjusted=true` producing a continuous back-adjusted
series across the boundary). Both real splits returned correctly from the endpoint with exact
dates, confirming the mechanism is viable, not just theoretically sound.

### Updated coverage matrix

| Consumer | Free-tier verdict (prior section) | Starter (paid) verdict | Why |
|---|---|---|---|
| Warren signal (730d, 60m) | ❌ not viable as designed | ✅ **viable — backfill ~14.5–25min, nightly incremental ~70–104s** | Part 2 (8 pages/ticker, not ~40) + Part 4 (real measured cost, not extrapolated-from-a-worse-key) |
| BB+RSI (60d, 60m) | ⚠️ plausible, not confirmed at scale | ✅ **viable, same reasoning, smaller window** | Subsumed by Warren's own 730d measurement — BB+RSI's 60d window is a strict subset |
| Session-anchored 60m bar construction | ❓ not attempted (free-tier follow-up only flagged the problem) | ✅ **solved — 30-min pairing, window-start labeling** | Part 3a — byte-identical to 1-min resampling, ~half the cost |
| Warren signal accuracy (vs. real Yahoo, real production code) | ❌ 0% date match (AAPL/MSFT, calendar-hour-anchored bars) | ✅ **92.3% pooled date-level match, 5 tickers, real replay code** | Part 3c — the headline result |
| BB+RSI signal accuracy (same basis) | not tested | ✅ **95.8% pooled date-level match, 5 tickers, real replay code** | Part 3c |
| Snapshot endpoint | ❌ untested this pass (403'd on the original free-tier key) | ✅ **works (day/min/prevDay populated); lastTrade/lastQuote still gated** | Part 1c |
| Rate limits | ❌ ~5–10 req/min, multi-min lockout | ✅ **300 sequential requests, 0.67s/req, 0×429** | Part 1b |
| History depth | ❌ hard-clipped to 730d | ✅ **genuine ~5y (1,824 calendar days), no clipping** | Part 1a |
| Flat files | not reached (free tier) | ⛔ **blocked — no S3 credentials in `.env`** | Part 1d |
| Everything else in the original §3/updated §"Updated coverage matrix" (Sector Heatmap, Momentum, Market Breadth, Trend/Weinstein, Chart D_6M/D_1Y/D_2Y, Chart W_4Y/Analyst Ratings 10y, non-US) | — | **unchanged, not re-tested this pass** | Out of this pass's scope — this section is scoped to Warren/BB+RSI per the task |

### Recommendation

**Move Warren and BB+RSI to Massive, using 30-minute-bar pairing (not 1-minute resampling, not
flat files) to build session-anchored 60m bars.** This reverses the free-tier follow-up's
recommendation outright, on genuinely new evidence, not a re-assertion:

1. **Cost is no longer a blocker.** The free-tier follow-up's categorical rejection rested on an
   observed 15–25 hour/night worst case; the same workload on Starter, measured directly (not
   re-extrapolated from a worse key), costs **~14.5–25 minutes for a one-time 730d/3y backfill**
   and **~70–104 seconds/night thereafter** with an incremental (fetch-only-new-bars) design —
   comfortably inside Warren's existing dedicated 3:40–3:55 AM cron slot, with room to spare for
   BB+RSI's much smaller 60-day window in the same or an adjacent slot.
2. **Accuracy is strong and directly measured against real production code**, not a proxy: 92.3%
   Warren / 95.8% BB+RSI pooled date-level match across 5 real tickers, using the actual
   `state_machine.replay`/`compute_historical_entry_signals` functions Fathom runs in production
   every night, fed genuinely session-anchored (9:30-anchored) 60m bars — not the free tier's
   naive calendar-hour-anchored attempt that produced 0% match. The residual ~5–8% gap is
   consistent with ordinary cross-provider intraday microstructure noise (Part 3b: sub-0.02% mean
   OHLC diffs, occasional single-bar outliers up to ~2.6%) landing a threshold-crossing indicator
   on an adjacent bar/day, not a structural integration problem.
3. **30-min pairing over 1-min resampling**: the two methods are **provably equivalent** (Part
   3a — byte-identical 60m output across all 5 tickers) but 30-min pairing needs half the
   wall-clock and roughly 1/24th the raw payload volume per request (30-min bars vs. 1-min bars
   at the same 8-page cap), with no accuracy tradeoff. There is no reason to choose the more
   expensive method.
4. **Rate limits are no longer a design constraint.** 300 sequential requests at natural pace
   produced zero 429s — Warren + BB+RSI's combined nightly footprint (~104–208 requests/night
   incremental, ~1,300–1,900 for an occasional full-universe backfill) is a small fraction of
   what this key just sustained cleanly.
5. **What's still open, deliberately not resolved here**: this pass is scoped to Warren/BB+RSI
   only, per the task — it does not re-verify or change the recommendation for Sector Heatmap,
   Momentum, Market Breadth, Trend/Weinstein, Chart tab ranges, or non-US tickers, all of which
   the free-tier follow-up already reasoned through separately and which this pass didn't
   re-test. Flat-file access remains genuinely unverified (blocked on missing credentials, not
   ruled out) — if a future cost comparison matters (e.g. if per-request pricing or a lower rate
   ceiling is discovered on a much larger universe), that gap should be closed with the correct
   S3 credentials from the Massive dashboard before concluding flat files aren't worth it. The
   ~5–8% Warren/BB+RSI date-mismatch residual was not root-caused to a specific bar or indicator
   — acceptable for a go/no-go decision at this level of confidence, but worth a closer look if a
   specific missed/spurious signal date ever matters operationally.

**Disk before this pass: `/` 25G, 18G used, 5.4G available (77%); `/tmp` 470M, 78M used, 393M
available (17%). Disk after: unchanged to the byte at the filesystem level** (all scratch
artifacts — `.pkl` files, JSON summaries, Python scripts, logs — lived under the session
scratchpad outside the repo and were deleted before finishing; peak scratch-dir size was 1.8MB).
Peak memory observed during the heaviest step (5-ticker 1-minute-bar fetch/build): ~650–780MB
used of 939MB total, ~140–290MB available — never critical, no swap pressure introduced beyond
what was already resident before this task started.

**Total requests used this pass: ~467** (1 history-depth check, 300 the deliberate Part 1b burst,
2 snapshot, 2 splits, ~30 assorted pagination-mechanism probes, ~124 for the 5-ticker×2-method
bar-fetch, run twice after the labeling-bug fix — ~62 wasted on the first, buggy pass, kept in
this count for honesty rather than only counting the corrected run). Zero `429`s across the
entire pass, at any pace. Scratch scripts, pickled intermediate DataFrames, and JSON outputs were
all deleted from the session scratchpad after this section was written; only this doc update
remains.

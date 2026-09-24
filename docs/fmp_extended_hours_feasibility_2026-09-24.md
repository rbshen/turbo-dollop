# FMP extended-hours price feasibility test (2026-09-24)

Standalone API test, **not** a description of anything wired into Fathom. A throwaway
script called Financial Modeling Prep's `/stable` API directly (backend `.env` key, our
current paid plan) from a temporary sandbox; nothing in the app was touched, read, or
changed. All times below are US/Eastern.

## 1. Verdict

**Yes, on our current plan.** No single FMP endpoint does this end-to-end, but two
endpoints combine to cover the full 04:00–20:00 ET extended-trading day plus the
20:00–04:00/weekend/holiday "last known price" case, and both returned real, current
data with zero access errors in this test: `GET /stable/historical-chart/1min` **with
`extended=true`** (undocumented via search, found empirically — see below) covers
pre-market (04:00+), regular session, and post-market (through 19:59) in one series;
`GET /stable/aftermarket-trade` (or `aftermarket-quote`) gives the single latest
post-market print and, once the 20:00 ET post-market session ends, simply stops
updating — which is exactly the "last post-market price" behaviour the 20:00–04:00/
weekend/holiday case needs, confirmed live (see §3). The one endpoint that looked like
the natural fit for a single always-current price, `GET /stable/quote`, is **not**
usable for this — it freezes at the 16:00 regular close and never reflects pre- or
post-market moves at all (confirmed live: `quote` showed AAPL 337.02 as of 16:00:00
while `aftermarket-trade` showed a real, different, current 336.9361 at the same
moment). Session-state detection (which of the four windows applies right now) has no
reliable FMP endpoint of its own — see §4 — so it has to be computed client-side from
wall-clock ET time plus FMP's holiday-calendar endpoint (which does work and does
include early closes).

## 2. Endpoint-by-endpoint results

| Endpoint | Plan access | Pre-market | Regular | Post-market | Overnight/weekend | Timestamp field / tz | Notes |
|---|---|---|---|---|---|---|---|
| `GET /quote` | ✅ 200 | ❌ frozen at close | ✅ live | ❌ frozen at close | ❌ frozen at close | `timestamp`, Unix **seconds** | Confirmed: returned `timestamp=1790193600` (16:00:00 ET, exact regular close) for every one of AAPL/NVDA/TSLA/SPY/NWL when called at 20:39 ET, i.e. ~4.5h after close — it is a regular-session-only field, not "latest known price." Do not use for any extended-hours need. |
| `GET /quote-short` | ✅ 200 | ❌ | ✅ live | ❌ | ❌ | none (no timestamp field at all) | Same restriction as `/quote`, minus even a timestamp to detect staleness by. |
| `GET /aftermarket-quote` | ✅ 200 | ⚠️ untested — see gap below | n/a (post-market only by name/design) | ✅ live | ✅ correctly frozen at last post-market print | `timestamp`, Unix **milliseconds** | Bid/ask/sizes/volume, no trade price. At 20:39 ET call time (39 min into the overnight window), returned AAPL/NVDA/TSLA/SPY all timestamped 19:59:43–20:00:06 ET — i.e. the literal last post-market tick, not visibly refreshed since. This is the correct behaviour for the 20:00–04:00 case. |
| `GET /batch-aftermarket-quote` | ✅ 200 (`symbols=` plural, comma-joined; `symbol=` singular not accepted; no-param call → 400 "Invalid or missing query parameter - symbols") | same as above | n/a | ✅ live | ✅ same as above | same | One call for AAPL+NVDA+TSLA+SPY returned identical values to 4 individual `aftermarket-quote` calls — no disagreement. |
| `GET /aftermarket-trade` | ✅ 200 | ⚠️ untested, same caveat | n/a | ✅ live | ✅ correctly frozen | `timestamp`, Unix **milliseconds** | Last-trade price + size, no bid/ask. Same 19:59:41–19:59:59 ET freeze at call time. **Thin-name gap, confirmed**: NWL's last aftermarket trade was 19:30:00 ET — 30 min before the post-market session even closed — because nothing traded after that; not a bug, just illiquidity. |
| `GET /batch-aftermarket-trade` | ✅ 200 (`symbols=`) | same | n/a | ✅ live | ✅ same | same | Matches individual calls exactly. |
| `GET /historical-chart/1min` (no `extended` param) | ✅ 200 | ❌ | ✅ | ❌ | ❌ | `date`, naive local string, exchange-local (ET), **no tz offset in the string** | Confirmed: with no param (and even with `from=`/`to=` set), the series stops dead at `15:59:00` ET — the minute before close — every time. Regular session only. |
| `GET /historical-chart/1min?extended=true` | ✅ 200 | ✅ **confirmed** | ✅ | ✅ **confirmed** | n/a (market's closed, no bars generated) | same | **This is the key finding.** `extended=true` (not `extendedHours`/`includeExtendedHours` — both tried, both silently ignored, output identical to the no-param case) makes the series run from **04:00:00** through **19:59:00** ET, 952 one-minute bars for AAPL on 2026-09-23. Values agree with `aftermarket-trade`/`aftermarket-quote` at the boundary (see §3 cross-check). For NWL (thin), the series has **zero** pre-market bars at all that day and only 9 post-market bars, last one at 19:30 — real illiquidity, not a fetch gap. |
| `GET /historical-chart/5min` | ✅ 200 | untested (not tried with `extended=true`, but the no-param case matches 1min's no-param behaviour exactly — stops at 15:55 ET) | ✅ | untested | untested | same format as 1min | Not needed for this use case (1-minute granularity is already finer); included for completeness only. |
| `GET /exchange-market-hours?exchange=NASDAQ` | ✅ 200 | n/a | n/a | n/a | n/a | `openingHour`/`closingHour` as `"09:30 AM -04:00"` strings, `timezone: "America/New_York"` | Gives regular-session open/close and a live `isMarketOpen` boolean — but that boolean only reflects the **regular** session (it read `false` at 20:39 ET, which is technically correct but doesn't distinguish "post-market open" from "fully closed"). No pre/post-market state exposed. |
| `GET /market-hours`, `GET /is-the-market-open` | ❌ 404 | — | — | — | — | — | Not valid paths on the `/stable` surface (or not entitled) — both empty-array 404s regardless of params. Don't rely on either name. |
| `GET /holidays-by-exchange?exchange=NASDAQ` | ✅ 200 | n/a | n/a | n/a | n/a | `date` (calendar date) | Works, and usefully distinguishes full closures (`isClosed: true`) from early closes (`isClosed: null, adjCloseTime: "13:00"`, e.g. the day before Thanksgiving/Christmas) — the one FMP endpoint genuinely useful for the holiday/early-close part of session detection. |
| Dedicated pre-market endpoint (`premarket-quote`, `premarket-trade`, `pre-market-*`, `batch-premarket-*`, `extended-hours-quote`, …) | ❌ 404 (every name tried) | — | — | — | — | — | **Does not exist under any name we tried.** FMP's only extended-hours *quote/trade* endpoints are literally named "aftermarket" — pre-market has to come from the 1-min chart's `extended=true`, not a quote-shaped endpoint. |

## 3. Simulation — most recent completed trading day (2026-09-23), from `historical-chart/1min?extended=true`

Test run itself happened at 2026-09-23 20:39 ET, i.e. already inside the "20:00–04:00"
window relative to that day's session, so 23:00 and the weekend case are shown as the
**same, already-observed frozen value** (live-confirmed, not simulated) rather than a
hypothetical — the 20:00 ET session close is what fixes the value, and nothing changes
between 20:00 and the next pre-market open regardless of the exact clock time you query
at.

| Ticker | 08:30 ET (pre-market) | 17:30 ET (post-market) | 23:00 ET / Sat 12:00 (overnight/weekend) | Source |
|---|---|---|---|---|
| AAPL | 340.75 (bar `08:30:00`) | 336.90 (bar `17:30:00`) | 336.9361 (last bar `19:59:00`; matches live `aftermarket-trade` 336.9361 @ 19:59:59) | 1min chart, cross-checked against `aftermarket-trade` |
| NVDA | 227.72 | 225.0975 | 225.0409 (matches live `aftermarket-trade` 225.0409 @ 19:59:59) | same |
| TSLA | 378.01 | 379.92 | 380.13 (matches live `aftermarket-trade` 380.1339 @ 19:59:56) | same |
| SPY | 772.74 | 767.73 | 767.39 (matches live `aftermarket-trade` 767.39 @ 19:59:41) | same |
| NWL (thin) | **no bar** — zero pre-market trades that day | **no bar at 17:30**; nearest earlier bar 16:38 = 5.64 | 5.65, but the underlying last trade is from **19:30:00**, not 20:00 (matches live `aftermarket-trade` 5.65 @ 19:30:00 exactly) | same — illustrates the thin-ticker gap |

**Cross-check result: zero disagreements.** Every ticker where both sources had data,
the `1min?extended=true` chart's last bar close and the live `aftermarket-trade` price
matched to the reported precision. The only "disagreement" is NWL simply having no data
at some of the requested times — a real liquidity gap, not a source conflict.

## 4. Recommended combination + gaps/risks

**Recommended combination:**
1. **Pre-market (04:00–09:30 ET) and post-market (16:00–20:00 ET) "latest price":**
   `GET /historical-chart/1min?symbol=X&extended=true`, take the close of the most
   recent bar. This is the only endpoint confirmed to cover pre-market at all.
2. **20:00–04:00 ET / weekend / holiday "last post-market price":** either (a) the same
   1min-chart call's last bar of the most recent trading day, or (b)
   `GET /aftermarket-trade`/`GET /aftermarket-quote`, which empirically just stops
   advancing once the post-market session ends and so already returns the right answer
   with no extra date-math — confirmed live in this test. Prefer (a) for consistency
   (one code path for both "post-market" and "overnight"), or (b) if a single
   lightweight per-ticker call is preferred over pulling ~950 minute-bars.
3. **09:30–16:00 ET regular session:** `GET /quote` (or `/quote-short`) is fine and
   cheaper — it's only the extended-hours behaviour that's broken, not the regular-hours
   one.
4. **Session-state detection** (which of the four windows applies *right now*): don't
   rely on FMP for this — `is-the-market-open`/`market-hours` 404, and
   `exchange-market-hours`'s `isMarketOpen` only distinguishes regular-open from
   everything-else. Compute it from wall-clock ET (`zoneinfo`) plus
   `GET /holidays-by-exchange`, the one FMP endpoint that does correctly report full
   closures and early closes.

**Gaps / risks:**
- **Pre-market coverage for `aftermarket-quote`/`aftermarket-trade` is unverified.**
  This test ran at night; the two "aftermarket"-named endpoints were never called during
  04:00–09:30 ET, so whether they return anything (stale post-close data, an empty
  array, or genuinely fail) during pre-market is unknown. Doesn't block the
  recommendation above, since the recommended pre-market path doesn't use them — but
  worth confirming with the curl commands in §5 before depending on it.
- **Thin-ticker gaps are real, not hypothetical.** NWL had zero pre-market 1-min bars
  and only 9 post-market bars (last at 19:30, not 20:00) on a completely ordinary
  Wednesday. A "latest extended-hours price" for an illiquid name can legitimately be
  30–60+ minutes stale relative to the current clock time, through no fault of the
  integration — this needs to be an accepted/displayed characteristic (e.g. show the
  bar's own timestamp), not something to engineer around.
- **Plan tier**: everything above returned clean 200s on the current key/plan — no
  402/403 "upgrade" responses were hit anywhere in this test, unlike FMP's *intraday*
  endpoints being 402-blocked for a different reason noted elsewhere (see this
  repo's own memory on FMP intraday restrictions — that restriction was **not**
  reproduced here; `historical-chart/1min` itself worked cleanly, so whatever plan
  restriction was hit before was either endpoint-specific or has since changed. Worth a
  quick sanity re-check if this is picked up for real implementation, since the earlier
  finding and this one appear to disagree.)
- **`extended=true` is undocumented** (not found via web search of FMP's own docs pages,
  which return 403 to non-browser fetches) — found empirically by testing candidate
  param names side by side (`extended`, `extendedHours`, `includeExtendedHours`) and
  observing which one actually changed the output. Being unlisted, it could change or be
  removed without notice; there's no fallback plan-tier signal to detect that other than
  the bar range silently shrinking back to regular-hours-only.
- **Holiday awareness is not holiday-*time*-aware** — `holidays-by-exchange` tells you
  *which days* are closed/early-close, but session-state detection built on top of it
  still needs to combine that with wall-clock time correctly (e.g. an early-close day's
  "post-market" window starts at the *adjusted* close, not 16:00) — a real but
  mechanical detail, not a data availability gap.
- **Overnight/weekend was directly observed, not simulated**, since the test happened to
  run inside that window — this is a genuine strength of this test's timing, not a
  limitation, but the *Saturday* case specifically (as opposed to "any time after 20:00
  Friday") was not separately confirmed; there's no reason to expect it behaves
  differently, since the mechanism (frozen since last trade) has no notion of what day
  it currently is.

## 5. Live confirmation commands

Replace `YOUR_KEY` with the real FMP API key. Run these at 08:30 ET, 17:30 ET, and 23:00
ET on any US trading day to confirm live behaviour matches this report.

```bash
# Latest extended-hours bar (works at all three times; check the last bar's "date")
curl -s "https://financialmodelingprep.com/stable/historical-chart/1min?symbol=AAPL&extended=true&apikey=YOUR_KEY" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0])"

# Last post-market trade (compare its timestamp to the current time to see if/when it freezes)
curl -s "https://financialmodelingprep.com/stable/aftermarket-trade?symbol=AAPL&apikey=YOUR_KEY"

# Last post-market quote (bid/ask)
curl -s "https://financialmodelingprep.com/stable/aftermarket-quote?symbol=AAPL&apikey=YOUR_KEY"

# Regular-session quote, for contrast -- confirm it stays frozen at 16:00 ET outside 09:30-16:00
curl -s "https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey=YOUR_KEY"
```

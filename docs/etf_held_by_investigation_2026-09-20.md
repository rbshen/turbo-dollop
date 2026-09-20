# ETF "Held by" on stock ticker pages -- Round 1 investigation (2026-09-20)

Phase 1 only: investigation, no code changes. Scope: which ETFs hold a given stock,
shown on an existing stock ticker page, from FMP's ETF Asset Exposure endpoint. Rounds 2
(ETF page) and 3 (market dashboard) are out of scope and deliberately not discussed.

Live FMP calls used: **20** (budget was ~25). Raw calls only -- nothing went through
`get_or_fetch`, nothing touched `backend/fathom.db` except two read-only lookups of which
sample tickers already have a cached profile. All scratch files deleted.

## 1. Verdict in one paragraph

The endpoint **works on our plan** (HTTP 200, no 402) and its numbers are **accurate where
it matters**, but the raw response is **not displayable as-is**: it is a *global* list of
~1,600-4,000 rows per stock (US ETFs mixed with every foreign-listed clone and every
mutual-fund share class), unsorted, with no ETF names, and with a small tail of garbage
rows. A usable "Held by" needs a filter/sort/name step on top. That step is cheap (one extra
FMP call per week, globally), so the feature is viable and small -- but it is not "just
render the endpoint."

## 2. The endpoint

`GET /stable/etf/asset-exposure?symbol=<STOCK>` -- confirmed. One row per (ETF, stock):

```
{"symbol": "SPY", "asset": "AAPL", "sharesNumber": 175203823,
 "weightPercentage": 7.514951, "marketValue": 59138717517}
```

- `symbol` = the **ETF/fund**; `asset` = the queried **stock**. (Same field naming as
  `/etf/holdings`, which has `symbol` = ETF and `asset` = holding.)
- `weightPercentage` = the stock's weight **within that ETF**, in percent (7.51 = 7.51%).
- `marketValue` = dollars (in the ETF's *local currency*, see quality below) that ETF holds
  of the stock. `sharesNumber` = shares held.
- **No** ETF name, AUM, expense ratio, exchange, currency, or as-of date on any row.
- Keys are identical on all rows. Numbers arrive as a mix of int/float.
- **Not sorted** by weight, market value, or shares (verified on AAPL, 3,740 rows).
- **No paging/limit params needed**: one call returns everything (up to ~4,000 rows).

### Accuracy cross-check (AAPL in SPY)

| Source | shares | market value | weight |
|---|---|---|---|
| `/etf/asset-exposure` (AAPL) | 175,203,823 | $59,138,717,517 | 7.514951% |
| `/etf/holdings?symbol=SPY` (AAPL row) | 175,203,823 | $59,138,717,517 | 7.518127% |

Shares and market value match exactly; weight differs by 0.003pp (different price basis /
timestamp). SPY's holdings weights sum to 100.00000005. So for major ETFs this is
trustworthy. (Also: `/etf/holdings` carries an `updatedAt` of the same day; asset-exposure
carries no timestamp at all -- the only "as of" we can show is our own `fetched_at`.)

## 3. Volume and payload (real measurements)

| Ticker | rows | raw bytes | US-listed rows* | after filter+trim bytes | top-50 bytes |
|---|---|---|---|---|---|
| AAPL | 3,740 | 567,411 (470 KB re-serialized) | 816 | 94,056 | 6,056 |
| MSFT | 4,039 | 612,424 | 906 | 104,083 | 6,023 |
| GOOGL | 3,191 | 485,165 | 792 | 92,162 | 6,057 |
| JPM | 2,260 | 334,577 | 546 | 62,393 | 5,928 |
| BRK-B | 1,713 | 260,576 | 380 | 44,124 | 6,018 |
| O (REIT) | 1,600 | 235,071 | 322 | 36,030 | 5,781 |
| CRWV (recent IPO) | 1,109 | 165,533 | 266 | 30,472 | 5,857 |
| AAOI (small cap) | 313 | 45,639 | 111 | 12,691 | 5,784 |
| HSBC (ADR) | 91 | 13,125 | 33 | 3,742 | 3,742 |

\* "US-listed" = symbol matches `^[A-Z]{1,5}$` **and** is present in `/etf-list` (see 4).

Latency: 1.0-2.5 s per call regardless of size. Cold fetch for a heavy name is ~2 s.

## 4. Data quality -- what's wrong with the raw list

Measured on AAPL (3,740 rows) and spot-checked on the rest.

1. **It is a global universe.** Only 1,104 of AAPL's 3,740 rows have no exchange suffix.
   The rest are `.L` 658, `.DE` 549, `.SW` 281, `.MI` 267, `.TO` 233, `.PA` 172, `.AS` 109,
   `.MX`, `.SG`, `.F`, `.AX`, `.SN`, `.HK`, `.KS`, `.T`, ... plus some Bloomberg-style
   symbols with spaces (`VWRL SW`, `WTAI FP`) and junk like `VALQVALQVALQ`.
2. **Mutual funds are mixed in.** 227 of the no-suffix rows match the mutual-fund pattern
   (`VTSAX`, `VSMPX`, `VITSX`, `VWNFX`...). **None of them are in `/etf-list`**, so that list
   is a clean membership test for "is an ETF."
3. **Same fund, many lines.** 613 groups (2,038 rows) share identical
   shares/weight/marketValue -- the same fund listed on many exchanges or in several share
   classes (`VTI`/`VTSAX`/`VSMPX`/`VITSX`/`VTS.AX` all read 466,773,438 shares). Even after
   filtering to US-looking symbols a few real duplicates remain (`FMIL`/`FFLC`,
   `TRPL`/`SLT`/`LSLT`...), and 6 OTC-listed Irish/Lux UCITS lines slip through the symbol
   regex (`VNGDF`, `ISMCF`, `AMSPF`, `XTRTF`...). They are identifiable by "UCITS" in the
   `/etf-list` name.
4. **`marketValue` is in local currency, unlabeled.** The top raw row by marketValue is
   `1557.T` at 9.17 *trillion* (yen). Ranking the raw list by marketValue is meaningless
   until non-US lines are removed. For US-listed rows it is USD.
5. **Garbage tail.** In AAPL's raw list: 18 negative weights (`AAPS.L` -299.99%, a
   leveraged-short product), 6 weights >100%, 5 weights == 0, 38 null/zero market values.
   Inside the US-listed subset: `HEMI` weight **33,700%** with 0 shares / $0; `VIRS` and
   `SZNE` both 56.96% with identical share counts (implausible for an equal-weight fund);
   `XVAP` 49.4%; `UPSD`/`RVRS`/`GPAL`/`GDEF` weight 0. A rule of "drop rows with
   marketValue <= 0 or sharesNumber <= 0" removes the worst (HEMI, the negatives); a
   weight cap (>40%) would catch the remaining suspicious four.
6. **Product-type noise is real but arguably correct.** 27 of AAPL's 816 US rows are
   leveraged/inverse products (`TQQQ`, `UPRO`, `SSO`, `TECL`...), plus covered-call/
   "income" funds. They do hold the stock; nothing in the payload lets us tag them
   without a per-ETF `/etf/info` call (`assetClass`) or name matching.
7. **The good part:** the biggest US ETFs are exactly right and stable in ranking.
   AAPL top by dollars held: VTI, VOO, IVV, SPY, VUG, QQQ, VGT, XLK, SPYM, IWF. The top 25
   US ETFs account for 84.5% of all US-listed dollars held. Ranking is dominated by a
   handful of funds that are the same for most large caps.

### Symbol handling (important)

| Query | Result |
|---|---|
| `BRK-B` (app's canonical form, `core/tickers.py`) | 1,713 rows, `asset = "BRK-B"` |
| `BRK.B` | 9 rows, a different unrelated set |
| `GOOGL` / `GOOG` | 3,191 / 2,937 rows -- separate, both work |
| `HSBC` (ADR) | 91 rows, works |

The app already normalizes `BRK.B -> BRK-B` on every entry path, so passing the canonical
ticker through unchanged is correct. `BF-B` (the other alias) was **not** tested (budget) --
assumed to behave like BRK-B.

### "No holders" and unknown symbols

Both an unknown symbol (`ZZZZQ`) and a real thin OTC name (`SINGY`) return **HTTP 200 `[]`**
-- indistinguishable. That is fine here (the ticker page is already 404-gated by the summary
call), but it means "no ETFs hold this" and "FMP doesn't know this symbol" look the same.
Even a very obscure ticker (`CNSWF`, OTC) had 7 rows, so "empty" is rare in practice.

### Querying an ETF itself

`SPY` returns 56 rows -- funds that hold SPY (fund-of-funds/hedged wrappers: `HEGD` 93.4%,
`MSTB` 82.4%). Not useful as a "Held by" and not something to show on an ETF page -- see 7.

## 5. Naming/enrichment: what it takes to show a name

The exposure rows have no name. Two FMP options, both measured:

| Option | Calls | Payload | Gives | Notes |
|---|---|---|---|---|
| `/etf-list` | **1 total (global)** | 15,549 rows, 1.18 MB | symbol + name for every ETF | Also serves as the ETF-vs-mutual-fund membership filter. Names are sometimes a trust name ("Xtrackers (IE) Public Limited Company...", "ETF Opportunities Trust - Tappalpha..."), mostly fine. |
| `/etf/info?symbol=X` | 1 **per ETF shown** | ~2.5 KB each | name, AUM, expense ratio, `domicile`, `assetClass`, holdingsCount, avg volume, inception, sector list | Per-ETF reuse across stocks is high (VTI/VOO/IVV/SPY are on nearly every large-cap page), and it would let us drop non-US `domicile` and tag leveraged/`assetClass`. Costs 10-25 extra calls on a cold page (parallelizable, ~2 s). |

Recommendation for Round 1: **`/etf-list` only** (one global cached row). It gives the
filter and the names for ~zero marginal cost. `/etf/info` is a clean later upgrade if AUM or
expense ratio is wanted on the card; its rows would be reusable if an ETF page is ever
built, but that is not decided here.

## 6. Caching design (follows the existing pattern)

- **Table/mechanism:** `FundamentalsCache` + `core/cache.get_or_fetch`, no new table, no
  migration.
- **Holders key:** `(ticker = <STOCK>, statement_type = "etf_asset_exposure", period =
  "latest")` -- same shape as `insider_trading_search`/`latest` and `forex_rate`/`latest`.
- **ETF-name list key:** `(ticker = "_ETF_LIST", statement_type = "etf_list", period =
  "latest")`. A pseudo-ticker key has direct precedent (`forex_rate` is keyed by e.g.
  `TWDUSD`, and `load_full_tracked_universe` explicitly filters on `statement_type ==
  "profile"` so pseudo-ticker rows can't pollute the tracked universe). `POST .../refresh`
  (`clear_ticker_cache`) deletes only that stock's rows, so the shared list is untouched --
  correct. Suggested staleness: 30 days (`profile_staleness_days` precedent; ETF names barely
  change).
- **What to store for holders: the filtered, sorted list, not the raw response.** Raw is
  190-610 KB per stock; filtered is 12-104 KB. Prefer filtering *before* caching (needs the
  name list at fetch time; if the list is unavailable, fall back to symbol-regex-only and
  show tickers without names).
- **Staleness for holders:** recommend reusing `cache_staleness_days` (7) rather than a new
  setting. Reasoning: the *ranking* is dominated by a few giant funds that don't change; the
  payload is heavy enough that avoiding refetches matters; a weekly-stale "who holds this"
  list is not a material error. **Caveat -- I did not measure day-over-day drift** (that
  needs a second fetch on a later day). If precision matters, diffing one ticker across two
  days would settle it cheaply.
- **FMP disabled / cold miss:** `get_or_fetch` returns the stale row if present, else `None`
  (`cache_only`/`fmp_enabled=False`). Insider Activity's `as_of = row.fetched_at` (null
  when never cached) pattern maps directly: null `as_of` -> "not cached yet", set `as_of`
  with empty list -> "no ETFs hold this."
- **No prefetch:** do **not** add this to `nightly_fundamentals_fetch`. 572 tickers x
  1-2.5 s = 10-25 minutes of extra FMP calls a night for data almost nobody views;
  lazy-on-view matches Analyst Ratings/News. Cache rows accumulate only for viewed tickers.

### Existing machinery -- does it need to change?

| Item | Change needed? | Why |
|---|---|---|
| `POST /api/tickers/{t}/refresh` / `clear_ticker_cache` | No | Deletes every `FundamentalsCache` row for the ticker generically; holders row repopulates on next view. |
| `pipeline/prune_cache.py` | No | Prunes all `FundamentalsCache` rows by `fetched_at` (180 days). |
| `backup_db` | No | Whole-DB gzip; adds a few MB at most. |
| `audit_fixture_contamination` | No | Scans only the statement types listed in its `CHECKS`; a new key is ignored. |
| `stale_data_health_check`, `load_full_tracked_universe` | No | Both key off `statement_type == "profile"` only. |
| `nightly_fundamentals_fetch` | No | See "No prefetch" above. |
| Cron / `core/cron_health.py` / `crontab.txt` | No | No new job. |
| Status page `FMP_POWERS` (`frontend/components/settings/StatusSection.tsx`) | **Yes (1 line)** | Add an "ETF Holders" entry so the FMP card lists what FMP powers. |
| `Settings` | Optional | Only if a dedicated holders staleness window is chosen over reusing the 7-day one. |
| `tests/conftest.py` | No | Write-guard is generic; new tests build their own in-memory engine. |

## 7. Where it slots on the ticker page

Findings from `TickerTabsContainer.tsx`, `SummaryTab.tsx`, `lib/tickerTabs.ts`:

- The page is a sticky header + 9 tabs (Summary default, Chart last). Insider Activity is
  shelved. Every tab is lazy-mounted and fetches through an SWR hook
  (`useApiResource(url | null)`); the container is already 404-gated by the summary call.
- `TickerSummaryOut.is_etf` is **already available client-side** (`useTickerSummary`), so
  gating needs no new data. Nothing on the page consumes `is_etf` today -- an ETF's own
  page (`/tickers/SPY`) currently renders the same stock tabs as any stock (a Round 2
  matter; noted only because "Held by" must not render there).

**Recommended placement: a new section at the bottom of the Summary tab**, below the
segmentation blocks -- titled like the existing section headers
(`text-sm font-semibold uppercase tracking-widest text-text-secondary`), e.g. "Held by ETFs".
- It is its own component with its own hook (`useEtfHolders`), fetched independently, so it
  never blocks or delays Summary's existing content (same "independent fetch" convention as
  `useLiquidityZones`/`useEntrySignal`).
- Summary is the default tab and the natural "who owns this" home; no new tab, no nav change,
  no header change.
- Body: a summary line ("Held by 816 US-listed ETFs"), then a compact table of the top
  ~10-25 rows (ETF ticker, name, $ held, weight in ETF) with a "Show N more" affordance, and
  a small "as of <fetched_at>" caption. Pass `null` to the hook when `is_etf` is true so no
  request is made.

**Runner-up: a header chip** ("In 816 ETFs") that expands or links to the Summary section.
Rejected as the primary because the header is sticky and already crowded with pills, and
because a list of this size does not fit a chip. It could complement the section later.

Rejected: a new tab (the brief said smallest surface; also cheap content for a whole tab),
and embedding into the summary payload (would add a 1-2.5 s FMP call to every Summary load
and to `compute_ticker_score`'s path).

## 8. What a Phase 2 build would touch

Backend
- `clients/fmp_client.py` -- `get_etf_asset_exposure(ticker)`, `get_etf_list()`
- `data/etf_holders_data.py` (new) -- fetch both blobs via `get_or_fetch`, normalize/filter/
  sort, return the out-model
- `core/schemas.py` -- `EtfHolderOut`, `EtfHoldersOut` (`as_of`, `total_us_listed`, rows)
- `core/main.py` -- `GET /api/tickers/{ticker}/etf-holders` (same try/except-502 shape as
  `analyst-ratings`)
- `core/config.py` -- only if a dedicated staleness setting is chosen
- `tests/test_etf_holders_data.py`, an endpoint test

Frontend
- `lib/api/types.ts`, `lib/hooks/useEtfHolders.ts`,
  `components/ticker/EtfHoldersSection.tsx` (+ a small `lib/etfHolders.ts` for
  formatting/limits, with tests)
- `components/ticker/SummaryTab.tsx` -- mount the section
- `components/settings/StatusSection.tsx` -- one `FMP_POWERS` entry

Docs: a `CLAUDE.md` section. No DB migration, no cron, no new table.

Rough size: comparable to the Analyst Ratings tab minus its scoring logic -- **~6-8 files,
one focused session**, the logic being the filter/sort/dedup rules in section 4.

## 9. Decisions needed before building

1. **Filter scope:** US-listed only (symbol `^[A-Z]{1,5}$` in `/etf-list`, positive shares
   and market value, weight capped/blanked above ~40%) -- recommended -- vs. show global
   listings too (would need currency handling; not recommended).
2. **Default sort:** dollars held (surfaces VTI/VOO/IVV/SPY -- recommended) vs. weight in
   ETF (surfaces concentrated thematic funds and the buggy 50%+ rows).
3. **Dedup/UCITS:** collapse identical-share-count lines and drop "UCITS" names (small,
   cosmetic win) -- yes/no?
4. **Leveraged/inverse products:** leave in (they do hold the stock), or tag/hide (needs
   `/etf/info` or name matching)?
5. **Names via `/etf-list` only** (recommended) vs. per-ETF `/etf/info` for AUM/expense.
6. **Staleness:** reuse 7 days (recommended) vs. a dedicated setting.
7. **How much to send to the browser:** top ~25 + total count (recommended; cache keeps the
   full filtered list so the limit can be widened without a refetch) vs. the whole ~100 KB list.

## 10. Risks / things I did not verify

- Day-over-day change of the holders data (see 6).
- `BF-B` symbol behavior (assumed to mirror `BRK-B`).
- Behavior for non-US-listed stocks beyond HSBC (one ADR checked); a foreign-primary listing
  such as `.TO` was not tested.
- FMP plan/tier risk: the endpoint works today; it is not one of the documented
  restricted ones, but intraday 402s show plan-gating is real.
- Side observation, not verified: `core.cache.safe_fetch` logs `exc` verbatim, and httpx
  status-error messages embed the request URL including the `apikey` query param. That is
  pre-existing behavior (other chart-events code deliberately logs the exception type only);
  a new endpoint that can 4xx would inherit it. Worth a separate look, out of scope here.
- Sandbox: a read-only aggregate query over the 1.2 GB `fathom.db` was OOM-killed, so I have
  no `FundamentalsCache` size-by-type numbers; sizing above is extrapolated from the sample.

## 11. Manual UI checklist (no browser was available; for after a Phase 2 build)

1. `/tickers/AAPL` -> Summary tab: "Held by ETFs" section appears below the revenue blocks;
   top rows are VTI, VOO, IVV, SPY, VUG, QQQ; each row has a name, a dollar figure and a
   weight of a few percent; the count reads ~800; an "as of" date is shown.
2. Click "Show more" -> list expands, no layout shift in the rest of the page; no
   foreign-suffixed tickers (`.L`, `.DE`), no mutual funds (`VTSAX`), no 33,700% weight.
3. Switch to another tab and back -> section renders from SWR/cache instantly, no error.
4. `/tickers/BRK-B` and `/tickers/BRK.B` -> both show the same full list (dot form is
   normalized).
5. `/tickers/GOOGL` vs `/tickers/GOOG` -> two different lists, both populated.
6. `/tickers/AAOI` (small cap) and `/tickers/HSBC` (ADR) -> short lists, no empty-state glitch,
   no oversized "Show more".
7. A ticker with a tiny/unknown holder set (`SINGY`) -> a plain "No ETFs hold this" line,
   not an error.
8. `/tickers/SPY` (an ETF) -> **no** "Held by ETFs" section, and no network request to the
   holders endpoint in the browser dev tools.
9. Cold cache, FMP up: first view takes ~2-4 s for the section only (spinner/skeleton),
   the rest of Summary is already visible.
10. FMP paused (`FMP_ENABLED=false`, restart): a previously-viewed ticker shows its cached
    list with the old "as of"; a never-viewed ticker shows a "not cached yet" note, distinct
    from "no ETFs hold this"; no page-level error.
11. Settings -> Status -> FMP card lists "ETF Holders".
12. Click Refresh on the ticker header -> holders row is cleared and refetched on next view.

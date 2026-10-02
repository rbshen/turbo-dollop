# Tracked-universe expiry: investigation (2026-10-02)

Phase 1, report only. No code, DB or cron change was made. Read-only queries against `backend/fathom.db` plus one
read-only FMP probe (profile, quote, daily EOD for AVB/EQR/EA, and the full `/delisted-companies` list). No earlier
investigation file existed, so this is written from scratch.

**Goal (decided with the owner):** a ticker is in the nightly universe only if it is (a) in the S&P 500, Nasdaq-100 or
Dow lists, (b) on a watchlist, (c) part of a system set the app needs (11 sector ETFs, SPY, similar), or (d) was
viewed in the last 30 days. A viewed-only ticker leaves the nightly jobs 30 days after its last view and re-enters on the
next view. Opening any ticker page must still work on demand. Excluding a ticker must not delete its data.

## Read this first: user-facing features that lose tickers

| Feature | What happens at day 30 under the rule exactly as stated | Count today |
|---|---|---|
| **Screener (default universe `all`)** | `GET /api/screener?universe=all` returns every `TickerScore` row, so the viewed-only stocks are on the page today. Their rows are not deleted, but they stop being recomputed. Either they stay visible with frozen numbers, or they are hidden. This needs a decision (below). | 49 live viewed-only stocks of 580 rows shown (another 5 are already hidden as delisted) |
| **Monthly Momentum ranking** | The ranking universe is "tracked tickers with a manual Moat rating". A Moat-rated viewed-only ticker that expires silently drops out of the next snapshot. | 29 of the 403 rows in the 2026-09-30 snapshot |
| **Saved Screener views** | The 3 saved views (`No Moat >SPY`, `Wide All score passed`, `Narrow All score passed`) are all `universe=all` and would show fewer rows. They store filters, not results, so nothing stored goes stale. | 3 |
| ETF page Overview, Trading data block | Reads only cached bars. A dropped ETF's bars stop refreshing, so on its first re-view the performance and volume rows are omitted until the Technical or Chart tab fetches bars. | 7 ETFs |
| Ticker search while `profile_quote` is off | The fallback matches symbols in the universe; an expired ticker is not matched. | edge case |

**Recommended rule change (needs the owner's call): add (e) "has user-authored data" to the protected set**, meaning a
`TickerMoat` row, an active `TickerCustomValuation`, or a `TickerBankCapitalMetrics` row. Without it, 29 Moat-rated
tickers fall out of Momentum for something the owner did deliberately. With it, 20 stocks and 7 ETFs actually expire at
day 30 (list in section 3).

## 1. What "tracked" means today

There is no table, flag or timestamp for "tracked". It is a derived set, defined once in
`backend/pipeline/nightly_fundamentals_fetch.py::load_full_tracked_universe` (the 2026-08-06 "index + ever-viewed +
watchlisted" decision):

```
index constituents (sp500 + dow + nasdaq via IndexConstituent)
  UNION every ticker with a cached FMP profile (FundamentalsCache.statement_type == "profile")
  UNION every ticker with a TickerScore row
  UNION every ticker on any Watchlist (WatchlistTicker)
```

**How a ticker enters.** Opening its page: `GET /api/tickers/{t}/summary` (`data/ticker_summary.py::get_summary`) caches
the profile, and `GET /api/tickers/{t}/score` (or any Watchlist row compute) writes the `TickerScore` row. Ticker search
does not add one (the ETF spec relies on that). Watchlisting alone adds a ticker through the watchlist leg.

**Does anything remove one? No.** Once a profile row or a `TickerScore` row exists, the ticker stays, because the nightly
jobs themselves refresh the profile every night and rewrite the score row. The only deleters are
`pipeline/purge_invalid_tickers.py` (empty profile, never an index member) and `pipeline/non_us_purge.py` (non-US
listing), and `prune_cache` (see section 4). The `prune_cache` docstring still says growth comes from "one-off lookups of
tickers outside the universe that are never revisited". That premise has been false since 2026-08-06.

## 2. Which universe each job iterates

Universe size on 2026-10-02: **595** (profile 595, scored 595, index 518, watchlisted 135 distinct).

| Job (cron) | Universe | Per-run FMP calls (observed) |
|---|---|---|
| `nightly_last_close_snapshot` (1:00) | `load_us_price_target_universe` = tracked, US-listed, minus delisted | ~1/ticker: 581-589 |
| `nightly_trend_calculation` (1:05) | tracked minus delisted, plus SPY benchmark in the same batch; the only job that fills the daily-bar cache | ~1 bar call/ticker incremental; weekly (Sunday UTC) full 5y resync |
| `nightly_liquidity_zone_calculation`, `nightly_entry_signal_calculation`, `nightly_warren_signal_calculation` | **monitored watchlists only** (`list_monitored_tickers`), 105 tickers | not affected by this work |
| `nightly_sector_heatmap` (1:35) | hard-coded 11 sector ETFs (`SECTOR_ETFS`) | 11 |
| `nightly_market_breadth` (1:40) | `IndexConstituent` sp500 only | warm cache, ~0 |
| `nightly_corporate_events` (disabled) | tracked US | ~1,165 when enabled |
| `nightly_fundamentals_fetch` (2:00) | tracked minus known ETFs/funds (`load_fundamentals_fetch_universe`), 585 tickers; **does not exclude delisted** | 5 to 223 on a warm night, 2,626 on the 2026-10-01 expiry wave (~4.5/ticker); a cold ticker costs ~12 |
| `monthly_momentum_snapshot` (2:50, days 1-5) | tracked, Moat-rated, not delisted, not ETF (`data/momentum_data.py`) | 4 (cache-only) |
| `nightly_price_target_snapshot` (3:10) | US-listed tracked minus delisted minus known ETFs | ~1/ticker: 581-582 (91 on 2026-10-02, 1-day cache) |
| `nightly_score_recompute` (3:25) | whole tracked universe, 595, cache-only | 0 |
| weekly `stale_data_health_check` | whole tracked universe (staleness report, delisted sync, non-US purge) | ~160 delisted-list pages |
| weekly `non_us_purge`, `purge_invalid_tickers` | tracked universe / all cache rows | 0 |
| backfills (`backfill_fmp_daily_bars`, `backfill_price_target_snapshots`) | tracked universe | one-off |

**Readers of the universe that are not nightly jobs:** `momentum_data` (above), `ticker_search._search_tracked_universe`
(only while `profile_quote` is off), `known_etf_tickers` (search badges, reads the profile and score tables directly, not
the universe). The Screener does not call the universe function; it reads `TickerScore` directly. Watchlist views compute
each row on demand and are independent of the universe.

Steady state is about 3 calls per ticker per night (last close, price target, bars) plus the fundamentals refresh wave.

## 3. Current universe by reason (read-only counts, 2026-10-02)

| Reason (first match) | Tickers |
|---|---:|
| Index members (sp500 503, dow 30, nasdaq 102, union) | 518 |
| Watchlist, not an index member (11 on a monitored list; `SEIC`, `CNSWF` only on non-monitored lists) | 13 |
| System sets (sector ETFs, SPY) that are in the universe only because they were viewed: SPY, XLK, XLV | 3 (counted in viewed-only below) |
| **Viewed-only** (no index, no watchlist) | **64** |
| Total | 595 |

Watchlist union is 135 tickers; 122 of them are also index members, so watchlists add only 13. The monitored union is 105.
The two non-monitored lists, `W score passed` (50) and `N scores passed` (33), are one-off snapshots created on 2026-09-04
and untouched since. All but `SEIC` and `CNSWF` are index members, so protecting any watchlist (rule (b), as today) costs
2 tickers of protection.

**The 64 viewed-only tickers:**

- 10 ETFs: GLD, IBIT, QQQ, SMH, SOXX, SPY, TECL, TLT, XLK, XLV. SPY, XLK, XLV are protected by the system set.
- 54 stocks, of which 5 are delisted-flagged (AVB, EA, EQR, TWTR, WBA) and 49 are live. Of the 49, **29 have a Moat,
  custom valuation or bank-capital entry**; the **20 without** are: AAP, ACHR, ASTS, AXTI, BB, BLDR, CNI, CRCL, ETSY, FLY,
  IONQ, JOBY, PARA, RIVN, SINGY, SOUN, TAP, TMP, TXG, WCN.
- Expiry outcome with rule (e): 20 stocks plus 7 ETFs (GLD, IBIT, QQQ, SMH, SOXX, TECL, TLT) leave the jobs at day 30
  (27 tickers, 4.5% of 595), and the 5 delisted ones should leave at once (below). Without (e): 49 + 7 + 5 = 61.

**Is there a last-viewed signal today? No reliable one.** There is no view column, table or access log
(`logs/uvicorn_dev.log` is 850 bytes). Every candidate proxy is polluted by the nightly jobs themselves:
`FundamentalsCache.fetched_at` and `TickerScore.computed_at` are rewritten nightly for all 595; the earliest cache row
gives only a rough "first seen" date (2026-07-18 onward for the oldest viewed-only tickers). `NewsCache` is view-driven but
holds 9 rows and covers only the News tab. So the backfill cannot recover real view times: every viewed-only ticker gets
the migration date.

**What recording a view takes.** One small table `TickerView(ticker PRIMARY KEY, last_viewed_at)`. Write point:
`GET /api/tickers/{t}/summary` in `core/main.py`, after `get_summary` succeeds (not on `TickerNotFoundError`). That route
is hit only by ticker pages (header, Summary, Chart, Analyst Ratings tabs all share `useTickerSummary`); the ETF page uses
it too; Watchlist and Screener do not. At most once per day per ticker, in a single statement and no pre-read:
`INSERT ... ON CONFLICT(ticker) DO UPDATE SET last_viewed_at = :now WHERE last_viewed_at < :start_of_today`. Wrapped in a
try/except so a DB hiccup never breaks the page (the same rule as the cron heartbeat). Left-open tabs revalidate through
SWR and so count as a view once per day; accepted.

## 4. Side effects of dropping a ticker (soft exclusion, nothing deleted)

| Data | Effect |
|---|---|
| `FundamentalsCache` rows | Stay, but stop refreshing. **`prune_cache` (weekly) deletes rows older than 180 days**, so a dropped ticker's cache rows disappear about 210 days after its last view. The `TickerScore` row survives, and the page re-fetches on demand. This is existing behaviour that now becomes reachable; recommend leaving it (bounding growth is its purpose) and recording it. |
| `TickerScore` row | Stays, frozen at its last recompute. Hidden from the Screener under option A below. |
| `TrendAnalysis` (Weinstein) | Stays. The ticker page recomputes on demand when stale (`get_trend_analysis_data`, `cache_only=False`), so the page is correct on re-view. |
| Daily bars (`SharedBarsCache`), `LongHistoryBars` | Stay; refetched on demand by Technical/Chart. |
| `PriceTargetSnapshot` history (2,915 rows), `MomentumSnapshot` history (87 rows), `TickerLastClose` | Stay. Accrual stops; history intact. |
| Liquidity zones, BB+RSI, Warren | Unaffected: monitored-watchlist only, by watchlist, not by this rule. |
| User-authored data (Moat, custom valuation, bank metrics) | Never touched by any job. Protected by (e) from the nightly drop. |
| Header Assessment chip | **Gap:** `GET /score` returns a stored row unless it is missing or has no overall score, so the first view of an expired ticker would show a stale chip. Needs a staleness self-heal (recompute when `computed_at` is older than ~36 h). Nightly keeps universe members under that bound, so it never fires for them. |
| Re-add on view | The next night's jobs include it again. Same-day, the page itself fetches everything on demand. |

**Screener options for the expired stock rows:**

- **A (recommended): the Screener's `all` universe, `screener_list` and `screener_meta`, filter to the same helper.**
  Expired tickers disappear from Screener and from the "X of Y" count, and reappear on re-view. Honest: no frozen scores
  presented as current. Loses the 20 tickers (49 with no (e)).
- B: keep showing frozen rows. Nothing visible changes, but those scores silently go stale with no marker.

**Non-monitored lists (`W score passed`, `N scores passed`).** They behave like any list for the universe (a ticker on any
list is in, as today) and do nothing else; the monitored rule applies only to LP, BB+RSI and Warren. Recommend any
watchlist protects (rule (b) as stated). Cost is 2 tickers (`SEIC`, `CNSWF`); if those lists are stale scratch, deleting
them is the owner's one-click way to let those two expire.

## 5. Why TWTR, WBA, EA, AVB, EQR are flagged

**Mechanism.** `stale_data_health_check` (weekly, Sunday) pages FMP `/delisted-companies` and sets
`TickerScore.delisted_at` for any tracked ticker listed with a delisted date on or before today (guard: skip when the
cached profile `ipoDate` is after the delisted date, a reused symbol). All five were flagged in one run, 2026-09-24
10:17. "Every night" is the nightly jobs' skip line ("5 skipped as delisted", Weinstein and last-close/price-target
filters), not re-flagging. **The flag is sticky: nothing ever clears it**, even if the ticker is later relisted or was a
mistake.

**Probe results (2026-10-02, FMP live):**

| Ticker | FMP delisted date | Profile `isActivelyTrading` | Last EOD | Verdict |
|---|---|---|---|---|
| TWTR | 2022-10-27 | false | 2022-10-27 | genuine |
| WBA | 2025-08-29 | false | 2025-08-27 | genuine (taken private) |
| EA | 2026-08-05 | false | 2026-08-04 | genuine |
| AVB | 2026-08-17 | false | 2026-08-24 | corporate action, not a feed glitch |
| EQR | 2026-08-18 | false | 2026-09-04 | corporate action, not a feed glitch |

**AVB and EQR are not simple false positives, but not confirmed either.** Three independent facts in FMP's own data agree
they stopped trading: both are on the delisted list, both profiles read `isActivelyTrading: false`, and neither has a daily
bar after 2026-09-04 (the 2026-10-01 EOD fetch ends there). AVB's frozen quote (184.06, timestamp 2026-08-17) divided by
EQR's (63.66, 2026-08-17) is 2.89, and AVB's EOD history after the delisted date is rescaled to the ~65-68 range, which
fits a combination of the two REITs with an exchange ratio rather than two data errors. I could not confirm the event
from a second source (no EDGAR 8-K check was run), and EQR's bars run 2.5 weeks past FMP's own delisted date, so the date
FMP gives is imprecise. Treat AVB and EQR as genuinely no-longer-trading, pending an 8-K check if the owner wants one.

**What is lost.** Nothing is deleted. Effects of the flag: hidden from the Screener and Momentum, no Weinstein or
price-target refresh. **The cached daily bars stop earlier than FMP's data**: EQR at 2026-08-21 versus 2026-09-04 (about 10
sessions), AVB at 2026-08-24 (complete). EA and the other three are complete.

**Wasted work today.** The fundamentals job and the score recompute still process all five every night (the fundamentals
job does not exclude delisted, so each costs a refetch of every statement at each 7-day window, ~12 calls). All five are
viewed-only, so the new rule removes them on its own; recommend the helper also excludes `delisted_at`-flagged tickers
immediately (they are the one case where waiting 30 days has no value). EA has a Moat, so rule (e) must not protect a
delisted ticker.

## 6. Smallest design

1. **One shared helper, defined once** (the monitored-watchlist pattern): new `backend/data/tracked_universe.py` with
   `TRACKED_VIEW_WINDOW_DAYS = 30`, `SYSTEM_TICKERS` (the 11 `SECTOR_ETFS` symbols plus the Weinstein benchmark SPY,
   imported from their owners, not retyped), `load_tracked_universe(session, today=None)`, `record_ticker_view(ticker)`,
   and `load_all_known_tickers(session)` (the old wide set). Membership is the union of: index lists; any
   `WatchlistTicker`; `SYSTEM_TICKERS` that are already known (protection, not insertion: nothing new is created for
   them); (if approved) tickers with user-authored data; and `TickerView.last_viewed_at >= today - 30 days`; minus
   `delisted_at`-flagged tickers. `load_full_tracked_universe` stays as a thin delegating name so its ~12 import sites do
   not churn.
2. **Which jobs use which function.** Expiring `load_tracked_universe`: last close, Weinstein, fundamentals, price target,
   momentum, score recompute, corporate events, the Screener `all` universe and its meta count. Wide
   `load_all_known_tickers` (hygiene and lookup, cheap and local): `non_us_purge`, `purge_invalid_tickers`,
   `stale_data_health_check` (so a non-US or delisted expired ticker is still found and handled), and the search fallback.
   `tests/test_watchlists.py` already pins that no job re-declares the monitored pattern; add the same guard here.
3. **Last-viewed recording.** New `TickerView` table (created by `create_all`, no `_add_missing_columns` needed), written
   from the `/summary` route at most once per day per ticker (section 3).
4. **Backfill with a fresh 30-day grace.** Seed inside `init_db()` the way `LiquidityZoneConfig` and the data groups are
   lazy-seeded: if `TickerView` is empty and the legacy universe is not, insert every legacy ticker with
   `last_viewed_at = now()` (idempotent, `INSERT OR IGNORE`). Doing it in `init_db()` means it cannot be forgotten, since
   `bin/start.sh` and every cron call it. Index, watchlist and system tickers get a row too (harmless). Also ship
   `pipeline/seed_ticker_views.py --dry-run` to print the counts before and after. Grace ends 30 days after the migration
   date, so no ticker expires before then.
5. **Soft exclusion.** Nothing is deleted; no job, table or cron time changes. Only membership functions change. The
   rollback is: revert the commit; the `TickerView` table is inert and can be dropped.
6. **Header chip staleness self-heal** in `ticker_score_out` (recompute when `computed_at` is older than ~36 h), so a
   re-view of an expired ticker never shows a frozen score. ETF Overview: let the overview route warm cached bars (one
   fetch) so its Trading data block is not empty on a re-view, or accept the gap for the 7 ETFs.
7. **Tests.** Helper unit tests (each of the four reasons, expiry boundary at day 29/30/31, delisted exclusion,
   protection-not-insertion for system tickers, (e) if approved); `record_ticker_view` once-per-day and 404 not
   recorded; `init_db` seed idempotent and grace dates; Screener `all` and meta use the helper; the guard test; update the
   existing tests that pin the old union (`tests/test_nightly_fundamentals_fetch.py`, `test_nightly_score_recompute.py`,
   `test_etf_page.py:529`).
8. **Docs.** `docs/specs/overview.md` (the "profile cached = ever-viewed" paragraph and Screener universe text),
   `docs/specs/price-target.md` (universe paragraph), `docs/specs/weinstein-stage.md` (sweeps the full tracked universe),
   `docs/specs/etf-page.md` (score recompute, momentum, search "still use the full tracked universe"),
   `docs/specs/fmp-data-and-bar-cache.md` (2% purge guard), `backend/OPS_RUNBOOK.md` (three universe mentions plus the
   prune_cache note), `CLAUDE.md` (a Tracked universe section next to Watchlists), `docs/decisions.md` (a 2026-10-02 entry
   that supersedes the 2026-08-06 "index + ever-viewed + watchlisted" decision).

**Size.** Helper module about 90 lines; `TickerView` model about 12; `init_db` seed about 25; route hook plus score
self-heal about 25; Screener `all` and meta about 15; swapping imports in about 9 jobs about 20; tests about 250; docs
about 8 files. Roughly one focused session. Backend only: the Screener change is server-side, so no frontend change.

**Expected effect (estimates, not measured).** Universe 595 to about 563 at day 30 with (e), about 534 without; the 5
delisted leave immediately. Steady-state saving about 3 calls per dropped ticker per night, so roughly 80-170 of the ~1,800
nightly calls (5-9%), plus about 4.5 calls per ticker on each fundamentals refresh wave, plus about 1 s of CPU each across
the technical jobs. `nightly_score_recompute` drops from 595 to the new size.

## 7. Risks and conflicts

- **Screener and Momentum lose tickers** (top of this file). The one owner decision that matters: add (e), and choose
  Screener A or B.
- **Conflict with the stated rule:** (e) is an addition; the rule as written is (a)-(d) only.
- **No ETF momentum universe exists.** `docs/specs/sector-heatmap.md` records the ETF momentum ranking as "investigated,
  not built", so (c) today is just the 11 sector ETFs and SPY (the Weinstein benchmark, also read for the 5Y-vs-SPY pill).
  Sector ETFs are fetched by their own hard-coded job, so (c) is protection for the ones already present, not a new list.
- **Sticky delisted flag.** A mistaken flag silently hides a live ticker forever. Out of scope here; worth a follow-up
  (clear when the profile reads `isActivelyTrading: true` and a recent bar exists).
- **`prune_cache`** will start deleting expired tickers' cache rows after 180 days (section 4).
- **View accounting is approximate:** SWR revalidation on open tabs counts as a view; a view of a ticker whose `/summary`
  404s is never recorded.
- **The backfill grace is a hard date:** all current viewed-only tickers expire together on the same night 30 days after
  deployment if not re-viewed, producing one visible step in the Screener and the call counts.

## 8. Decisions needed before Phase 2

1. Add rule (e), protect tickers with a Moat, custom valuation or bank-capital entry? (Recommended: yes.)
2. Screener `all`: option A (hide expired) or B (keep frozen rows)? (Recommended: A.)
3. Exclude `delisted_at`-flagged tickers from every universe immediately? (Recommended: yes.)
4. Leave `prune_cache` as is? (Recommended: yes.)
5. ETF Overview: warm bars on view, or accept the gap? (Recommended: warm.)

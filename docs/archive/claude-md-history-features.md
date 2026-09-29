# CLAUDE.md history: features

Verbatim history moved out of the original CLAUDE.md (archived at docs/archive/CLAUDE.original.md). Text is unedited; line ranges refer to that file.

## Analysis tab section-card reasoning (original lines 1614-1720)

### Analysis tab section-card reasoning (2026-09-05)

Each of the 4 Analysis-tab section cards (`frontend/components/step{1,2,4,5}/
Step{N}Card.tsx`, via the shared `AnalysisSectionCard`) always shows a
consistent 2-part reasoning block above the collapsible per-component
bullets: a verdict sentence and a static one-line methodology summary. This
is a frontend-only change for the verdict/methodology lines themselves —
`scoring/overall.py`/`overallScore.ts` never carried reasoning text, only
the score/verdict numbers the cards already had access to.

A section-level `Score: <score>/100 · Weight: <weight>% of Overall
Assessment` trailing line (reading the weight from a since-removed
`overallScore.ts::overallWeightPct(key)` helper) shipped in the same commit
as the verdict/methodology fix above, then was removed the same day per
follow-up review feedback — not wanted at the section level at all. In its
place, **every per-component bullet across all 4 sections now shows that
component's own weight and score inline** — e.g. "Revenue (35%, 100/100):
Grows every year" — via a shared `AnalysisSectionCard.tsx::
weightScoreSuffix(weight, score)` helper, so the format is identical across
cards. This weight is the component's share of its OWN section's blend
(e.g. Financials' Revenue/Net Income/CFO/Margins/FCF split), never the
Overall Assessment step weight the removed line showed — a different
number entirely, already available per-component in each step's own
`weights` dict.

- **Every component in all 4 sections already had a real 0-100 score
  feeding its section's blend** — including every Debt ratio
  (`Step5RatioResult.points`, e.g. Current Ratio/Debt-to-EBITDA/DSR/
  Gearing/CET1/NPL all carry a real graduated point value that literally
  feeds `score = sum(points * weight)` in `scoring/step5.py`), contrary to
  an initial assumption that some might be pure pass/fail checks with no
  natural numeric score. No fabricated/derived-for-display score was
  needed anywhere.
- **Step4Out was the one genuine gap**: `scoring/step4.py::score_step4`
  already computed a `weights` dict (`BASE_WEIGHTS`, proportionally
  renormalized across whichever of ROE/ROIC/Revenue-vs-AR/CCC apply for
  the ticker's company type), but it was silently dropped rather than
  reaching the API — `Step4Out` had no `weights` field at all before this
  fix, unlike Step1Out/Step2Out/Step5Out. Added `Step4Out.weights` and
  threaded `result["weights"]` through in `step4_data.py`.
- **Key-naming mismatch, found and fixed in the same change**:
  `score_step4`'s internal `weights` dict keys the Revenue-vs-AR entry
  `"ar"` (matching `BASE_WEIGHTS`), but `components` keys the same metric
  `"revenue_vs_ar"`. `step4_data.py` remaps `"ar"` → `"revenue_vs_ar"`
  before constructing `Step4Out` so `weights`/`components` share one
  consistent key set for API/UI consumers — `scoring/step4.py`'s own
  internal naming and its existing tests (which assert `weights ==
  {"roe": ..., "ar": ..., ...}`) are untouched.
- **Company-type exemptions and Bank/Standard regime-switching needed no
  new logic at all** — already handled correctly by each card's existing
  null-filtering (a REIT's CFO/FCF/ROIC/CCC components are already omitted
  entirely, not shown with a placeholder score) and by `weights`-keyed
  lookups (a Standard ticker's `weights` dict simply has no
  `cet1_ratio`/`gearing_ratio` keys, so those bullets never render; a
  reclassified-to-Standard ticker like IBKR/HOOD/SEIC/SEZL — see below —
  automatically shows ordinary Current-Ratio/Debt-to-EBITDA/DSR bullets
  with real weight/score, not a skipped-Bank placeholder, with zero
  Step5Card changes needed). Confirmed on real cached data: **JPM** (real
  Bank, CET1 50%/100, NPL 50%/100), **O** (REIT, Profitability 100%-ROE-
  weighted, Debt 100%-Gearing-weighted), **SEZL** (reclassified Standard,
  ordinary 3-ratio Debt split), **F** and **HON** (Fail cases — F's
  Debt/EBITDA correctly shows a real `negative_ebitda`/0-of-100 scored
  bullet at its normal 33% weight, not hidden or faked).

- **Financials' verdict sentence was wrong, not missing.** It showed a
  description of its own internal component weighting (e.g. "Weighted
  blend of revenue (35%), income (20%)... — not a per-component pass/fail
  count.") where every other section showed a real verdict sentence (e.g.
  Debt's "At least one ratio breached its hard limit."). Root cause (via
  git blame, commit `89b1728`, 2026-08-08): a deliberate fix that
  correctly removed an earlier, misleading "N of 5 components pass"
  framing (Step 1 is a continuous weighted blend, not a discrete gate) —
  but replaced it with pure methodology text and never restored an actual
  verdict, rather than a stub or placeholder. Financials has no hard-fail
  override at all (`score_step1` is a pure weighted blend against the
  shared 0-69/70-90/91-100 bands, unlike Debt/Profitability's hard-fail
  overrides), so the fix names whichever components actually scored below
  70 instead (e.g. "Cash Flow from Operations, Margins, and Net Income
  scored below the Pass threshold, pulling the blend down to a Fail.") —
  the per-component weight percentages this verdict sentence used to carry
  moved to the (already-existing) collapsible bullets instead, alongside
  each component's own tier.
- **The same class of bug, found via the same investigation, also existed
  in Debt and Profitability**, just less visibly: both have a documented
  score<70 verdict-floor fallback (`_verdict_for` in each's own
  `scoring/step{4,5}.py`) that can produce a Fail verdict with
  `hard_fail=false` — a mediocre blend with no actual ratio/ROE breach.
  Before this fix, the card still displayed "No ratio breached its hard
  limit." (Debt) / "Neither ROE nor ROIC breached its Fail tier." (Step 4)
  next to a Fail badge — confirmed live on real cached data: **HON** (Debt,
  score 67, `hard_fail=false`, verdict Fail) and **AVB** (Debt, score 60,
  same) for the Debt case; **F** (Profitability, score 44, `hard_fail=
  false`, verdict Fail) for the Profitability case. Both cards now have a
  third branch naming the actual mechanism ("No individual ratio breached
  its hard limit outright, but the blended score still fell short of the
  Pass threshold." / "Neither ROE nor ROIC breached its Fail tier
  outright, but {weak components} still pulled the blended score below the
  Pass threshold.") — Bank/Insurance/`pass_with_caution`/hard-fail branches
  are otherwise unchanged.
- Growth Rate's existing verdict sentence (`rationale()` in Step2Card.tsx)
  was already specific and accurate (states the actual growth %, basis,
  and analyst-agreement tier) — only the methodology line and score/weight
  line were added there, no verdict-text change.
- Existing exemption notes (CFO-exempt, ROIC/CCC/Revenue-vs-AR-exempt,
  Bank/Insurance blurbs) are unaffected — they render in the same `notes`
  slot as before, underneath the new methodology/score/weight lines.


## Insider Activity (fully deleted 2026-09-27) (original lines 4065-4200)

## Insider Activity (ticker-page tab, 2026-09-19) -- SHELVED 2026-09-20, FULLY DELETED 2026-09-27

**Fully deleted, not just shelved -- superseded by commit `6410970`.** The
description below (shelved, code left in the tree, revivable) was accurate
from 2026-09-20 through 2026-09-26 but is now historical: `6410970`
("Remove insider group, shelve news by default, move delisted-companies
group, restructure Settings") removed the FMP client methods,
`data/insider_activity_data.py`, the `/insider-activity` endpoint, the
`insider` data-group entry itself (registry + endpoint/statement-type/canary
maps), `insider_staleness_days`, every `Insider*` schema, and the whole
frontend feature (tab, cards, hook, types) outright. There is no `insider`
group left to re-enable and no code left to revive -- reviving the feature
now means rebuilding it, not flipping a toggle. Kept below as a historical
record of how the shelved (2026-09-20 to 2026-09-26) state worked, not as
current instructions.

The `insider` data group's user toggle (seeded **off**;
`INSIDER_ACTIVITY_ENABLED` was deleted 2026-09-24, see "Data groups" above)
gates `get_insider_activity_data` --
checked first, ahead of `cache_only`, so when off there is no FMP call and no
cache read or write. The route just calls that function and inherits the gate;
it returns 200 with `enabled: false` and every other field empty (mirroring
`CronHealthOut.enabled`), never a 404 -- so it's distinguishable from
"cached and genuinely empty" (`enabled: true`, `as_of` set) and "not cached
yet" (`as_of` null). The tab is off the ticker page (dropped from
`lib/tickerTabs.ts`'s `TickerTab`/`TICKER_TABS` and `TickerTabsContainer`) and
"Insider Activity" is off the Status page's `FMP_POWERS` list; it never had a
cron job, so Scheduled Jobs needed nothing. The two cache keys (`insider_trading_search`,
`insider_trading_statistics`) were purged from `FundamentalsCache` 2026-09-20
(22 rows, 11 tickers). **To revive (historical -- no longer applicable, see
above):** turn the `insider` group on in Settings > Status
(no restart), re-add `"insiderActivity"` to the `TickerTab` union and
`TICKER_TABS` (between Analyst Ratings and Technical), the
`InsiderActivityTab` branch in `TickerTabsContainer`, and the `FMP_POWERS`
entry. The seeded conftest state has `insider` off; the feature's own tests
turn it on explicitly. Everything below describes the feature as built.

A read-only lens on Form 4 insider trading -- never touches Step 1-5/Overall
Assessment scoring, no Screener/Watchlist surface. FMP-sourced (the "Insider
Activity" entry in `StatusSection.tsx`'s `FMP_POWERS`); no cron job, no new DB
table, no new heartbeat wiring.

- **Data** (`data/insider_activity_data.py`, `GET /api/tickers/{ticker}/insider-activity`):
  two standard `FundamentalsCache` blobs, `insider_trading_search`/`latest`
  (`/stable/insider-trading/search`, paged -- see "Search paging" below) and
  `insider_trading_statistics`/`latest` (`/stable/insider-trading/statistics`),
  both via `get_or_fetch` + `safe_fetch` on the dedicated
  `Settings.insider_staleness_days` (1 day, not the shared 7 -- Form 4s are
  event-driven, not earnings-cycle-driven).
- **Search paging (2026-09-20).** A single 100-row request covered under half a
  year for busy filers, so the table/cluster check saw a fraction of the chart's
  12 quarters. `_fetch_search_history` pages (`SEARCH_PAGE_SIZE` 500,
  `SEARCH_MAX_PAGES` 4) until the chart window is covered. Measured live: 12
  quarters needs ~600 rows for AVGO, ~1000 for FTNT, ~1600 for NVDA, and META
  exceeds 3000 (hits the cap). **FMP orders rows by FILING date, not transaction
  date** (verified monotone on AVGO/FTNT/NVDA) -- a late filing or Form 5 can
  carry a 2020 `transactionDate` deep inside a recent page, so the stop check is
  "oldest *filing* date fetched < window start" (a filing is never earlier than
  its transaction, so this bounds everything unfetched). Judging by
  `min(transactionDate)` stopped FTNT's paging after two pages. Per-request
  latency is a flat ~1s regardless of page size (measured 100-1000 rows), so
  pages are large to minimise round trips; the cost is overfetching up to one
  page (AVGO fetches 1000 for ~600 needed). Live coverage: AVGO/FTNT/MSFT/NVDA
  12/12 quarters; META 7/12 (capped). The cached blob is `{rows, exhausted}` --
  `exhausted` separates "FMP has nothing older" (a quiet ticker: older quarters
  are real zeros) from "we stopped at the cap" (older quarters are unseen);
  legacy bare-list blobs read as capped iff they hold a full 100 rows. A
  later-page failure keeps the rows already fetched; a first-page failure
  propagates (cold miss, nothing cached, as before).
- **Normalization is backend-only** -- the frontend never sees FMP's raw
  transaction codes. Rows with an empty `transactionType` (Form 3/5 position-
  only disclosures) are dropped; the rest are classified by the SEC code letter
  before the hyphen (`P` open_market_buy, `S` open_market_sale, `M`
  option_exercise, `A` award, `G` gift, everything else `other`) -- a fixed
  mapping, **not** fetched from `/insider-trading-transaction-type` at request
  time (SEC Form 4 codes are a fixed standard; a third FMP call per view buys
  nothing). Non-open-market rows priced at $0 get `has_cash_value: false`
  ("no cash value" in the UI, never "$0"); `dollar_value = price * shares` only
  when `has_cash_value`.
- **Aggregates**: the sentiment sums `totalPurchases`/`totalSales` over the 2
  most recent quarterly statistics rows (a "last 2 filed quarters"
  approximation, not a true rolling 6 months) and compares them directly --
  `net_buying`/`net_selling`/`no_activity`/`mixed`, a first-pass rule with no
  materiality band (retune in `classify_sentiment`). Cluster buy = 3+ distinct
  `reportingCik` with open-market buys within 90 days (inclusive), scanning
  this ticker's own search rows only -- **no `/latest` market-wide scanner**,
  deferred. The reported cluster is the most recent qualifying window, which
  can be old (the fetched history isn't recency-limited), so the pill's
  tooltip carries the window dates. Open-market buy/sale *counts* come from
  the normalized transactions over the same window as the totals.
- **Quarterly chart is transaction-derived, not the statistics endpoint
  (2026-09-20).** `totalAcquired`/`totalDisposed` count exercises, tax
  withholding and gifts alongside real sales (overstating "selling" by roughly
  half on a typical quarter, 100% on some) with no way to split them.
  `build_quarterly_activity` sums shares per calendar quarter from the
  normalized transactions, bucketed by `transactionDate`: `open_market_*` (P/S
  rows -- the default view, matching the sentiment summary) and `all_*` (every
  row carrying an acquired/disposed flag). Window = the 12 calendar quarters
  ending at the newest transaction's quarter, gaps zero-filled. Open-market
  direction is pinned by kind, not FMP's `acquisitionOrDisposition`, which
  mislabels some `S-Sale` rows `A` -- the only reason FTNT's 2024 Q1/Q2 differ
  from the stats endpoint (AVGO matches 12/12, FTNT 10/12). A ticker that hit the
  fetch cap drops quarters that begin on/before the oldest filing fetched (a
  partly-filled bar would read as a real, smaller total) and sets
  `history_truncated`, which the tab surfaces as a caption. The statistics
  endpoint still feeds the sentiment `totalPurchases`/`totalSales` (transaction-
  count-based, confirmed correct) -- only the chart's source changed. The
  existing Open market / All types toggle drives the chart and the table from
  one state in `InsiderActivityTab` (a synced control on each). The table
  renders 100 rows at a time ("Show N more") since the deeper fetch returns
  hundreds.
- **Notable-trade cards merge same-day, same-insider lines (2026-09-20).** Form 4
  splits one real sale into several price-band lines, so the largest single
  *line* understated it (AVGO: card showed one ~$40M line vs. a real $250.0M
  same-day sale across 22 lines; confirmed wrong on 9/11 tested tickers).
  `_largest_same_day` groups open-market lines by (`reportingCik` or name,
  `transactionDate`) per kind, sums shares/dollars, reports a share-weighted
  average price and `fill_count` (shown as "N fills" when >1). Deliberately
  same-day only -- wider windows added meaningfully on 3/11 tickers and would
  merge genuinely separate 10b5-1 drip sales. This is the only "largest" call
  site (the table has no per-row largest styling).
- **One name and one role per `reportingCik`.** Every row for a CIK carries its
  most recent row's name spelling (as filed -- not a synthetic re-casing, which
  would mangle "McDonald"/"O'Toole") and most recent *non-blank* role, so a blank
  latest `typeOfOwner` can't blank a role and casing variants ("Hennessy John
  L." vs "HENNESSY JOHN L") collapse. `fmtInsiderRole` parses FMP's flag list
  (`director, 10 percent owner, officer: <title>`) into one label joined by " / "
  ("Director", "Director / CEO", "Director / 10% owner / Chief Strategy
  Officer"); a title-less officer reads "Officer", blank reads null.
- **`as_of` = the search row's `fetched_at`** (null if never cached). It is the
  only thing separating "cached and genuinely empty" (HK/France/quiet tickers:
  FMP answers `[]`) from "not cached yet" (cold miss -- FMP paused, or the fetch
  failed, e.g. a plan that doesn't cover the endpoint: `safe_fetch` swallows the
  HTTP error and nothing is cached). The tab renders two distinct empty states
  off it (`lib/insiderActivity.ts::insiderViewState`) -- never conflate them.


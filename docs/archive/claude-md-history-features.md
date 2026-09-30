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



## Ad-hoc reproduction scripts must not touch the real database (original lines 257-375)

### Ad-hoc reproduction scripts must not touch the real database

`backend/fathom.db` is the one real database — `config.py`'s
`database_path` has no environment-based split between "real" and "test."
The only thing keeping test runs from polluting it is that every test in
`backend/tests/` explicitly constructs its own fresh in-memory engine
(`create_engine("sqlite://")`) and monkeypatches it onto every module's
`engine` reference *before* calling any `get_stepN_data`/`get_summary`/
`compute_ticker_score` function. `cache.py::get_or_fetch` has no way to
tell "this is a controlled repro" from "this is real" — it will silently
persist whatever `fmp_client` returns into whatever `engine` happens to be
bound at that moment, indistinguishable later from genuine FMP data.

Any one-off script that reproduces test-like behavior against real ticker
data (monkeypatching `fmp_client` to return controlled/fixture responses)
**must** follow the exact same convention: construct a fresh in-memory
engine and monkeypatch it onto every module's `engine` reference first.
Never monkeypatch `fmp_client` alone and call these functions against the
default (real, file-backed) `db.engine`. Confirmed root cause of the
original incident (2026-07-28): `backend/tests/test_debt_metrics.py`'s
"Acme Corp" profile fixture — used correctly, with proper engine
isolation, by the tests themselves at that time — ended up cached under
the real ticker **PEP** (and the inert placeholder ticker **ACME**) in
`backend/fathom.db`, live in production (`/tickers/PEP` and its Screener
card showed "Acme Corp") for several hours before being caught.
Root-caused to an ad-hoc script that mirrored the test's fixture/
monkeypatch setup but only patched `fmp_client`, not `engine`. Purged and
re-fetched 2026-07-28.

**This recurred 2026-08-04, via a different mechanism — not an ad-hoc
script this time, but the test suite itself.** `test_debt_metrics.py`'s
own two tests call `get_summary(ticker)` (`ticker_summary.py`), which
internally calls `get_step2_data()`/`get_step3_data()` — both of which
manage their **own independent `Session(engine)` blocks**, bound to
`data/step2_data.py`'s and `data/step3_data.py`'s own separate `engine`
imports. The test only monkeypatches `step5_data.engine` and
`ticker_summary.engine`, so `fmp_client`'s fakes (a true shared singleton,
correctly patched) flow through step2/step3_data's calls, but their
`get_or_fetch` cache **writes** land on the real, unpatched
`core.db.engine` — silently persisting fixture data into production,
exactly the same class of bug, just triggered by an ordinary `uv run
pytest` run rather than a bespoke script. `test_ticker_summary.py`
independently discovered and fixed the `step2_data.engine` half of this
same trap (see its own comment there) but that fix was never propagated
to `test_debt_metrics.py`, and neither test patches `step3_data.engine`.
Confirmed via `fetched_at` timestamps that this fired twice, from two
unrelated ordinary `pytest` runs, at 2026-08-04 05:28 and 21:31 — and was
**not caught by `audit_fixture_contamination.py`** despite that script's
existence, because the live installed crontab (`crontab -l`) was
confirmed to be byte-for-byte the original 2026-07-20 version, never once
reinstalled since (not after this incident's own original fix, not after
the later backend package reorg, not after `audit_fixture_contamination`
was finally added to `crontab.txt` on 2026-08-05) — so nothing in
`crontab.txt`, including this scanner, has ever actually been running on
schedule on this box. Purged and re-fetched again 2026-08-05 (PEP fully
re-fetched via the same `pipeline.nightly_fundamentals_fetch` code path
the nightly cron job uses per-ticker; `ACME`'s rows deleted outright, not
re-fetched, since it isn't a real ticker); PEP's `TickerScore` recomputed.
**Fully resolved 2026-08-05, three parts:**

1. `test_debt_metrics.py` now also monkeypatches `step2_data.engine` and
   `step3_data.engine` (matching `step5_data`/`ticker_summary`) — the
   actual fix, not just a symptom purge. Confirmed: this test now creates
   zero rows in the real DB, where every prior run had created 9 fake
   `ACME` rows without fail.
2. **The live crontab was reinstalled** (`crontab crontab.txt`) and
   confirmed byte-for-byte identical to `backend/crontab.txt` — it had
   been stuck on the original 2026-07-20 schedule the entire time,
   through the backend reorg and every job added since, including
   `audit_fixture_contamination` itself. (A prior release-readiness
   report had characterized the nightly fetch as "actively running,"
   inferred from the log file's recent mtime rather than a direct
   `crontab -l` vs `crontab.txt` diff — accurate at the moment it was
   checked, since neither had changed since 2026-07-20 either, but it
   couldn't have caught the reorg breaking the schedule hours later
   without anyone reinstalling it.)
3. **A session-scoped write-guard** (`backend/tests/conftest.py`, new)
   hooks SQLAlchemy's `before_cursor_execute` on the real `core.db.engine`
   for the whole pytest session and raises immediately on any write —
   catching every write path, not just `get_or_fetch`, so a future
   missing `engine` monkeypatch fails loudly in CI instead of silently
   reaching production. `test_write_guard.py` is a permanent regression
   test confirming the guard itself actually fires. Never active outside
   a pytest session (a real interactive/cron run never imports `pytest`).

Purged and re-fetched PEP 2026-08-05 (via the same
`pipeline.nightly_fundamentals_fetch` code path the nightly cron job uses
per-ticker); `ACME`'s rows deleted outright, not re-fetched, since it
isn't a real ticker; PEP's `TickerScore` recomputed.
`audit_fixture_contamination.py` confirmed clean after all three fixes,
with the full suite (589 tests) passing.

**Follow-up investigation (2026-09-23) found the 2026-08-05 manual
remediation above likely missed two cache rows.** `ratios`/`annual_10y`
and `analyst_estimates`/`latest` are cache keys only `step2_data.py`/
`step3_data.py` write (added by the same Step 3 rollout, `2a8a3ac`, that
opened this whole vulnerability window) — not part of the original
2026-07-28 incident's known-endpoint fingerprint, so the person doing the
2026-08-05 cleanup likely didn't know to force-refresh them. Live-DB
evidence: every other PEP row this bug could have touched shows
`fetched_at` from the 2026-08-05 15:21 remediation batch, but these two
show `fetched_at` of 2026-08-06 03:30 and 2026-08-13 00:45 respectively —
consistent with them being left on contaminated (empty-list) data that
only self-healed once each row's own 7-day `cache_staleness_days` window
naturally expired, rather than being explicitly purged. Circumstantial
only — no DB backup survives from that far back (retention currently
starts 2026-09-13) to directly confirm what those rows held beforehand —
and moot for current correctness, since both rows hold genuine PEP data
today. **Lesson for any future contamination remediation: force-refresh
every cache key the leaking code path can write, not just the keys in the
incident's own known fingerprint** — a code path can grow new cache keys
(as this one did) between when a fingerprint list was first written and
when it's next relied on.

`backend/pipeline/audit_fixture_contamination.py` (read-only, safe to run
anytime) scans `FundamentalsCache` for the same class of fingerprint and
should be run if this is ever suspected again — now genuinely running
weekly via cron (Sundays 1:20 AM), not just documented as if it were.



## Cron job heartbeat: FMP_ENABLED interaction investigation and nightly_price_target_snapshot guard-parity fix (original lines 401-433)

**`Settings.cron_health_enabled`** (`CRON_HEALTH_ENABLED` in `.env`,
default `true`, same read-once-at-process-start convention as
`fmp_enabled`) gates only this reporting/surfacing layer — when `false`,
`get_cron_health()` short-circuits to `{enabled: false, jobs: []}` before
touching the DB, and the Scheduled Jobs section renders nothing for cron
health, an explicit skip distinct from "checked and everything's ok". `cron_heartbeat()` itself is
never gated by this flag — `CronRunLog` rows keep being written regardless,
so history isn't lost and flipping the flag back on picks up right where
it left off. Investigated (2026-08-17) whether the heartbeat itself needs
a way to distinguish a job intentionally no-op'ing under `FMP_ENABLED=
false` from a genuine failure: confirmed every FMP call site across the 11
wired scripts existing at the time already sat inside a per-ticker
`try/except` that swallows `FMPDisabledError` before it reaches
`cron_heartbeat`'s own exception handler, so no wired job currently
produces a spurious `"failure"` row purely from an FMP pause — no
heartbeat change was needed for this flag. (The 12th job,
`pipeline.nightly_trend_calculation`, added later for the trend-structure
feature, needs no equivalent reasoning at all — it makes zero FMP calls,
so `FMP_ENABLED` never affects it either way; see "Trend structure
analysis (Technical)" below.)
(Separately found, and fixed the same day: `nightly_price_target_snapshot.py`
was missing the equivalent `if not settings.fmp_enabled: ...` early-return
guard `nightly_fundamentals_fetch.py` already had, so during an FMP pause
it still looped the full ticker list and reported a misleading `"success"`
with 0 tickers actually snapshotted, rather than skipping outright. Added
the same guard, placed identically (right after `init_db()`, before
resolving the ticker universe) — the comment there notes the one real
difference from nightly's version: this script never goes through
`cache.get_or_fetch` at all, so there's no `cache_only` distinction to
carry over, just a direct always-live `fmp_client` call either way. Same
`skipped: True` summary-dict convention, so a gated no-op still reads as a
legitimate `cron_heartbeat` `"success"` while remaining distinguishable
from "ran normally and genuinely snapshotted nothing" in the log.)


## Company classification: non-lender ticker overrides -- narrative (Bank-keyword broadening, regression, NII drift note) (original lines 1721-1752)

## Company classification: non-lender ticker overrides

`classify_company_type` (`backend/scoring/classification.py`) broadens its
Bank branch beyond the literal "bank" substring to also catch brokers
("Financial - Capital Markets"), asset managers ("Asset Management"), and
credit-card/credit issuers ("Financial - Credit Services"). **Sector/
industry text alone cannot reliably distinguish a genuine lender from a
non-lender within these categories** — companies with the *identical*
industry string can have completely different balance-sheet economics
(a payment network vs. a card issuer; a pure asset manager vs. one with a
captive bank subsidiary). Confirmed live via FMP profile + income-statement
data: BLK and AMP both report "Asset Management"; V and AXP both report
"Financial - Credit Services." Only a ticker-level check of actual
netInterestIncome-as-%-of-revenue — not the sector/industry text — can tell
these apart, so `NON_LENDER_TICKER_OVERRIDES` exists to carve the confirmed
non-lenders back out to `"Standard"`. This was verified once, by hand,
against real data for each ticker below — it is not derived from any rule.

Applying Bank's treatment (Financials' CFO/FCF de-emphasis in favor of Net
Interest Income, Profitability's ROIC exemption, Valuation's forced
Price-to-Book method) to a genuine non-lender produces nonsensical output —
confirmed regression: V/MA/BLK's Financials scores dropped 30-50+ points
purely from a near-zero/negative NII series standing in for real revenue,
not from the intended CFO-de-emphasis effect.

NII/revenue % below is each ticker's most recent annual FMP figure at the
time of the 2026-07-28 investigation (`netInterestIncome / revenue`,
cached in `backend/fathom.db`'s `fundamentalscache` table) — it will drift
year to year and isn't re-verified automatically. BNY's figures (added to
the confirmed-lenders table below) are from a separate, later check
(2026-08-05, FY2025 data), not the original 2026-07-28 pass.



## Company classification: HOOD removed from confirmed-lenders table (original lines 1787-1795)

**HOOD was previously listed here (33.9% NII, "margin lending and
cash-sweep interest are real NII, not incidental") and has been removed —
NII-as-%-of-revenue answers "does this company lend?", not "does this
company report under banking regulation?", and the latter is what Bank's
CET1/NPL check actually requires. See "Bank classification requires
genuine CET1/NPL-reporting capability, not just lending activity" below
for the corrected standard and why HOOD (and three others) moved to
`NON_LENDER_TICKER_OVERRIDES` on that basis instead.**



## Bank classification requires genuine CET1/NPL-reporting capability (2026-09-05): framing correction, universe-wide scan, HSBC/MTB false positives (original lines 1803-1849)

### Bank classification requires genuine CET1/NPL-reporting capability, not just lending activity (2026-09-05)

A 2026-09-04 investigation (documented above, in this same section, before
this fix) asked the wrong question for IBKR: "does this company do real
lending at meaningful scale?" — and concluded IBKR should stay `"Bank"`
because it runs a large margin-lending book (gross `interestIncome`/
`interestExpense` both ~41% of revenue, even though the *net* figure washes
out near zero). The user corrected this framing: Fathom's `"Bank"`
treatment exists specifically to run Step 5's CET1 (capital adequacy) and
NPL (loan quality) checks (`data/step5_data.py`), both of which only make
sense for an institution that actually reports under banking regulation —
i.e., is a genuine deposit-taking institution. Lending *shape* (margin
loans, credit-card loans, BNPL installment credit) is irrelevant to this
specific question; regulatory reporting shape is what matters. A company
classified `"Bank"` that doesn't report CET1/NPL shouldn't get Bank
treatment *anywhere* (Step 1's NII swap, Step 4's ROIC exemption, Step 3's
forced Price-to-Book) — not just have the CET1/NPL check itself skipped
while everything else stays Bank-shaped, which is what
`BANK_CET1_NPL_EXCLUDED_TICKERS` (`data/step5_data.py`) did for IBKR/HOOD
before this fix.

**Universe-wide scan, not just IBKR/HOOD.** Reused
`pipeline.nightly_fundamentals_fetch.load_full_tracked_universe` (572
tickers) rather than hand-rolling a new universe helper; 32 classify as
`"Bank"` via `classify_company_type`. Evidence standard: the same one
`BANK_CET1_NPL_EXCLUDED_TICKERS`'s original IBKR/HOOD entries were built
on — presence/absence of a genuine deposit-liability figure in FMP's
`financial_statement_full_as_reported` raw XBRL-tag dump (quarterly,
falling back to annual — same fallback convention `helpers/npl.py::
compute_npl_ratio` already uses), checked against total assets.

A literal `deposits`-tag-only check (what the original IBKR/HOOD
investigation used) turns out to produce two false positives at
universe scale, both confirmed via the raw tag data before being ruled
out:
- **HSBC** files under IFRS-style tag names (`depositsfromcustomers` =
  $1.79T, 52.0% of total assets) rather than the literal `deposits` tag
  FMP's US-GAAP filers use — a tag-naming artifact of HSBC filing as a
  foreign private issuer, not evidence of no deposit-taking.
- **MTB** (M&T Bank)'s literal `deposits` tag is a mis-scoped, too-small
  XBRL dimension member ($4.7B, 2.1% of assets) — the same class of issue
  `npl.py`'s own comment already documents for `TOTAL_LOANS_TAG` on
  BAC/WFC/C. Summing MTB's real deposit-liability tags
  (`noninterestbearingdepositliabilitiesdomestic` +
  `savingsandinterestcheckingdeposits` + `timedeposits`) gives ~$168.9B
  (77% of assets) — a genuine, well-capitalized regional bank.



## Bank classification requires genuine CET1/NPL-reporting capability (2026-09-05): before/after impact table (original lines 1878-1893)

**Before/after impact, measured on real cached data before shipping (all
four gain a real Step 5 verdict for the first time — previously
permanently `not_supported`, since none of them can ever have CET1
entered — this is the direct, intended payoff, not a side effect):**

| Ticker | | Step 1 | Step 4 | Step 5 | Step 3 |
|---|---|---|---|---|---|
| IBKR | Before (Bank) | 85/Pass (NII) | 100/Strong Pass, ROIC exempt | not_supported | overvalued |
| IBKR | After (Standard) | 90/Pass (Revenue) | 68/Fail, ROIC included | 71/Fail (hard-fail breach despite score ≥70) | undervalued |
| HOOD | Before (Bank) | 53/Fail (NII) | 60/Fail | not_supported | overvalued |
| HOOD | After (Standard) | 42/Fail (Revenue) | 28/Fail | 35/Fail | undervalued |
| SEIC | Before (Bank) | 52/Fail (NII) | 100/Strong Pass | not_supported | overvalued |
| SEIC | After (Standard) | 88/Pass (Revenue) | 85/Pass | 100/Strong Pass | undervalued |
| SEZL | Before (Bank) | 49/Fail (NII) | 100/Strong Pass | not_supported | overvalued |
| SEZL | After (Standard) | 84/Pass (Revenue) | 85/Pass | 100/Strong Pass | overvalued (unchanged) |



## Screener excludes ETFs (2026-09-20): Country=US remark (Country filter since removed) (original lines 1937-1941)

- **Country=US is NOT "US-domiciled stocks"**: Country is exchange-based
  (see `TickerScore.country`), so with ETFs gone `US` still includes
  NYSE/NASDAQ-listed ADRs (HSBC, TSM, NVO, ASML, ARM, BABA, TME) and OTC
  names (SINGY, EVVTY, CNSWF). Deliberate, unchanged here -- excluding them
  is a different, domicile/ADR-based rule.

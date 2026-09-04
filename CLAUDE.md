# CLAUDE.md — Fathom

## What this is

Fathom is a company fundamentals valuation web app. It runs a multi-step
fundamental screen on any US-listed ticker. The automated Analysis
framework has 4 steps -- **Financials (Revenue, income and cash flow)**,
**Growth Rate (Positive growth rate)**, **Profitability (Profitable and
operationally efficient)**, and **Debt (Conservative debt)** -- plus a
manually-set Economic Moat rating, together forming the Overall Assessment
score (see `STEP_WEIGHTS`/`MOAT_WEIGHT` in "Overall Assessment's step
weighting" below). **Valuation**, internally `backend/step3_data.py` /
`backend/scoring/step3.py`, is a separate, fully-implemented "Valuation"
tab with its own DCF/DDM/P-B/PSG method-selection logic -- it is **not**
part of the Overall Assessment blend (no `step3` key exists in
`STEP_WEIGHTS`).

## Tech stack

- **Frontend**: Next.js (App Router), TypeScript, Tailwind v4, shadcn/ui
  (`base-lyra` style, phosphor icons, neutral base color). Dark-only theme —
  no light mode toggle, `dark` class hardcoded on `<html>` in
  `app/layout.tsx`. SWR for data fetching. Mirrors the visual style and
  conventions of the sibling `options_tracker` project.
- **Backend**: Python (>=3.12), FastAPI, SQLModel, pandas/numpy for any data
  manipulation — favor vectorised operations over row-wise loops. Dependency
  management via `uv` (`uv run`, `uv sync`).

## Running the app

`./bin/start.sh` from the repo root brings up both servers (preflight
checks, explicit `init_db()`, an FMP connectivity check, then backend +
frontend, each in its own process group) — see `backend/OPS_RUNBOOK.md`'s
"Starting / stopping the app" section for what success/failure look like.
`./bin/stop.sh` stops both, safe to run anytime including when nothing is
running.

## Folder layout

```
bin/         start.sh / stop.sh / common.sh -- see "Running the app" above.
frontend/    Next.js app (App Router)
backend/     FastAPI app, organized into packages by role (2026-08-05
             reorg away from the previous fully-flat, feature-file
             layout — see below for the rationale and what each package
             holds):
  core/        App entrypoint + shared infrastructure: main.py (the
               FastAPI app itself — run as `uv run uvicorn core.main:app`,
               not `main:app`), models.py (SQLModel tables), db.py
               (engine/init_db), schemas.py (API response models),
               config.py (Settings/BASE_DIR), cache.py (get_or_fetch/
               safe_fetch), logging_config.py.
  clients/     Thin external API clients: fmp_client.py, sec_edgar.py,
               yahoo_client.py (Yahoo Finance, the non-FMP data source
               behind trend-structure analysis and the FMP-disabled price
               fallback), yahoo_cache.py (YahooPriceCache's own bespoke
               get-or-fetch helpers, separate from core/cache.py's
               FundamentalsCache-shaped ones -- see YahooPriceCache's own
               docstring in models.py).
  helpers/     Shared calculation helpers consumed by data/: ttm.py,
               shares.py, debt_metrics.py, npl.py, bank_capital_metrics.py,
               discount_rate_config.py, first.py.
  data/        Per-tab data orchestration (the get_stepN_data pattern):
               step1_data.py .. step5_data.py, ticker_summary.py,
               financials_data.py, ratios_data.py, analyst_ratings_data.py,
               news_data.py, segmentation_data.py,
               moat.py, watchlist_data.py, watchlists.py,
               saved_screener_filters.py, ticker_score.py,
               trend_analysis_data.py (see "Trend structure analysis
               (Technical)" below).
  scoring/     Pure scoring functions (classification.py, trend.py,
               series_trend.py, step1.py..step5.py, overall.py) — this
               package predates the 2026-08-05 reorg and was always split
               out; unchanged by it.
  analysis/    Standalone quantitative research modules, each its own
               subpackage: ma_magnet/ (unwired research script, not part of
               the production app -- see its own run.py docstring) and
               trend_structure/ (production, wired end-to-end via
               data/trend_analysis_data.py -- pure functions/dataclasses,
               no DB/HTTP of its own, matching ma_magnet's calculation
               style but NOT its unwired scope).
  scrapers/    Index/constituent Wikipedia scrapers: index_scraper.py,
               sp500_scraper.py, dow_scraper.py, refresh_sp500_list.py,
               refresh_dow_list.py.
  pipeline/    Production cron/maintenance entrypoints that read/write the
               real DB: nightly_fundamentals_fetch.py,
               nightly_trend_calculation.py,
               monthly_price_target_snapshot.py, recompute_ticker_scores.py,
               audit_fixture_contamination.py, refresh.py, prune_cache.py,
               backup_db.py, rotate_logs.py, stale_data_health_check.py --
               see backend/OPS_RUNBOOK.md for what each of the latter four
               does, its cadence, and what to check if it fails.
    backfills/   One-time historical cache backfill scripts (already run,
                 kept as documentation of how those migrations were done):
                 bulk_refresh_balance_sheet_quarterly.py,
                 bulk_refresh_ratios_ttm.py, bulk_refresh_step4_annual.py.
  scripts/     Untracked, ad-hoc research tooling that never touches
               production data — deliberately kept separate from
               pipeline/, since blurring that exact distinction (a script
               that looked like ad-hoc research but wasn't isolated from
               real data) caused the fixture-contamination incident this
               file documents elsewhere. Not committed to git.
  tests/       pytest suite, mirrors the package layout via import paths
               (e.g. `from data.step1_data import ...`) rather than a
               parallel directory tree.
```

Every cron entry in `crontab.txt` invokes its script as `-m package.module`
(e.g. `uv run python -m pipeline.nightly_fundamentals_fetch`), not a bare
script path — a script moved into a subpackage that's run as a direct file
path (`python pipeline/foo.py`) fails immediately with `ModuleNotFoundError`
on its own sibling imports, since that puts the script's own directory on
`sys.path` instead of `backend/` itself. `-m`, run with `backend/` as the
working directory, doesn't have this problem. Confirmed by actually running
both forms during the reorg, not assumed.

## Data source

[Financial Modeling Prep (FMP)](https://financialmodelingprep.com) (paid
tier) is the **sole** data source for fundamentals, company classification,
and Steps 1-5/Overall Assessment scoring, via `backend/clients/fmp_client.py`.
As of the trend-structure feature (see "Trend structure analysis
(Technical)" below), **price/OHLCV data alone** has a second, independent
source: Yahoo Finance (`backend/clients/yahoo_client.py`, via the `yfinance`
package), used for the swing/BOS trend engine (deliberately decoupled from
the FMP subscription) and as a live fallback for the ticker header's
current price when `FMP_ENABLED=false` (see "Pausing the FMP subscription"
below). No other data on this app comes from Yahoo -- fundamentals,
classification, and every score still come from FMP alone.

## Watchlists

Each watchlist is capped at `WATCHLIST_CAPACITY` (100 tickers,
`backend/core/main.py`) — adding tickers past the cap is rejected with an
explanatory error rather than silently truncating.

## Caching policy

Fundamentals change infrequently, so raw FMP pulls are cached in a local
SQLite database (`backend/models.py::FundamentalsCache`, via SQLModel) keyed
by `(ticker, statement_type, period)`, with a `fetched_at` timestamp on each
row. Before refetching from FMP, check whether a cached entry is fresher than
the configurable staleness window — `Settings.cache_staleness_days` in
`backend/config.py`, default 7 days, overridable via the
`CACHE_STALENESS_DAYS` env var. Never hardcode the staleness window at a call
site.

### Pausing the FMP subscription

`Settings.fmp_enabled` (`FMP_ENABLED` in `.env`, default `true`) is a global
kill switch for pausing the FMP subscription without hangs or unhandled
errors. Read once at process start — toggling it requires a backend
restart, not a live/runtime toggle. Enforced at two layers: `FMPClient.get`
(`backend/clients/fmp_client.py`) is the literal single choke point every
FMP call passes through, and raises immediately instead of attempting a
network call when disabled; `core/cache.py`'s `get_or_fetch`/
`get_or_fetch_earnings_aware`/`force_fetch` additionally check the same
flag directly, so a stale cached row is served (matching `cache_only=True`
semantics) rather than the read just failing. Together, no call site under
`data/` needs any change for the common path.

**What degrades while paused:**
- Cold search for a ticker not yet in cache falls back to matching against
  the app's own tracked-ticker universe (symbol only, no company name —
  materially narrower than FMP's live search) instead of calling FMP.
- `POST /api/tickers/{ticker}/refresh` returns 503 and does nothing else —
  no cache clear, no live call. (Clearing the cache and then failing to
  repopulate it would be the one genuinely destructive path this flag
  guards against.)
- News (`GET /.../news`) serves the last cached articles, however stale,
  instead of refreshing — never wiped/replaced by a failed fetch attempt.
- Price/quote **now has a live alternate feed** (built as part of the
  trend-structure feature — see "Trend structure analysis (Technical)"
  below): `get_summary()`'s quote-fetch block still runs the same
  `force_fetch`/`get_or_fetch` gating as everything else, but when
  `not settings.fmp_enabled` (and not `cache_only`, whose own contract is
  zero live calls of any kind), the resolved `price` field is overridden
  with a live Yahoo Finance close (`data/ticker_summary.py::
  _fetch_yahoo_latest_close`, via `clients/yahoo_client.py`/
  `clients/yahoo_cache.py`) rather than staying pinned to the last cached
  FMP value. Every other quote-derived field (`change`, `marketCap`,
  `yearHigh`, `yearLow`) is untouched — Yahoo's OHLCV has no equivalent for
  those, so they still degrade to the last cached FMP value exactly as
  before. This corrects an earlier version of this note, which (accurately,
  at the time) said no such feed existed and that an even-earlier project
  note referencing a planned Yahoo/Google Finance migration had never
  actually been built — that migration is what this entry now documents as
  done, scoped specifically to price, not a general Yahoo takeover of every
  quote field.

**What stays unaffected:** `pipeline/nightly_score_recompute.py` (already
`cache_only=True` throughout, zero FMP calls regardless of this flag), and
any read whose cache is still within its normal staleness window — which,
on a warm cache, is most of the app most of the time.

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

`backend/pipeline/audit_fixture_contamination.py` (read-only, safe to run
anytime) scans `FundamentalsCache` for the same class of fingerprint and
should be run if this is ever suspected again — now genuinely running
weekly via cron (Sundays 1:20 AM), not just documented as if it were.

## Cron job heartbeat / health monitoring

Built after a 2026-08-16 audit found an uncaught exception in a cron
script (Python's default excepthook) bypasses `configure_logging()`'s
handlers entirely, landing only in stderr/`<job>_cron.log` — invisible
anywhere in the app itself (real incidents: `sp500_list_refresh`'s
`sqlite3.IntegrityError` on 07-26/08-02, `backup_db`'s disk-full error on
08-09). `backend/core/cron_health.py::cron_heartbeat("<job_name>")` wraps
every one of the 12 real cron jobs' entry points (`if __name__ ==
"__main__":`), writing a `CronRunLog` row regardless of how the job fails.
Purely additive — on failure the original exception is always re-raised
unchanged, so existing stderr/`_cron.log` capture and exit codes are
untouched; the heartbeat's own DB writes are independently
try/except-swallowed, so a heartbeat failure (e.g. the exact disk-full
case above) can never mask or alter the job's real outcome.

`GET /api/config/cron-health` computes each job's health from its
`CronRunLog` history (`ok`/`overdue`/`failed`/`unknown`) and backs the
site-wide `CronHealthBanner` (mounted next to `FmpPausedBanner`), visible
only when at least one job isn't healthy.

**`Settings.cron_health_enabled`** (`CRON_HEALTH_ENABLED` in `.env`,
default `true`, same read-once-at-process-start convention as
`fmp_enabled`) gates only this reporting/surfacing layer — when `false`,
`get_cron_health()` short-circuits to `{enabled: false, jobs: []}` before
touching the DB, and `CronHealthBanner` renders nothing, an explicit skip
distinct from "checked and everything's ok". `cron_heartbeat()` itself is
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
(Separately found, and fixed the same day: `monthly_price_target_snapshot.py`
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

**`CRON_JOB_NAMES` in `core/cron_health.py` is the single source of truth
for which cron jobs exist** — a new cron job added to `crontab.txt` needs
a matching `CRON_JOB_NAMES` entry, an `_EXPECTED_CADENCE_HOURS` entry, and
a `cron_heartbeat(...)` call at its own entry point, or it ships
unmonitored. `backend/tests/test_cron_wiring.py` fails loudly if any of
these three ever drift apart, so this isn't just a documentation
convention to remember by hand. Full mechanism, exact cadence windows, and
the two incidents this closed are documented in `backend/OPS_RUNBOOK.md`'s
"Cron job heartbeat / health monitoring" section and its "Known gaps"
entry, not duplicated here.

## Scoring rubric notes

Financials' scoring rubric has been refined several times after live
testing against real tickers — these are deliberate tuning decisions, not
implementation drift. `financials.md` is the technical reference for the
exact current thresholds and formulas; `backend/scoring/trend.py` and
`backend/scoring/step1.py` are the source of truth in code, with comments
at each point below. Notable design decisions and fixes:

- **Verdict bands** are 0-69 Fail / 70-90 Pass / 91-100 Strong Pass. The score badge further splits the
  70-90 "Pass" band into two color shades (70-74 amber, 75-90 light green)
  without a text distinction — see `frontend/components/step1/ScoreBadge.tsx`.
  Growth Rate uses the same bands and badge.
- **Margins classification** uses windowed early-vs-late direction plus
  explicit dip-count and sustained-decline checks, not a raw stdev-of-diffs
  volatility check — a single big dip-and-full-recovery year no longer
  reads as "wildly inconsistent" just because it produces high variance.
- **Multi-dip trend tier** (2+ real dips in Revenue/Net Income/CFO/Operating
  Income) is split by recovery rather than one flat score: an unrecovered
  dip (TTM hasn't reclaimed the pre-dip peak) stays at 40; once every dip
  has recovered past its own pre-dip peak, it scores 75 regardless of how
  recently the dip happened -- a fully resolved dip reads the same whether
  it was 5 years ago or last fiscal year.
- **`classify_trend` (`scoring/trend.py`) made age-aware, and contiguous
  dip transitions now merge into one event (2026-08-08)** -- the tier
  above previously required LITERAL recovery only (TTM re-clearing a
  dip's own pre-dip peak), with no age-awareness at all: an old,
  durably-recovered dip could permanently cap a series at
  `multiple_dips`/40 even after 5+ clean recovery years, simply because
  TTM never re-cleared a possibly-structural old peak. Confirmed hitting
  113/569 tracked tickers (20%), 96 currently "Fail" overall. A dip can
  now also resolve via a secondary durable path (age >=4 periods, >=3
  clean trailing periods, non-negative robust late-window direction) --
  new pattern `dip_durably_resolved`, same 75 score, kept distinct only so
  the reasoning panel says "durably improved, not yet a new high" rather
  than implying a literal new peak. The flat TTM-decline-forces-0 override
  is now graduated (only fires beyond a 15% decline, not any real
  decline), and `flat_then_spike` is narrowed by the same robust-average
  convention Margins/CCC use. Full mechanism, exact thresholds, and the
  regulated-utilities FCF capex-driven softening this same build shipped
  are documented in `financials.md`'s "Trend classification"/"Free Cash
  Flow classification" sections, not duplicated here. Motivating case:
  HWM's Revenue (a 2018 pre-Arconic-split peak never literally re-cleared
  despite 6 clean growth years since) -- Financials score 66/Fail ->
  80/Pass. Full-universe validation: 28 tickers flip Fail->Pass, 0
  regress. Shared logic, not Step-1-local -- Step 3's method-selection
  tree and Step 4's ROE/ROIC recovery-aware exclusion (`profitability.md`)
  both reuse the same underlying machinery.
- **Margins' `sustained_decline` override (Rule 1) is gated on durable
  reversal**, not unconditional. The 10yr+TTM window extension exposed the
  same class of bug fixed in Profitability's CCC classifier: a sustained decline
  occurring once anywhere in the window (frequently the COVID-2020 FY)
  permanently capped the score at "gradually_compressing" even when the
  company had since fully recovered to new highs. Confirmed affecting
  128/499 tickers (26%), including MSCI, ADBE, CRM, TJX, PG, STE, VRSN. The
  override now only applies if direction is still net negative, OR the
  current (TTM) value is still below the early-window baseline `direction`
  itself is measured against (deliberately not the single pre-decline
  value, which is frequently an anomalous spike rather than a real
  baseline — requiring re-exceedance of a spike would leave genuine
  recoveries capped forever). Exempted cases read straight off the
  stable/expanding check rather than falling through to Rule 2 (whose
  independent per-series dip-count logic has its own separately-known
  issues — see below) — falling through was found to actively worsen 16
  tickers from 60 to 0 during verification. The sharp-decline check still
  runs first regardless of reversal status, so a still-declining net
  margin is never excused by an unrelated gross-side recovery.
- **Rule 2's "wildly_inconsistent" trigger (2+ real dips netting flat) and
  the fixed 2-point absolute dip threshold are known, separate issues, not
  yet fixed.** Rule 2 fires independently per-series (gross OR net), so a
  company with one genuinely choppy series and one clearly, strongly
  improving series (e.g. GOOGL: net margin nearly doubled, direction
  +14.6) can still land on the worst possible score. Separately, the
  2-point absolute dip threshold isn't scaled to a company's margin level,
  so naturally low-margin businesses (e.g. MCK, ~1-5% margins) can trip it
  on ordinary noise. Both deferred pending a follow-up investigation.
- **`score_step1` returns `score: None, verdict: "insufficient_data"`**
  (Step2Out/Step4Out/Step5Out's own convention) when any of Revenue/Net
  Income/CFO/Margins/FCF has too few real data points to classify — rather
  than folding `classify_trend`'s/`_classify_fcf`'s "insufficient_data"
  pattern (score `0`) into the weighted sum like any other real result. A
  prior version of this code did exactly that, fabricating a scored Fail
  out of a data gap: confirmed via repro that a single failed FMP fetch
  (e.g. `cash_flow_statement`) on an otherwise-strong ticker dragged the
  score down to 65/"Fail" purely because CFO/FCF read as `insufficient_data,
  0` rather than being excluded. This is the same class of bug already fixed
  in Growth Rate (`cache.py::safe_fetch` swallows `httpx.HTTPError` to `{}`,
  indistinguishable downstream from a genuinely-thin real response) — CFO-
  exempt companies (Bank/Property Developer/Commodity) are unaffected, since
  cfo/fcf simply aren't required for them. Net Income's own Operating-Income
  backup is unaffected too: NI only counts as a genuine gap if OI's
  `classify_trend` also reads `insufficient_data` — if OI has real data, the
  existing backup mechanism already produces a legitimate score.
- **Revenue, Net Income, and CFO must clear a hard positivity gate on top
  of `classify_trend`'s existing dip/recovery grading (2026-08-03)**, via
  `scoring/step1.py::_classify_positive_trend`. `classify_trend` is purely
  relative — it only asks whether a series has grown/recovered relative to
  its own prior points, never whether the current value is actually
  positive. Confirmed real case: SYM (Symbotic) has posted a net loss every
  single year for 8 straight periods (-$104.4M FY19 → -$4.97M TTM, each
  "dip" a relative worsening that later reverses) yet scored
  `multiple_dips_resolved`/75 — indistinguishable from a company that had
  actually turned the corner into real profitability. The gate is narrow
  and additive, not a rewrite: if the current/TTM value is ≤0, the result
  reads `not_yet_positive`/0 regardless of what the relative trend pattern
  says; if TTM is positive, `classify_trend`'s own tiers (100/90/85/75/
  40/20/0) are used unchanged — a historical dip, even one that went
  negative mid-dip, is still tolerated as long as the series has since
  recovered and the current value clears zero. Deliberately does **not**
  tighten `classify_trend`'s own recovery math (e.g. to penalize a
  volatile, sign-flipping history) — only the current value's sign is new;
  a currently-positive-but-historically-choppy series (SYM's CFO: 3 full
  sign-flips before settling positive the last 2 periods) still scores
  `multiple_dips_resolved`/75, unchanged. `classify_trend` itself,
  `RECOVERY_PATTERNS`, and every other consumer (Valuation's method-selection
  tree, Profitability's ROE negative-equity substitute, `_classify_fcf`'s own
  separate cash-burn-recovery logic) are untouched — this is a
  Financials-local wrapper, not a change to the shared primitive.
  - **Net Income's Operating-Income fallback is now recency-gated**
    (`NET_INCOME_BACKUP_RECENCY_YEARS = 2`, via the new
    `scoring/trend.py::most_recent_real_dip_age`), replacing the old
    threshold-only trigger (`net_income_raw.score <= 40` alone, regardless
    of how long ago the disqualifying dip happened). The fallback exists
    for a plausible one-off — a charge that hit 1-2 years ago — not a
    chronic, long-unresolved Net Income problem; OI is only consulted when
    NI's failing dip landed within the last 2 periods (inclusive of the
    current/TTM period itself — the single most common one-off shape, a
    charge that just hit the latest reported period). NI having too few
    points to have any notion of "recency" (`insufficient_data`) still
    unconditionally checks OI, unchanged from before.
  - **Confirmed via a full-universe recompute** (503 S&P 500 + Dow
    tickers, `recompute_ticker_scores.py`, cache-only/zero FMP calls): 29
    tickers' Financials score changed, 6 flipped verdict (all Pass → Fail,
    never the reverse — a stricter gate can only lower a score):
    **AVB** (75→64), **C** (72→61), **CCL** (73→66), **CTSH** (73→66),
    **GEN** (76→69), **PSKY** (75→58). 0 Overall Assessment verdicts
    flipped — Financials' ~24% weight in the Overall blend (see
    `STEP_WEIGHTS` below) wasn't enough on its own to cross a Pass/Fail
    boundary for any of these 29, though 22 tickers' Overall score moved.
    Two failure shapes confirmed in the changed set: **MRNA** (Moderna) —
    Net Income *and* CFO both currently negative, correctly reading
    `not_yet_positive`/0 on both (a genuine, still-unresolved post-COVID
    revenue/cash-burn problem, not a relative-recovery false positive);
    **AVB/C/CCL/CTSH/GEN** — Net Income's old dip is real but more than 2
    periods back, so the recency-gated OI fallback correctly stops
    rescuing it (previously capped-rescued to 80 regardless of recency).
- **`flat_then_spike` (CFO/Revenue/NI/OI) and Margins' `sharply_declining`
  check both fixed for a stale-baseline/stale-average distortion
  (2026-08-13), following a GLW investigation.** Two independent bugs,
  same root shape (an old anomalous value poisoning a reference average
  or gate), found via a from-scratch trace of GLW's Step 1 score (58/Fail
  despite recovering Revenue/CFO/FCF):
  1. **CFO's `flat_then_spike` gate discarded TTM as noise even when TTM
     was the actual evidence of a real recovery.** `robust_late_direction`
     (used to confirm a terminal jump is backed by genuine multi-year
     improvement, not just a lone spike) excludes the late window's single
     most extreme point before averaging — but with no way to tell "TTM is
     a plausible continuation of the trend" from "TTM is a fluke," it
     always treated TTM as the excludable outlier whenever it happened to
     be the late window's most extreme point, throwing out the one number
     that mattered. Fixed by gating `protect_terminal=True` on the size of
     the jump into TTM: only protected when the jump is **≤100%** (reusing
     `DIP_BASELINE_SPIKE_RATIO`, the same threshold `_effective_pre_dip_
     value` already uses to flag an unreliable one-off jump elsewhere in
     this file) — a modest, plausible jump gets trusted; a jump with no
     precedent anywhere in the series' history still doesn't. Stress-
     tested against the full universe before shipping (not just GLW):
     **NBIS** (CFO +682.9% YoY, no precedent in 10 years of history) and
     **VLO** (Net Income +207.2%, a second single-year commodity-margin
     spike in a business that already lived through one boom-bust cycle in
     this exact window) both stay conservatively unrescued, confirming the
     magnitude gate — not just "add `protect_terminal=True`" — was
     necessary. Only 2 tickers in the tracked universe hit this exact gate
     (GLW, CVS); of the wider 9-ticker `flat_then_spike` population, only
     GLW/YUM (CFO/NI) actually flip to a materially better pattern.
  2. **Margins' `sharply_declining` check had no equivalent to NI's
     `_effective_pre_dip_value` spike guard for its own early-window
     average.** `net.direction` (the early-vs-late-window average
     difference that check gates on) has no protection against a single
     anomalous point *inside* the early window — GLW's 2016 net margin
     (39.35%, an evident one-off immediately followed by a -4.91% 2017)
     inflated the 3-year early average enough that `direction` read -6.2pp
     even though net margin has genuinely recovered the last 3 years
     (4.62 → 3.86 → 10.21 → 11.2%). New `robust_early_direction`
     (`scoring/series_trend.py`) mirrors the already-shipped
     `robust_late_direction` — single most extreme point excluded before
     averaging — but applied to the early window. **Deliberately not a
     safe drop-in replacement for `direction`**: the exclusion is
     symmetric by construction, so it can just as easily exclude a genuine
     LOW early value (a real trough, not a spike) — which *raises* the
     early average and makes the reading *more* negative, the opposite of
     the intended fix. Confirmed via a full-universe check: an unguarded
     version regressed 16 tickers, most dramatically **DVN** (whose 2016
     oil-crash trough got excluded, collapsing Margins from
     `stable_or_expanding`/100 to `sharply_declining`/20). Fixed by using
     `max(direction, robust_early_direction(...))` at this one call site
     only — never the robust value alone, and never touching `direction`
     anywhere else in `_classify_margins` (`_series_recovered`,
     `_stable_and_spike_robust`, Rule 2, and Rule 2's own separate
     `sharply_declining` check at the bottom of the function are all
     untouched) — the fix is scoped to exactly the one branch that was
     wrong, not a general redefinition of "direction." With `max()`
     guarding it, 0 tickers regress.
  - **GLW's Financials score: 58/Fail → 78/Pass.** CFO: `flat_then_spike`/
    20 → `multiple_dips_resolved`/75 (CFO's TTM, $3.915B, is a literal new
    high 14.7% above its own 2021 peak). Margins: `sharply_declining`/20 →
    `gradually_compressing`/60 (not a full `stable_or_expanding` rescue —
    `_series_recovered`'s own gate is untouched by this fix, so GLW only
    gets credit for no longer being falsely flagged as currently sharply
    declining, not for a durable full recovery).
  - **Confirmed via a full-universe recompute: 18 tickers changed, 5
    verdict flips, 0 regressions.** Flips (all upward): **GLW** (58→78,
    Fail→Pass), **CPT** (64→72, Fail→Pass), **WELL** (68→76, Fail→Pass),
    **CSX** (67→71, Fail→Pass), **ICE** (87→91, Pass→Strong Pass). The
    other 13 changed tickers move within their existing verdict band
    (APD, EQR, WY, AXTI, CVS, CME, CNI, EBAY, GEHC, LITE, MO, NSC, VST).
- **`declining` and `not_yet_positive` graduated (2026-08-13)**, the
  remaining two Step 1 hard-fail cliffs found in the same universe-wide
  investigation that produced the CFO/Margins fix above and Step 2's/
  Step 4's/Step 5's own graduated-scale fixes (see their respective
  entries).
  - **`declining`** (`scoring/trend.py`, the severe->15% TTM decline
    override) was a flat 0 no matter how far past -15% the drop was.
    Confirmed via a full-universe scan: 141 hits, ranging from 15.2%
    (barely past the line) to absurd outliers driven by a near-zero
    prior-year base (e.g. INTC net income read as a -4128% "decline").
    Now graduates from 15 points (just past -15%) to 0 (at -50% or
    worse) — 50% chosen because it covers 101/141 (72%) of real hits.
    `classify_trend` is shared with Step 3's method-selection tree and
    Step 4's ROE/ROIC recovery checks, but both only test pattern
    membership in `RECOVERY_PATTERNS` (`declining` was never in that set
    either way) — confirmed via a project-wide grep of every
    `classify_trend` call site that this is a Step-1-only score change,
    despite living in the shared file.
  - **`not_yet_positive`** (`scoring/step1.py`, Revenue/Net Income/CFO's
    positivity gate) was a flat 0 regardless of how close to breakeven
    the current value was. Confirmed via a full-universe scan: 45 hits,
    margin (value ÷ real revenue) ranging from -149.0% (MRNA operating
    margin, a real structural loss) to -0.1% (ZETA net margin,
    effectively breakeven) — 44% of hits sat under -5% margin. Now
    graduates from 15 points (at 0% margin) to 0 (at -20% margin or
    worse, covering 34/45 (76%) of real hits) — measured against real
    revenue (the same denominator Margins itself uses, threaded through
    as a new optional `revenue_for_scale` parameter on
    `_classify_positive_trend`; falls back to the original flat 0 when no
    revenue is available to normalize against). `_classify_positive_trend`
    is Step-1-local (confirmed via grep — no other step calls it), so
    this has no cross-step ripple.
  - **No companion-floor risk, confirmed not just assumed**: Step 1's
    `_verdict_for` (unlike Step 2's/Step 4's pre-fix versions) is purely
    `VERDICT_BANDS` on the final blended score — no per-component gate on
    any individual pattern or score exists to interact badly with a
    graduated value, verified by reading the actual implementation before
    shipping, not inferred from the band design alone.
  - **Confirmed via a full-universe recompute: 71 tickers changed, 2
    verdict flips, 0 regressions.** Both flips upward: **SNPS** (68→71,
    Fail→Pass — Net Income `declining`/0→13, crossing the OI-backup
    threshold and pulling the blend over 70) and **CNC** (68→70,
    Fail→Pass — Net Income `not_yet_positive`/0→13).

Growth Rate's original methodology called for averaging projections
across 3-4 independent platforms (GuruFocus, Finviz, Zacks, etc.) and
comparing them for cross-platform agreement. FMP is Fathom's sole data
source, so this is substituted with FMP's `/analyst-estimates` endpoint,
which aggregates multiple analysts (not multiple platforms) into
avg/high/low per forward fiscal year — see `growth.md` for the exact
current formulas. Notable design decisions:

- The average projected growth rate (CAGR from the nearest forward
  estimate to the forward estimate closest to 4 years out) stands in for
  what a cross-platform average would have been.
- The high/low spread as a % of the average, for that same target year,
  stands in for what a cross-platform "source agreement" check would have
  been. This is **analyst estimate range**, not cross-platform consensus,
  and is labeled as such in the API/UI (`backend/schemas.py::Step2Out`,
  `frontend/components/step2/Step2Card.tsx`) so it's never mistaken for
  genuine cross-platform consensus.
- **Verdict *logic* deliberately diverges from the shared 0-69 Fail /
  70-90 Pass / 91-100 Strong Pass scale** every other step (Financials,
  Profitability, Debt, Overall Assessment) uses. Fail is gated on the
  magnitude tier alone (`growth_rate_pct < 0%`, i.e. `magnitude_score == 0`), not the
  blended score (`scoring/step2.py::_verdict_for`) — the 30%-weighted
  agreement component should never by itself drag a genuinely
  positive-growth company under the Fail line, so a weak-but-positive
  magnitude tier always reads "Pass", never "Fail", regardless of the
  blended number. Strong Pass still requires `score > 90`. This is
  intentional and unchanged.
- **The *score number* is floored at 70 whenever growth is non-negative**
  (`magnitude_score > 0`), via `PASS_SCORE_FLOOR` — a fix, not part of the
  original verdict-logic deviation above. Before this fix, a weak-but-
  positive-growth ticker's genuinely-computed blend could land anywhere
  in 0-69 while still displaying "Pass" text — confirmed real case
  (2026-07-31): FTNT's EPS CAGR of +1.16% ("weak" magnitude tier, 40/100)
  with a tight analyst spread (6.85%, "tight" agreement tier, 100/100)
  blended to `40*0.70 + 100*0.30 = 58`, a Fail-range number sitting next
  to "Pass" text, colored amber by the shared color system
  (`frontend/lib/tierColor.ts`) with no visibility into Growth Rate's
  different verdict semantics. The floor raises only the *displayed
  score* for a Pass (FTNT now shows 70, not 58) — it does not touch
  `magnitude_score`/`agreement_score` (the UI's own breakdown still shows
  the raw component tiers) and can never affect an already-≥70 blend or
  cross into Strong Pass range (floor value 70 < the `> 90` threshold).
  Fail-verdict tickers (negative growth) are untouched: the floor's guard
  is `magnitude_score > 0`, so a Fail still displays its real sub-70 score.
- **EPS estimates are preferred over revenue** when both are available;
  revenue is used as a fallback when EPS doesn't yield a usable CAGR (most
  commonly a negative base-year EPS, which makes a CAGR mathematically
  undefined even though the field itself is populated). This is a
  deliberate reversal of this app's original choice, which preferred
  revenue specifically because EPS is more exposed to buyback/margin-
  expansion noise than the underlying growth story — that reasoning still
  holds, but EPS growth is now judged the more decision-relevant figure for
  this methodology and the noise tradeoff is accepted. `basis` in
  `Step2Out` reflects whichever field actually produced the score, and the
  UI/Valuation-input labeling already read this dynamically, so no
  hardcoded "Revenue" label needed to change anywhere. This growth rate is
  also reused directly as Valuation's Yr 1-5 growth input
  (`step3_data.py`, `growth_yr_1_5`), so this switch changes Valuation
  outputs project-wide, not just Growth Rate's own verdict.
- The target-year picker (closest forward estimate to 4 years out, within
  the 3-5yr window) skips rows where the field being scored is null or
  zero, preferring a usable row from elsewhere in the same candidate pool
  over blindly taking whichever row is nearest the window center. This
  matters far more under EPS than it ever did under revenue: FMP
  frequently reports `epsAvg: 0` for sparsely-analyst-covered far-out
  years even when a nearer in-window year has a real EPS estimate, which
  would otherwise misread as "insufficient data" for names that do have a
  usable projection.
- Growth catalysts (originally envisioned as qualitative research into
  why a company is expected to grow) are a manually-curated free-text
  field (`models.py::GrowthCatalystNote`), not factored into the score —
  same scoping as Financials' manually-flagged one-off booleans. No edit UI
  exists yet; it's backend-settable only.
- **When neither EPS nor Revenue yields a usable CAGR** (too few/no future
  analyst estimate rows — including the case where `cache.py::safe_fetch`
  swallowed a genuine FMP fetch failure to `{}`, indistinguishable
  downstream from a real empty response), Growth Rate returns `score: None,
  verdict: "insufficient_data"` — Step4Out/Step5Out's own convention —
  rather than a fabricated `score: 0, verdict: "Fail"`. A prior version of
  this code scored these identically to a genuinely weak/negative growth
  projection, which fed a false Fail into Overall Assessment's Growth-Rate-
  weighted blend and the Screener with no way to distinguish "no data" from "bad
  growth". `scoring/overall.py`'s `_status_for` already treated any
  null-score/non-`"not_supported"` step as `"incomplete"` (excluded from
  the blend, whole Overall Assessment marked incomplete rather than
  computed) — this was Profitability/Debt's existing behavior; Growth Rate
  just never adopted it. Confirmed via cache-only inspection of the live
  universe that this only changes tickers with a genuinely empty/too-thin
  cached `analyst_estimates` response (e.g. ECHO, HONA, L) — every other ticker's
  score/verdict is unaffected.
- **Negative-magnitude score graduated (2026-08-13)**, following the same
  hard-fail-cliff investigation that produced Step 4's ROIC/ROE fix. Below
  0% growth, `_score_magnitude` used to return a flat 0 regardless of
  depth — a ticker projected at -0.03% (DVN, statistically indistinguishable
  from flat) scored identically to one at -60% (SNDK, a genuine collapse).
  Confirmed via a full-universe scan: of 27 tickers hitting this branch, 20
  sit at or above -9.0% ("mildly negative") and only 7 are genuinely severe
  (SNDK -60.0%, VLO -25.9%, CF -18.9%, INSW -14.5%, DOW -11.5%, LYB -11.0%,
  APA -10.8%). New graduated scale: linear from 35pts (near 0%) down to
  10pts (at `MAGNITUDE_SEVERE_NEGATIVE = -10.0%`, a first-pass round-number
  choice mirroring the `solid` tier's own magnitude); beyond -10%, still a
  flat 0, unchanged. Ceiling (35) deliberately kept below the `weak` tier's
  40, so a mildly-negative ticker can never outscore a genuinely-positive-
  but-weak one.
  - **Companion dependency, found and fixed in the same change (not a
    follow-up)**: `_verdict_for`'s Fail condition and `PASS_SCORE_FLOOR`'s
    guard were both keyed on `magnitude_score == 0` / `magnitude_score >
    0`. The moment a mildly-negative ticker's magnitude score became
    nonzero, both would have silently misfired — the Fail gate would read
    the verdict as Pass, and the floor would push the score to ≥70 — a
    false Pass for a company with genuinely negative projected growth.
    This is the exact same class of bug Step 4's ROIC/ROE fix needed an
    explicit companion floor for (see below), just via a pre-existing
    mechanism instead of a missing one. Fixed by keying both gates on
    `growth_rate_pct`'s own sign directly instead of `magnitude_score` —
    preserves the verdict boundary byte-for-byte (any negative growth
    still fails, unconditionally, exactly as the source doc specifies)
    while letting the score itself be an honest, graduated number.
  - **Confirmed via a full-universe recompute: 20 tickers changed, 0
    verdict flips** — every affected ticker stays Fail, just with a truer
    score (e.g. DVN 6→30, NUE/INCY →42, PG →53 — the highest of the 20,
    still well under both 70 and the `weak` tier's 40-point magnitude
    equivalent). The 7 genuinely severe tickers are byte-identical to
    before.

Debt's original methodology calls for a CET1 ratio check for Banks. An
investigation confirmed FMP has no CET1 field and no raw components to
compute one (checked ratios, ratios-ttm, key-metrics, balance sheet, and
speculative bank-specific endpoints — all absent or 404). CET1 is
therefore **manual-entry only,
never fabricated or estimated** (`backend/bank_capital_metrics.py`,
`frontend/components/step5/BankCapitalMetricsForm.tsx`) — but as of
`4a4fe26` ("Add manual CET1/NPL entry to unblock Step 5 Bank verdicts",
2026-08-02) this is **no longer a permanent block**. A Bank ticker reads
`verdict: "not_supported"` / `score: null` only until a CET1 value is
entered; once it is, `score_step5_bank` blends it 50/50 with an NPL
(Non-Performing Loan) ratio — auto-computed from FMP's raw XBRL tag dump
via `backend/npl.py` where available, manually overridable otherwise — into
a real score and verdict (`backend/scoring/step5.py::score_step5_bank`,
`WEIGHTS_BANK`). NPL itself is a metric the original methodology never
specified at all. `BANK_CET1_NPL_EXCLUDED_TICKERS` (`IBKR`, `HOOD` — confirmed no
customer deposit-taking business via FMP's `deposits` XBRL tag) are
carved out of this entirely: no manual-entry UI is offered and they stay
permanently `not_supported`, same as every Bank ticker before this
feature shipped.

Debt is a hard pass/fail bankruptcy filter, not a continuous score, so
these notes are structural rather than threshold tweaks — see `debt.md`
for the exact current formulas and severity bands:

- **Hard-fail override**: if any ratio breaches its hard limit (Current
  Ratio <1.0, Debt/EBITDA >3.0, Debt Servicing Ratio ≥30%, or Gearing >45%
  for REITs), the verdict is Fail regardless of the blended score — mirrors
  the Growth Rate fix (a hard rule must never be diluted by averaging with
  healthy ratios). The numeric score still displays for context.
- Company classification (Standard / Bank / REIT-or-Property-Developer) is
  a best-effort sector/industry text match, surfaced in the UI/API
  (`classification_note`) rather than hidden, since a misclassified ticker
  would silently apply the wrong ratio set.
- The deferred-revenue exception (a low Current Ratio driven by deferred
  revenue isn't a red flag) is shown as an informational note only, not
  auto-detected or auto-adjusted — same non-automated treatment as
  Financials' one-off items.
- **"Pass with caution" scores are capped at `PASS_WITH_CAUTION_SCORE_CAP`
  (74)**, separate from the `BORDERLINE_SAVED_SCORE` (60) an individual
  rescued ratio scores. Without this, the blended score could still land in
  "excellent" territory (95-100) even though a real breach occurred,
  because Current Ratio's deferred-revenue rescue re-scores off the
  adjusted ratio's own Comfortable-zone tier (up to 100), unlike Debt/
  EBITDA's and DSR's ICR rescue which is always flat-capped at
  `BORDERLINE_SAVED_SCORE` regardless of how comfortably ICR cleared the
  bar — ADBE (95) and AMP (100) were real cases of this before the cap.
  The verdict text already couldn't say "Strong Pass" for a saved breach,
  but that only protected the label; a 95-100 *number* next to an amber
  "caution" badge/chip still read as contradictory (a top performer
  flagged as risky) rather than as "barely passing," which a caution state
  should read as. Capped at 74 to land in the same lowest-shade "Pass"
  bucket the shared badge/chip already uses for a plain, unqualified
  70-74 score (`frontend/lib/tierColor.ts`) — never raises an
  already-lower natural blend, only lowers one that would otherwise land
  above the cap.
- **Breach-context framework (2026-08-01)**: a Borderline breach (never
  Severe — that stays an unconditional Fail, no exceptions, exactly as
  before) on Debt/EBITDA or Current Ratio gets a second, richer look
  before falling back to a flat Fail, replacing what used to be a single
  narrow Interest-Coverage-Ratio-only check for Debt/EBITDA (Current
  Ratio had no equivalent second chance at all beyond its existing
  deferred-revenue-to-Comfortable rescue). Two primary gates (the OTHER
  two ratios' literal raw values, not their own possibly-rescued
  classification — `current_ratio >= 1.0` and `debt_servicing_pct < 30.0`
  for Debt/EBITDA's breach; `debt_to_ebitda <= 3.0` and
  `debt_servicing_pct < 30.0` for Current Ratio's) must both pass cleanly
  before a strict majority of secondary signals (5yr trend, FCF vs Total
  Debt, Interest Coverage for Debt/EBITDA; deferred-revenue magnitude,
  5yr trend, cash position, current-asset liquidity for Current Ratio) is
  even considered — `backend/scoring/step5.py::evaluate_debt_to_ebitda_
  breach_context` / `evaluate_current_ratio_breach_context`. A qualifying
  breach reuses the existing `saved_by_tiebreaker`/"Pass with
  caution"/`PASS_WITH_CAUTION_SCORE_CAP` machinery verbatim (no new
  verdict state) under a new label, `marginal_via_breach_context` — but
  the points awarded are now **graded** (40-60, `MARGINAL_SCORE_FLOOR` to
  `BORDERLINE_SAVED_SCORE`) by the favorable-signal fraction, not a flat
  60 regardless of how convincing the evidence is. Two signals (cause of
  debt, undrawn revolving credit — plus Net-vs-Gross Debt as a third,
  informational-only aside) are **never** scored, since neither is
  reliably determinable from FMP's structured data; these always render
  an explicit manual-check note in reasoning rather than being silently
  omitted.
  - Using the OTHER ratios' *raw* values (not their own rescued state) as
    primary gates is a deliberate, real behavior change from the old
    narrow mechanism: previously, DSR Borderline-but-ICR-rescued (e.g.
    35%) would ALSO rescue a Borderline Debt/EBITDA off the exact same
    ICR boolean, independently. Now it doesn't — a DSR that itself needed
    rescuing isn't "clean" enough to vouch for a different ratio's
    breach.
  - Confirmed via a full-universe recompute (503 tickers): 42 tickers'
    Debt score/verdict changed. Real examples: **ROL** and **DAL** newly
    qualify — both are exactly the deferred-revenue-heavy business model
    (prepaid pest-control contracts / advance ticket sales) the framework
    was built to recognize, previously with no way to get partial credit
    once the deferred-revenue-to-Comfortable rescue alone fell short.
    **APD** and **AMGN** conversely lose their old rescue — Debt/EBITDA
    has genuinely risen (+103% and +17% over 5 years) with weak FCF
    coverage (6% and 15% of total debt), so a safe ICR alone no longer
    overrides that. **AVB, EQR, GEHC, HON, HST, IFF, KIM, O, REG** flip
    from an incorrect "Pass" to "Fail" at an unchanged score — the
    residual fallback-floor fix below, not this framework.
  - **MA and FICO (this framework's original motivating cases) were
    checked directly against real cached data and BOTH remain unchanged**
    — MA's Current Ratio breach reaches the framework (primary gates pass
    cleanly) but 3 of 4 secondary signals are genuinely unfavorable (zero
    deferred revenue, a real ~24% 5yr decline, cash covering only 34% of
    current liabilities), so it correctly stays Fail rather than being
    rescued just because the mechanism exists. FICO's Debt/EBITDA (4.81x)
    is Severe, not Borderline, so it never reaches the framework at all —
    confirms the framework doesn't quietly extend into Severe-breach
    territory.
- **Residual fallback-floor fix**: `_verdict_for`'s `hard_fail=False,
  saved_by_tiebreaker=False` fallback previously had no score floor at
  all (unlike the `saved_by_tiebreaker=True` branch, fixed earlier) — a
  plain mediocre-but-non-breaching ratio combination could land under 70
  and still read "Pass". Both checks are now one hoisted `score < 70 →
  "Fail"` check ahead of the `saved_by_tiebreaker` branch. Because
  `score_step5_reit` calls the same `_verdict_for`, this also fixes REIT
  gearing's own "approaching_limit" tier (60pts, no rescue mechanism at
  all) — confirmed via the recompute that AVB/EQR/HST/KIM/O/REG (REIT
  gearing) and GEHC/HON/IFF (Standard-path fallback) all flip from
  "Pass" to "Fail" at their unchanged score.
- **Negative EBITDA is a real Fail, not `insufficient_data`; a negative-
  CFO-only Debt Servicing Ratio is a genuine exemption, not a Fail
  (2026-08-06).** Previously, any Standard-path ticker with EBITDA ≤0
  (Debt/EBITDA undefined) or CFO ≤0 (Debt Servicing Ratio undefined) hit
  an all-or-nothing gate straight to `insufficient_data` — which, unlike
  a real exemption (IBKR/HOOD's `not_supported`, which reweights), sets
  `can_compute = False` and silently blanks the ENTIRE Overall Assessment,
  not just Debt. Two distinct fixes, shipped as two commits:
  1. **Negative EBITDA → Fail.** A company not generating positive
     operating earnings at all is a real weakness, not a neutral data gap
     the way a Bank/Insurance/broker-dealer exemption is —
     `score_step5_standard` now returns a `negative_ebitda` result (0
     points, hard-fail, with an explicit reasoning note) whenever EBITDA
     is ≤0, and this stays IN the blend as a genuine Fail rather than
     blocking the whole check. `step5_data.py`'s gate now only reads
     `insufficient_data` when `total_debt`/`ebitda_ttm` is genuinely
     missing, not when `ebitda_ttm` is present but non-positive.
     Confirmed real cases (all previously `insufficient_data`/Overall
     blanked entirely, now genuine Fails): **CNC** (57/Fail, Overall
     56/Fail), **COIN** (62/Fail, Overall 32/Fail), **F** (57/Fail,
     Overall 46/Fail), **IP** (57/Fail, Overall 46/Fail), **KHC**
     (52/Fail, Overall 41/Fail), **MRNA** (50/Fail — also has negative
     CFO, see below), **PSKY** (23/Fail, Overall 45/Fail), **TAP**
     (28/Fail, Overall 44/Fail), **ECHO** (50/Fail — also has negative
     CFO; Overall stays `None`, unaffected by this fix — a pre-existing,
     unrelated Growth Rate `insufficient_data` gap).
  2. **DSR excluded (not failed) when CFO is negative but EBITDA is
     positive.** CTVA (a seasonal working-capital cycle) and SMCI (an
     inventory buildup) both have positive EBITDA — only Debt Servicing
     Ratio's CFO input was undefined, while Current Ratio and Debt/EBITDA
     were both real and computable. Unlike negative EBITDA, a temporary/
     seasonal negative-CFO period isn't evidence DSR itself is unhealthy,
     so this is a genuine exemption (`RatioResult.excluded=True`): DSR
     drops out of the blend entirely and its weight is proportionally
     redistributed across whichever of {Current Ratio, Debt/EBITDA}
     remain (50/50, when both apply) — mirroring Profitability's own
     equal-weight redistribution for its exempt metrics (`BASE_WEIGHTS`,
     below). Confirmed: **CTVA** now 85/Pass (Overall 79/Pass); **SMCI**
     now 50/Fail — a genuine Debt/EBITDA breach that, with DSR
     unverifiable this period, can no longer be breach-context-rescued
     using it as a primary-gate input (Overall 53/Fail).
  Both breach-context frameworks (above) now guard against a `None`
  `debt_to_ebitda`/`debt_servicing_pct` input, treating an undefined
  ratio the same as a real breach for gating purposes — it can't vouch
  for a different ratio's rescue any more than a bad one could.
- **Debt/EBITDA and DSR's Severe-zone points graduated (2026-08-13)**,
  following the same hard-fail-cliff investigation as Step 4's ROIC/ROE
  fix and Step 2's negative-magnitude fix. The Severe zone was a flat 0
  no matter how far beyond the boundary a ratio sat — confirmed via a
  full-universe scan: Debt/EBITDA's Severe population spans 4.04× to
  84.56× (NET), DSR's spans 42.68% to 478.91% (HUM). **Both FDXF
  (current_ratio 0.00, flagged in the original investigation) and HUM
  were spot-checked for a data-quality artifact before this shipped**:
  FDXF's is confirmed a genuine FMP data gap (`totalCurrentAssets`
  reports as a literal `0` against $993M of current liabilities for this
  recently-spun-off FedEx Freight subsidiary — implausible for an
  actively-trading company, not touched by this fix since Current Ratio's
  Severe zone is out of scope here); HUM's 478.9% DSR is confirmed
  **genuine, not an artifact** — a real, seasonally-lumpy $147M TTM CFO
  (Humana's quarterly cash flow swings ±$400M-1.65B and happens to net to
  a small residual this TTM window) divided into a normal ~$704M TTM
  interest expense.
  - Unlike Step 4/Step 2, this is **display-only** — `label` stays
    `"severe"` and `hard_fail` stays unconditionally `True` for the whole
    zone (Debt is deliberately "a hard pass/fail bankruptcy filter, not a
    continuous score" — see above), so there is no companion-floor risk
    to fix here the way the other two needed: the verdict is already
    forced to Fail by `hard_fail` regardless of the displayed score, both
    before and after this change. Confirmed via a full-universe recompute:
    **86 tickers' points/score changed, 0 verdicts changed** — including
    PCAR, whose blended score rises to 72 (nominally "Pass" range) while
    still correctly reading Fail, since `hard_fail` is checked first and
    unconditionally in `_verdict_for`.
  - Points graduate linearly from 15 (at the Comfortable/Severe boundary)
    to 0 (Debt/EBITDA: at 10.0×, `DEBT_EBITDA_SEVERE_FLOOR_RATIO`, 2.5x
    the 4.0x boundary; DSR: at 120%, `DSR_SEVERE_FLOOR_PCT`, 3x the 40%
    boundary) — both floor ratios chosen from the real Severe population
    (covering 92%/59% of actual tracked-universe Severe tickers
    respectively), not guessed. 15-point ceiling deliberately kept below
    `MARGINAL_SCORE_FLOOR` (40) so even the least-bad Severe reading can
    never numerically outscore a genuinely-rescued Borderline breach.

Profitability's original methodology gives ROE/ROIC tiers, an
AR-outpacing-magnitude concept, and a qualitative CCC pattern table
without committing to exact scoring formulas for any of them.
`profitability.md` is the technical reference for the exact current
formulas; `backend/scoring/step4.py` operationalizes each into concrete
thresholds. Notable design decisions and fixes:

- **Both the display and scoring window are 10yr+TTM**, matching
  Financials, for consistency across the whole app.
  `backend/step4_data.py`'s `ANNUAL_WINDOW` (10) controls both what's
  fetched/shown and what feeds the score — there
  used to be a separate, narrower `SCORING_ANNUAL_WINDOW` (5) sliced out via
  a `_scoring_window()` helper so the chart could show more history than
  the score was based on; that decoupling has been removed, so a ticker's
  score now reflects its full 10-year history, not just the most recent 5.
  This means scores can shift versus the earlier 5yr-scoring behavior for
  tickers with a materially different pattern in years 6-10 versus the
  most recent 5 — an intentional tradeoff for a longer, more complete read
  on ROE/ROIC/AR/CCC trends.
- **Company classification** extends the same shared classifier Debt
  uses (`classify_company_type`, now in `backend/scoring/classification.py`
  rather than duplicated) with Insurance and Utility. Insurance is checked
  **before** Bank since both share the "Financial Services" sector — an
  insurer whose industry text doesn't also match "bank" would otherwise be
  misclassified. Debt's own branching is `if Bank / if Insurance / if REIT
  / else standard-path` — Insurance always reads `not_supported` (no
  ratios attempted at all; see `debt.md`), while Utility tickers fall
  through to the standard ratio path unaffected.
- **ROE/ROIC tiering** uses both the average across the 10yr+TTM window
  *and* the minimum single-year value as a consistency check (a high
  average diluted by one very weak year lands in the "marginal" tier, not
  "excellent") — a straight average alone would let one bad year hide
  behind several good ones.
- **Recovery-aware exclusion (2026-08-08)**: that average is now computed
  on a *reduced* series when a real dip in it has since resolved (literally
  or durably, reusing Step 1's `classify_trend`/`DipEvent` machinery) —
  the whole prefix through the last resolved dip's own trough is dropped
  before averaging, not just that dip's own declining leg. Fixes a
  one-directional blind spot the unrecovered-decline demotion (below)
  didn't cover: demotion can only ever lower a tier a good-average ticker
  has since let slip, never raise one a bad-average ticker has since
  durably fixed. Motivating case: HWM's ROE had two crash years
  (2016-17) followed by 8 straight years of genuine improvement, yet
  scored `marginal` because those two years never stopped counting —
  fixed to `excellent`. Full-universe validation: 68 of 90 affected
  hard-fails resolved, 13 known, accepted regressions (structural
  decliners like LHX/LUV/MU, whose only strong years sit before a
  resolved-by-age dip, can score *worse* once those years are excluded —
  evaluated against two alternative designs, a narrower span-only
  exclusion and a recency-weighted average, both prototyped and
  rejected). Full mechanism and the regression tradeoff are documented in
  `profitability.md`'s "Recovery-aware exclusion" section, not duplicated
  here.
- **Negative-equity substitute signal**: if shareholders' equity is ≤0 in
  any period, raw ROE is ignored entirely for the whole metric (not just
  that period) and replaced by a check for positive-and-non-declining Net
  Income across the window (net income positive throughout, last period ≥
  first) — a simple "last ≥ first" bar, deliberately not a full trend
  classifier, since "consistently maintained/growing" is inherently a
  qualitative judgment.
- **Revenue vs. Accounts Receivable** tiers are checked worst-first, since
  the qualifying conditions overlap: majority-outpacing or revenue-
  declining-while-AR-grows (0) takes priority over 3+-years-or-large-gap (40), which
  takes priority over 0-or-one-small-gap (100), with 1-2 isolated years
  otherwise landing at 70. A YoY gap under 2 percentage points is treated
  as noise, not real outpacing (same noise-floor convention as Financials'
  margin classifier).
- **CCC trend classification** reuses Financials' margin-classifier logic
  (early/late-window direction + dip-count + sustained-decline, now shared
  via `backend/scoring/series_trend.py`) run on the *negated* series, since
  a declining CCC is the desirable direction (faster cash conversion) while
  a declining margin is not. No numeric CCC thresholds were specified
  upfront (unlike margins, which were tuned after live testing) — the
  window/dip/sustained-
  decline constants in `scoring/step4.py` are first-pass judgment calls, not
  values validated against a prior baseline.
- **CCC exemption (no physical inventory)** is data-driven — inventory
  reading as 0 or null — but is checked **only against the 10 annual
  filings**, not the latest-quarter snapshot appended for the "TTM" column.
  FMP's latest-quarter inventory figure proved unreliable for genuinely
  inventory-free companies during verification (Mastercard showed +$2.06B,
  ServiceNow showed -$28M in their latest quarter despite straight
  clean-zero annual years) — a data-provider classification artifact, not a
  real change in the business.
- **Equal-weight redistribution** is a generalized N-way split (1/N across
  whatever metrics are applicable — 25% each if all 4 apply, 33.3% each if
  ROIC is exempt, 50% each if ROIC and CCC are both exempt), not a fixed
  reassignment table like Financials' CFO exemption — Profitability has more
  possible exemption combinations than Financials' single CFO on/off switch.
- **Hard-fail override**: verdict is Fail regardless of the blended score
  if ROE lands in its Fail tier (avg <8%), or ROIC does (when applicable) —
  mirrors Growth Rate/Debt's hard-fail pattern. Revenue-vs-AR and CCC landing
  in their own worst tier (0 points) drag the score down but do **not**
  force a Fail verdict — a Receivables/CCC red flag is treated as worth
  investigating, not an automatic disqualifier the way persistently poor
  ROE/ROIC is.
- **CCC's `sustained_decline` override is gated on `direction` sign.** The
  10yr+TTM window extension exposed a contradiction: `sustained_decline`
  scans the *entire* window for a qualifying multi-period rise in real CCC
  with no recency awareness, so an old, small, fully-reversed blip (e.g.
  MSFT's 2016-2018 uptick, since outweighed by a decade of improvement)
  could permanently cap the score at 0 even while `direction` (the
  early-vs-late-window average) was strongly positive. `classify_ccc_trend`
  now only honors the override when `direction < CCC_STABLE_TOLERANCE_DAYS`
  (reusing the existing -1.0 constant, not a new one) — a durably-reversed
  decline no longer masks an otherwise-improving trend. `analyze_series_direction`
  itself and Financials' margin classifier (which independently calls the same
  shared function) are untouched by this.
- **Revenue-vs-AR's "concerning" tier threshold is proportional, not a
  fixed count.** It was originally "3 of 5" transitions (60% severity,
  matching the original 5yr window) but was never rescaled when the window
  extended to 10yr+TTM (10 transitions), so it fired at just 30% severity
  instead — inflating false positives. `AR_CONCERNING_TRANSITION_RATIO`
  (0.6) now generalizes this to `max(3, round(0.6 * n))` transitions,
  restoring the original relative severity at any window size (still 3 at
  n=5, 6 at n=10). `majority_outpacing` was already proportional (`> n/2`)
  and needed no change. Because the ratio (0.6) sits above the 50%
  majority line, the count-based "concerning" tier remains structurally
  subsumed by "majority" at every window size — a pre-existing property of
  the original design, not an artifact of this rescaling.
- **CCC (Cash Conversion Cycle) classification is sign-aware (2026-08-01),**
  not just trend-aware. The prior classifier ran every series through the
  same early/late-direction logic regardless of sign, so a company whose
  CCC is deeply negative and drifting toward zero (still elite) scored
  identically to one whose CCC is genuinely positive and rising — a
  negative CCC isn't a milder version of positive CCC, it's the opposite
  signal (suppliers fund the business, since customers pay before
  suppliers are paid). Confirmed real case: AAPL's CCC is negative the
  entire 10yr window (-84 to -54 days) yet scored 0/"sustained_upward",
  dragging an otherwise-100/100-ROE/ROIC company to a Profitability score of 50.
  `classify_ccc_trend` (`backend/scoring/step4.py`) now dispatches on sign
  profile before applying any trend logic: **consistently negative**
  throughout (`max <= CCC_SIGN_EPS_DAYS`) always scores 100, split only by
  reasoning text into strengthening (getting more negative) vs. weakening
  (getting less negative but still solidly negative, AAPL's case);
  **consistently positive** throughout delegates to
  `_classify_positive_ccc_trend`, today's entire pre-existing logic moved
  verbatim and confirmed byte-for-byte unchanged (the NVDA/IDXX path —
  both genuinely positive and rising, still score 0); a **mixed** series
  (crosses the sign boundary) first passes an isolated-spike rescue (a
  single point disproportionately far from the majority side —
  `CCC_SPIKE_ISOLATION_RATIO = 3.0` — is treated as a one-off, not a real
  crossing; confirmed real case: ABBV, 10yrs of 62-102 day positive CCC
  then one TTM value of -496.7, an evident one-time acquisition-related
  accounting event, rescued back to the unchanged positive-CCC path,
  score unchanged at 70), then a genuine crossing is sub-classified by
  whether it durably settled on one side using a robust (single-outlier-
  excluded) late-window average — `"gained_bargaining_power", 100` if it
  settled negative (KR-shape: starts ~+8 days, ends ~-7.6 days) or
  `"lost_bargaining_power", 0` if it settled positive (the mirror,
  genuinely losing supplier leverage) — or, absent a clear settle, by
  overall amplitude: `"negligible_working_capital", 85` if the whole
  series stays within `CCC_NEAR_ZERO_AMPLITUDE_DAYS` (10 days — COST,
  CASY, TGT: oscillates near zero, structurally low capital intensity,
  not noise to flag) vs. `"mixed_unclear", 40` otherwise (CCL-shape: real,
  larger swings with no clear pattern — worth a manual look). All three
  new constants (`CCC_SIGN_EPS_DAYS=1.0`, `CCC_NEAR_ZERO_AMPLITUDE_DAYS
  =10.0`, `CCC_SPIKE_ISOLATION_RATIO=3.0`) were derived from a real,
  cache-only sweep of all 318 CCC-scorable tickers in the universe (not
  guessed) — confirmed via a full-universe recompute: 78/318 tickers' CCC
  sub-score changed, propagating to 78 changed Profitability blended scores, 3
  verdict flips (AZO/FDS/ORLY, Pass 85 → Strong Pass 92), and 13 tickers
  moving off a masked-Pass read (score <70, "Pass" shown anyway) to a
  genuinely-earned ≥70 — including AAPL (50 → 75). 194 tickers remain
  masked-Pass afterward, since this fix only addresses CCC's own
  contribution — Revenue-vs-AR's separately-known majority-count
  miscalibration (see the "score floor" investigation this fix followed
  from) still drags many of these down independently, and remains
  deferred, not yet scoped.
- **Revenue-vs-AR's worst tier gained a noise floor and switched from an
  individual-year count to an aggregate multi-year trend (2026-08-01).**
  Two calibration bugs, both found via the same masked-Pass investigation
  as CCC's fix above: (1) the `strong_red_flag` check (revenue declining
  while AR grows) was a bare sign comparison with no materiality floor,
  unlike every other check in `score_revenue_vs_ar` — confirmed CAT
  (revenue -3.4%, AR +0.14%, both trivial) scored identically to BA
  (revenue -24.3%, AR +217%, genuinely material). Now gated on
  `AR_GAP_NOISE_FLOOR` (2pp) on both legs, matching the rest of the
  function. (2) The worst tier's own trigger — "majority of individual
  years outpacing" — mis-flagged companies whose year-to-year timing is
  lumpy but whose aggregate multi-year trend is fine: AAPL outpaced in
  6/10 individual years yet AR actually grew slower than revenue in
  aggregate (93% vs 109% over the full window). A raw full-period
  growth-% comparison was tried first but proved fragile whenever a base
  year is small/near-zero — confirmed via **TER**, whose cached TTM
  Accounts Receivable value is $1.1 trillion against $3.8B revenue
  (almost certainly a raw FMP data-quality issue, not a scoring bug),
  which alone produced a 576,425pp "gap" under a raw growth-%
  comparison. Comparing **Days Sales Outstanding** (`AR/Revenue*365` —
  the same DSO formula `_compute_ccc_series` already uses for CCC in this
  file) between an early window and a **robust** late window (single
  most-extreme point excluded, mirroring CCC's own spike guard —
  `robust_late_direction`, reused with zero duplication) is scale-
  invariant and far more robust to a single bad/anomalous year.
  `AR_DSO_TREND_MATERIALITY_DAYS` (15.0) was derived from the real
  distribution of DSO gaps among the 163 tickers in the worst tier at the
  time: median gap was only +2.3 days (most of the old tier was noise,
  not signal); 15.0 keeps the ~24% with a genuinely elevated multi-year
  DSO increase while clearing the noise-dominated majority. Only the
  worst tier's trigger changed — `outpacing_concerning`/
  `outpacing_isolated`/`healthy` keep their existing individual-year-
  count logic unchanged, matching the narrower scope of the bug report.
  Confirmed via a full-universe recompute: 122/504 tickers' Profitability
  blended score changed (0 verdict flips — Profitability's verdict is
  hard_fail-gated, unaffected by AR's point contribution); the worst AR
  tier dropped from 164 to 98 tickers (60% of the reduction from the
  noise-floor fix alone, the rest from the aggregate-trend fix); AAPL,
  ANET, ISRG, CVNA, IBKR, VRSN all confirmed moving off the worst tier;
  PRU/TFC (genuine, current, material red flags) confirmed staying at 0.
  TER stays flagged (real, if smaller, elevated DSO trend even robust-
  late-window-adjusted) — its underlying $1.1T cached AR value is a
  data-quality issue worth a manual check, flagged but not fixed here.
  Whenever Revenue-vs-AR lands in any non-healthy tier, a dynamically-
  computed manual-check note (`components.revenue_vs_ar.note`, built in
  `step4_data.py::_build_ar_note` — deliberately not in the pure
  `scoring/step4.py`, since it needs Operating Cash Flow, which isn't
  part of the AR score itself) states which comparison actually drove the
  flag (DSO trend vs individual-year count, with real numbers either way)
  plus whether OCF is tracking Net Income over the same window (a lagging
  OCF alongside rising Net Income is the real red flag for revenue being
  recognized before cash arrives) plus a static business-model-shift
  prompt that can't be answered from FMP's structured data.
- **Profitability's internal blend is weighted, not equal-split (2026-08-01).**
  Previously every applicable metric (ROE, ROIC, Revenue-vs-AR, CCC) split
  the score evenly (`weight = 1.0 / len(applicable)`). `BASE_WEIGHTS`
  (`backend/scoring/step4.py`) now sets ROIC 35% / ROE 25% / Revenue-vs-AR
  20% / CCC 20% when all 4 apply — a deliberate user design call, not a
  bug-driven fix like the rest of this section. Rationale: ROE and ROIC
  are the headline profitability verdict, with ROIC weighted above ROE
  since it's harder to game (unaffected by the leverage/buyback effects
  that inflate ROE — see `check_roe_roic_divergence`'s own docstring) and
  reflects capital efficiency more directly; Revenue-vs-AR and CCC are
  corroborating/contradicting supporting evidence for what ROE/ROIC
  already say, not independent headline signals, so they're weighted
  lower and equal to each other. `score_step4` renormalizes proportionally
  (not equally) when a metric is exempt via the company-type gates —
  each remaining metric's `BASE_WEIGHTS` entry is divided by the sum of
  the applicable entries, preserving relative ratio rather than falling
  back to an equal split. Worked examples: ROIC+CCC exempt (Bank/
  Insurance/Utility) → ROE 25/45=55.6%, AR 20/45=44.4% (not 50/50); REIT
  (AR+ROIC+CCC all exempt) → ROE alone at 100%, unchanged from before
  since there's only one metric either way. This is a pure re-weighting —
  no individual metric's own tiering (`score_roe`, `score_roic`,
  `score_revenue_vs_ar`, `classify_ccc_trend`) changed. Confirmed via
  spot-check against real cached data: AAPL 85→88 (verdict unchanged,
  Pass), MA 90→92 (**verdict flip Pass → Strong Pass** — MA's ROE/ROIC
  were already both "excellent" at 100, so shifting weight toward them
  pulls the blend above the >90 Strong Pass line), FICO 67→75 (verdict
  unchanged — Profitability's `_verdict_for` has no low-score Fail gate the
  way Debt's does, only `hard_fail` and the >90 Strong Pass threshold, so a
  score move within the 0-90 range never changes the verdict on its own).
  A full-universe recompute has not been run for this change (unlike the
  AR/CCC fixes above, which were bug fixes verified at that scale) — this
  is a deliberate re-weighting, not a correctness fix, so no universe-wide
  before/after audit was required before shipping it.
- **ROE/ROIC below-floor and CCC `sustained_upward` graduated (2026-08-13),
  shipped together with a companion verdict floor** — the third and
  largest fix in the same hard-fail-cliff investigation that produced
  Step 1's/Step 2's/Step 5's own graduated-scale fixes (see their
  respective entries), and the one that most directly motivated the
  whole investigation (a from-scratch GLW trace: Step 4 scored 35/Fail
  purely from ROIC/CCC both flattening to 0 despite GLW's ROIC never
  once going negative in 11 years).
  - **ROE/ROIC's `< 8%` tier** (`_score_avg_min_tier`) was a flat 0/
    hard_fail regardless of sign or depth. Confirmed via a full-universe
    scan: 142/170 (83.5%) of ROIC hard-fails and 61/86 (71%) of ROE
    hard-fails never had a negative average at all. Now split by sign:
    `avg ≥ 0` graduates 20→55 points (new `weak_but_positive` label, not
    hard_fail); `avg < 0` unchanged (flat 0, hard_fail). See
    `profitability.md`'s "ROE and ROIC tiering" section for the exact
    formula and ceiling rationale.
  - **CCC's `sustained_upward`** (all three return sites in
    `_classify_positive_ccc_trend`) was likewise a flat 0. Confirmed via
    a full-universe scan: median worsening 26.3 days, p75 51.8 — now
    graduates 40→0 between 10 and 50 days (`CCC_UPWARD_MILD_DAYS`/
    `CCC_UPWARD_SEVERE_DAYS`), using the robust late-window direction
    (not the raw one) for the spike-guard branch specifically, since raw
    direction is deceptively non-negative there. See `profitability.md`'s
    "Cash Conversion Cycle" section.
  - **Companion floor, non-negotiable, shipped in the same change**:
    `_verdict_for` gained a `score < 70 → Fail` check (mirroring Debt's
    own `PASS_SCORE_THRESHOLD`) — before this, `hard_fail` was the
    *only* thing keeping a low-scoring, non-hard-fail ticker from
    displaying "Pass" (the same pre-existing gap already noted in the
    entry above via FICO). Stress-tested BEFORE shipping: without the
    floor, graduating ROE/ROIC alone would have flipped 153 tickers to a
    false Pass (146 of them, 95%, still scoring under 70).
  - **The floor's blast radius turned out much larger than the graduated
    fix's own direct effect, confirmed via a full-universe recompute
    before shipping (not assumed) — 189 Step 4 verdict changes, not the
    ~7 originally estimated from an isolated simulation.** Because
    `hard_fail` was previously the *only* mechanism keeping any
    non-hard-fail Step 4 ticker's verdict honest, adding a real,
    permanent score floor to `_verdict_for` necessarily also corrects
    every OTHER Step 4 ticker already below 70 for unrelated reasons
    (mediocre-but-not-hard-fail ROE/ROIC, weak Revenue-vs-AR, weak CCC)
    — not just the ones this specific fix touches. Breakdown: **7 flip to
    a genuine Pass** (VZ, T, CFG, KR, EFX, WCN, CNSWF — the graduated
    fix's own direct, originally-expected effect). **182 flip from a
    previously-masked Pass to a correctly-computed Fail** — of those,
    135 have an *unchanged* score (never touched by the graduated fix at
    all, already below 70 before this build) and 47 have an improved
    score that still lands under 70. This is the same class of discovery
    Debt's own residual-floor fix already produced (AVB/EQR/GEHC/HON/
    HST/IFF/KIM/O/REG flipping Pass → Fail at an unchanged score) — an
    explicit, deliberate decision to accept the wider correction rather
    than scope the floor artificially narrow, made mid-rollout after
    surfacing the discrepancy between the isolated simulation and the
    real, shared-function effect.
  - **GLW itself: Step 4 score 35 → 58, verdict stays Fail** — correctly:
    GLW's ROIC (avg 6.42%) and CCC (~18 days worse than its 2016-19
    baseline) are genuinely weak, just not capital-destroying. The fix's
    value is a truthful 58 instead of a misleading 35, not a rescue.
  - **Overall Assessment ripple, also measured before shipping**: 27
    tickers' Overall verdict flips, **all upward, 0 regressions** —
    Profitability's ~20% weight in the Overall blend isn't enough on its
    own to newly fail anything. GLW's own Overall Assessment flips
    Fail(68) → Pass(72), even though its Step 4 verdict stays Fail — the
    improved *number* alone is enough for the blend.
- **`AR_EXEMPT_TYPES` extended to Bank/Insurance/Utility/REIT (2026-09-04) —
  a deliberate design decision, not a bug fix.** Previously REIT-only,
  while `ROIC_EXEMPT_TYPES`/`CCC_EXEMPT_TYPES` already covered all four
  types (see `data/step4_data.py`'s own constants). Revenue-vs-Accounts-
  Receivable isn't a meaningful signal for Bank/Insurance/Utility either —
  their revenue recognition doesn't map onto ordinary trade receivables the
  way a Standard operating company's does, the same reasoning REIT's
  existing exemption already rests on. `score_step4`'s weight
  renormalization (`scoring/step4.py`) is fully generic over whatever
  metrics are `applicable`, so this required no scoring-math change at
  all — only the exemption gate itself — confirmed by running the change
  against real cached data before shipping: Bank/Insurance/Utility become
  100%-ROE-weighted, same as REIT already was. Before/after on real cached
  tickers: **JPM** (Bank) 65/Fail → 85/Pass; **MET**/**PRU** (Insurance)
  33/Fail → 60/Fail; **DUK** (Utility) 51/Fail → 60/Fail; **SO** (Utility)
  64/Fail → 60/Fail (AR was pulling this one's blend *up*, not down before
  this change — an expected consequence of the reweighting, not a
  regression). REIT tickers (**O**, **PLD**) are unaffected, already
  exempt before this change.

Overall Assessment's step weighting (`backend/scoring/overall.py::STEP_WEIGHTS`
/ `frontend/lib/overallScore.ts::STEP_WEIGHTS` — must never drift from each
other, see that constant's own comment) was rebalanced 2026-07-31, following
an investigation into cases where Overall read "Pass"/"Strong Pass" while a
contributing step genuinely scored below the shared 70 Pass floor:

- **What actually lands in a ticker's full Overall blend** (i.e. `STEP_WEIGHTS`
  values as fractions of the 69% non-Moat portion, times `1 - MOAT_WEIGHT`,
  plus Moat's own 31%) is Financials 24% (unchanged), Growth Rate 10% (was
  15%), Debt 15% (was 10%), Profitability 20% (was ~19%, itself a rounding
  artifact of the old 0.28×0.69 — not a prior bug in the code, which always
  summed to exactly 100%), Moat 31% (unchanged).
- **Motivation**: Debt's previously-lowest weight (10%) let genuine
  per-step Fails get fully absorbed by strong scores elsewhere — worked
  examples: MA (Debt genuinely `Fail` at 67) blended to Overall 92
  "Strong Pass" pre-rebalance, now 90 "Pass"; FICO (Debt `Fail` at 52)
  blended to 89 "Pass" pre-rebalance, now 87 "Pass" (still Pass — see
  below, reweighting alone is a limited lever).
- **A universe-wide investigation found this contradiction pattern in
  ~25% of tickers (125/493)**, split roughly evenly between two distinct
  causes: about half (62) are genuine per-step Fails diluted by blend
  weighting (what this rebalance targets), and about half (63) are cases
  where *no* step says "Fail" at all — the sub-70 step's own verdict gate
  (see Growth Rate's magnitude-tier gate above, and Profitability's
  equivalent `hard_fail`-gated `_verdict_for`, which shows "Pass" for 206
  tickers scoring <70 — a bigger version of the same pattern) already masks
  it before blending starts. **Reweighting cannot fix the masked half** —
  confirmed via sensitivity testing (even a larger Debt-weight shift to
  25% only flipped 4/111 complete-data FICO-type tickers to Fail). Growth
  Rate/Profitability's own verdict gates are a separate, not-yet-addressed
  question.
- **Not yet built**: Debt's own breach-context/scoring nuance (Debt/EBITDA
  and Current Ratio) is unchanged by this rebalance — a distinct follow-up.

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

**Excluded from Bank → classified `"Standard"`:**

| Ticker | NII/revenue | Business model |
|---|---|---|
| V | -1.5% | Payment network (Visa) — no cardmember lending, small net interest *expense* |
| MA | -2.2% | Payment network (Mastercard) — no cardmember lending |
| PYPL | +0.2% | Payment processor/digital wallet — positive NII is float/interest on customer balances, not a loan book |
| GPN | -6.4% | Payment processor/merchant acquirer (Global Payments) — no lending |
| APO | -0.8% | Alternative asset manager/PE (Apollo) — no banking subsidiary |
| ARES | -1.5% | Alternative asset manager (Ares Management) — no banking subsidiary |
| BEN | -1.1% | Traditional asset manager (Franklin Resources/Templeton) — no banking subsidiary |
| BLK | -0.09% | Asset manager (BlackRock), the largest in the world — no banking subsidiary |
| BX | -0.7% | PE/alternative asset manager (Blackstone) — no banking subsidiary |
| IVZ | -0.5% | Asset manager (Invesco) — no banking subsidiary |
| KKR | +0.6% | PE/alternative asset manager — positive but negligible NII, not a real loan book |
| TROW | +6.8% | Traditional/mutual-fund asset manager (T. Rowe Price) — no banking subsidiary; NII is short-term investment income, not a retail/commercial loan book |
| PFG | -0.01% | Insurance and retirement-services company (Principal Financial Group) — not a lender at all; industry text alone puts it in the Bank-keyword branch |

**Confirmed lenders — kept as `"Bank"`:**

| Ticker | NII/revenue | Business model |
|---|---|---|
| SYF | 96.6% | Private-label/co-brand credit-card issuer (Synchrony) with Synchrony Bank — pure consumer lending business |
| COF | 61.9% | Credit-card issuer *and* retail bank (Capital One) — full consumer lending book |
| SCHW | 42.5% | Broker with Charles Schwab Bank — real deposit-taking/lending balance sheet |
| AXP | 21.6% | Card network *with* a real cardmember loan book (American Express), unlike V/MA |
| AMP | 17.2% | Ameriprise Financial — has Ameriprise Bank FSB subsidiary |
| NTRS | 16.9% | Northern Trust — custody bank with real lending/deposit operations |
| RJF | 13.5% | Raymond James — has Raymond James Bank subsidiary |
| STT | 13.1% | State Street — custody bank (State Street Bank and Trust) with real lending |
| BNY | 12.2% | The Bank of New York Mellon — chartered custody bank; deposits are 70.3% of total assets (FY2025, SEC EDGAR `Deposits`/`Assets` XBRL tags). Shares IBKR's exact "Investment - Banking & Investment Services" industry text, but unlike IBKR (whose `Deposits` tag was never filed — see `BANK_CET1_NPL_EXCLUDED_TICKERS` below) is a genuine, materially larger deposit-taking lender — confirmed explicitly here rather than left to be inferred from the shared industry string |
| GS | 10.8% | Goldman Sachs — investment bank with real deposit-taking/lending and trading-book NII |
| MS | 8.7% | Morgan Stanley — investment bank with Morgan Stanley Private Bank / wealth-management lending |

**HOOD was previously listed here (33.9% NII, "margin lending and
cash-sweep interest are real NII, not incidental") and has been removed —
NII-as-%-of-revenue answers "does this company lend?", not "does this
company report under banking regulation?", and the latter is what Bank's
CET1/NPL check actually requires. See "Bank classification requires
genuine CET1/NPL-reporting capability, not just lending activity" below
for the corrected standard and why HOOD (and three others) moved to
`NON_LENDER_TICKER_OVERRIDES` on that basis instead.**

**This list does not auto-generalize.** A new ticker that lands in the same
sector/industry buckets (e.g. a newly-listed fintech IPO, a new asset
manager) classifies as `"Bank"` by default and needs the same manual
NII/revenue check before being added to either side of this list — there
is no automated signal that would catch a new non-lender or a new lender
on its own.

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

Fixed by broadening the check: use the literal `deposits` tag if present
and material, otherwise the largest plausible deposit-liability-shaped tag
— excluding tag names containing `interest`, `fee`, `expense`, `income`,
`increasedecrease`, `adjustmentsfor`, `paymentsfor`, `proceedsfrom`,
`acquisition`, `premium`, `fairvaluedisclosure`, or `reserve`. That last
exclusion is load-bearing, not incidental: IBKR's own largest
`*deposit*`-named tag is `cashreservedepositrequiredandmade` (22.9% of
assets) — an SEC Rule 15c3-3 customer segregated-cash reserve requirement
(a broker-dealer customer-protection concept), not a deposit liability
that funds the balance sheet the way a bank's does. Without excluding
`reserve`, IBKR would have wrongly cleared this check.

**Result: 26 of the 32 Bank-classified tickers are confirmed genuine
deposit-taking institutions** (real deposits 15–81% of total assets,
including HSBC/MTB once correctly measured): AMP, AXP, BAC, BNY, C, CFG,
COF, FITB, GS, HBAN, JPM, KEY, MS, MTB, NBN, NTRS, PNC, RF, RJF, RY, SCHW,
STT, SYF, TFC, TMP, USB, WFC, HSBC.

**4 tickers have no genuine deposit-liability tag at any magnitude —
added to `NON_LENDER_TICKER_OVERRIDES`:**

| Ticker | Industry | Best deposit-shaped tag found | Business |
|---|---|---|---|
| IBKR | Investment - Banking & Investment Services | none (closest was the customer-reserve tag above, excluded as non-deposit) | Interactive Brokers — broker-dealer, large margin-lending book, no bank charter |
| HOOD | Financial - Capital Markets | `depositswithclearingorganizationsandotherssecurities` = 0.7% of assets (immaterial) | Robinhood — broker-dealer; previously kept as Bank on NII grounds (see the removed table row above) — that was the wrong test |
| SEIC | Asset Management | none | SEI Investments — confirmed via FMP profile description as a pure asset-management/investment-processing firm, no banking subsidiary |
| SEZL | Financial - Credit Services | none | Sezzle — confirmed via FMP profile description as a BNPL/consumer-credit fintech, no bank charter |

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

`BANK_CET1_NPL_EXCLUDED_TICKERS` (`data/step5_data.py`) is now an empty
set — IBKR/HOOD's presence there is redundant once they're
`"Standard"` everywhere (a Standard-classified ticker never reaches the
Bank branch that constant gates). The mechanism itself (constant + branch
+ classification note) is kept rather than deleted outright, since
`tests/test_step5_data.py`'s own regression test for it exercises the
behavior generically, independent of which real tickers populate the set.

## Valuation (Step 3) scoring notes

Three fixes shipped together 2026-08-08, all originating from an
investigation into what Discounted Net Income (Normalized) actually
computes — see `valuation.md` for the exact current formulas/mechanism;
these are the design decisions and fixes behind them.

- **`RECOVERY_PATTERNS` (`scoring/trend.py`) was missing
  `dip_durably_resolved`**, the age-aware recovery pattern added earlier
  the same day (see the Financials section above) — scored identically to
  `multiple_dips_resolved` in `classify_trend` (both 75) and documented
  there as meant to be treated the same by any caller, but the set itself
  was never updated. Three call sites gate on `pattern in
  RECOVERY_PATTERNS`: `scoring/step1.py`'s FCF cash-burn-recovery check
  (Revenue/NI/OI/CFO's own Step 1 scores read `classify_trend`'s score
  directly, not this set, so they already benefited immediately — only
  FCF's own recovery check had the gap), Step 3's method-selection tree
  (`_positive_and_increasing`/`_fcf_positive_and_consistent`), and Step
  4's ROE/ROIC min-year-consistency gate and negative-equity Net Income
  substitute. Fixed by adding the pattern to the set — one line, every
  call site already treats the set as the single source of truth.
  Confirmed via a full 503-ticker before/after scan: 0 Step 1 changes (no
  cached ticker happened to hit the FCF-specific gap), 17 Step 3
  method-selection changes, 1 Step 4 verdict flip. Every Step 3 change is
  an upgrade to a more direct method, never a regression: **AWK, CMS,
  EXC, LVS, PNR, PRU, TROW** (DNI_NORMALIZED → DNI); **DAL, MDT, NWS,
  NWSA, PFG** (DNI_NORMALIZED → DFCF); **IQV, T** (DNI → DFCF); **TER**
  (DNI → DCF); **KHC, SJM** (PASS → DFCF — Valuation was previously
  unavailable for these two entirely). **MCK**'s Step 4 ROE negative-
  equity substitute flips from `negative_equity_inconsistent_income` (60
  pts) to `positive_despite_negative_equity` (100 pts), score 90 → 100,
  Pass → Strong Pass.

- **DNI_NORMALIZED's 5-period smoothed average double-counted TTM when a
  fiscal year had just closed with no newer quarter reported since.** TTM
  is a genuine sum of the 4 most recent quarterly filings
  (`helpers/ttm.py::sum_last_four_quarters`), never a copy of the annual
  figure — but the smoothing average (`net_income_clean[-5:]`, all annual
  values + TTM appended unconditionally) has no way to tell "TTM is a
  distinct, more-current period" from "TTM's 4 quarters ARE the latest
  annual filing's own Q1–Q4, describing the identical period." In the
  latter case that one period counted twice in a 5-point average (2/5
  weight instead of the intended 1/5) while every other period counted
  once. Confirmed real case: **SNDK**'s FY2026 (a memory-pricing
  supercycle year, $11.4B Net Income — more than the prior 4 years
  combined) was being counted twice, inflating `net_income_smoothed` from
  a corrected $1.61B to $3.68B — directly undermining the metric's own
  purpose, since normalization exists specifically to dilute an anomalous
  year, not double-weight it.
  - **Detection is period-identity, not value-equality**
    (`helpers/ttm.py::is_ttm_period_duplicate_of_last_fy`): compares the 4
    most recent quarters' own `fiscalYear`/`period` labels against the
    latest annual filing's, not the resulting sums — a coincidental value
    match isn't the same condition (would false-clear on genuinely
    distinct periods), and a genuine period match can differ slightly in
    value after a restatement (would false-miss under a value check).
    Confirmed via a full-universe scan that both checks currently agree
    100% of the time on real cached data (30/503 tickers hit the NI
    condition, 28/503 the CFO condition) — but the period-based check is
    the structurally correct one regardless.
  - **Fix (Option B): when detected, TTM is excluded and the average is
    taken over the prior 5 *distinct* fiscal years instead of 4** — not
    just dropping to a 4-point average, which would work but shrink the
    window. `scoring/step3.py::trailing_smoothed_average` (shared by all
    three normalized methods — see below) falls back to including TTM if
    excluding it would leave fewer than 2 points, mirroring
    `step4.py::recovery_excluded_prefix_length`'s own "never make it less
    scoreable" guard — not reachable for any currently-tracked ticker
    (every ticker hitting the duplicate condition has 5+ years of
    history) but cheap insurance for a future thin-history ticker.
  - Of the 30 NI-affected tickers, 10 auto-selected DNI_NORMALIZED at the
    time of the fix (**CLX, FDX, MCHP, MDT, NKE, NWS, NWSA, SNDK, SYY,
    WDC**) — though after the `RECOVERY_PATTERNS` fix above lands first,
    **MDT/NWS/NWSA no longer auto-select DNI_NORMALIZED at all** (they
    flip to DFCF), leaving **CLX, FDX, MCHP, NKE, SNDK, SYY, WDC** as the
    tickers whose live Auto Calculation value this fix actually changes;
    the rest only affect what Manual Calculation's DNI_NORMALIZED
    pre-fill would show if a user switched to it. Confirmed real
    before/after (Option B, post-`RECOVERY_PATTERNS`-fix): SNDK
    $3.68B → $1.61B (−56%), WDC $3.65B → $2.07B (−43%), MCHP $0.91B →
    $1.13B (+24%), NKE $4.04B → $4.63B (+15%).

- **New `CF_NORMALIZED`/`FCF_NORMALIZED` methods — Manual Calculation /
  Custom Valuation-only, never auto-selected.** Motivated by a real gap:
  CFO/FCF growing very fast in the last 2-3 years, where the raw TTM
  figure would overstate a sustainable run-rate the way DNI_NORMALIZED
  already protects against for Net Income. Two candidate auto-trigger
  designs were tested against the live universe and both rejected in
  favor of a manual-only method: a 3-year CAGR threshold flagged 40-70+
  tickers even at 25%, essentially "most growth stocks"; a spike-ratio
  threshold (TTM ÷ avg of prior 3 years, reusing the
  `ROE_SPIKE_RATIO_THRESHOLD`/`DIP_BASELINE_SPIKE_RATIO` convention)
  still flagged NVDA/MU/PLTR/AMD even at 2.5x. Computed smoothed values
  for a sample of both groups show why: **NVDA** CFO $125.6B raw vs.
  $41.9B smoothed (+200%), **AMD** FCF $8.6B vs. $3.3B (+158%), **DASH**
  FCF $2.3B vs. $1.16B (+97%) — all durable, still-accelerating
  structural growth that a smoothing trigger would systematically
  under-value — statistically indistinguishable, on CFO/FCF magnitude
  alone, from **SNDK** CFO $11.7B vs. $2.4B (+391%) and **WDC** FCF
  $3.5B vs. $0.7B (+392%) — a genuine cyclical memory-pricing supercycle
  where smoothing is the right call. FMP has no industry-cyclicality
  signal that could tell these apart (the existing
  `NON_LENDER_TICKER_OVERRIDES` table above required manual per-ticker
  verification for a much narrower classification problem). Rather than
  risk auto-suppressing exactly the highest-quality compounders in the
  tracked universe, `select_method`'s tree is unchanged — CF_NORMALIZED/
  FCF_NORMALIZED exist purely as method choices a user can pick in Manual
  Calculation/Custom Valuation, pre-filled from `cfo_smoothed`/
  `fcf_smoothed` (computed unconditionally, same pattern as
  `net_income_smoothed`/`pb_mean_ratio`, and reusing the TTM-duplicate
  fix above), and behave identically to DNI_NORMALIZED once selected —
  same 20yr engine, same Custom Valuation pre-fill/freeze semantics, same
  FX handling (already-USD by the time smoothing runs, since every raw
  figure is converted immediately after each FMP pull, before any
  smoothing math).

- **Item 4 (2026-08-08, docs-only): `valuation.md`'s `fx_rate` section was
  stale**, still describing it as "always 1.0, no conversion performed" —
  true before non-USD reported-currency conversion shipped (`dd5045f`),
  false since. Rewrote `valuation.md` §2.1 (inputs table) and added a new
  §2.1b covering the real mechanism: per-ticker `reportedCurrency` →
  `<CCY>USD` spot-rate resolution, cached via the same
  `FundamentalsCache`/`get_or_fetch` machinery every other fetch uses,
  applied once upfront to every monetary figure before any scoring/
  smoothing math runs, never silently falling back to 1.0 (an
  unresolvable rate reads `insufficient_data`/PASS instead), and shown in
  the UI as a caption under Fair Value ("Converted from `<CCY>` @
  `<rate>` (as of `<date>`)"). `docs/valuation.md` was checked too (per
  this fix's own instructions) but has no FX-related content at all, stale
  or otherwise — no change needed there.
  - **Found, then resolved (2026-08-08, follow-up cleanup):**
    `backend/core/config.py` defined `fx_rate_staleness_days = 1`, with a
    comment explaining it was intended to be tighter than
    `cache_staleness_days` (7 days) since "a forex spot rate moves daily"
    — and `dd5045f`'s own commit message claimed the FX cache used this
    1-day setting. It never did: `data/step3_data.py::get_step3_data`
    always passed the general `cache_staleness_days` (not
    `fx_rate_staleness_days`) into `_resolve_fx_rate` at its only call
    site, and `fx_rate_staleness_days` was otherwise unreferenced anywhere
    in the codebase — confirmed via project-wide grep. Rather than wire
    the unused setting in (which would have changed live FX-refresh
    behavior from 7 days to 1), the user's call was to keep FX rate
    refresh aligned with the same `cache_staleness_days` window as
    fundamentals — this is a genuine choice, not just accepting the
    accidental status quo: a spot rate moving daily doesn't necessarily
    need a tighter cache than fundamentals if the intrinsic-value
    calculation it feeds is itself only meaningfully updated on a similar
    cadence. `fx_rate_staleness_days` was deleted (not wired in) as a
    result; `valuation.md` §2.1b no longer mentions a separate FX
    staleness setting at all, describing the single shared 7-day window
    only.

- **`book_value_per_share`'s formula and anchor fixed (2026-08-13)**, following a fuller
  Price-to-Book methodology spec review. Previously sourced from FMP's own `bookValuePerShare`
  ratio field (raw stockholders' equity per share -- confirmed identical to FMP's own
  `shareholdersEquityPerShare`, i.e. **not** intangibles-stripped) off the **latest annual**
  `ratios` row, up to ~12 months stale versus the quarterly balance-sheet data this same
  calculation already used for `total_debt`/`cash_and_st_investments` (a self-inconsistency,
  not just a spec mismatch -- a comment elsewhere in the same function already cites the
  original source spec's own "latest instant, not FY-end" rule for those other two fields).
  Now computed directly from the latest quarter's balance sheet
  (`totalAssets − goodwillAndIntangibleAssets − totalLiabilities`, divided by shares
  outstanding) -- no new FMP fetch, every field was already being pulled for `debt_metrics`.
  Confirmed via real cached data: JPM $129.97 (FY2025 annual, raw equity) → $115.80 (Q2 2026
  quarter, tangible); O (Realty Income) $44.35 → $39.52 -- both moves reflect the anchor
  advancing ~2 quarters *and* intangibles being stripped, not either alone. At the time, the
  *historical* P/B ratio series feeding the mean/SD bands (`valuation.md` §3.2) was left on
  FMP's own `priceToBookRatio` (non-tangible, annual-lagged) -- documented as a deliberate,
  accepted approximation rather than a fix, since rebuilding it would need a new annual
  balance-sheet fetch this calculation didn't otherwise require. See the next entry for why
  that approximation was revisited and fixed two days later.

- **Historical P/B series rebuilt onto the same tangible/quarterly-consistent basis as the
  point estimate above (2026-08-15)**, closing the gap the prior entry left open. Averaging a
  series computed under one book-value definition (FMP's raw `priceToBookRatio`) and
  multiplying it by a point value computed under a different one (the corrected tangible
  `book_value_per_share`) produces a number that isn't internally consistent -- this was worth
  fixing outright, not leaving as a documented approximation, once actually checked against
  real data (see below). Implementation: `step3_data.py` now also fetches
  `balance_sheet_statement`/`annual` (10yr) -- the same cache key Step 4/Step 5 already
  populate, so a cache hit with zero new FMP calls for any ticker already scored elsewhere in
  the app, not a new per-ticker cost. Each year's `historical_pb_ratios` entry is rescaled
  algebraically rather than refetched from a separate price series: FMP's own
  `priceToBookRatio = price / bookValuePerShare` for that fiscal year, so multiplying by
  `(totalStockholdersEquity / tangible_book_value)` for the same year converts it to
  `price / tangible_book_value_per_share` exactly -- the share-count term FMP's own
  `bookValuePerShare` embeds cancels out of the algebra, so no separate historical price fetch
  or reconstructed share count is needed. A year is dropped (not fabricated as zero) if its
  balance sheet can't be matched by fiscal year, a required field is missing, or the resulting
  tangible book value is non-positive -- the same "don't fabricate a meaningless multiple"
  convention `book_value_per_share` itself already uses; `pb_lookback`'s 10yr/5yr threshold is
  based on the count of years that clear these guards, not the raw FMP series length (confirmed
  the 5yr fallback still engages correctly for a thinner-history ticker, HOOD, which had only 5
  of its 7 raw years survive the guards).

  Confirmed via real cached data this was a genuine, material inconsistency, not a rounding
  concern: **JPM**'s mean P/B moved 1.61x → 2.01x, intrinsic value $186.75 → $232.75 (+24.6%,
  verdict unchanged, still overvalued); **BAC** +33.5%; **WFC** +23.3%; **O** (REIT) +25.2%,
  with its verdict flipping **fair → undervalued**; **AVB** moved essentially not at all
  (−0.2%) -- its goodwill/intangibles load is small relative to its equity, so the tangible and
  raw bases were already nearly identical for that specific ticker. This is the expected shape
  of the fix (it corrects for how much goodwill/intangibles a company carries, not a uniform
  shift applied to every ticker alike), not evidence the fix is inconsistent.

## Speculative Growth (new classification) scoring notes

Speculative Growth is a new, independent, read-only lens layered on top of the existing 5-step
framework (`scoring/speculative_growth.py`, `data/speculative_growth_data.py`) -- never touches
Step1-5/Overall Assessment scoring. Gate: `company_type == "Standard"` AND Moat is Narrow/Wide AND
Step2 forward growth clears `GROWTH_GATE_MIN_PCT` (15%). Trailing growth, gross margin, CFO
sign/direction, cash runway, and PSG are informational only, never gates.

- **Profitability gate added 2026-08-15**, following a false-positive investigation: mature,
  thoroughly profitable, wide/narrow-moat companies (**MSFT, ABNB, APH, MA, TSM, AVGO, ANET** --
  all user-reported) were qualifying purely on Moat + Growth, since profitability was originally
  scoped as informational-only (to accommodate the spec's "can be negative, acceptable" framing for
  NI/CFO) with the unintended side effect that a company didn't need to be unprofitable *at all* to
  qualify. Confirmed via real cached data: all 7 named tickers pass Moat+Growth cleanly and are
  durably profitable (0-1 of 10-11 tracked annual+TTM periods negative, except ABNB at 5/10 -- still
  a tie, not a majority). Sized the actual false-positive rate before fixing: **73 of 77 (94.8%)**
  currently-qualifying Standard-type tickers in the tracked universe (S&P500+Dow+Watchlist) were
  NI-profitable; only 4 (CRWD, LITE, NET, TRMB) were genuinely NI-negative. Separately confirmed the
  growth threshold itself is not the effective lever -- growth is roughly uniformly spread among the
  73 profitable qualifiers (49% still clear 20%, 21% still clear 30%, ORCL/MRK/NKE-tier names still
  clear 40%), so raising it can't selectively exclude mature blue-chips without also cutting
  legitimate high-growth candidates.
- **Gate shape: NI negative in a majority (>50%) of tracked annual+TTM periods**
  (`scoring/speculative_growth.py::is_not_durably_profitable`), not a flat `NI TTM <= 0` check.
  A flat TTM-only check was tried first and correctly excludes all 7 named false positives, but
  leaves one edge case: **TRMB** (10 of 11 tracked periods profitable, only the latest TTM negative
  off a one-off charge) is a mature, historically-profitable company having a rough year, not a
  "not yet profitable" story -- yet a flat TTM check would still let it through, since it was
  already qualifying under the old gate too (moat=narrow, growth=15.6%, just barely above the
  threshold). Majority-of-periods correctly excludes TRMB while still including every genuine case
  (CRWD 10/11, LITE 6/11, NET 11/11 negative) and leaving RKLB (8/8, the original design-phase
  spot-check name) unaffected. Validated against all 5 original spot-check names (RKLB/IONQ/SOUN/
  ACHR/JOBY): RKLB (the only one that already qualified on moat+growth) is unaffected by the new
  gate; IONQ/SOUN/ACHR/JOBY were already excluded before this fix on moat/growth grounds unrelated
  to profitability (no moat set, or SOUN's 4.8% growth), so the new gate changes nothing for them.
  An empty/missing NI series fails closed (reads as durably profitable, i.e. doesn't qualify),
  matching every other gate in this module.
- **Confirmed real-world effect**: universe-wide qualifying count drops from 77 to 10. All 7 named
  false positives excluded. The 10 remaining qualifiers split into 3 still NI-negative (CRWD, LITE,
  NET) and 7 with a positive NI TTM but majority-negative history -- i.e. recently-turned-profitable
  growth names (DASH, DDOG, DOCN, MRVL, PANW, PLTR, UBER) -- the intended "not yet *durably*
  profitable" reading, not new false positives.

## Trend structure analysis (Technical)

A new, independent, read-only lens on price structure -- swing highs/lows, break-of-structure
(BOS) flips, and a blended -10..+10 conviction score -- sourced from **Yahoo Finance**
(`backend/clients/yahoo_client.py`, `yfinance`), not FMP, so it keeps working through an
`FMP_ENABLED=false` pause. Never touches Step 1-5/Overall Assessment scoring or the existing
`FundamentalsCache`/FMP pipeline in any way -- a second, parallel data path from ingestion through
to display.

- **Engine** (`backend/analysis/trend_structure/`, pure functions/dataclasses, no DB/HTTP):
  fractal swing detection on daily CLOSE only (N=5 bars each side); each swing classified against
  the highest/lowest of the **trailing 3** same-type swings (not just the single prior one) into
  HH/HL ("bullish") or LH/LL ("bearish"); Wilder's ATR(14) from real OHLC gates confirmation via
  `ratio = margin/ATR`. **Flip gate**: `trend_state` only flips to uptrend on a confirmed
  (ratio≥1.0) HH, or to downtrend on a confirmed LL -- a confirmed LH/HL (regardless of ratio)
  never flips state, only sets `warning_flag`+`warning_swing`, clearing on the next same-direction
  confirmed (≥0.5) swing or converting into a real flip once the genuine opposite extreme
  eventually confirms. `magnitude_tier` (weak/confirmed/strong) only updates on weak-confirmed+
  (≥0.5) same-direction swings -- a tentative (<0.5) swing still bumps `persistence_count` but must
  not change the tier. A 60-day Kaufman Efficiency Ratio (`regime`: "trending" if ER≥0.15 else
  "range-bound") and the blended conviction score (tier/persistence/recency weighted 50/30/20%,
  discounted 0.7x for a non-trending regime and 0.7x again under an active warning) round out the
  output; `bar_level` (1-5, for the Watchlist's bar indicator) is a **continuous rescale** of the
  blended score, computed backend-only and never re-derived on the frontend.
  - **The original spec's bar_level formula and its own reference band table disagreed** (the
    literal `(score+10)/20*4` produces width-5 bands, transitioning at -5/0/5, not the width-4
    bands at -6/-2/2/6 the table itself documents) -- confirmed with the user that the table is
    authoritative; the code uses `(score+10)/20*5` (equivalently `/4`), which reproduces the table
    exactly. See `analysis/trend_structure/conviction.py`'s own comment for the full derivation.
- **Data**: `YahooPriceCache` (ticker+date OHLCV, `backend/clients/yahoo_cache.py`'s own bespoke
  get-or-fetch helpers -- deliberately not routed through `core/cache.py`, which is hard-wired to
  `FundamentalsCache`'s different (ticker, statement_type, period)+raw_json shape) and
  `TrendAnalysis` (ticker-PK, `computed_at`, latest-only, upserted per run -- same convention as
  `TickerScore`; `last_confirmed_swing`/`warning_swing` stored as plain `str` JSON columns, this
  codebase's established convention for a JSON-shaped field, not a native JSON column type, which
  doesn't exist anywhere else in this codebase either).
- **Nightly cron** (`pipeline/nightly_trend_calculation.py`, 3:10 AM, after the two FMP-dependent
  nightly jobs and before the 3:30 AM backup): sweeps the full tracked universe
  (`load_full_tracked_universe`, shared with the fundamentals/score-recompute jobs) via **one**
  `yfinance` multi-ticker batch download (`clients.yahoo_cache.get_or_fetch_price_history_batch`),
  then runs the engine and upserts per ticker -- never one live fetch per ticker. Makes zero FMP
  calls, so unlike `nightly_fundamentals_fetch.py`/`monthly_price_target_snapshot.py` it needs no
  `if not settings.fmp_enabled: ...` guard at all (there's no FMP-gated work to skip). Wired into
  `core/cron_health.py`'s `CRON_JOB_NAMES`/`_EXPECTED_CADENCE_HOURS` as the 12th job.
- **API / Watchlist surfacing**: `GET /api/tickers/{ticker}/trend-analysis` (standalone endpoint,
  `data/trend_analysis_data.py::get_trend_analysis_data`) is designed to feed a future ticker-page
  "Technical" tab -- **not built this round**, UI-only future work. The Watchlist table's own new
  "Trend" column instead reads `bar_level`/`blended_score`/`trend_state` off the existing bulk
  `GET /watchlists/{id}/rows` response (`watchlist_data.py::_compose_row`, cache-only), consistent
  with every other Watchlist column, rather than firing one extra per-row request just for this
  column. `SignalBars` (`frontend/components/watchlist/SignalBars.tsx`) was generalized to a
  `maxBars` prop (default 3, so the existing Moat/Value/vs-SPY 3-bar indicators are unaffected) to
  support this new 5-bar indicator without a duplicate component.
- **Price fallback**: `data/ticker_summary.py::get_summary()`'s quote-fetch block now overrides
  just the `price` field with a live Yahoo close when `FMP_ENABLED=false` (and not `cache_only`) --
  see "Pausing the FMP subscription" above for the full mechanism and what stays untouched.
- **A/D Bullish Divergence (2026-08-23)**: a validated (ticker-clustered p<0.01, replicated on two
  separate backtest universes, ~+2pp hit rate / ~+2% mean-median return to the eventual confirmed
  HH) minor conviction signal layered on top of the swing engine above -- never a standalone entry
  trigger, never applied to bearish/HH-side swings (tested, no edge, intentionally excluded), and
  a binary flag only, not a graduated/magnitude score (never validated at that granularity).
  - **Signal**: `analysis/trend_structure/ad_line.py` adds the Accumulation/Distribution line
    (Money Flow Multiplier * Volume, cumulative sum; MFM reads `0.0`, not NaN, on a zero-range
    high==low bar) and the Chaikin Oscillator (`EMA(3) - EMA(10)` of the A/D line, standard/
    non-Wilder EMA via `adjust=False` -- a deliberate, documented formula choice the same way
    `atr.py` calls out its own Wilder smoothing).
  - **Divergence rule, pinned down exactly after several rounds of clarification (worth recording
    precisely -- easy to misremember or reimplement slightly wrong later):** at each LL swing
    (any ratio), take the literal minimum Chaikin Oscillator value within a **positional
    (trading-bar, not calendar-day) +/-10-bar window centered on that swing's own date** --
    naturally truncated/asymmetric near either end of available history via plain slice bounds,
    never waiting on a future bar that doesn't exist yet (a newly-confirmed LL with only 3-4
    forward trading days gets evaluated on that truncated window immediately, not left pending).
    Call this the swing's own "matched oscillator low." Bullish divergence fires when
    **this matched low is strictly greater than the MIN (floor) of the matched lows of the
    trailing 3 prior *CONFIRMED* (ratio >= `CONFIRMED_RATIO`, 1.0 -- the same threshold
    `state_machine.py` already uses for a genuine trend_state flip) LL swings** -- an exact
    equal value does not count. This deliberately mirrors `classification.py`'s own price-swing
    convention (a new low that stays above the trailing-3 floor classifies as the non-confirming
    "HL", not a new "LL"), just applied to the oscillator's values instead of price. A
    non-confirmed LL still gets its own divergence flag computed against whatever floor already
    exists, but is never itself added to the trailing-3 confirmed pool (`classification.py`'s
    `test_non_confirmed_ll_is_evaluated_but_excluded_from_the_confirmed_pool` is the regression
    test for this specific rule). Zero prior confirmed LLs to build a floor from reads as `False`
    (no baseline), the same "not classifiable without trailing history" convention
    `classify_swings` already uses for HH/HL/LH/LL itself.
  - **Folded into the existing single swing-classification pass, not a second pass or a second
    per-ticker fetch** (`classification.py::classify_swings` gained a third `chaikin_osc`
    parameter; the divergence lookup/comparison happens inline exactly where a new "LL" is
    classified, reusing the same in-memory OHLCV series `engine.py` already computes ATR from).
    Confirmed via a real before/after nightly-job timing comparison (60 tickers, warm Yahoo
    cache to isolate compute cost from network variance): 4.4s baseline vs. 3.6s with this
    feature -- no measurable regression, as expected for one extra O(n) EMA pass plus O(1)-ish
    per-LL-swing window lookups.
  - **Fields**: `TrendAnalysis.ad_bullish_divergence` (bool, nullable) / `ad_divergence_swing_date`
    (date, nullable) hold the ticker's **most recent confirmed LL's** own divergence result only
    (`engine.py` selects it from the full classified list; `classification.py` computes the flag
    for every LL inline as described above). Nullable -- unlike the pure engine's own always-real
    `bool`/`date|None` output -- specifically because `core/db.py::_add_missing_columns` adds
    columns via a raw `ALTER TABLE` with no backfill: existing rows read as `NULL` until the next
    nightly run rewrites every field, and every consumer already treats `None` the same as
    `False`, so this is a transient-read-safety concern only, not a modeling one.
  - **`blended_score` integration**: a flat `1.15x` multiplier (`AD_BULLISH_DIVERGENCE_MULTIPLIER`,
    `conviction.py`), applied as the literal last step -- multiplying the already-fully-computed
    `-10..+10` score, strictly after the regime/warning_flag dampeners are baked in -- and gated
    on `trend_state == "uptrend"`. This is deliberately retrospective, not a downtrend-name
    trigger: it only boosts conviction on names where the divergence-flagged LL has already played
    out into a confirmed uptrend. Can push `blended_score` slightly past the documented +/-10
    ceiling for an already-near-ceiling score (e.g. `10.0 * 1.15 = 11.5`) -- left unclamped, since
    clamping would silently zero out the boost for exactly the highest-conviction names, and
    `compute_bar_level`'s own `min(4, floor(...))` clamp already tolerates it downstream.
  - **UI**: a dedicated "A/D Div." column (`WatchlistTable.tsx`), sitting right after the TREND
    column, showing the matched confirmed-LL swing date (`ad_divergence_swing_date`, already
    "YYYY-MM-DD" as serialized by the backend) when `ad_bullish_divergence === true`, and a fully
    empty cell (no dash/placeholder) otherwise. Superseded an initial small `bg-chart-purple` dot
    badge next to TREND's own `SignalBars` (2026-08-23) -- replaced same-day per user request, in
    favor of showing the actual date rather than a bare boolean marker. `WatchlistRowOut` (both
    `core/schemas.py` and `data/watchlist_data.py::_compose_row`) carries
    `ad_divergence_swing_date` alongside `ad_bullish_divergence` for this.
  - **Spot-checked against known backtest ticker/dates post-implementation**: **CMG (2018-12-24)
    matches exactly** -- a genuine confirmed LL (ratio 1.71) at that literal date, `ad_bullish_
    divergence=True`. This is the relevant confirmation for what actually shipped.
    **GD (2021-02-24) was a mismatched test case, not a discrepancy**: that date is a genuine
    swing **high** (149.39, HH) for GD, confirmed independently at the raw `find_swing_lows`/
    `find_swing_highs` level -- correctly so, since it was the original *bearish* divergence
    example (a swing-high case), a variant that was tested and explicitly excluded/dropped early
    in the backtest process (see this section's own "NOT applicable to bearish divergence" scope
    note above) and was never part of what shipped here. It has no bearing on the bullish-only LL
    divergence logic in this build. The CMG match, plus classification.py's 12 unit tests covering
    the exact algorithm above with hand-verified expected floors/matches, are the correctness
    evidence for the divergence logic itself.
- **SMA (20/50/200) position tracking (2026-08-23)**: a second, much simpler technical signal
  layered on the same swing engine's data -- for each ticker, how far the latest close sits
  above/below its 20/50/200-day SMA (`position_pct = (close - SMA)/SMA*100`), plus whether it
  crossed the SMA today (`cross: "up" | "down" | None`). Folds into the exact same nightly batch
  fetch the swing engine already uses -- no new fetch, no second pass over the universe, no
  nightly-loop or cron change at all.
  - **New `analysis/trend_structure/sma_position.py::compute_sma_position(close, period)`**, a
    single pure function matching `atr.py`'s one-file-per-concern style (deliberately not a reuse
    of `analysis/ma_magnet/indicators.py::compute_mas` -- `ma_magnet` is explicitly unwired
    research code production never imports from). `position_pct` is `None` whenever fewer than
    `period` bars of history exist yet (`rolling(window=period).mean()`'s own `min_periods ==
    window` already produces NaN there -- a recent-IPO ticker degrades the same way the rest of
    this engine already does for thin history).
  - **Crossing compares the PRIOR bar's own SMA against the PRIOR close, not today's SMA reused
    against yesterday's close** -- a deliberate choice, since `rolling().mean()` produces a
    distinct SMA value per day: reusing today's SMA would false-positive or miss real crossings
    whenever the SMA itself moved meaningfully day over day. `cross` is `None` whenever there's no
    valid prior bar to compare against (a ticker's very first eligible bar, i.e. exactly `period`
    bars of history), even when `position_pct` itself is real.
  - **A single tri-state `cross` field per SMA**, not two separate booleans (`crossed_up`/
    `crossed_down`) -- the two booleans could never both be true, so one field is simpler and maps
    directly to the Watchlist cell's single background-tint decision.
  - **`today_sma == 0` (and the prior day's SMA) is guarded, returns `None` rather than
    dividing.** Effectively impossible for a real equity close, but a `0/0`/`x/0` division would
    otherwise upsert `inf`/`nan` into SQLite, which Python's default JSON encoder serializes as
    the literal tokens `Infinity`/`NaN` -- invalid strict JSON that would break the frontend's
    `JSON.parse` on that one row.
  - **Six new flat fields** (`sma20_position_pct`/`sma20_cross`, ×3 for 50/200) threaded through
    `TrendStructureResult` -> `TrendAnalysis` (nullable, same `_add_missing_columns`-has-no-
    backfill reasoning as `ad_bullish_divergence`) -> `TrendAnalysisOut` -> `WatchlistRowOut` ->
    `_compose_row` -- the exact plumbing shape the A/D Bullish Divergence feature above already
    established, matched file-for-file rather than inventing a new shape.
  - **Watchlist**: three new columns (20SMA/50SMA/200SMA, `WatchlistTable.tsx`) show
    `position_pct` as `"+X.X%"`/`"-X.X%"`, text colored green/red by sign (`text-positive`/
    `text-negative`, the same tokens the Rating column's own sign-based coloring already uses),
    cell background lightly tinted (`bg-positive/8`/`bg-negative/8` -- deliberately lighter than
    `tierColor.ts`'s existing `/16` chip convention, so it reads as a subtle full-cell highlight
    rather than a repeat of the chip style) on a same-day cross. Sortable via the existing
    sort-field dropdown (`SORT_FIELD_OPTIONS` in `app/watchlist/page.tsx`) by `position_pct` --
    this table has no click-to-sort column headers at all, so no per-column header wiring was
    needed, only the three new `WatchlistSortField` entries.

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before
  writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before
  committing each phase's work, and again before pushing — push only after
  explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.

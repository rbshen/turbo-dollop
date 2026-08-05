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

## Folder layout

```
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
  clients/     Thin external API clients: fmp_client.py,
               alpha_vantage_client.py, sec_edgar.py.
  helpers/     Shared calculation helpers consumed by data/: ttm.py,
               shares.py, debt_metrics.py, npl.py, bank_capital_metrics.py,
               discount_rate_config.py, first.py.
  data/        Per-tab data orchestration (the get_stepN_data pattern):
               step1_data.py .. step5_data.py, ticker_summary.py,
               financials_data.py, ratios_data.py, analyst_ratings_data.py,
               news_data.py, news_sentiment_data.py, segmentation_data.py,
               moat.py, watchlist_data.py, watchlists.py,
               saved_screener_filters.py, ticker_score.py.
  scoring/     Pure scoring functions (classification.py, trend.py,
               series_trend.py, step1.py..step5.py, overall.py) — this
               package predates the 2026-08-05 reorg and was always split
               out; unchanged by it.
  scrapers/    Index/constituent Wikipedia scrapers: index_scraper.py,
               sp500_scraper.py, dow_scraper.py, refresh_sp500_list.py,
               refresh_dow_list.py.
  pipeline/    Production cron/maintenance entrypoints that read/write the
               real DB: nightly_fundamentals_fetch.py,
               monthly_price_target_snapshot.py, recompute_ticker_scores.py,
               audit_fixture_contamination.py, refresh.py.
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
tier) is the **sole** data source. All fundamentals, prices, and company
classification data come from FMP via `backend/fmp_client.py`.

## Caching policy

Fundamentals change infrequently, so raw FMP pulls are cached in a local
SQLite database (`backend/models.py::FundamentalsCache`, via SQLModel) keyed
by `(ticker, statement_type, period)`, with a `fetched_at` timestamp on each
row. Before refetching from FMP, check whether a cached entry is fresher than
the configurable staleness window — `Settings.cache_staleness_days` in
`backend/config.py`, default 7 days, overridable via the
`CACHE_STALENESS_DAYS` env var. Never hardcode the staleness window at a call
site.

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
default (real, file-backed) `db.engine`. Confirmed root cause of a real
incident (2026-07-28): `backend/tests/test_debt_metrics.py`'s "Acme Corp"
profile fixture — used correctly, with proper engine isolation, by the
tests themselves — ended up cached under the real ticker **PEP** (and the
inert placeholder ticker **ACME**) in `backend/fathom.db`, live in
production (`/tickers/PEP` and its Screener card showed "Acme Corp") for
several hours before being caught. Root-caused to an ad-hoc script that
mirrored the test's fixture/monkeypatch setup but only patched
`fmp_client`, not `engine`. Purged and re-fetched; see git history around
that date for the remediation. `backend/audit_fixture_contamination.py`
(read-only, safe to run anytime) scans `FundamentalsCache` for the same
class of fingerprint and should be run if this is ever suspected again.

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
year to year and isn't re-verified automatically.

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
| HOOD | 33.9% | Robinhood — margin lending and cash-sweep interest are real NII, not incidental |
| AXP | 21.6% | Card network *with* a real cardmember loan book (American Express), unlike V/MA |
| AMP | 17.2% | Ameriprise Financial — has Ameriprise Bank FSB subsidiary |
| NTRS | 16.9% | Northern Trust — custody bank with real lending/deposit operations |
| RJF | 13.5% | Raymond James — has Raymond James Bank subsidiary |
| STT | 13.1% | State Street — custody bank (State Street Bank and Trust) with real lending |
| GS | 10.8% | Goldman Sachs — investment bank with real deposit-taking/lending and trading-book NII |
| MS | 8.7% | Morgan Stanley — investment bank with Morgan Stanley Private Bank / wealth-management lending |

**This list does not auto-generalize.** A new ticker that lands in the same
sector/industry buckets (e.g. a newly-listed fintech IPO, a new asset
manager) classifies as `"Bank"` by default and needs the same manual
NII/revenue check before being added to either side of this list — there
is no automated signal that would catch a new non-lender or a new lender
on its own.

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before
  writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before
  committing each phase's work, and again before pushing — push only after
  explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.

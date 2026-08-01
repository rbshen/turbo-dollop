# CLAUDE.md — Fathom

## What this is

Fathom is a company fundamentals valuation web app. It runs a multi-step
fundamental screen on any US-listed ticker. There are 5 steps total in the
methodology; **Step 1 (Revenue, income and cash flow)**, **Step 2 (Positive
growth rate)**, **Step 4 (Profitable and operationally efficient)**, and
**Step 5 (Conservative debt)** are implemented so far. Step 3 follows the
same chart/table/score pattern and is added in a later phase.

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
backend/     FastAPI app (flat, feature-file style — no routers/ or
             services/ package split; see main.py, config.py, db.py,
             models.py, fmp_client.py)
```

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

## Scoring rubric deviations

Step 1's scoring rubric intentionally diverges from
`step1_revenue_income_cfo_assessment_prompt.md` in a few specific,
deliberate ways — these are refinements made after live testing against
real tickers, not implementation drift. The doc describes the tiers
qualitatively; `backend/scoring/trend.py` and `backend/scoring/step1.py`
are the source of truth for the exact thresholds and logic, with comments
at each deviation point. Current deviations:

- **Verdict bands** are 0-69 Fail / 70-90 Pass / 91-100 Strong Pass (not
  the doc's original 4-band scale). The score badge further splits the
  70-90 "Pass" band into two color shades (70-74 amber, 75-90 light green)
  without a text distinction — see `frontend/components/step1/ScoreBadge.tsx`.
  Step 2 uses the same bands and badge.
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
  same class of bug fixed in Step 4's CCC classifier: a sustained decline
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
  in Step 2 (`cache.py::safe_fetch` swallows `httpx.HTTPError` to `{}`,
  indistinguishable downstream from a genuinely-thin real response) — CFO-
  exempt companies (Bank/Property Developer/Commodity) are unaffected, since
  cfo/fcf simply aren't required for them. Net Income's own Operating-Income
  backup is unaffected too: NI only counts as a genuine gap if OI's
  `classify_trend` also reads `insufficient_data` — if OI has real data, the
  existing backup mechanism already produces a legitimate score.

Step 2's source doc (`step2_positive_growth_rate_assessment_prompt.md`)
calls for 3-4 independent platforms (GuruFocus, Finviz, Zacks, etc.) with
projections averaged and compared for cross-platform agreement. FMP is our
sole data source, so this is substituted with FMP's `/analyst-estimates`
endpoint, which aggregates multiple analysts (not multiple platforms) into
avg/high/low per forward fiscal year:

- The average projected growth rate (CAGR from the nearest forward
  estimate to the forward estimate closest to 4 years out) stands in for
  the doc's cross-platform average.
- The high/low spread as a % of the average, for that same target year,
  stands in for the doc's cross-platform "source agreement" check. This is
  **analyst estimate range**, not cross-platform consensus, and is labeled
  as such in the API/UI (`backend/schemas.py::Step2Out`,
  `frontend/components/step2/Step2Card.tsx`) so it's never mistaken for
  what the source doc actually describes.
- **Verdict *logic* deliberately diverges from the shared 0-69 Fail /
  70-90 Pass / 91-100 Strong Pass scale** every other step (Step 1, Step 4,
  Step 5, Overall Assessment) uses. Fail is gated on the magnitude tier
  alone (`growth_rate_pct < 0%`, i.e. `magnitude_score == 0`), not the
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
  (`frontend/lib/tierColor.ts`) with no visibility into Step 2's
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
  also reused directly as Step 3's (Valuation) Yr 1-5 growth input
  (`step3_data.py`, `growth_yr_1_5`), so this switch changes Valuation
  outputs project-wide, not just Step 2's own verdict.
- The target-year picker (closest forward estimate to 4 years out, within
  the 3-5yr window) skips rows where the field being scored is null or
  zero, preferring a usable row from elsewhere in the same candidate pool
  over blindly taking whichever row is nearest the window center. This
  matters far more under EPS than it ever did under revenue: FMP
  frequently reports `epsAvg: 0` for sparsely-analyst-covered far-out
  years even when a nearer in-window year has a real EPS estimate, which
  would otherwise misread as "insufficient data" for names that do have a
  usable projection.
- Growth catalysts (the doc's Step 3/4 qualitative research) are a
  manually-curated free-text field (`models.py::GrowthCatalystNote`), not
  factored into the score — same scoping as Step 1's manually-flagged
  one-off booleans. No edit UI exists yet; it's backend-settable only.
- **When neither EPS nor Revenue yields a usable CAGR** (too few/no future
  analyst estimate rows — including the case where `cache.py::safe_fetch`
  swallowed a genuine FMP fetch failure to `{}`, indistinguishable
  downstream from a real empty response), Step 2 returns `score: None,
  verdict: "insufficient_data"` — Step4Out/Step5Out's own convention —
  rather than a fabricated `score: 0, verdict: "Fail"`. A prior version of
  this code scored these identically to a genuinely weak/negative growth
  projection, which fed a false Fail into Overall Assessment's Growth-Rate-
  weighted blend and the Screener with no way to distinguish "no data" from "bad
  growth". `scoring/overall.py`'s `_status_for` already treated any
  null-score/non-`"not_supported"` step as `"incomplete"` (excluded from
  the blend, whole Overall Assessment marked incomplete rather than
  computed) — this was Step 4/5's existing behavior; Step 2 just never
  adopted it. Confirmed via cache-only inspection of the live universe that
  this only changes tickers with a genuinely empty/too-thin cached
  `analyst_estimates` response (e.g. ECHO, HONA, L) — every other ticker's
  score/verdict is unaffected.

Step 5's source doc (`step5_conservative_debt_assessment_prompt.md`) calls
for a CET1 ratio check for Banks. An investigation confirmed FMP has no
CET1 field and no raw components to compute one (checked ratios,
ratios-ttm, key-metrics, balance sheet, and speculative bank-specific
endpoints — all absent or 404). This is **deferred, not approximated**:
Bank tickers get `verdict: "not_supported"` and `score: null`
(`backend/step5_data.py`, `frontend/components/step5/Step5Card.tsx`), never
a fabricated or estimated capital ratio.

Step 5 is a hard pass/fail bankruptcy filter, not a continuous score, so
its "Scoring rubric deviations" are structural rather than threshold
tweaks:

- **Hard-fail override**: if any ratio breaches its hard limit (Current
  Ratio <1.0, Debt/EBITDA >3.0, Debt Servicing Ratio ≥30%, or Gearing >45%
  for REITs), the verdict is Fail regardless of the blended score — mirrors
  the Step 2 fix (a hard rule must never be diluted by averaging with
  healthy ratios). The numeric score still displays for context.
- Company classification (Standard / Bank / REIT-or-Property-Developer) is
  a best-effort sector/industry text match, surfaced in the UI/API
  (`classification_note`) rather than hidden, since a misclassified ticker
  would silently apply the wrong ratio set.
- The deferred-revenue exception (a low Current Ratio driven by deferred
  revenue isn't a red flag) is shown as an informational note only, not
  auto-detected or auto-adjusted — same non-automated treatment as Step 1's
  one-off items.
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

Step 4's source doc (`step4_profitability_efficiency_assessment_prompt.md`)
gives ROE/ROIC tiers, an AR-outpacing-magnitude concept, and a qualitative
CCC pattern table without committing to exact scoring formulas for any of
them. `backend/scoring/step4.py` operationalizes each into concrete
thresholds — deviations from a strict reading of the doc:

- **Both the display and scoring window are 10yr+TTM**, matching Step 1.
  The doc specifies "5 years" explicitly for ROE, ROIC, Revenue-vs-AR, and
  CCC (unlike Step 1's doc, which gives a "5-10 year" range) — this is a
  deliberate deviation beyond that explicit language, for consistency with
  Step 1 across the whole app. `backend/step4_data.py`'s `ANNUAL_WINDOW`
  (10) controls both what's fetched/shown and what feeds the score — there
  used to be a separate, narrower `SCORING_ANNUAL_WINDOW` (5) sliced out via
  a `_scoring_window()` helper so the chart could show more history than
  the score was based on; that decoupling has been removed, so a ticker's
  score now reflects its full 10-year history, not just the most recent 5.
  This means scores can shift versus the earlier 5yr-scoring behavior for
  tickers with a materially different pattern in years 6-10 versus the
  most recent 5 — an intentional tradeoff for a longer, more complete read
  on ROE/ROIC/AR/CCC trends, at the cost of the doc's own "5 years" framing.
- **Company classification** extends the same shared classifier Step 5
  uses (`classify_company_type`, now in `backend/scoring/classification.py`
  rather than duplicated) with Insurance and Utility. Insurance is checked
  **before** Bank since both share the "Financial Services" sector — an
  insurer whose industry text doesn't also match "bank" would otherwise be
  misclassified. Step 5 is unaffected: its code already branches
  `if Bank / if REIT / else standard-path`, so Insurance/Utility tickers
  fall through to Step 5's standard ratio path exactly as before.
- **ROE/ROIC tiering** uses both the average across the 10yr+TTM window
  *and* the minimum single-year value as a consistency check (a high
  average diluted by one very weak year lands in the "marginal" tier, not
  "excellent") — the doc doesn't specify this, but a straight average alone
  would let one bad year hide behind several good ones.
- **Negative-equity substitute signal**: per the doc's own exception, if
  shareholders' equity is ≤0 in any period, raw ROE is ignored entirely for
  the whole metric (not just that period) and replaced by a check for
  positive-and-non-declining Net Income across the window (net income
  positive throughout, last period ≥ first) — a simple "last ≥ first" bar,
  deliberately not a full trend classifier, since the doc's own language
  ("consistently maintained/growing") is qualitative.
- **Revenue vs. Accounts Receivable** tiers are checked worst-first since
  the doc's bullets overlap: majority-outpacing or revenue-declining-
  while-AR-grows (0) takes priority over 3+-years-or-large-gap (40), which
  takes priority over 0-or-one-small-gap (100), with 1-2 isolated years
  otherwise landing at 70. A YoY gap under 2 percentage points is treated
  as noise, not real outpacing (same noise-floor convention as Step 1's
  margin classifier).
- **CCC trend classification** reuses Step 1's margin-classifier logic
  (early/late-window direction + dip-count + sustained-decline, now shared
  via `backend/scoring/series_trend.py`) run on the *negated* series, since
  a declining CCC is the desirable direction (faster cash conversion) while
  a declining margin is not. The doc gives no numeric CCC thresholds (unlike
  margins, which were tuned after live testing) — the window/dip/sustained-
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
  reassignment table like Step 1's CFO exemption — Step 4 has more possible
  exemption combinations than Step 1's single CFO on/off switch.
- **Hard-fail override**: verdict is Fail regardless of the blended score
  if ROE lands in its Fail tier (avg <8%), or ROIC does (when applicable) —
  mirrors Step 2/Step 5's hard-fail pattern. Revenue-vs-AR and CCC landing
  in their own worst tier (0 points) drag the score down but do **not**
  force a Fail verdict — the doc treats a Receivables/CCC red flag as
  "investigate before proceeding," not an automatic disqualifier the way
  persistently poor ROE/ROIC is.
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
  itself and Step 1's margin classifier (which independently calls the same
  shared function) are untouched by this.
- **Revenue-vs-AR's "concerning" tier threshold is proportional, not a
  fixed count.** It was originally "3 of 5" transitions (60% severity,
  matching the doc's 5yr window) but was never rescaled when the window
  extended to 10yr+TTM (10 transitions), so it fired at just 30% severity
  instead — inflating false positives. `AR_CONCERNING_TRANSITION_RATIO`
  (0.6) now generalizes this to `max(3, round(0.6 * n))` transitions,
  restoring the original relative severity at any window size (still 3 at
  n=5, 6 at n=10). `majority_outpacing` was already proportional (`> n/2`)
  and needed no change. Because the ratio (0.6) sits above the 50%
  majority line, the count-based "concerning" tier remains structurally
  subsumed by "majority" at every window size — a pre-existing property of
  the original design, not an artifact of this rescaling.

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
  examples: MA (Step 5 genuinely `Fail` at 67) blended to Overall 92
  "Strong Pass" pre-rebalance, now 90 "Pass"; FICO (Step 5 `Fail` at 52)
  blended to 89 "Pass" pre-rebalance, now 87 "Pass" (still Pass — see
  below, reweighting alone is a limited lever).
- **A universe-wide investigation found this contradiction pattern in
  ~25% of tickers (125/493)**, split roughly evenly between two distinct
  causes: about half (62) are genuine per-step Fails diluted by blend
  weighting (what this rebalance targets), and about half (63) are cases
  where *no* step says "Fail" at all — the sub-70 step's own verdict gate
  (see Step 2's magnitude-tier gate above, and Step 4's equivalent
  `hard_fail`-gated `_verdict_for`, which shows "Pass" for 206 tickers
  scoring <70 — a bigger version of the same pattern) already masks it
  before blending starts. **Reweighting cannot fix the masked half** —
  confirmed via sensitivity testing (even a larger Debt-weight shift to
  25% only flipped 4/111 complete-data FICO-type tickers to Fail). Step
  2/4's own verdict gates are a separate, not-yet-addressed question.
- **Not yet built**: Step 5's own breach-context/scoring nuance (Debt/EBITDA
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

Applying Bank's treatment (Step 1's CFO/FCF de-emphasis in favor of Net
Interest Income, Step 4's ROIC exemption, Valuation's forced Price-to-Book
method) to a genuine non-lender produces nonsensical output — confirmed
regression: V/MA/BLK's Step 1 scores dropped 30-50+ points purely from a
near-zero/negative NII series standing in for real revenue, not from the
intended CFO-de-emphasis effect.

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

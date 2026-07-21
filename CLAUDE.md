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
- Revenue estimates are preferred over EPS when both are available (EPS is
  more exposed to buyback/margin noise than the underlying growth story);
  EPS is used as a fallback when revenue estimates are missing.
- Growth catalysts (the doc's Step 3/4 qualitative research) are a
  manually-curated free-text field (`models.py::GrowthCatalystNote`), not
  factored into the score — same scoping as Step 1's manually-flagged
  one-off booleans. No edit UI exists yet; it's backend-settable only.

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

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before
  writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before
  committing each phase's work, and again before pushing — push only after
  explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.

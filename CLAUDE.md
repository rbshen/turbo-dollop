# CLAUDE.md — Fathom

## What this is

Fathom is a company fundamentals valuation web app. It runs a multi-step
fundamental screen on any US-listed ticker. There are 5 steps total in the
methodology; only **Step 1 (Revenue, income and cash flow)** is implemented
so far. Later steps follow the same chart/table/score pattern established by
Step 1 and are added in later phases.

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

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before
  writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before
  committing each phase's work, and again before pushing — push only after
  explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.

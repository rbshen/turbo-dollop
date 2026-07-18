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

- **Verdict bands** are 0-69 Fail / 70-85 Pass / 86-100 Strong Pass (not
  the doc's original 4-band scale).
- **Margins classification** uses windowed early-vs-late direction plus
  explicit dip-count and sustained-decline checks, not a raw stdev-of-diffs
  volatility check — a single big dip-and-full-recovery year no longer
  reads as "wildly inconsistent" just because it produces high variance.
- **Multi-dip trend tier** (2+ real dips in Revenue/Net Income/CFO/Operating
  Income) is split by recovery and recency rather than one flat score: an
  unrecovered dip stays at 40, a recovered dip within the last 2 fiscal
  years is 60, and a recovered dip older than that is 75.

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before
  writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before
  committing each phase's work, and again before pushing — push only after
  explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.

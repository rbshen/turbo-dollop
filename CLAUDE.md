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

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before
  writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before
  committing each phase's work, and again before pushing — push only after
  explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.

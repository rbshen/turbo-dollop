# CLAUDE.md — Fathom

## Migration note

CLAUDE.md was slimmed on 2026-09-29. The complete pre-slimming file is `docs/archive/CLAUDE.original.md` (NOT auto-loaded). Detailed reference is moving into `docs/specs/` and `docs/archive/`. If a topic is not yet covered in `docs/specs/`, grep `docs/archive/CLAUDE.original.md` for it before assuming it is undocumented. See "Docs map" below for known pointers.

## What this is

Fathom is a company fundamentals valuation web app. It runs a multi-step fundamental screen on any US-listed ticker. The automated Analysis framework has 4 steps -- **Financials (Revenue, income and cash flow)**, **Growth Rate (Positive growth rate)**, **Profitability (Profitable and operationally efficient)**, and **Debt (Conservative debt)** -- plus a manually-set Economic Moat rating, together forming the Overall Assessment score (see `STEP_WEIGHTS`/`MOAT_WEIGHT`, documented in `docs/specs/overview.md`). **Valuation**, internally `backend/step3_data.py` / `backend/scoring/step3.py`, is a separate, fully-implemented "Valuation" tab with its own DCF/DDM/P-B/PSG method-selection logic -- it is **not** part of the Overall Assessment blend (no `step3` key exists in `STEP_WEIGHTS`).

## Tech stack

- **Frontend**: Next.js (App Router), TypeScript, Tailwind v4, shadcn/ui (`base-lyra` style, phosphor icons, neutral base color). Dark-only theme — no light mode toggle, `dark` class hardcoded on `<html>` in `app/layout.tsx`. SWR for data fetching. Mirrors the visual style and conventions of the sibling `options_tracker` project.
- **Backend**: Python (>=3.12), FastAPI, SQLModel, pandas/numpy for any data manipulation — favor vectorised operations over row-wise loops. Dependency management via `uv` (`uv run`, `uv sync`).

## Running the app

`./bin/start.sh` from the repo root brings up both servers (preflight checks, explicit `init_db()`, an FMP connectivity check, a `next build`, then backend + frontend in production mode — no hot reload, so code changes need a stop/start — each in its own process group) — see `backend/OPS_RUNBOOK.md`'s "Starting / stopping the app" section for what success/failure look like. `./bin/stop.sh` stops both, safe to run anytime including when nothing is running.

## Folder layout

```
bin/         start.sh / stop.sh / common.sh -- see "Running the app" above.
frontend/    Next.js app (App Router)
backend/     FastAPI app, organized into packages by role (2026-08-05
             reorg away from the previous fully-flat, feature-file layout):
  core/        App entrypoint + shared infrastructure: main.py (the
               FastAPI app itself — run as `uv run uvicorn core.main:app`,
               not `main:app`), models.py (SQLModel tables), db.py
               (engine/init_db), schemas.py (API response models),
               config.py (Settings/BASE_DIR), cache.py (get_or_fetch/
               safe_fetch), logging_config.py.
  clients/     Thin external API clients: fmp_client.py, sec_edgar.py,
               daily_bar_sources.py (the FMP daily/60m bar sources),
               shared_bars_cache.py (the SharedBarsCache get-or-fetch),
               long_history_bars.py, technical_sources.py. FMP is the only
               market-data provider (Phase 6b) -- see
               docs/specs/fmp-data-and-bar-cache.md.
  helpers/     Shared calculation helpers consumed by data/: ttm.py,
               shares.py, debt_metrics.py, npl.py, bank_capital_metrics.py,
               discount_rate_config.py, first.py.
  data/        Per-tab data orchestration (the get_stepN_data pattern):
               step1_data.py .. step5_data.py, ticker_summary.py,
               financials_data.py, ratios_data.py, analyst_ratings_data.py,
               news_data.py, segmentation_data.py, moat.py,
               watchlist_data.py, watchlists.py, saved_screener_filters.py,
               ticker_score.py, trend_analysis_data.py (see
               docs/specs/trend-structure-technical.md).
  scoring/     Pure scoring functions (classification.py, trend.py,
               series_trend.py, step1.py..step5.py, overall.py) — this
               package predates the 2026-08-05 reorg and was always split
               out; unchanged by it.
  analysis/    Standalone quantitative research modules, each its own
               subpackage: ma_magnet/ (unwired research script, not part
               of the production app -- see its own run.py docstring) and
               trend_structure/ (production, wired end-to-end via
               data/trend_analysis_data.py -- pure functions/dataclasses,
               no DB/HTTP of its own, matching ma_magnet's calculation
               style but NOT its unwired scope).
  scrapers/    Index/constituent Wikipedia scrapers: index_scraper.py,
               sp500_scraper.py, dow_scraper.py, refresh_sp500_list.py,
               refresh_dow_list.py.
  pipeline/    Production cron/maintenance entrypoints that read/write
               the real DB: nightly_fundamentals_fetch.py,
               nightly_trend_calculation.py,
               nightly_entry_signal_calculation.py,
               nightly_liquidity_zone_calculation.py,
               nightly_price_target_snapshot.py,
               monthly_momentum_snapshot.py, recompute_ticker_scores.py,
               audit_fixture_contamination.py, refresh.py, prune_cache.py,
               backup_db.py, rotate_logs.py, stale_data_health_check.py --
               see backend/OPS_RUNBOOK.md for what each of the latter
               four does, its cadence, and what to check if it fails.
    backfills/   One-time historical cache backfill scripts (already run,
                 kept as documentation of how those migrations were
                 done): bulk_refresh_balance_sheet_quarterly.py,
                 bulk_refresh_ratios_ttm.py, bulk_refresh_step4_annual.py.
  scripts/     Untracked, ad-hoc research tooling that never touches
               production data — deliberately kept separate from
               pipeline/, since blurring that exact distinction caused a
               real fixture-contamination incident (see "Ad-hoc
               reproduction scripts" below). Not committed to git.
  tests/       pytest suite, mirrors the package layout via import paths
               (e.g. `from data.step1_data import ...`) rather than a
               parallel directory tree.
```

Every cron entry in `crontab.txt` invokes its script as `-m package.module` (e.g. `uv run python -m pipeline.nightly_fundamentals_fetch`), not a bare script path — a script moved into a subpackage that's run as a direct file path (`python pipeline/foo.py`) fails immediately with `ModuleNotFoundError` on its own sibling imports, since that puts the script's own directory on `sys.path` instead of `backend/` itself. `-m`, run with `backend/` as the working directory, doesn't have this problem. Confirmed by actually running both forms during the reorg, not assumed.

## Data source

[Financial Modeling Prep (FMP)](https://financialmodelingprep.com) (paid tier) is the **sole** data source for fundamentals, company classification, and Steps 1-5/Overall Assessment scoring, via `backend/clients/fmp_client.py`. Since Phase 6b (2026-09-26) FMP is the **only** external data source for everything, price/OHLCV bars included, with no fallback provider anywhere. (SEC EDGAR, `clients/sec_edgar.py`, remains only as a fundamentals cross-check source, not a market-data one.) See docs/specs/fmp-data-and-bar-cache.md.

## Watchlists

Each watchlist is capped at `WATCHLIST_CAPACITY` (100 tickers, `backend/core/main.py`) — adding tickers past the cap is rejected with an explanatory error rather than silently truncating.

Watchlists whose name matches `^W[1-5]$` (i.e. `"W1"` through `"W5"`) have a special role beyond ordinary user-created lists: the BB+RSI entry-signal and Liquidity Zone (LP) nightly jobs read from the deduped union of every matching watchlist (see docs/specs/liquidity-zones.md, pending migration — until then see `docs/archive/CLAUDE.original.md`, section "Liquidity Zone (LP) detection (Technical)" — for the full mechanism) — a ticker on more than one matching watchlist is only processed once, and a ticker on none of them has no row in either feature's table at all. Originally hardcoded to two watchlists literally named `"Main"`/`"Secondary"`, then renamed to `"W1"`/`"W2"`, then generalized to this `^W[1-5]$` pattern match (`data/watchlists.py::list_tickers_across_watchlists`) so a user can add a W3/W4/W5 watchlist later with no code change.

## Caching policy

Fundamentals change infrequently, so raw FMP pulls are cached in a local SQLite database (`backend/models.py::FundamentalsCache`, via SQLModel) keyed by `(ticker, statement_type, period)`, with a `fetched_at` timestamp on each row. Before refetching from FMP, check whether a cached entry is fresher than the configurable staleness window — `Settings.cache_staleness_days` in `backend/config.py`, default 7 days, overridable via the `CACHE_STALENESS_DAYS` env var. Never hardcode the staleness window at a call site.

### Data groups: pausing FMP (per-group toggles, replaces `FMP_ENABLED`)

**2026-09-24: the global `FMP_ENABLED` env flag and `INSIDER_ACTIVITY_ENABLED` were deleted** (no `.env` shim; only `FMP_API_KEY`/`FMP_BASE_URL` remain in `.env`). FMP on/off is now per **data group**, stored in the DB (`core/data_groups.py`, tables `DataGroupSetting` -- one row per group -- and the singleton `DataGroupGlobal`; lazy-seeded like `LiquidityZoneConfig`, 5 s in-process cache invalidated on write) and edited live from Settings > Status, with no restart. Cron jobs are separate processes and read the same DB.

- **Groups:** `fundamentals`, `profile_quote`, `analyst_ratings`, `segmentation`, `news`, `insider` (seeded **off** -- the shelved feature), `index_membership`, `corporate_events`, `daily_prices`, `daily_prices_long`, `intraday_bars` (live since P2/P3/P4 respectively -- see docs/specs/fmp-data-and-bar-cache.md). **Since Phase 6b none of the price groups has a fallback provider: off = cached-only, and the nightly bar jobs report `skipped`**. One seeded-but-unwired row for the price migration: `extended_hours` (P5).
- **Effective state** = master switch on AND group enabled AND required tier <= my plan AND status != `plan_restricted`. Off means **cache-only**: the last cached row is served (even if stale), nothing is ever wiped.
- **Required tier per group is a user-editable value** (Starter/Premium/Ultimate) with a "verified" tick the user sets after checking FMP's pricing page -- the seeded values are unverified guesses from the 2026-09-24 investigation. "My FMP plan" is one more editable value (seeded Ultimate); a group above the plan reads "Not on plan" and is treated as off. Editing a group's tier clears its verified tick.
- **Master switch** ("disable all FMP", same semantics the old `FMP_ENABLED=false` had): Settings > Status, or `uv run python -m pipeline.data_groups pause-all | resume | status` when the API is down.
- **Single gate, two layers.** `FMPClient.get` maps endpoint -> group (`ENDPOINT_GROUP`; the two endpoints shared by two features pass an explicit `group=`: `/earnings`, `/quote`) and raises `FMPGroupDisabledError`, a `FMPDisabledError` subclass, so existing `except httpx.HTTPError`/`safe_fetch` sites need no edits. `core/cache.py`'s `get_or_fetch`/`get_or_fetch_earnings_aware`/`force_fetch` gate per `statement_type` -> group (`STATEMENT_TYPE_GROUP`) with the original cache-only semantics (stale row served; `force_fetch` raises if nothing cached). `tests/test_data_groups_registry.py` **fails if any FMP endpoint or cached statement_type used in the code is unmapped**, and pins that any bulk/batch endpoint must be Ultimate (none is used; never call one). An unmapped endpoint fails closed.
- **What degrades when a group is off:**
  - `profile_quote`: search falls back to the tracked-ticker universe (symbol only); the ticker header's `price` uses the last official close cached nightly (`TickerLastClose`), every other quote field stays at the last cached FMP value; `/refresh` 503s.
  - `analyst_ratings` / `news` / `segmentation` / `fundamentals`: their tabs/scores serve cached data; the nightly fundamentals fetch, the nightly price-target snapshot and the index-list refresh jobs skip.
  - `corporate_events`: chart E/D markers are served from the cached `CorporateEvent` rows (however old).
  - `insider`: shelved (fully deleted 2026-09-27); the group entry itself is gone too.
- **`POST /api/tickers/{t}/refresh`** returns **503** if any group it would clear (the ticker's cached statement types) or must re-fetch through (`profile_quote`, `fundamentals`, always needed by the immediate score recompute) is not live -- never a partial clear (`pipeline/refresh.py::groups_blocking_refresh`).
- **402 safety net** (`FMPClient._handle_plan_restriction`): on HTTP 402 it probes a canary (AAPL, same endpoint); only if the canary also 402s is the group marked `plan_restricted` (a symbol-scoped 402 leaves it live). 401/403 = a *key* problem (global warning in Settings, no group blamed); 429 never marks anything; 5xx/transport errors count toward a "Failing" chip after 3 in a row and never disable a group. Restricted groups are re-probed weekly (`pipeline.stale_data_health_check`) and whenever the plan is edited.
- **Nightly jobs** whose group is off log `skipped (group X ...)` and record a real **`skipped` cron status** (`run.skip(reason)` -> `CronRunLog.status="skipped"`; health view `skipped` with `skipped_since` = start of the current streak; never `ok`/`overdue` while skipped, `last_success_at` still shows the last real run).
- **API/UI:** `GET /api/config/data-groups` (+ `PUT .../master`, `.../plan`, `.../{group}`). Settings > Status shows one row per group (toggle, chip Live / Cached only / Not on plan / Restricted by FMP / Failing, last success, tier + verified tick, "feeds:" list; disabling warns with the dependent features). Ticker-page tabs show a "not refreshing -- as of [date]" badge for off groups (`GroupOffBadge`).
- `bin/start.sh` skips the AAPL `/quote` preflight when master or `profile_quote` is not live; a 402 there warns and startup continues.
- Tests get a fresh in-memory group config per test (`conftest._isolate_data_groups_engine`: master on, plan Ultimate, everything live except `insider`); a test wanting an off state calls `core.data_groups.set_master`/`set_group_enabled`.

**What stays unaffected:** `pipeline/nightly_score_recompute.py` (already `cache_only=True` throughout, zero FMP calls regardless of any group state), and any read whose cache is still within its normal staleness window — which, on a warm cache, is most of the app most of the time.

For the exact FMP endpoint→group and cache-key→group mappings, see docs/specs/fmp-data-and-bar-cache.md.

### Ad-hoc reproduction scripts must not touch the real database

`backend/fathom.db` is the one real database — `config.py`'s `database_path` has no environment-based split between "real" and "test." The only thing keeping test runs from polluting it is that every test in `backend/tests/` explicitly constructs its own fresh in-memory engine (`create_engine("sqlite://")`) and monkeypatches it onto every module's `engine` reference *before* calling any `get_stepN_data`/`get_summary`/`compute_ticker_score` function. `cache.py::get_or_fetch` has no way to tell "this is a controlled repro" from "this is real" — it will silently persist whatever `fmp_client` returns into whatever `engine` happens to be bound at that moment, indistinguishable later from genuine FMP data.

Any one-off script that reproduces test-like behavior against real ticker data (monkeypatching `fmp_client` to return controlled/fixture responses) **must** follow the exact same convention: construct a fresh in-memory engine and monkeypatch it onto **every module's own `engine` reference** first — each data-layer module (`step1_data.py` .. `step5_data.py`, `ticker_summary.py`, etc.) manages its own independent `Session(engine)` block bound to its own `engine` import, so patching one module's `engine` does not patch another's. Never monkeypatch `fmp_client` alone and call these functions against the default (real, file-backed) `db.engine`. This has caused real production contamination twice (2026-07-28, 2026-08-04) — a real ticker's fundamentals were silently overwritten with fixture data for several hours before being caught and purged. A session-scoped write-guard (`backend/tests/conftest.py`) now hooks SQLAlchemy's `before_cursor_execute` on the real `core.db.engine` for the whole pytest session and raises immediately on any write, so a future missing `engine` monkeypatch fails loudly in CI instead of silently reaching production. `backend/pipeline/audit_fixture_contamination.py` (read-only, safe to run anytime) scans `FundamentalsCache` for this class of fingerprint and runs weekly via cron (Sundays 1:20 AM).

For the full incident history behind this rule, see docs/archive/claude-md-history-features.md (pending migration; until then see `docs/archive/CLAUDE.original.md`, section "Ad-hoc reproduction scripts must not touch the real database").

## Cron job heartbeat / health monitoring

`backend/core/cron_health.py::cron_heartbeat("<job_name>")` wraps every real cron job's entry point (`if __name__ == "__main__":`), writing a `CronRunLog` row regardless of how the job fails. Purely additive — on failure the original exception is always re-raised unchanged, so existing stderr/`_cron.log` capture and exit codes are untouched; the heartbeat's own DB writes are independently try/except-swallowed, so a heartbeat failure can never mask or alter the job's real outcome. `GET /api/config/cron-health` computes each job's health from its `CronRunLog` history (`ok`/`overdue`/`failed`/`unknown`) and backs Settings > Scheduled Jobs.

**`CRON_JOB_NAMES` in `core/cron_health.py` is the single source of truth for which cron jobs exist** — a new cron job added to `crontab.txt` needs a matching `CRON_JOB_NAMES` entry, an `_EXPECTED_CADENCE_HOURS` entry, and a `cron_heartbeat(...)` call at its own entry point, or it ships unmonitored. `backend/tests/test_cron_wiring.py` fails loudly if any of these three ever drift apart, so this isn't just a documentation convention to remember by hand. Note also: editing `crontab.txt` alone changes nothing on the running box — it must be reinstalled (`crontab crontab.txt` from `backend/`) and `crontab -l` checked against the file, or a job silently never runs on the new schedule.

Full mechanism, exact cadence windows, and past incidents are documented in `backend/OPS_RUNBOOK.md`'s "Cron job heartbeat / health monitoring" section (not duplicated here) and docs/archive/claude-md-history-features.md (pending migration; until then see `docs/archive/CLAUDE.original.md`, section "Cron job heartbeat / health monitoring").

## Company classification

`classify_company_type` (`backend/scoring/classification.py`) drives Bank/REIT/Insurance/Utility/Property-Developer detection, including several manually-verified non-lender ticker overrides (sector/industry text alone can't reliably distinguish a genuine lender from a non-lender in some categories) and the requirement that "Bank" treatment implies genuine CET1/NPL-reporting capability, not just lending activity. See docs/specs/company-type-variations.md for the current tables and mechanism.

## Docs map

Scoring methodology and feature-specific detail live in `docs/specs/*.md` and `docs/archive/*.md`, not in this file. Where a pointer below is marked "pending migration," the destination file doesn't exist yet — read the named section of `docs/archive/CLAUDE.original.md` instead.

**Scoring methodology:** Financials — docs/specs/financials.md. Growth Rate — docs/specs/growth-rate.md. Debt — docs/specs/debt.md. Profitability — docs/specs/profitability.md. Valuation (Step 3) — docs/specs/valuation.md. Overall Assessment step weighting, Screener ETF exclusion — docs/specs/overview.md. Company classification / non-lender ticker overrides — docs/specs/company-type-variations.md. Economic Moat — docs/specs/economic-moat.md. Glossary of terms — docs/specs/glossary.md. Speculative Growth lens — docs/specs/speculative-growth.md (pending migration; section "Speculative Growth (new classification) scoring notes").

**Technical-analysis lenses:** Trend structure / BOS / A-D divergence / SMA position — docs/specs/trend-structure-technical.md. Weinstein Stage Analysis — docs/specs/weinstein-stage.md. Sector Heatmap — docs/specs/sector-heatmap.md. Market Breadth — docs/specs/market-breadth.md. Chart indicators (Stochastic, etc.) — docs/specs/chart-indicators.md. Price-target snapshot — docs/specs/price-target.md. Liquidity Zone (LP) detection — docs/specs/liquidity-zones.md (pending migration; section "Liquidity Zone (LP) detection (Technical)"). Warren RSI/ADX/WVF entry signal — docs/specs/warren-signal.md (pending migration; section "Warren RSI/ADX/WVF entry signal (2h) (Technical)"). Chart tab fetch behavior, earnings/dividend markers — docs/specs/chart-tab.md (pending migration; sections "Chart tab reverted to zero-cache on-demand fetch (2026-09-18)" and "Chart tab earnings/dividend markers (2026-09-20)"). Institutional Ownership (shelved feature) — docs/specs/institutional-ownership.md (pending migration; section "Institutional Ownership (ticker-page tab, 2026-09-27) -- SHELVED 2026-09-27").

**Data infrastructure:** FMP endpoint/cache-key → data-group mappings, shared bars cache, daily/intraday price fetch mechanism, delisted-ticker handling — docs/specs/fmp-data-and-bar-cache.md. Corporate events (earnings/dividends/splits cache) — docs/specs/corporate-events.md (pending migration; may instead be folded into fmp-data-and-bar-cache.md — undecided; until then see `docs/archive/CLAUDE.original.md`, section "Phase 6a: Massive removed; FMP last-close, corporate-events and delisted-companies (2026-09-26)").

**History** (completed migrations, resolved incidents, shelved/deleted features — all pending migration; until then read the relevant dated section of `docs/archive/CLAUDE.original.md`): Financials/Growth/Debt/Profitability/Valuation investigation narratives ("confirmed via full-universe recompute" write-ups) — docs/archive/claude-md-history-scoring.md. Trend/Liquidity Zone/Warren investigation narratives, the watchlist-rename history — docs/archive/claude-md-history-technical-signals.md. FMP migration phases (Massive removal, Yahoo removal, non-US removal, daily-bar backfills and parity checks) — docs/archive/claude-md-history-fmp-migration.md. Insider Activity (deleted 2026-09-27), the Analysis-tab-reasoning fix, company-classification investigation narrative, ad-hoc-repro-script and cron-heartbeat incident write-ups — docs/archive/claude-md-history-features.md.

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before committing each phase's work, and again before pushing — push only after explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.
- **No browser-based verification after a code change.** This environment can't drive a browser — rely on `tsc`, `eslint`, and the test suite instead of visually checking the result.
- **Clean up after yourself.** Delete any temporary files, scratch scripts, or processes you started, before ending a task.
- **Design and product decisions live in `docs/design-system.md`, `docs/design-system-charts.md`, and `docs/decisions.md`.** Check these before styling anything or proposing a new UI pattern — don't re-derive a decision that's already been made.

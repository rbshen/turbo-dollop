# CLAUDE.md — Fathom

## What this is

Fathom is a company fundamentals valuation web app. It runs a multi-step fundamental screen on any US-listed ticker. The automated Analysis framework has 4 steps -- **Financials (Revenue, income and cash flow)**, **Growth Rate (Positive growth rate)**, **Profitability (Profitable and operationally efficient)**, and **Debt (Conservative debt)** -- plus a manually-set Economic Moat rating, together forming the Overall Assessment score (see `STEP_WEIGHTS`/`MOAT_WEIGHT`, documented in `docs/specs/overview.md`). **Valuation**, internally `backend/data/step3_data.py` / `backend/scoring/step3.py`, is a separate, fully-implemented "Valuation" tab with its own DCF/DDM/P-B/PSG method-selection logic -- it is **not** part of the Overall Assessment blend (no `step3` key exists in `STEP_WEIGHTS`). A ticker whose profile says `isEtf`/`isFund` gets a separate ETF page variant instead of the stock tabs and scoring (docs/specs/etf-page.md); for such a ticker `get_summary` also skips every stock-only FMP fetch (statements, ratios, growth, earnings, Step 2/3), so an ETF open makes 4 calls and writes no empty cache rows, and the Watchlists page makes no consensus-rating call for an ETF row.

## Tech stack

- **Frontend**: Next.js (App Router), TypeScript, Tailwind v4, shadcn/ui (`base-lyra` style, phosphor icons, neutral base color). Dark-only theme — no light mode toggle, `dark` class hardcoded on `<html>` in `app/layout.tsx`. SWR for data fetching. Mirrors the visual style and conventions of the sibling `options_tracker` project.
- **Backend**: Python (>=3.12), FastAPI, SQLModel, pandas/numpy for any data manipulation — favor vectorised operations over row-wise loops. Dependency management via `uv` (`uv run`, `uv sync`).

## Running the app

`./bin/start.sh` from the repo root brings up both servers in **dev mode by default** (preflight checks, explicit `init_db()`, an FMP connectivity check, then `uvicorn --reload` + `next dev` with hot reload, each in its own process group); `./bin/start.sh --prod` (or `FATHOM_MODE=prod`) instead does a `next build` and runs both in production mode — lower memory, but no hot reload, so code changes need a stop/start — see `backend/OPS_RUNBOOK.md`'s "Starting / stopping the app" section for what success/failure look like. `./bin/stop.sh` stops both, safe to run anytime including when nothing is running.

## Folder layout

```
bin/         start.sh / stop.sh / common.sh -- see "Running the app" above.
frontend/    Next.js app (App Router)
backend/     FastAPI app, organized into packages by role:
  core/        App entrypoint + shared infrastructure: main.py (the
               FastAPI app itself — run as `uv run uvicorn core.main:app`,
               not `main:app`), models.py (SQLModel tables), db.py
               (engine/init_db), schemas.py (API response models),
               config.py (Settings/BASE_DIR), cache.py (get_or_fetch/
               safe_fetch), history_merge.py (the history-protection
               merge rule), logging_config.py.
  clients/     Thin external API clients: fmp_client.py, sec_edgar.py,
               daily_bar_sources.py (the FMP daily/60m bar sources),
               shared_bars_cache.py (the SharedBarsCache get-or-fetch),
               long_history_bars.py, technical_sources.py.
  helpers/     Shared calculation helpers consumed by data/: ttm.py,
               shares.py, debt_metrics.py, npl.py, bank_capital_metrics.py,
               discount_rate_config.py, first.py.
  data/        Per-tab data orchestration (the get_stepN_data pattern):
               step1_data.py .. step5_data.py, ticker_summary.py,
               financials_data.py, ratios_data.py, analyst_ratings_data.py,
               news_data.py, segmentation_data.py, moat.py,
               etf_data.py (ETF page Overview + "known ETF" lookups),
               watchlist_data.py, watchlists.py, saved_screener_filters.py,
               tracked_universe.py (the one nightly-universe definition),
               ticker_score.py, trend_analysis_data.py (the
               "trend" names are historical -- Weinstein only; see
               docs/specs/weinstein-stage.md).
  scoring/     Pure scoring functions (classification.py, trend.py,
               series_trend.py, step1.py..step5.py, overall.py).
  analysis/    Standalone quantitative research modules, each its own
               subpackage: ma_magnet/ (unwired research script, not part
               of the production app -- see its own run.py docstring) and
               trend_structure/ (production; historical name -- now
               just the Weinstein stage engines and the chart's
               Stochastic, wired via data/trend_analysis_data.py).
  scrapers/    Index/constituent Wikipedia scrapers: index_scraper.py,
               sp500_scraper.py, dow_scraper.py, refresh_sp500_list.py,
               refresh_dow_list.py.
  pipeline/    Production cron/maintenance entrypoints that read/write
               the real DB: nightly_fundamentals_fetch.py,
               nightly_trend_calculation.py (Weinstein + bar-cache
               fill; historical name),
               nightly_entry_signal_calculation.py,
               nightly_liquidity_zone_calculation.py,
               nightly_price_target_snapshot.py,
               nightly_etf_screener.py (the ETFs screener read-model, 1:45 AM;
               registered 2026-10-03, see docs/specs/etf-screener.md),
               monthly_momentum_snapshot.py, recompute_ticker_scores.py,
               tracked_universe_report.py (read-only universe report),
               audit_fixture_contamination.py, refresh.py, prune_cache.py,
               backup_db.py, rotate_logs.py, stale_data_health_check.py --
               see backend/OPS_RUNBOOK.md for what each of the latter
               four does, its cadence, and what to check if it fails.
    backfills/   One-time historical cache backfill scripts (already run,
                 kept as documentation of how those migrations were
                 done): bulk_refresh_balance_sheet_quarterly.py,
                 bulk_refresh_ratios_ttm.py, bulk_refresh_step4_annual.py.
  scripts/     Ad-hoc research tooling that never touches
               production data — deliberately kept separate from
               pipeline/, since blurring that exact distinction caused a
               real fixture-contamination incident (see "Ad-hoc
               reproduction scripts" below). Not part of the app.
  tests/       pytest suite, mirrors the package layout via import paths
               (e.g. `from data.step1_data import ...`) rather than a
               parallel directory tree.
```

Every cron entry in `crontab.txt` invokes its script as `-m package.module` (e.g. `uv run python -m pipeline.nightly_fundamentals_fetch`), not a bare script path — a script moved into a subpackage that's run as a direct file path (`python pipeline/foo.py`) fails immediately with `ModuleNotFoundError` on its own sibling imports, since that puts the script's own directory on `sys.path` instead of `backend/` itself. `-m`, run with `backend/` as the working directory, doesn't have this problem. Confirmed by actually running both forms during the reorg, not assumed.

## Data source

[Financial Modeling Prep (FMP)](https://financialmodelingprep.com) (paid tier) is the **sole** data source for fundamentals, company classification, and Steps 1-5/Overall Assessment scoring, via `backend/clients/fmp_client.py`. FMP is the **only** external data source for everything, price/OHLCV bars included, with no fallback provider anywhere. (SEC EDGAR, `clients/sec_edgar.py`, remains only as a fundamentals cross-check source, not a market-data one.) See docs/specs/fmp-data-and-bar-cache.md.

## Watchlists

Each watchlist is capped at `WATCHLIST_CAPACITY` (100 tickers, `backend/core/main.py`) — adding tickers past the cap is rejected with an explanatory error rather than silently truncating.

**Monitored watchlists.** A watchlist whose name is `E<positive integer>` (`E1`, `E6`, `E10`, ... -- no upper limit on the number of lists) or exactly `ETF` has a special role beyond ordinary user-created lists: the Liquidity Zone (LP), BB+RSI and Warren nightly jobs read from the deduped union of every such list (see docs/specs/liquidity-zones.md for the full mechanism) -- a ticker on more than one monitored list is only processed once, and a ticker on none of them has no row in any of those features' tables at all. The rule is defined once, in `data/watchlists.py` (`MONITORED_WATCHLIST_PATTERN`, `is_monitored_watchlist_name`, `list_monitored_tickers`): case-sensitive full match, no leading zeros (`E0`, `E01`, `e1`, `ETFs`, `W1` are NOT monitored). The three jobs and the daily-bars backfill all call that helper -- never re-declare the pattern in a job (`tests/test_watchlists.py` fails if one does). The ETF page's "Add to watchlist" button (`POST /api/tickers/{t}/etf-watchlist`) adds to the list named `ETF`, creating it on first use; `WatchlistOut.monitored` tells the frontend which lists are monitored so it never re-implements the name rule (see docs/specs/etf-page.md). (The Chart tab's 2H·90D range computes the same three signals live for **any** ticker, monitored or not, and stores nothing; see docs/specs/chart-tab.md.) **The "ETF" list is ETF-only and permanent** (docs/decisions.md 2026-10-04): a ticker may join it only if it is a *known* ETF (`known_etf_tickers` or an `EtfScreenerRow`; a stock or a never-seen ticker is refused), enforced for every add path (`POST /api/watchlists/{id}/tickers`, `.../tickers/bulk` all-or-nothing, `POST /api/tickers/{t}/etf-watchlist`) by the one helper `data/watchlists.py::tickers_not_allowed_on_watchlist` with an HTTP 400; the list cannot be renamed or deleted, and no other list can be renamed to (or newly created as a case/whitespace variant of) `ETF` (400). Never re-implement the rule at a call site. Stock UI never offers the list (`AddToWatchlistButton` `audience` defaults to `"stock"`, which hides it; the ETFs screener's bulk add passes `"etf"`; the Stocks screener's Watchlist filter omits it, and the ETFs screener has no Watchlist filter at all). The list has its own read endpoint, `GET /api/watchlists/{id}/etf-rows` (`data/watchlist_data.py::get_etf_watchlist_rows`): stored `EtfScreenerRow` figures plus the cached profile exchange, in added order, no FMP call, no score computation, no write, 400 for any other list; the stock `GET /rows` is untouched. The Watchlists page draws that list with its own **ETF table** (`EtfWatchlistTable`: Ticker, Name, Price, % Chg, Class, Exp %, AUM, Holdings, Avg Vol 30d, Yield %, Beta, YTD, 1Y, remove; null = "–"; all columns sortable, default AUM descending, nulls last, own localStorage key) only when the active list is named exactly "ETF"; every other list keeps the stock table (docs/specs/etf-page.md, "Watchlist rows"). Changing the name of any other monitored list silently drops it from the jobs, and its readings are cleared after 7 days. There is no cap on how many lists exist, only the 100-ticker cap above on each list. In practice the number of monitored tickers is bounded by the nightly cron slot widths (about 1.7-2.4 s of CPU per ticker across the three jobs; BB+RSI's 5-minute slot overruns around 235-510 tickers). `docs/watchlist-rename-investigation-2026-10-02.md` has the load numbers.

## Tracked universe (which tickers the nightly jobs process)

Defined once, in `backend/data/tracked_universe.py::load_tracked_universe` (spec: docs/specs/tracked-universe.md; **opt-in**: a page view does not admit a ticker): it is the **stock side** of `partition_known_tickers` (no ETF is in it: ETFs have their own universe, `load_etf_universe`, refreshed by `pipeline/nightly_etf_screener.py`, which also writes their `TrendAnalysis` and `TickerLastClose`). Every known ticker gets ONE reason, first match in this order: `delisted` (out of every universe and job, wins over everything), `index` (S&P 500, Nasdaq-100 or Dow), `watchlist` (any watchlist), `system` (a seed ETF, the Weinstein benchmark constant or the live `rs_benchmark`), `manual` (Moat, custom valuation, bank-capital entry or growth-catalyst note: never expires because Monthly Momentum is "Moat-rated tracked tickers"), `added` (`TickerView.added_at` set by the Add API; in the universe at **any** idle age, leaves only through Remove), then `browsed` (opened within 30 days, not added), `expired` (idle over 30 days) and `untracked` (known, no `TickerView` row): those three are **not in the universe** (not in the screeners or the nightly jobs; an ETF's `EtfScreenerRow` is pruned by the 1:45 job), keep all their data, and are only candidates for the **wipe** (`pipeline/wipe_untouched_tickers.py`: dry run by default, `--apply` locked behind `FATHOM_ALLOW_WIPE_APPLY=1`, not scheduled). `TickerView.last_viewed_at` (written by `GET /api/tickers/{t}/summary`, touched at the start of the request for an existing row, read-first: a row already on today's date issues no write, so at most one write per ticker per day; best-effort, a lock error is logged and swallowed) is only the wipe's clock; `GET/POST/DELETE /api/tickers/{t}/universe` is the status/Add/Remove API (the buttons are step 3b). The header score chip recomputes a row older than 36 h. `SYSTEM_TICKERS` does not exist; do not reintroduce it. ETF Momentum ranks `load_etf_universe` itself, so it needs no `ETF_SEED_TICKERS` entry (docs/specs/momentum.md). `load_all_known_tickers` is the wide set, kept for the non-US purge, the delisted sync, the search fallback and the backfills. Never re-declare the union in a job or call a removed name (`tests/test_tracked_universe.py` fails if one does). `core/db.py::init_db` seeds `TickerView` once when the table is empty; a seeded view admits nobody. A delisted flag removes a ticker from every job immediately and is cleared by the weekly sync when FMP no longer lists it and its live profile says `isActivelyTrading`. Operations (verify, back up, roll back): `backend/OPS_RUNBOOK.md`, "Tracked universe".

## Caching policy

Fundamentals change infrequently, so raw FMP pulls are cached in a local SQLite database (`backend/core/models.py::FundamentalsCache`, via SQLModel) keyed by `(ticker, statement_type, period)`, with a `fetched_at` timestamp on each row. Before refetching from FMP, check whether a cached entry is fresher than the configurable staleness window — `Settings.cache_staleness_days` in `backend/core/config.py`, default 7 days, overridable via the `CACHE_STALENESS_DAYS` env var. Never hardcode the staleness window at a call site.

### History protection

A cached statement row is a whole FMP response, so it is **never overwritten by a shorter one**: every `FundamentalsCache` write (`core/cache.py::_write_cache_row`, the single write path for `get_or_fetch`, `get_or_fetch_earnings_aware` and `force_fetch`) goes through the one rule in `core/history_merge.py` for the keys in `HISTORY_KEYS` (income/balance/cash-flow statements annual and quarterly, key-metrics, ratios, enterprise values, financial growth, as-reported, analyst estimates, grades history, segmentation): new rows replace cached rows for the same period (a restatement still updates), cached older periods the answer lacks are kept (up to `max(len(cached), len(new))`), and an empty, null, error or non-list body never replaces a non-empty row. The caller is handed the merged rows. A new cached statement type must be added to `HISTORY_KEYS` or `SNAPSHOT_STATEMENT_TYPES` (`tests/test_history_merge.py` fails otherwise). A clamp (fewer periods than cached, oldest cached older than oldest returned) is logged once per ticker per run and counted into `nightly_fundamentals_fetch`'s message as `N history-clamped` (informational, never red). The Refresh button keeps history rows and marks them stale (`INVALIDATED_AT`) instead of deleting them; the shared bars cache's replace path keeps the older bars when FMP answers with less history than held and than asked. Read-only audit: `uv run python -m pipeline.cache_history_audit`. Detail: docs/specs/fmp-data-and-bar-cache.md, "History protection"; `CorporateEvent` was already upsert-only.

### Data groups: pausing FMP (per-group toggles)

FMP on/off is per **data group**, stored in the DB (`core/data_groups.py`, tables `DataGroupSetting` -- one row per group -- and the singleton `DataGroupGlobal`; lazy-seeded like `LiquidityZoneConfig`, 5 s in-process cache invalidated on write) and edited live from Settings > FMP data groups, with no restart. Cron jobs are separate processes and read the same DB. There is no global env flag (no `FMP_ENABLED` or `INSIDER_ACTIVITY_ENABLED`); only `FMP_API_KEY`/`FMP_BASE_URL` are read from `.env`.

- **Groups:** `fundamentals`, `profile_quote`, `analyst_ratings`, `segmentation`, `news`, `institutional_ownership` (seeded **off** -- the shelved feature), `index_membership`, `corporate_events`, `daily_prices` and `daily_prices_long` (both via `/historical-price-eod/full`, split by history depth) and `intraday_bars` (via `/historical-chart/1hour`; all three wired to live FMP endpoints -- see docs/specs/fmp-data-and-bar-cache.md), `etf_info` (`/etf/info` only, feeds the ETF page Overview tab; tier Starter (the owner's recorded value and the code default; not FMP-verified); its canary/probe symbol is **SPY**, not AAPL, because AAPL returns `200 []` -- `CANARY_SYMBOL_OVERRIDES`; see docs/specs/etf-page.md). **For the price groups, off = cached-only, and the nightly bar jobs report `skipped`**.
- **Effective state** = master switch on AND group enabled AND required tier <= my plan AND status != `plan_restricted`. Off means **cache-only**: the last cached row is served (even if stale), nothing is ever wiped.
- **Required tier per group is a user-editable value** (Starter/Premium/Ultimate) -- the seeded values are unverified guesses from the 2026-09-24 investigation. "My FMP plan" is one more editable value (seeded Ultimate); a group above the plan reads "Not on plan" and is treated as off.
- **Master switch** ("disable all FMP", same semantics the old `FMP_ENABLED=false` had): Settings > FMP data groups (the status card below the group table), or `uv run python -m pipeline.data_groups pause-all | resume | status` when the API is down.
- **Single gate, two layers.** `FMPClient.get` maps endpoint -> group (`ENDPOINT_GROUP`; the two endpoints shared by two features pass an explicit `group=`: `/earnings`, `/quote`) and raises `FMPGroupDisabledError`, a `FMPDisabledError` subclass, so existing `except httpx.HTTPError`/`safe_fetch` sites need no edits. `core/cache.py`'s `get_or_fetch`/`get_or_fetch_earnings_aware`/`force_fetch` gate per `statement_type` -> group (`STATEMENT_TYPE_GROUP`) with the original cache-only semantics (stale row served; `force_fetch` raises if nothing cached). `tests/test_data_groups_registry.py` **fails if any FMP endpoint or cached statement_type used in the code is unmapped**, and pins that any bulk/batch endpoint must be Ultimate (none is used; never call one). An unmapped endpoint fails closed.
- **What degrades when a group is off:**
  - `profile_quote`: search falls back to the tracked-ticker universe (symbol only); the ticker header's `price` uses the last official close cached nightly (`TickerLastClose`), every other quote field stays at the last cached FMP value; `/refresh` 503s.
  - `analyst_ratings` / `news` / `segmentation` / `fundamentals`: their tabs/scores serve cached data; the nightly fundamentals fetch, the nightly price-target snapshot and the index-list refresh jobs skip.
  - `corporate_events`: chart E/D markers are served from the cached `CorporateEvent` rows (however old).
  - `insider`: no `insider` data group exists (the feature was shelved and fully removed); do not reintroduce it without an explicit decision.
- **`POST /api/tickers/{t}/refresh`** returns **503** if any group it would clear (the ticker's cached statement types) or must re-fetch through (`profile_quote`, `fundamentals`, always needed by the immediate score recompute) is not live -- never a partial clear (`pipeline/refresh.py::groups_blocking_refresh`).
- **402 safety net** (`FMPClient._handle_plan_restriction`): on HTTP 402 it probes a canary (AAPL, same endpoint); only if the canary also 402s is the group marked `plan_restricted` (a symbol-scoped 402 leaves it live). **Exception, 2026-10-02: the `fundamentals` group (`VARIANT_GROUPS`) restricts a request VARIANT, not the group.** A canary-confirmed 402 (the failing request's `period`/`limit` replayed for AAPL) is recorded in `DataGroupVariant` (`/income-statement?limit=12&period=quarter`); the group stays **live**, annual and every other endpoint keep working, and a restricted variant makes `FMPClient.get` raise `FMPVariantUnavailableError` (an `FMPDisabledError`, so `safe_fetch` reads it as no data) with no call; `core.cache` serves the stale cached row and writes nothing for it. Only that variant's own replay clears it (weekly `stale_data_health_check`, a plan edit, Settings > FMP data groups **Re-test**, or `pipeline.data_groups retest|clear-variant`), so it cannot flap. `nightly_fundamentals_fetch` reports `N variant-unavailable (V request types refused by the plan)` (informational, never red). 429, 5xx, timeouts and a symbol-scoped 402 restrict nothing. Every other group still uses the group-level canary (docs/specs/fmp-data-and-bar-cache.md, "Request variants", lists which could flap). 401/403 = a *key* problem (global warning in Settings, no group blamed); 429 never marks anything; 5xx/transport errors count toward a "Failing" chip after 3 in a row and never disable a group. Restricted groups (and variants) are re-probed weekly (`pipeline.stale_data_health_check`) and whenever the plan is edited.
- **Nightly jobs** whose group is off log `skipped (group X ...)` and record a real **`skipped` cron status** (`run.skip(reason)` -> `CronRunLog.status="skipped"`; health view `skipped` with `skipped_since` = start of the current streak; never `ok`/`overdue` while skipped, `last_success_at` still shows the last real run).
- **API/UI:** `GET /api/config/data-groups` (+ `PUT .../master`, `.../plan`, `.../{group}`). Settings > FMP data groups shows one row per group (Switch, chip Live / Cached only / Not on plan / Restricted by FMP / Failing, last success, tier select, feeds list; disabling warns with the dependent features), with the plan select and master switch in a status card below the table. Ticker-page tabs show a "not refreshing -- as of [date]" badge for off groups (`GroupOffBadge`).
- `bin/start.sh` skips the AAPL `/quote` preflight when master or `profile_quote` is not live; a 402 there warns and startup continues.
- Tests get a fresh in-memory group config per test (`conftest._isolate_data_groups_engine`: master on, plan Ultimate, everything live except `news` and `institutional_ownership`, both shelved and default-off); a test wanting an off state calls `core.data_groups.set_master`/`set_group_enabled`.

**What stays unaffected:** `pipeline/nightly_score_recompute.py` (already `cache_only=True` throughout, zero FMP calls regardless of any group state), and any read whose cache is still within its normal staleness window — which, on a warm cache, is most of the app most of the time.

For the exact FMP endpoint→group and cache-key→group mappings, see docs/specs/fmp-data-and-bar-cache.md.

### Ad-hoc reproduction scripts must not touch the real database

`backend/fathom.db` is the one real database — `config.py`'s `database_path` has no environment-based split between "real" and "test." The only thing keeping test runs from polluting it is that every test in `backend/tests/` explicitly constructs its own fresh in-memory engine (`create_engine("sqlite://")`) and monkeypatches it onto every module's `engine` reference *before* calling any `get_stepN_data`/`get_summary`/`compute_ticker_score` function. `cache.py::get_or_fetch` has no way to tell "this is a controlled repro" from "this is real" — it will silently persist whatever `fmp_client` returns into whatever `engine` happens to be bound at that moment, indistinguishable later from genuine FMP data.

Any one-off script that reproduces test-like behavior against real ticker data (monkeypatching `fmp_client` to return controlled/fixture responses) **must** follow the exact same convention: construct a fresh in-memory engine and monkeypatch it onto **every module's own `engine` reference** first — each data-layer module (`step1_data.py` .. `step5_data.py`, `ticker_summary.py`, etc.) manages its own independent `Session(engine)` block bound to its own `engine` import, so patching one module's `engine` does not patch another's. Never monkeypatch `fmp_client` alone and call these functions against the default (real, file-backed) `db.engine`. This has caused real production contamination twice (2026-07-28, 2026-08-04) — a real ticker's fundamentals were silently overwritten with fixture data for several hours before being caught and purged. A session-scoped write-guard (`backend/tests/conftest.py`) now hooks SQLAlchemy's `before_cursor_execute` on the real `core.db.engine` for the whole pytest session and raises immediately on any write, so a future missing `engine` monkeypatch fails loudly in CI instead of silently reaching production. `backend/pipeline/audit_fixture_contamination.py` (read-only, safe to run anytime) scans `FundamentalsCache` for this class of fingerprint and runs weekly via cron (Sundays 1:25 AM).

For the full incident history behind this rule, see docs/archive/claude-md-history-features.md, section "Ad-hoc reproduction scripts must not touch the real database".

## Cron job heartbeat / health monitoring

`backend/core/cron_health.py::cron_heartbeat("<job_name>")` wraps every real cron job's entry point (`if __name__ == "__main__":`), writing a `CronRunLog` row regardless of how the job fails. Purely additive — on failure the original exception is always re-raised unchanged, so existing stderr/`_cron.log` capture and exit codes are untouched; the heartbeat's own DB writes are independently try/except-swallowed, so a heartbeat failure can never mask or alter the job's real outcome. `GET /api/config/cron-health` computes each job's health from its `CronRunLog` history (`ok`/`overdue`/`failed`/`unknown`) and backs Settings > Scheduled jobs.

**`CRON_JOB_NAMES` in `core/cron_health.py` is the single source of truth for which cron jobs exist** — a new cron job added to `crontab.txt` needs a matching `CRON_JOB_NAMES` entry, an `_EXPECTED_CADENCE_HOURS` entry, and a `cron_heartbeat(...)` call at its own entry point, or it ships unmonitored. `backend/tests/test_cron_wiring.py` fails loudly if any of these three ever drift apart, so this isn't just a documentation convention to remember by hand. Note also: editing `crontab.txt` alone changes nothing on the running box — it must be reinstalled (`crontab crontab.txt` from `backend/`) and `crontab -l` checked against the file, or a job silently never runs on the new schedule.

**A deliberately disabled job** (its `crontab.txt` line commented out) is listed in `core/cron_health.py::DISABLED_CRON_JOBS` (job -> date + reason); it stays in `CRON_JOB_NAMES`/`JOB_METADATA`, the Scheduled Jobs page shows it as the neutral "Skipped" pill with "Disabled since <date>: <reason>" (never "Overdue"), and `test_cron_wiring.py` requires a listed job to be absent from `crontab.txt` and every other job to be present. **`pipeline.nightly_corporate_events` has been disabled since 2026-10-01** (about 1,165 FMP calls per run at 406-527 requests/min, over Starter's 300/min; investigation pending): the Chart E/D markers serve the frozen cache; re-enable = uncomment the cron line at its planned slot **1:50 AM** (not the old 2:45; it must end before fundamentals starts at 2:00) + delete the `DISABLED_CRON_JOBS` entry + update `JOB_METADATA` + `crontab crontab.txt` from `backend/` (see `backend/OPS_RUNBOOK.md`, docs/specs/corporate-events.md, docs/decisions.md 2026-10-01).

**Status messages and the failure threshold.** `core/cron_health.py::check_failure_threshold(attempted, failed, summary)` is the one shared rule for jobs that report attempted/failed counts: the run is marked failed (the existing red `failure` state, no new status) when failed/attempted >= 5% (`FAILURE_RATE_THRESHOLD`; only from 25 attempted, `FAILURE_RATE_MIN_ATTEMPTED`) or when everything attempted failed. "No data" and "skipped" counts go in the message only, never in the threshold. `nightly_price_target_snapshot` classifies each ticker written / no_data (HTTP 200, empty body: no analyst coverage) / failed, and skips known ETFs/funds up front (docs/specs/price-target.md); fundamentals, BB+RSI, Warren, score recompute and backup_db now set a message too. A new count-reporting job should call the helper from its `record_outcome`, not hand-roll a rule.

Full mechanism, exact cadence windows, and past incidents are documented in `backend/OPS_RUNBOOK.md`'s "Cron job heartbeat / health monitoring" section (not duplicated here) and docs/archive/claude-md-history-features.md (section "Cron job heartbeat: FMP_ENABLED interaction investigation and nightly_price_target_snapshot guard-parity fix").

## Company classification

`classify_company_type` (`backend/scoring/classification.py`) drives Bank/REIT/Insurance/Utility/Property-Developer detection, including several manually-verified non-lender ticker overrides (sector/industry text alone can't reliably distinguish a genuine lender from a non-lender in some categories) and the requirement that "Bank" treatment implies genuine CET1/NPL-reporting capability, not just lending activity. See docs/specs/company-type-variations.md for the current tables and mechanism.

## Docs map

Scoring methodology and feature-specific detail live in `docs/specs/*.md` and `docs/archive/*.md`, not in this file.

**Scoring methodology:** Financials — docs/specs/financials.md. Growth Rate — docs/specs/growth-rate.md. Debt — docs/specs/debt.md. Profitability — docs/specs/profitability.md. Valuation (Step 3) — docs/specs/valuation.md. Overall Assessment step weighting, Screener ETF exclusion — docs/specs/overview.md. Company classification / non-lender ticker overrides / Bank CET1-NPL standard — docs/specs/company-type-variations.md. Economic Moat — docs/specs/economic-moat.md. Glossary of terms — docs/specs/glossary.md. Speculative Growth lens — docs/specs/speculative-growth.md.

**Tracked universe** (nightly ticker set, 30-day view expiry, protected set, seed, delisted clearing) — docs/specs/tracked-universe.md.

**ETFs screener** (read-model table `EtfScreenerRow`, `/api/etf-screener` endpoints, equity-only Beta, saved-view `kind`; the `/etfs` page ("ETFs" in the top nav, built step 5; the old "Screener" nav item and page are now "Stocks" / "Stocks Screener", same `/screener` route) — docs/specs/etf-screener.md.

**ETF page** (ticker page variant for `isEtf || isFund`: Overview/Technical/Chart, `/etf/info`, `etf_info` group, ETF watchlist button, Moat guard) — docs/specs/etf-page.md.

**Technical-analysis lenses:** Weinstein Stage Analysis (also covers the historically named `TrendAnalysis` table / `nightly_trend_calculation` job / `/trend-analysis` endpoint) — docs/specs/weinstein-stage.md. Sector Heatmap — docs/specs/sector-heatmap.md. Momentum (stocks and ETFs, snapshots, "previous month" rule) — docs/specs/momentum.md. Market Breadth — docs/specs/market-breadth.md. Chart indicators (Stochastic, etc.) — docs/specs/chart-indicators.md. Price-target snapshot — docs/specs/price-target.md. Liquidity Zone (LP) detection — docs/specs/liquidity-zones.md. Warren RSI/ADX/WVF entry signal — docs/specs/warren-signal.md (SPY/QQQ/TQQQ/TECL have their own Blue Up profile, chosen by `data/warren_signal_data.py::profile_for` from the ThinkScripts in `~/warren-thinkscripts/`; every other ticker is the unchanged ANY-TICKER rule; the spec lists the ported-as-written quirks and the FMP volume caveats). The profiled tickers' volume terms read **guarded** volume: `data/warren_signal_data.py::signal_candles` (shared by the nightly store and the 2H chart) blanks a day's 2h volume when it is > 1.5x that day's EOD volume or the EOD volume is missing (fail-closed); it never adds a Blue and never touches non-profiled tickers. Chart tab fetch behavior, earnings/dividend markers, and the intraday 2H·90D range (2h candles, on-demand Warren/BB+RSI/LP for any ticker, Warren RSI/ADX/WVF panes) — docs/specs/chart-tab.md. Institutional Ownership (shelved feature) — docs/specs/institutional-ownership.md.

**Data infrastructure:** FMP endpoint/cache-key → data-group mappings, shared bars cache, daily/long-history/intraday price fetch mechanism, delisted-ticker handling, US-listed-only (non-US) handling — docs/specs/fmp-data-and-bar-cache.md. Corporate events (earnings/dividends/splits cache) — docs/specs/corporate-events.md. History protection (merge rule for shorter/empty FMP answers, clamp counting, bars replace guard, audit command) and Request variants (a 402 restricts one request type, not the group; what each caller shows) — docs/specs/fmp-data-and-bar-cache.md, "History protection" / "Request variants".

**History** (scoring-rubric history, technical-signal investigations, watchlist-rename history, FMP migration phases, shelved/deleted features, incident write-ups): docs/archive/claude-md-history-scoring.md, docs/archive/claude-md-history-technical-signals.md, docs/archive/claude-md-history-fmp-migration.md, docs/archive/claude-md-history-features.md.

**Old CLAUDE.md:** the pre-slimming file is `docs/archive/CLAUDE.original.md` (NOT auto-loaded); if a topic isn't found in `docs/`, grep it before assuming it is undocumented. Code comments that cite old section names ("Step 1 deviations", "Scoring rubric deviations", ...) resolve via docs/legacy-claude-md-citations.md.

## Workflow rules

- **Plan Mode by default.** Propose a plan and wait for confirmation before writing code for each phase.
- **Confirm before committing.** Stop and confirm with the user before committing each phase's work, and again before pushing — push only after explicit confirmation.
- **One commit per logical change.**
- Never use `--dangerously-skip-permissions`.
- **No browser-based verification after a code change.** This environment can't drive a browser — rely on `tsc`, `eslint`, and the test suite instead of visually checking the result.
- **Clean up after yourself.** Delete any temporary files, scratch scripts, or processes you started, before ending a task.
- **Design and product decisions live in `docs/design-system.md`, `docs/design-system-charts.md`, and `docs/decisions.md`.** Check these before styling anything or proposing a new UI pattern — don't re-derive a decision that's already been made.
- **`docs/design-system.md` is authoritative for visual style** (fonts, sentence case, dark-only, no theme toggle) and overrides any conflicting style guidance in the generic skills under `.claude/skills/` (`frontend-design`, `ui-styling`, `design-system`, `ui-ux-pro-max`).

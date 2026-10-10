# Backend layout and conventions

The full package-by-package layout of the repo, moved out of `CLAUDE.md` on 2026-10-10 (which keeps a short map and the rule that cron jobs run as `-m package.module`). Verbatim from `CLAUDE.md` at that date; the code is authoritative if the two ever disagree.

## Folder layout

```
bin/         start.sh / stop.sh / common.sh -- see `CLAUDE.md` "Running the app".
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
               statement_view.py (the cleaned-statement loader, docs/specs/
               statement-data-quality.md), shares.py, debt_metrics.py, npl.py,
               bank_capital_metrics.py,
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
               series_trend.py, step1.py..step5.py, overall.py, weights.py: the one definition of every
               score weight and its defaults, `DEFAULT_WEIGHTS`).
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

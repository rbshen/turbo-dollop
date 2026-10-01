# Legacy CLAUDE.md citations — how to resolve them

Code comments, docstrings, test comments and a few strings under `backend/`, `frontend/` and `bin/` cite "CLAUDE.md" and its old section names. **Those citations refer to the pre-slimming CLAUDE.md, which is now `docs/archive/CLAUDE.original.md`** (byte-identical, sha256 `ac2f4e35…40c3`, not auto-loaded; 4,316 lines). The slim CLAUDE.md that loads each session no longer contains most of those sections. Use the table below to resolve any old citation to (a) its current spec file and (b) the verbatim original text (archive file + source line range).

Two more things to know:

- The archive files (`docs/archive/claude-md-history-*.md`) label every block "(original lines A-B)", so a source line range in this table can be looked up directly in `CLAUDE.original.md` or in the archive file named.
- Several cited names ("Step 1 deviations", "Scoring rubric deviations", "Item 3 note", "Fork B scope decision" ...) are **not headings in `CLAUDE.original.md` at all**. Some come from an even earlier CLAUDE.md layout (the "## Scoring rubric deviations" heading existed until 2026-08-05; see `git show 89ee5fe^:CLAUDE.md`), and some never existed as CLAUDE.md sections. They are resolved by topic, and the status column says how confident the mapping is.

## Totals

**200 citing lines** (199 in `.py`/`.ts`/`.tsx`/`.css`/`.txt`/`.sh` files, 1 in `backend/.env.example`). 4 further "CLAUDE.md" mentions in `backend/OPS_RUNBOOK.md` are documentation, not code, and were handled in the B6 stale-reference sweep. Of the 200 code-side citations, 2 are not comments: `backend/tests/conftest.py:42` (an assertion message string) and `frontend/components/settings/DiscountRateSettingsForm.tsx:51` (**user-visible UI text**, "see CLAUDE.md"). 34 cite CLAUDE.md without naming a section on that line, or wrap the name onto the neighbouring line (listed separately below, and marked "(inferred)" in the index).

| Status | Meaning |
|---|---|
| RESOLVED | The cited name is a real heading (or a bullet inside one) in `CLAUDE.original.md`. |
| RESOLVED BY TOPIC | The name is not an original heading, but the topic maps cleanly to a contiguous original range. |
| PARTIAL / AMBIGUOUS | Only part of the citation, or a nearby text, exists. |
| UNRESOLVABLE | No text under this name exists in `CLAUDE.original.md`; the code and tests are the source of truth (and in three cases, a documentation gap: BB+RSI entry signal, ticker dot/hyphen normalization, Momentum). |

## Section map

| Old CLAUDE.md section name | Citations | Current spec / home | Original lines (`CLAUDE.original.md`) | Archive file (verbatim text) | Status | Notes |
|---|---|---|---|---|---|---|
| Step 1 deviations (Financials) | 24 | docs/specs/financials.md | 446-910 (Financials part of "Scoring rubric notes") | docs/archive/claude-md-history-scoring.md (blocks 446-458 ... 778-910, contiguous) | RESOLVED BY TOPIC | No heading of this name exists in `CLAUDE.original.md`; the name predates the 2026-08-05 restructure (commit 89ee5fe, "Drop stale doc-deviation framing"). Useful sub-ranges: spike/HWM/age-aware trend 469-493, NI Operating-Income backup 539-591, `robust_early_direction` (GLW) 592-661, `multiple_dips` graduation 705-777, Bank Margins exemption + resolved-dip graduation 778-910. |
| Step 4 deviations (Profitability) | 19 | docs/specs/profitability.md | 1241-1579 | docs/archive/claude-md-history-scoring.md (blocks 1241-1259 ... 1560-1579) | RESOLVED BY TOPIC | Same name-history caveat. 10yr+TTM window 1241-1259; ROE/ROIC tiering 1269-1293; `BASE_WEIGHTS` 1463-1495; ROIC/CCC/AR exempt types 1560-1579; below-floor graduation + verdict floor 1496-1559. |
| Ad-hoc reproduction scripts must not touch the real database (also cited as "engine-isolation convention", "ad-hoc-script warning/policy", "fixture-contamination section") | 19 | CLAUDE.md (rule, still auto-loaded) | 257-375 | docs/archive/claude-md-history-features.md (block 257-375) | RESOLVED | The rule is still in CLAUDE.md; the two incident narratives are archived. |
| Valuation section / non-USD currency conversion investigation / Bank-REIT-Insurance investigation / Valuation FX | 15 | docs/specs/valuation.md; docs/specs/fmp-data-and-bar-cache.md (FX conversion kept for non-US) | 1945-2272 (FX doc fix 2061-2096; book-value/P-B 2097-2197); 4037-4064 (Non-US cleanup: FX conversion kept) | docs/archive/claude-md-history-scoring.md; docs/archive/claude-md-history-fmp-migration.md (block 4057-4064) | PARTIAL | Sub-names "non-USD currency conversion investigation", "Bank/REIT/Insurance investigation" and "Valuation FX section" are not headings anywhere in `CLAUDE.original.md`; nearest text only. |
| Step 2 deviations (Growth Rate) | 14 | docs/specs/growth-rate.md | 911-1035 | docs/archive/claude-md-history-scoring.md (block 911-1035) | RESOLVED BY TOPIC | Same name-history caveat as Step 1. Covers EPS-preferred substitution, insufficient_data, target-year picker, REIT revenue basis, negative-magnitude graduation. |
| Scoring rubric deviations (general: verdict bands, the 70 floor, hard-fail semantics) | 14 | docs/specs/overview.md; docs/specs/financials.md ("Verdict bands") | 446-1613 (the whole "Scoring rubric notes" range; verdict bands 446-458) | docs/archive/claude-md-history-scoring.md (all 37 blocks for 446-1613) | RESOLVED BY TOPIC | Old CLAUDE.md heading "## Scoring rubric deviations" existed until 2026-08-05: `git show 89ee5fe^:CLAUDE.md` lines 137-741. In `CLAUDE.original.md` the same material sits under "## Scoring rubric notes" (line 446). |
| Step 5 / Debt deviations, CET1 deviation note, "Debt is a hard pass/fail bankruptcy filter", `PASS_WITH_CAUTION_SCORE_CAP` | 9 | docs/specs/debt.md | 1036-1240 (CET1 1036-1060; hard-fail 1061-1073; cap 1074-1091; breach-context + MA/FICO examples 1092-1147) | docs/archive/claude-md-history-scoring.md (blocks 1036-1060 ... 1204-1240) | RESOLVED BY TOPIC | Same name-history caveat. |
| Item 1 / Item 2 / Item 3 notes (Valuation follow-ups) | 9 | docs/specs/valuation.md | 1945-2272: Item 1 = 1952-1977 (RECOVERY_PATTERNS), Item 2 = 1978-2026 (DNI_NORMALIZED TTM double-count), Item 3 = 2027-2060 (CF_NORMALIZED/FCF_NORMALIZED manual-only) | docs/archive/claude-md-history-scoring.md (blocks 1945-1951 ... 2238-2272) | RESOLVED BY TOPIC (numbering inferred) | No heading "Item N" exists; the numbering is inferred from the 2026-08-08 "three fixes shipped together" block (1945-1951) and the archive block titles. Item 4 (fx_rate doc fix) = 2061-2096. |
| Trend structure analysis (Technical) section (incl. Screener-surfacing note, SMA position tracking entry, Weinstein) | 9 | docs/specs/weinstein-stage.md (trend-structure-technical.md was deleted 2026-10-01 with the swing/BOS feature; only the shared job/storage notes survive, in weinstein-stage.md) | 2316-2662 | docs/archive/claude-md-history-technical-signals.md (blocks 2349-2357, 2358-2372, 2403-2410, 2428-2447, 2480-2489, 2503-2525, 2549-2560, 2572-2584, 2585-2593, 2609-2613, 2625-2637, 2638-2662) | RESOLVED | Sub-names ("Screener surfacing note" ~2638, "SMA position tracking entry" ~2692) are bullets inside this section. |
| Caching policy; also "cache-freshness design note", "FMP-pause investigation", "2026-08-16 nightly-sweep fix", "cron thundering-herd follow-up", and (via test docstrings) engine isolation | 8 | CLAUDE.md ("Caching policy"); docs/specs/fmp-data-and-bar-cache.md; backend/OPS_RUNBOOK.md | 146-156 (policy); 3440-3543 (close-aware freshness); 157-256 (FMP pause) | docs/archive/claude-md-history-technical-signals.md (blocks 2780-2823, 3500-3537) | PARTIAL | Only "Caching policy" is a real heading. The four dated sub-names have no heading in the original; the nearest text is listed. `test_speculative_growth_data.py:2` cites "caching-policy convention" but means the engine-isolation rule (Ad-hoc row). |
| Speculative Growth section / investigation notes | 8 | docs/specs/speculative-growth.md | 2273-2315 | none (moved 100% into the spec) | RESOLVED | Heading in original: "Speculative Growth (new classification) scoring notes". |
| Feature-scoping notes: news v1 scoping, Ratios tab (caching investigation / kickoff notes), Summary tab expansion, ticker-search UX investigation, segmentation | 8 | none | none | none | UNRESOLVABLE | None of these is a heading in `CLAUDE.original.md` (the only "Summary tab" hits, lines 4212/4293, are about Institutional Ownership). The cited code and tests are the source of truth. |
| Economic Moat deviation note | 5 | docs/specs/economic-moat.md; docs/specs/overview.md (69/31 split) | 1580-1613 (69/31 weighting); lines 10 and 4290 mention Moat only in passing | docs/archive/claude-md-history-scoring.md (blocks 1580-1585, 1586-1610, 1611-1613) | PARTIAL | No dedicated Moat section in `CLAUDE.original.md`; the spec is the real home. |
| Warren signal section | 5 | docs/specs/warren-signal.md | 3169-3439 | docs/archive/claude-md-history-technical-signals.md (blocks 3196-3216, 3228-3235, 3268-3278, 3288-3293, 3310-3324, 3332-3338, 3357-3375, 3382-3386, 3393-3407, 3427-3439) | RESOLVED | `nightly_warren_signal_calculation.py:8` cites "nightly_entry_signal_calculation.py's own CLAUDE.md entry" (see EntrySignal row). |
| Chart tab entries / investigation notes (incl. the FMP-cache staleness bug) | 4 | docs/specs/chart-tab.md; docs/specs/fmp-data-and-bar-cache.md (staleness bug) | 2838-2868; 3074-3157; 2780-2823 (staleness bug) | docs/archive/claude-md-history-technical-signals.md (blocks 2838-2868, 3074-3091, 3143-3152, 2780-2823) | RESOLVED |  |
| Fork B scope decision (custom valuation override) | 3 | docs/specs/valuation.md (custom valuation / `valuation_source`) | none | none | UNRESOLVABLE | Not present in `CLAUDE.original.md` or any CLAUDE.md revision (`git log --all -S"Fork B"` finds only commit d03ccc5, 2026-08-07, "Wire Manual Calculation panel to persistent custom valuation state"). |
| Company classification: non-lender ticker overrides | 3 | docs/specs/company-type-variations.md | 1721-1802 | docs/archive/claude-md-history-features.md (blocks 1721-1752, 1787-1795) | RESOLVED | Exact heading exists in the original (line 1721). |
| Bank classification requires genuine CET1/NPL-reporting capability | 3 | docs/specs/company-type-variations.md | 1803-1901 | docs/archive/claude-md-history-features.md (blocks 1803-1849, 1878-1893) | RESOLVED | Exact heading exists (line 1803). |
| Data groups | 3 | CLAUDE.md ("Data groups: pausing FMP"); docs/specs/fmp-data-and-bar-cache.md for endpoint mappings | 157-256 | none (KEEP, in CLAUDE.md) | RESOLVED | Section still auto-loaded. |
| technical entry-signal section (BB+RSI) | 3 | docs/specs/warren-signal.md (BB+RSI comparisons, shared retention); docs/specs/liquidity-zones.md (cron ordering); backend/OPS_RUNBOOK.md | none dedicated (BB+RSI is only mentioned in passing, e.g. lines 134, 2693, 2936) | none | UNRESOLVABLE (no dedicated section) | No BB+RSI spec exists: this is a documentation gap, not just a mis-citation. The code (`analysis/entry_signal/`, `data/entry_signal_data.py`) is the source of truth. |
| Liquidity Zone (LP) detection (Technical) section | 2 | docs/specs/liquidity-zones.md | 2663-2779; 2869-2925; 2983-3073 | docs/archive/claude-md-history-technical-signals.md (blocks 2696-2709, 2719-2725, 2744-2752, 2869-2925, 2983-3028, 3035-3042, 3067-3073) | RESOLVED |  |
| Ticker dot/hyphen normalization | 2 | none (`normalize_ticker` appears in no spec) | none | none | UNRESOLVABLE | Never a heading in CLAUDE.md; introduced by commit 713c912 (2026-08-11, "Add normalize_ticker() choke point") and 9732780. Documentation gap. |
| Momentum section | 2 | none (momentum appears only in passing in specs) | 88, 230, 3442 (folder-layout / cron mentions only) | none | UNRESOLVABLE | Never a dedicated section; introduced by commits 6ebda40 / 117789a (2026-09-08). Documentation gap. |
| Analyst Ratings design-round / verdict-sentence entries | 2 | docs/specs/price-target.md (adjacent); `frontend/lib/analystRatingsVerdict.ts` itself | none | none | UNRESOLVABLE | No such section in the original; nearest text is in the Phase 3/6 migration notes (lines 3601, 3979, 4097) and does not cover the verdict thresholds. |
| design-system migration notes / "plan notes" | 2 | docs/design-system.md; docs/decisions.md | 4313-4316 (pointer only) | none | UNRESOLVABLE (redirect) | Design decisions live in `docs/design-system.md`, `docs/design-system-charts.md` and `docs/decisions.md`, never in CLAUDE.md. |
| Cron job heartbeat / health monitoring | 1 | CLAUDE.md (gotcha paragraph); backend/OPS_RUNBOOK.md | 376-445 (gotcha 435-444; mechanism 376-400 deleted as duplicate of OPS_RUNBOOK) | docs/archive/claude-md-history-features.md (block 401-433) | RESOLVED | Cited from `backend/.env.example:10`. |
| Shared bars cache (cited as "2026-09-18 investigation, see CLAUDE.md") | 1 | docs/specs/fmp-data-and-bar-cache.md | 3440-3543; 2780-2823 | docs/archive/claude-md-history-technical-signals.md (blocks 3500-3537, 2780-2823) | RESOLVED (inferred) | Cited without a section name. |
| Daily prices: FMP | 1 | docs/specs/fmp-data-and-bar-cache.md | 3544-3598 | docs/archive/claude-md-history-fmp-migration.md (blocks 3544-3549, 3581-3598) | RESOLVED |  |
| Institutional Ownership entry | 1 | docs/specs/institutional-ownership.md | 4201-4298 | none (moved 100% into the spec) | RESOLVED |  |
| "deferred-revenue/one-off precedent (surface it, don't guess)" | 1 | docs/specs/debt.md (deferred-revenue rescue) | 1061-1073 (nearest) | docs/archive/claude-md-history-scoring.md (block 1061-1073) | AMBIGUOUS | Not a heading; cited from `helpers/ttm.py:9` for the "surface it, don't alter it" convention. |

## Citations that name no section (or name it on another line)

These cannot be resolved from the citation text alone; the mapping below is inferred from the surrounding comment. Verify against the comment before relying on it.

| Location | Inferred section |
|---|---|
| `backend/clients/sec_edgar.py:47` | Step 1 deviations |
| `backend/clients/shared_bars_cache.py:4` | Shared bars cache |
| `backend/core/config.py:43` | Caching policy; also "cache-freshness design note", "FMP-pause investigation", "2026-08-16 nightly-sweep fix", "cron thundering-herd follow-up", and |
| `backend/core/models.py:308` | technical entry-signal section |
| `backend/core/models.py:545` | Valuation section / non-USD currency conversion investigation / Bank-REIT-Insurance investigation / Valuation FX |
| `backend/core/schemas.py:251` | Step 2 deviations |
| `backend/core/schemas.py:255` | Step 2 deviations |
| `backend/data/chart_data.py:105` | Chart tab entries / investigation notes |
| `backend/data/ratios_data.py:21` | Feature-scoping notes: news v1 scoping, Ratios tab |
| `backend/data/segmentation_data.py:11` | Step 4 deviations |
| `backend/data/step3_data.py:356` | Valuation section / non-USD currency conversion investigation / Bank-REIT-Insurance investigation / Valuation FX |
| `backend/data/step5_data.py:216` | Step 5 / Debt deviations, CET1 deviation note, "Debt is a hard pass/fail bankruptcy filter", `PASS_WITH_CAUTION_SCORE_CAP` |
| `backend/data/trend_analysis_data.py:29` | Trend structure analysis |
| `backend/helpers/discount_rate_config.py:7` | Valuation section / non-USD currency conversion investigation / Bank-REIT-Insurance investigation / Valuation FX |
| `backend/pipeline/nightly_warren_signal_calculation.py:8` | Warren signal section |
| `backend/scoring/classification.py:63` | Company classification: non-lender ticker overrides |
| `backend/scoring/overall.py:174` | Economic Moat deviation note |
| `backend/scoring/overall.py:179` | Scoring rubric deviations |
| `backend/scoring/speculative_growth.py:53` | Speculative Growth section / investigation notes |
| `backend/scoring/step1.py:331` | Step 1 deviations |
| `backend/scoring/step1.py:598` | Step 2 deviations |
| `backend/scoring/step3.py:173` | Item 1 / Item 2 / Item 3 notes |
| `backend/scoring/step3.py:18` | Step 4 deviations |
| `backend/scoring/step4.py:717` | Step 4 deviations |
| `backend/scoring/step5.py:113` | Step 5 / Debt deviations, CET1 deviation note, "Debt is a hard pass/fail bankruptcy filter", `PASS_WITH_CAUTION_SCORE_CAP` |
| `backend/scoring/step5.py:9` | Scoring rubric deviations |
| `backend/scoring/trend.py:113` | Step 1 deviations |
| `backend/scoring/trend.py:473` | Step 1 deviations |
| `backend/tests/test_segmentation_data.py:15` | Feature-scoping notes: news v1 scoping, Ratios tab |
| `backend/tests/test_step1_data.py:324` | Step 2 deviations |
| `backend/tests/test_step5_data.py:543` | Company classification: non-lender ticker overrides |
| `frontend/app/globals.css:13` | design-system migration notes / "plan notes" |
| `frontend/components/settings/DiscountRateSettingsForm.tsx:51` | Valuation section / non-USD currency conversion investigation / Bank-REIT-Insurance investigation / Valuation FX |
| `frontend/components/ticker/RatioTrendsGrid.tsx:44` | Feature-scoping notes: news v1 scoping, Ratios tab |

## Citation index (for a later comment-repointing pass)

Every citing line, grouped by the section it resolves to. `(i)` = inferred (see the previous table).

**Step 1 deviations** — 24

`backend/clients/sec_edgar.py:47` (i), `backend/data/step1_data.py:33`, `backend/data/step3_data.py:64`, `backend/scoring/series_trend.py:107`, `backend/scoring/step1.py:38`, `backend/scoring/step1.py:99`, `backend/scoring/step1.py:211`, `backend/scoring/step1.py:248`, `backend/scoring/step1.py:269`, `backend/scoring/step1.py:319`, `backend/scoring/step1.py:331` (i), `backend/scoring/step1.py:502`, `backend/scoring/test_step1.py:289`, `backend/scoring/test_step1.py:471`, `backend/scoring/test_trend.py:52`, `backend/scoring/test_trend.py:99`, `backend/scoring/trend.py:22`, `backend/scoring/trend.py:96`, `backend/scoring/trend.py:113` (i), `backend/scoring/trend.py:342`, `backend/scoring/trend.py:414`, `backend/scoring/trend.py:451`, `backend/scoring/trend.py:473` (i), `frontend/components/step1/Step1Card.tsx:18`

**Step 4 deviations** — 19

`backend/core/schemas.py:406`, `backend/core/schemas.py:453`, `backend/core/schemas.py:615`, `backend/data/financials_data.py:17`, `backend/data/segmentation_data.py:11` (i), `backend/data/step4_data.py:47`, `backend/data/step4_data.py:51`, `backend/pipeline/backfills/bulk_refresh_step4_annual.py:6`, `backend/scoring/step3.py:18` (i), `backend/scoring/step4.py:84`, `backend/scoring/step4.py:147`, `backend/scoring/step4.py:241`, `backend/scoring/step4.py:613`, `backend/scoring/step4.py:662`, `backend/scoring/step4.py:717` (i), `backend/scoring/test_step4.py:685`, `backend/tests/test_step4_data.py:348`, `backend/tests/test_step4_data.py:391`, `frontend/lib/api/types.ts:431`

**Ad-hoc reproduction scripts must not touch the real database** — 19

`backend/analysis/ma_magnet/data.py:66`, `backend/core/data_source_health.py:9`, `backend/crontab.txt:171`, `backend/pipeline/audit_fixture_contamination.py:3`, `backend/pipeline/backup_db.py:137`, `backend/pipeline/purge_invalid_tickers.py:30`, `backend/tests/conftest.py:4`, `backend/tests/conftest.py:42`, `backend/tests/test_backup_db.py:43`, `backend/tests/test_chart_data.py:102`, `backend/tests/test_chart_endpoint.py:42`, `backend/tests/test_debt_metrics.py:145`, `backend/tests/test_debt_metrics.py:233`, `backend/tests/test_nightly_entry_signal_calculation.py:22`, `backend/tests/test_nightly_liquidity_zone_calculation.py:26`, `backend/tests/test_nightly_warren_signal_calculation.py:24`, `backend/tests/test_refresh.py:123`, `backend/tests/test_refresh.py:156`, `backend/tests/test_ticker_summary.py:1070`

**Valuation section / non-USD currency conversion investigation / Bank-REIT-Insurance investigation / Valuation FX** — 15

`backend/core/models.py:545` (i), `backend/core/schemas.py:1896`, `backend/data/financials_data.py:514`, `backend/data/ratios_data.py:288`, `backend/data/step3_data.py:78`, `backend/data/step3_data.py:356` (i), `backend/data/step3_data.py:779`, `backend/helpers/discount_rate_config.py:7` (i), `backend/pipeline/nightly_fundamentals_fetch.py:117`, `backend/scoring/step3.py:572`, `backend/scoring/step3.py:716`, `backend/tests/test_financials_data.py:462`, `backend/tests/test_ratios_data.py:189`, `frontend/components/settings/DiscountRateSettingsForm.tsx:51` (i), `frontend/components/step3/ValuationGauge.tsx:13`

**Step 2 deviations** — 14

`backend/core/models.py:830`, `backend/core/schemas.py:251` (i), `backend/core/schemas.py:255` (i), `backend/data/step2_data.py:26`, `backend/data/step2_data.py:57`, `backend/data/step2_data.py:211`, `backend/data/step2_data.py:218`, `backend/scoring/step1.py:598` (i), `backend/tests/test_step1_data.py:324` (i), `backend/tests/test_step1_data.py:373`, `backend/tests/test_step2_data.py:211`, `backend/tests/test_step2_data.py:237`, `frontend/components/step2/Step2Card.tsx:82`, `frontend/lib/api/types.ts:601`

**Scoring rubric deviations** — 14

`backend/core/schemas.py:235`, `backend/core/schemas.py:324`, `backend/core/schemas.py:413`, `backend/scoring/overall.py:179` (i), `backend/scoring/series_trend.py:23`, `backend/scoring/step1.py:168`, `backend/scoring/step2.py:102`, `backend/scoring/step5.py:9` (i), `backend/scoring/step5.py:503`, `backend/scoring/trend.py:424`, `frontend/components/step1/ScoreBadge.tsx:5`, `frontend/components/step4/Step4Card.tsx:112`, `frontend/lib/api/types.ts:281`, `frontend/lib/overallScore.ts:27`

**Step 5 / Debt deviations, CET1 deviation note, "Debt is a hard pass/fail bankruptcy filter", `PASS_WITH_CAUTION_SCORE_CAP`** — 9

`backend/core/models.py:658`, `backend/core/schemas.py:335`, `backend/data/step5_data.py:216` (i), `backend/pipeline/purge_invalid_tickers.py:12`, `backend/scoring/step5.py:37`, `backend/scoring/step5.py:113` (i), `backend/scoring/step5.py:485`, `frontend/components/shared/AnalysisSectionCard.tsx:73`, `frontend/components/step5/Step5Card.tsx:200`

**Item 1 / Item 2 / Item 3 notes** — 9

`backend/core/schemas.py:495`, `backend/core/schemas.py:624`, `backend/data/step3_data.py:575`, `backend/scoring/step3.py:173` (i), `backend/scoring/step3.py:676`, `backend/scoring/test_step1.py:737`, `backend/tests/test_step3_data.py:1195`, `backend/tests/test_step3_data.py:1428`, `frontend/lib/api/types.ts:739`

**Trend structure analysis** — 9

`backend/analysis/trend_structure/sma_position.py:32`, `backend/analysis/trend_structure/swings.py:4`, `backend/analysis/trend_structure/technical_status.py:8`, `backend/analysis/trend_structure/types.py:3`, `backend/analysis/trend_structure/weinstein.py:3`, `backend/core/schemas.py:1243`, `backend/data/trend_analysis_data.py:29` (i), `frontend/components/ticker/WeinsteinStagePill.tsx:19`, `frontend/components/watchlist/WatchlistTable.tsx:173`

**Caching policy; also "cache-freshness design note", "FMP-pause investigation", "2026-08-16 nightly-sweep fix", "cron thundering-herd follow-up", and** — 8

`backend/core/cache.py:80`, `backend/core/cache.py:133`, `backend/core/config.py:43` (i), `backend/data/financials_data.py:226`, `backend/data/step4_data.py:555`, `backend/data/step5_data.py:26`, `backend/helpers/debt_metrics.py:48`, `backend/tests/test_speculative_growth_data.py:2`

**Speculative Growth section / investigation notes** — 8

`backend/core/schemas.py:909`, `backend/data/speculative_growth_data.py:28`, `backend/pipeline/nightly_score_recompute.py:12`, `backend/pipeline/recompute_ticker_scores.py:14`, `backend/pipeline/stale_data_health_check.py:17`, `backend/scoring/speculative_growth.py:19`, `backend/scoring/speculative_growth.py:34`, `backend/scoring/speculative_growth.py:53` (i)

**Feature-scoping notes: news v1 scoping, Ratios tab** — 8

`backend/core/schemas.py:67`, `backend/data/news_data.py:18`, `backend/data/ratios_data.py:21` (i), `backend/data/ticker_summary.py:179`, `backend/pipeline/backfills/bulk_refresh_ratios_ttm.py:5`, `backend/tests/test_segmentation_data.py:15` (i), `backend/tests/test_ticker_summary.py:906`, `frontend/components/ticker/RatioTrendsGrid.tsx:44` (i)

**Economic Moat deviation note** — 5

`backend/scoring/overall.py:117`, `backend/scoring/overall.py:174` (i), `backend/scoring/test_overall.py:237`, `frontend/components/ticker/MoatPill.tsx:44`, `frontend/lib/screenerFilters.ts:52`

**Warren signal section** — 5

`backend/analysis/warren_signal/indicators.py:2`, `backend/crontab.txt:98`, `backend/pipeline/nightly_warren_signal_calculation.py:4`, `backend/pipeline/nightly_warren_signal_calculation.py:8` (i), `backend/pipeline/nightly_warren_signal_calculation.py:29`

**Chart tab entries / investigation notes** — 4

`backend/clients/shared_bars_cache.py:33`, `backend/data/chart_data.py:3`, `backend/data/chart_data.py:12`, `backend/data/chart_data.py:105` (i)

**Fork B scope decision** — 3

`frontend/components/screener/ValuationBadge.tsx:34`, `frontend/components/step3/ManualCalculationPanel.tsx:375`, `frontend/components/ticker/FairValuePill.tsx:47`

**Company classification: non-lender ticker overrides** — 3

`backend/scoring/classification.py:49`, `backend/scoring/classification.py:63` (i), `backend/tests/test_step5_data.py:543` (i)

**Bank classification requires genuine CET1/NPL-reporting capability** — 3

`backend/data/step5_data.py:49`, `backend/scoring/classification.py:41`, `backend/scoring/test_classification.py:160`

**Data groups** — 3

`backend/core/data_groups.py:16`, `backend/crontab.txt:27`, `bin/start.sh:102`

**technical entry-signal section** — 3

`backend/analysis/entry_signal/indicators.py:3`, `backend/core/models.py:308` (i), `backend/pipeline/nightly_entry_signal_calculation.py:5`

**Liquidity Zone** — 2

`backend/analysis/liquidity_zones/types.py:3`, `backend/pipeline/nightly_liquidity_zone_calculation.py:5`

**Ticker dot/hyphen normalization** — 2

`backend/core/tickers.py:5`, `backend/pipeline/merge_duplicate_ticker_identities.py:6`

**Momentum section** — 2

`backend/helpers/trading_calendar.py:6`, `backend/scoring/momentum.py:8`

**Analyst Ratings design-round / verdict-sentence entries** — 2

`frontend/lib/analystRatingsVerdict.test.ts:9`, `frontend/lib/analystRatingsVerdict.ts:150`

**design-system migration notes / "plan notes"** — 2

`frontend/app/globals.css:13` (i), `frontend/app/globals.css:60`

**Cron job heartbeat / health monitoring** — 1

`backend/.env.example:10`

**Shared bars cache** — 1

`backend/clients/shared_bars_cache.py:4` (i)

**Daily prices: FMP** — 1

`backend/clients/daily_bar_sources.py:20`

**Institutional Ownership entry** — 1

`backend/core/data_groups.py:111`

**"deferred-revenue/one-off precedent** — 1

`backend/helpers/ttm.py:9`

## Factually stale comments (not just mis-cited)

These are reported, not edited (a later, optional repointing pass can fix them along with the citations).

| Location | Why it is stale |
|---|---|
| `backend/scoring/trend.py:111-112` | Says `multiple_dips_resolved`/`dip_durably_resolved` are "still flat 75" and Margins' `gradually_compressing` is "still flat 60". Both were graduated later: `RESOLVED_CEILING = 75` / `RESOLVED_FLOOR = 65` (`trend.py:343`, the comment block at 311-342 says they "used to score a flat 75"), and `step1.py:183` says `gradually_compressing` "used to score a flat 60". See `docs/specs/financials.md`. |
| `backend/scoring/trend.py:111-116` (same comment, continued) | "held for later review" — the review happened and both were graduated. |
| `backend/scoring/trend.py:472-473` | "multiple_dips_resolved's 75 is untouched" — that value is now the graduated `RESOLVED_CEILING`, no longer a flat 75. |

# Documentation consolidation — migration plan

**Status: proposal only. Nothing has been moved, merged, or deleted yet.** This file is a
working document for the session that executes the plan — delete it once execution is done
and its contents are reflected in `docs/specs/`, `CLAUDE.md`, `docs/design-system.md`, and
`docs/design-system-charts.md`.

Audit date: 2026-09-29. No browser-based verification was used or needed — this is a static
read/classify pass over the repo plus targeted `grep`/`git log` cross-checks against the
actual codebase to tell "shipped feature, doc just never got folded in" apart from "proposal
that never happened."

---

## 0. Special / pinned files (not part of the docs/specs migration)

These are excluded from the docs/specs mapping below for structural reasons, not because
they're unimportant.

| File | Size | Verdict |
|---|---|---|
| `CLAUDE.md` | 328K | **(a) live, stays at repo root.** It's the auto-loaded instructions file — it can't be "moved." But it has accumulated a huge amount of exhaustive, changelog-style per-feature narrative (scoring-rubric tuning history, and full feature write-ups for Speculative Growth, Warren signal, Liquidity Zones, Shared bars cache, Phase 6a/6b provider removal, Screener ETF exclusion, company-classification overrides, delisted-ticker handling, cron heartbeat, Insider/Institutional Ownership shelving...) that structurally belongs in `docs/specs/<feature>.md` rather than the root instructions file. See §5 below — this is flagged as a distinct, larger follow-up, **not attempted in this pass** (rewriting/trimming 328K of auto-loaded content is a different, higher-risk job than migrating standalone files). |
| `backend/OPS_RUNBOOK.md` | 44K | **(a) live, stays.** Well-organized, ops-audience-appropriate, already at the right path. CLAUDE.md points to it by relative path in several places — moving it would break those references for no benefit. |
| `docs/decisions.md` | 8K | **(a) live, current.** The UI-redesign decision log this very audit's own instructions named as a merge destination. Untracked in git (`??` in status) — that's this session's own work-in-progress, not this audit's concern. |
| `docs/design-system.md` | 8K | **(a) live, current.** Same as above — a named merge destination, untracked, no action. |
| `docs/design-system-charts.md` | 8K | **(a) live, current.** Same. |
| `frontend/AGENTS.md` | 12K | **Excluded.** Auto-generated Next.js docs index (`<!-- NEXT-AGENTS-MD-START -->` marker, regenerable via `npx @next/codemod agents-md`). Not authored documentation. |
| `frontend/CLAUDE.md` | 4K (1 line) | **Excluded.** Just `@AGENTS.md` — an include pointer, not content. |
| `backend/.pytest_cache/README.md` | 4K | **Excluded.** pytest-generated cache artifact, same category as `node_modules` — should be gitignored. |
| `backend/crontab.txt` | 20K | **Excluded from doc classification** (it's a real config file consumed by `crontab`, not prose), though it's a living reference CLAUDE.md's cron sections point to constantly. No action. |
| `frontend/README.md` | 4K | **(c) low-priority delete candidate.** Generic, unedited `create-next-app` boilerplate — zero Fathom-specific content. Safe to delete or replace; very low stakes either way, included for completeness only. |

---

## 1. Full inventory + classification

51 documentation files were classified (the 4 files in §0 marked "Excluded" don't count
toward this). "Merge → X" in the Destination column means the content is real and should
survive, just not as its own file — see §3 for what actually lands where.

### 1a. Root-level technical scoring references (all `(a)`/`(b)` — merge into `docs/specs/`)

| File | Size | Last touched | Verdict |
|---|---|---|---|
| `debt.md` | 16K | 2026-08-13 | Live technical reference, accurate as written. → merges with `docs/debt.md`. |
| `financials.md` | 20K | 2026-08-13 | Live technical reference. → merges with `docs/financials.md`. |
| `growth.md` | 12K | 2026-08-13 | Live technical reference. → merges with `docs/growth-rate.md`. |
| `moat.md` | 4K | 2026-08-05 | Live technical reference, short and simple. → merges with `docs/economic-moat.md`. |
| `profitability.md` | 28K | 2026-08-13 | **Known stale point found**: its company-type exemption table (line ~31) still says "Revenue vs. Accounts Receivable — REIT/Property Developer only," but CLAUDE.md documents this was extended to Bank/Insurance/Utility on 2026-09-04. `docs/profitability.md` (the end-user copy) was actually updated for this and is *more* current on this one point. → merges with `docs/profitability.md`, needs this one correction during the merge. |
| `valuation.md` | 28K | 2026-08-12 | **Stale**: predates the 2026-09-14/15 changes documented in CLAUDE.md — the new standard (non-tangible) Price-to-Book method (`PRICE_TO_BOOK_STANDARD`, now the Bank/REIT default) and the negative-book-value-per-share guard (`bands_from_mean_sd` returning `None`) aren't in either version. → merges with `docs/valuation.md`, needs real content updates during the merge (not just a file move). |

### 1b. End-user documentation hub (`docs/`, cross-linked, `overview.md` is the index)

| File | Size | Last touched | Verdict |
|---|---|---|---|
| `docs/overview.md` | 8K | 2026-08-05 | Accurate — Overall Assessment weights (Financials 24/Growth 10/Profitability 20/Debt 15/Moat 31) match CLAUDE.md's current, rebalanced values. → `docs/specs/overview.md`. |
| `docs/glossary.md` | 4K | 2026-08-05 | Accurate, still matches current verdict-label semantics. → `docs/specs/glossary.md`. |
| `docs/company-type-variations.md` | 8K | 2026-09-04 | Accurate, current (already reflects the Bank/Insurance/Utility AR-exemption extension). → `docs/specs/company-type-variations.md`. Good future home for CLAUDE.md's "non-lender ticker overrides" and "Bank classification requires genuine CET1/NPL" tables too (see §5). |
| `docs/financials.md` | 4K | 2026-08-05 | End-user companion to root `financials.md`. → merges into `docs/specs/financials.md`. |
| `docs/growth-rate.md` | 4K | 2026-08-12 | End-user companion to root `growth.md`. → merges into `docs/specs/growth-rate.md`. |
| `docs/profitability.md` | 8K | 2026-09-04 | End-user companion, currently *more* up to date than the root technical file on the AR-exemption point (see 1a). → merges into `docs/specs/profitability.md`. |
| `docs/debt.md` | 8K | 2026-08-06 | End-user companion to root `debt.md`. Predates the 2026-08-13 severe-zone graduation, but that's a display-only scoring nuance the end-user doc doesn't need to restate in the same detail. → merges into `docs/specs/debt.md`. |
| `docs/economic-moat.md` | 4K | 2026-08-05 | End-user companion to root `moat.md`. → merges into `docs/specs/economic-moat.md`. |
| `docs/valuation.md` | 4K | 2026-08-08 | End-user companion to root `valuation.md`, same staleness caveat as 1a. → merges into `docs/specs/valuation.md`. |

### 1c. CLAUDE.md merge candidate

| File | Size | Verdict |
|---|---|---|
| `docs/claude-md-additions.md` | 4K | Untracked. A literal "proposed CLAUDE.md addition" — its own header says so. Three genuinely new Workflow-rules bullets (no-browser-verification-after-a-code-change, clean-up-after-yourself, and a pointer to design-system.md/design-system-charts.md/decisions.md) that aren't in CLAUDE.md's current "Workflow rules" section yet. **(b) merge into CLAUDE.md's existing "Workflow rules" section, then delete this file.** |

### 1d. One-off ops/incident logs — all `(c)`, safe to delete

| File | Size | Verdict |
|---|---|---|
| `docs/aapl_technical_tab_stale_row_investigation_2026-09-13.md` | 12K | Resolved transient staleness bug, self-healed same day. The general mechanism (`_add_missing_columns` has no backfill) is already documented generically in CLAUDE.md in many places. No ongoing-relevant content. |
| `docs/cron_audit_2026-09.md` | 20K | Phase 1/2 of a cron audit from 2026-09-11; "Awaiting go-ahead for Phase 3" that never formally happened — superseded piecemeal by later specific fixes. The job list it audited has grown substantially since (Sector Heatmap, Market Breadth, Warren, Liquidity Zones all added after). OPS_RUNBOOK.md + CLAUDE.md are the current sources of truth. |
| `docs/crontab_warren_backup_fix_2026-09-13.md` | 8K | One-time crontab-reinstall fix, action log of a completed fix. Nothing ongoing. |
| `docs/trend_analysis_backfill_and_crontab_drift_2026-09-13.md` | 16K | One-time forced-recompute + investigation, completed and closed out same day. |
| `docs/market_breadth_failure_2026-09-23.md` | 12K | One-off incident (a Yahoo-side data delay causing one missing breadth row). Root cause is moot — Yahoo was removed from the codebase entirely in Phase 6b (2026-09-26). |
| `docs/price_target_trend_signal_investigation_2026-09-22.md` | 24K | Explicitly superseded — `price_target_signal_conclusion_2026-09-25.md`'s own header says it "replaces [this] as the reference." |
| `docs/price_target_daily_refresh_feasibility_2026-09-26.md` | 16K | Feasibility study for a change that was then implemented; fully superseded by `price_target_daily_snapshot_implementation_2026-09-26.md`, which CLAUDE.md cites directly instead of this one. |
| `docs/fmp_migration_and_toggles_investigation_2026-09-24.md` | 40K | Phase-0 planning doc for the FMP price-data migration. All phases it scoped (P1–P6b) are now complete and documented in CLAUDE.md's own Phase sections; its "Open questions" are all resolved (in some cases differently than it recommended — e.g. it suggested keeping one dormant Yahoo fallback "for a quarter," but Phase 6b deleted Yahoo outright). Historical only. |

### 1e. Feature docs that are live, shipped, and **not documented anywhere else** — merge into `docs/specs/`

These are the most important finds of this audit: standalone investigation docs describing
features that are actually live in the codebase (confirmed via `grep`/`git log`, not assumed),
but that CLAUDE.md's otherwise-exhaustive narrative never mentions, or mentions only in
passing without the mechanism. Deleting these without migrating them would be a real loss.

| File | Size | Verdict |
|---|---|---|
| `docs/pullback_history_investigation_2026-09-13.md` | 20K | Investigation proposing `trend_started`/`pullback_history` tracking for the Technical tab's Pullback-recovery card. **Confirmed shipped**: `pullback_history`/`flip_swing` are real fields in `state_machine.py`, `core/models.py`, `core/schemas.py`, consumed by `frontend/components/technical/TrendContinuationCard.tsx`. CLAUDE.md never explains this mechanism. → `docs/specs/trend-structure-technical.md`. |
| `docs/reversal_history_investigation_2026-09-13.md` | 16K | Follow-up investigation, same pattern applied to `ReversalCard.tsx` (`reversal_history`). **Confirmed shipped** (same grep). → `docs/specs/trend-structure-technical.md`. |
| `docs/weinstein_daily_timeframe_investigation_2026-09-22.md` | 16K | Proposal for a daily-timeframe Weinstein variant alongside the shipped weekly one. **Not shipped** (no code found) — kept as a live, still-open proposal, not stale. → `docs/specs/weinstein-stage.md`, flagged "proposed, not built." |
| `docs/weinstein_pending_confirmation_investigation_2026-09-22.md` | 28K | Design proposal for "pending confirmation + ETA." **Confirmed shipped**: `backend/analysis/trend_structure/weinstein_pending.py` exists and is exactly what CLAUDE.md's "Engine swap" section calls "Flip-ETA/pending (`weinstein_pending.py`)" — CLAUDE.md never explains the *why* (thin-cushion/long-ETA divergence reasoning) that this doc has. → `docs/specs/weinstein-stage.md`. |
| `docs/sector_breadth_investigation_2026-09-22.md` | 24K | Feasibility study for extending Market Breadth to per-sector view, "nothing implemented" at the time it was written. **Confirmed shipped since**: `git log` shows "Sector-level market breadth (backend)" (`7c63d87`) and "(frontend)" (`aedf1e3`) commits, and `frontend/components/breadth/BreadthSectorView.tsx` exists. **CLAUDE.md's "Market Breadth" section does not mention this feature at all** — a real documentation gap. → `docs/specs/market-breadth.md`. |

### 1f. Feature docs cited directly by CLAUDE.md — live, merge into `docs/specs/`

CLAUDE.md explicitly points to these by path ("Details: `docs/...`", "Plan/decisions:
`docs/...`") as the deep-detail companion to its own summary. All still accurate.

| File | Size | Verdict → destination |
|---|---|---|
| `docs/chart_tab_missing_bar_investigation_2026-09-18.md` | 12K | → `docs/specs/fmp-data-and-bar-cache.md` |
| `docs/fmp_phase2_daily_prices_plan_2026-09-24.md` | 8K | → `docs/specs/fmp-data-and-bar-cache.md` |
| `docs/fmp_phase3_long_history_non_us_investigation_2026-09-25.md` | 32K | → `docs/specs/fmp-data-and-bar-cache.md`. **Partial staleness**: its non-US sections (routing, phantom-bar filter) describe support that was fully removed in the Phase 6a follow-up (2026-09-26) — merge only the still-live long-history/W_4Y mechanism, drop the non-US-specific parts as historical. |
| `docs/market_breadth_investigation_2026-09-21.md` | 16K | → `docs/specs/market-breadth.md` |
| `docs/stochastic_divergence_investigation_2026-09-25.md` | 12K | → `docs/specs/chart-indicators.md` (new) |
| `docs/price_target_daily_snapshot_implementation_2026-09-26.md` | 20K | → `docs/specs/price-target.md` |
| `docs/etf_heatmap_momentum_investigation_2026-09-20.md` | 24K | → `docs/specs/sector-heatmap.md` |

### 1g. Other live/current feature docs — merge into `docs/specs/`

| File | Size | Verdict |
|---|---|---|
| `docs/price_target_trend_sept_gap_investigation_2026-09-25.md` | 16K | Real, still-relevant findings (legacy/live methodology split, several "not investigated / decision points" that appear to still be open — recency cutoff, cron catch-up, health-check gap). → `docs/specs/price-target.md`. |
| `docs/price_target_signal_conclusion_2026-09-25.md` | 16K | The authoritative conclusion: price-vs-analyst-target gap is **not a viable signal** (no out-of-sample edge). This is the definitive answer, not a superseded step. → `docs/specs/price-target.md`. |
| `docs/market_breadth_live_marker_investigation_2026-09-27.md` | 8K | Diagnosis-only, ends with three open decision points and "no fix made" — still an open item as far as the file record shows. → `docs/specs/market-breadth.md`, carried forward as "open items." |
| `docs/sector_heatmap_tradingview_divergence_investigation_2026-09-25.md` | 4K | Concludes "no bug," and flags an incidental doc-drift finding of its own: **CLAUDE.md's Sector Heatmap section still says "Yahoo-only, `Adj Close` total return, 7 windows"; actual current behavior is FMP-sourced, plain split-adjusted close, 8 windows.** → `docs/specs/sector-heatmap.md`, and this doc-drift note should specifically inform the CLAUDE.md trim in §5. |
| `docs/fmp_endpoint_inventory_2026-09-27.md` | 24K | Ground-truth endpoint→tier audit, recent (2 days old) and explicitly says "no relayout proposed." → `docs/specs/fmp-data-and-bar-cache.md`. |
| `docs/fmp_extended_hours_feasibility_2026-09-24.md` | 16K | Feasibility test for a feature that is **still unbuilt** (per user memory: "P5 extended hours unbuilt") — not stale, it's the reference for if/when that gets built. → `docs/specs/fmp-data-and-bar-cache.md`, flagged "feasibility confirmed, not yet built." |

### 1h. Design-system audit input — `(b)`, merges into the existing design docs (not `docs/specs/`)

| File | Size | Verdict |
|---|---|---|
| `docs/frontend_chart_table_audit_2026-09-28.md` | 48K | Explicitly "done to inform a chart/table spec for the new design system" — raw research behind the already-created `docs/design-system-charts.md`. Most of it is likely already absorbed there; worth a diff-check during execution to confirm nothing was missed. **Two incidental product bugs it found are not design-system content** and should be flagged as their own follow-up instead of folded into a docs merge: (1) Sector Heatmap's page footnote says "total return, price change plus reinvested distributions," contradicting the actual price-only/dividend-excluded computation; (2) Growth Rate (Step 2) has no chart/table in the frontend at all despite full backend data existing for it. → merge remaining un-migrated content into `docs/design-system-charts.md` / `docs/design-system.md`, then delete. |

### 1i. Uncertain — do not delete, decide with the user first

| File | Size | Why uncertain |
|---|---|---|
| `docs/etf_held_by_investigation_2026-09-20.md` | 20K | "Round 1" investigation for an ETF "Held by" section on stock ticker pages. **No shipped code found** (`grep` for `held_by`/`heldBy`/`etf_holders` across frontend and backend returns nothing). Explicitly scoped as "Round 1" of a 3-round plan (Round 2 = ETF ticker page, Round 3 = market dashboard). Can't tell from the file alone whether this was deliberately shelved in favor of the simpler "exclude ETFs from Screener" approach that shipped the same day (2026-09-20, see CLAUDE.md's "Screener excludes ETFs" section), or is still pending a later round. |
| `docs/etf_ticker_page_investigation_2026-09-20.md` | 28K | "Round 2" companion to the above — a minimal ETF-specific ticker page. Same evidence: no shipped code found (`is_etf`/`isEtf` is only used for Screener filtering, nowhere else). Same uncertainty about whether this is shelved or deferred. |

---

## 2. Cross-check against `docs/decisions.md` / `docs/design-system.md`

Done — nothing in the classification above proposes re-creating content that already lives in
either file. `docs/frontend_chart_table_audit_2026-09-28.md` (§1h) is the one file whose
content plausibly already migrated into `docs/design-system-charts.md`; that needs confirming
by diff during execution, not assuming either way.

---

## 3. Proposed `docs/specs/` structure

One file per feature/system. Numbers in parens are how many source files feed each one.

| New file | Feeds from | What it covers |
|---|---|---|
| `docs/specs/overview.md` | 1 | How the 4 automated checks + Economic Moat blend into Overall Assessment; incomplete-vs-not-supported handling; Valuation's independence. |
| `docs/specs/glossary.md` | 1 | Verdict-label definitions (Fail/Pass/Strong Pass/Pass with caution/Insufficient data/Not supported). |
| `docs/specs/company-type-variations.md` | 1 | Which checks apply/don't apply per company type (Standard/Bank/Insurance/REIT/Utility/Commodity), at a glance. |
| `docs/specs/financials.md` | 2 | Financials check: weights, data window, trend classification, exemptions, end-user explanation + full technical formula reference. |
| `docs/specs/growth-rate.md` | 2 | Growth Rate check: analyst-estimate methodology, EPS/revenue basis, magnitude/agreement scoring. |
| `docs/specs/profitability.md` | 2 | Profitability check: ROE/ROIC, Revenue-vs-AR, CCC, company-type exemptions (needs the AR-exemption table corrected during merge — see 1a). |
| `docs/specs/debt.md` | 2 | Debt check: the 3 standard ratios, Bank/REIT variants, breach-context rescue framework. |
| `docs/specs/economic-moat.md` | 2 | Economic Moat: the manual rating and its fixed point values. |
| `docs/specs/valuation.md` | 2 | Valuation methods (DCF/DDM/P-B/PSG), method-selection tree (needs the standard-P/B-method and negative-book-value-guard updates during merge — see 1a). |
| `docs/specs/trend-structure-technical.md` | 2 | Swing/BOS/A-D-divergence/SMA engine's `pullback_history`/`reversal_history`/`trend_started` mechanism — currently undocumented outside these two files. (CLAUDE.md's own "Trend structure analysis" section is a good future addition here too, see §5.) |
| `docs/specs/weinstein-stage.md` | 2 | Weinstein Stage engine: the shipped `weinstein_pending.py` ETA/pending-confirmation mechanism and its design rationale, plus the still-open daily-timeframe-variant proposal. |
| `docs/specs/sector-heatmap.md` | 3 | Sector Heatmap ETF-return feature: methodology, the TradingView-divergence non-bug finding, and the doc-drift note about CLAUDE.md's stale Yahoo/Adj-Close/7-window description. |
| `docs/specs/market-breadth.md` | 4 | Market Breadth (20/50/200-day SMA %, net new highs/lows): methodology, the sector-level breadth extension (currently undocumented in CLAUDE.md), and the still-open "Live →" marker labeling question. |
| `docs/specs/price-target.md` | 3 | Price-target signal research conclusion (not viable, shelved), the daily-snapshot-with-methodology-labeling implementation, and the legacy/live methodology-split gap investigation. |
| `docs/specs/fmp-data-and-bar-cache.md` | 5 | FMP data-group endpoint/tier ground truth, the daily-bar staleness/cache-key bugs and their fixes, the long-history (Phase 3) mechanism, and the still-unbuilt extended-hours feasibility finding. |
| `docs/specs/chart-indicators.md` | 1 | Chart-tab technical indicator implementation notes (Stochastic 5/3/3 EMA ThinkOrSwim parity) — a natural home for similar future indicator-parity write-ups too. |

That's **16 new files**, absorbing **35 source files** (6 root + 9 docs-hub-and-companions +
20 investigation docs from §1e/1f/1g), plus 2 files (`docs/claude-md-additions.md`,
`docs/frontend_chart_table_audit_2026-09-28.md`) merging into existing docs instead
(CLAUDE.md and design-system-charts.md/design-system.md respectively).

---

## 4. Deletion list (exactly what, one line each)

1. `docs/aapl_technical_tab_stale_row_investigation_2026-09-13.md` — resolved, self-healed transient bug; generic mechanism already documented elsewhere.
2. `docs/cron_audit_2026-09.md` — Phase-1/2-only audit of a job list that's since grown substantially; Phase 3 never formalized.
3. `docs/crontab_warren_backup_fix_2026-09-13.md` — one-time completed fix, action log only.
4. `docs/trend_analysis_backfill_and_crontab_drift_2026-09-13.md` — one-time completed backfill/fix, action log only.
5. `docs/market_breadth_failure_2026-09-23.md` — root cause (Yahoo data lag) is moot; Yahoo fully removed in Phase 6b.
6. `docs/price_target_trend_signal_investigation_2026-09-22.md` — explicitly superseded by `price_target_signal_conclusion_2026-09-25.md`.
7. `docs/price_target_daily_refresh_feasibility_2026-09-26.md` — superseded by `price_target_daily_snapshot_implementation_2026-09-26.md`.
8. `docs/fmp_migration_and_toggles_investigation_2026-09-24.md` — Phase-0 plan; all phases complete and documented in CLAUDE.md.
9. `docs/claude-md-additions.md` — **delete only after** its 3 bullets are merged into CLAUDE.md's Workflow rules section (see 1c) — not an immediate delete.
10. `frontend/README.md` — generic, unedited boilerplate (low priority, §0).

This migration-plan file itself (`docs/_migration-plan.md`) should also be deleted once the
plan above is executed.

---

## 5. Not part of this file-migration pass, but worth flagging

CLAUDE.md contains full, exhaustive narrative sections for several live features that have
**no standalone source file at all** — they exist only inside CLAUDE.md's 328K of prose. Since
this audit is file-driven, they don't appear in the tables above, but they're the most obvious
next candidates for extraction into their own `docs/specs/<feature>.md` in a **separate,
dedicated follow-up session** (rewriting/trimming the auto-loaded instructions file is a
different kind of risk than moving standalone files, and shouldn't be bundled into this pass):

- Speculative Growth (classification lens)
- Warren RSI/ADX/WVF entry signal
- Liquidity Zone (LP) detection
- Shared bars cache (mechanism + retention/pruning)
- Delisted-ticker handling
- Phase 6a/6b FMP-only provider migration (Massive/Yahoo removal, non-US cleanup)
- Screener ETF exclusion
- Company classification: non-lender ticker overrides + Bank CET1/NPL genuine-lender
  reclassification (natural fit inside `docs/specs/company-type-variations.md` once that
  extraction happens)
- Insider Activity (deleted) / Institutional Ownership (shelved) — historical record of two
  shelved features
- Cron job heartbeat / health monitoring
- The scoring-rubric tuning history for Financials/Growth Rate/Debt/Profitability/Overall
  Assessment weighting (natural fit as the "history" section of each corresponding
  `docs/specs/<feature>.md` created in this pass)

This is a list to work from, not a commitment — sizing and sequencing that follow-up is a
separate decision.

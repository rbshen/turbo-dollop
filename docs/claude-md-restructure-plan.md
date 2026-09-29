# CLAUDE.md restructure plan (audit only)

**Status: Phase A (audit) only. `CLAUDE.md` was not modified.** This document is the plan
Phase B (a later session) will execute. All char/line splits within a heading are **estimates**
from reading the section, not a mechanical diff — Phase B must re-read each bullet before
moving it, per the "Open questions" section at the end.

## 1. Summary

| | Lines | Chars (unicode, incl. trailing newline) |
|---|---|---|
| **CLAUDE.md today** | 4,316 | 333,459 |
| **CLAUDE.md projected after restructure** | ~290 | ~21,500 |
| Moved to `docs/specs/*.md` (merged into existing files + a few new ones) | ~2,050 | ~153,500 |
| Moved to `docs/archive/*.md` (new, split into ~4 topic files) | ~1,830 | ~156,500 |
| Deleted outright (pure duplicates / superseded, no destination) | ~150 | ~4,150 |

Projected CLAUDE.md (~21.5k chars) comfortably clears the ~25k-char / 300-line target, with
headroom for the pointer sentences Step 3 lists.

**Why the split is so lopsided toward SPEC+ARCHIVE**: `CLAUDE.md` is not really one document —
it's a running engineering log. Roughly 80% of its content is dated, narrative "here's what we
investigated, what we found, what we changed, and the before/after ticker counts that proved it"
writing. That style is exactly right for a decision record, wrong for a file reloaded into every
session's context. The KEEP list is deliberately narrow: build/run commands, repo layout,
cross-cutting mechanisms every feature touches (data groups, the W1-W5 watchlist pattern, the
cache-contamination guard, cron heartbeat wiring), and the four standing workflow rules.

## 2. Section table

One row per top-level (`##`) heading in file order, plus sub-rows for `###` subsections that need
a different treatment than their parent. "Reason" is abbreviated; full reasoning is in §7 for the
non-obvious calls.

| Heading | Lines | Chars (unicode, incl. trailing newline) | Category | Destination | Reason |
|---|---|---|---|---|---|
| `# CLAUDE.md — Fathom` (title) | 1-2 | 22 | KEEP | — | trivial |
| What this is | 3-17 | 816 | KEEP | — | mission statement, needed every session |
| Tech stack | 18-28 | 555 | KEEP | — | build-tooling facts |
| Running the app | 29-38 | 481 | KEEP | — | commands |
| Folder layout | 39-117 | 4,869 | KEEP | — | navigation, needed every session |
| Data source | 118-126 | 526 | KEEP | — | short, cross-cutting (FMP is sole source) |
| Watchlists | 127-145 | 1,047 | KEEP | — | short; W1-W5 pattern is referenced by ~6 other sections |
| Caching policy (intro) | 146-156 | 537 | KEEP | — | short |
| — Data groups: pausing FMP | 157-256 | 7,689 | KEEP | — | cross-cutting gate every FMP call site goes through; large but load-bearing every session code touches FMP |
| — Ad-hoc repro scripts must not touch real DB | 257-375 | 7,588 | **split** | KEEP (~900c, the rule itself) / ARCHIVE (~6,700c, the two incident narratives) | the rule ("fresh in-memory engine + monkeypatch every module's `engine` ref before calling get_stepN_data") is a standing gotcha; the PEP/ACME incident play-by-play is history |
| Cron job heartbeat / health monitoring | 376-445 | 4,425 | **split** | KEEP (~900c: "new job needs `cron_heartbeat` + `CRON_JOB_NAMES` + `_EXPECTED_CADENCE_HOURS` or it ships unmonitored, enforced by `test_cron_wiring.py`") / DELETE (~1,500c, duplicates OPS_RUNBOOK.md's own "Cron job heartbeat" section, confirmed present there) / ARCHIVE (~2,000c, the FMP_ENABLED-interaction investigation and the `nightly_price_target_snapshot` guard-parity fix) | OPS_RUNBOOK.md line 475 already has a "Cron job heartbeat / health monitoring" section covering full mechanism |
| **Scoring rubric notes** (Financials/Growth/Debt/Profitability/Overall weighting) | 446-1,613 | 79,860 | **split, large** | SPEC (~32,400c) → merge into `docs/specs/financials.md`, `growth-rate.md`, `debt.md`, `profitability.md`, `overview.md` (all already exist) / ARCHIVE (~47,000c) → `docs/archive/claude-md-history-scoring.md` | see §7.1 — specs already cover current thresholds for most named constants; the "confirmed via full-universe recompute: N tickers changed, 0 regressions" validation narratives are what's left over and are archive material |
| — Analysis tab section-card reasoning (2026-09-05) | 1,614-1,720 | 6,990 | ARCHIVE | `docs/archive/claude-md-history-features.md` | one-time UI fix narrative (verdict-sentence bug, `weightScoreSuffix` helper); the resulting behavior is self-documenting in the component code, no spec depends on this text |
| Company classification: non-lender ticker overrides | 1,721-1,802 | 5,862 | **split** | SPEC (~3,500c, the two tables) → `docs/specs/company-type-variations.md` / ARCHIVE (~2,360c, narrative) → `claude-md-history-features.md` | `company-type-variations.md:18` already says "see `CLAUDE.md`'s ... section" — the spec currently *depends on* CLAUDE.md holding this table; that's backwards and should be fixed by moving the table in |
| — Bank classification requires genuine CET1/NPL capability (2026-09-05) | 1,803-1,901 | 6,561 | **split** | SPEC (~2,500c, the final tickers-and-tags outcome) → `company-type-variations.md` / ARCHIVE (~4,060c, the HSBC/MTB tag-hunting investigation) → `claude-md-history-features.md` | same reasoning as above; `debt.md:58,263` also point back to this CLAUDE.md section |
| Screener excludes ETFs (2026-09-20) | 1,902-1,944 | 2,686 | SPEC | fold into `docs/specs/overview.md` (Screener is introduced there) | short, current mechanism, no narrative bloat, no existing home |
| **Valuation (Step 3) scoring notes** | 1,945-2,272 | 24,873 | **split** | SPEC (~9,950c) → merge into `docs/specs/valuation.md` (already 21.5k chars, already covers `CF_NORMALIZED`/`PRICE_TO_BOOK_STANDARD`) / ARCHIVE (~14,920c) → `claude-md-history-scoring.md` | see §7.1 |
| Speculative Growth scoring notes | 2,273-2,315 | 3,652 | SPEC | new `docs/specs/speculative-growth.md` | no existing spec file covers this lens at all |
| **Trend structure analysis (Technical)** | 2,316-2,662 | 31,971 | **split, mostly SPEC** | SPEC (~19,200c) → `docs/specs/trend-structure-technical.md` (expand it — see below) / ARCHIVE (~12,800c) | `trend-structure-technical.md`'s own text says "See `CLAUDE.md`'s ... section for the full ... mechanism, which this document does not repeat" — the spec is *intentionally* thin today and expects this content to land there; more of this section is durable mechanism than in the scoring-rubric sections above, hence the higher SPEC share |
| **Liquidity Zone (LP) detection (Technical)** (main body) | 2,663-2,779 | 9,603 | SPEC | new `docs/specs/liquidity-zones.md` | no existing spec file; nothing to merge into |
| — Shared FMP daily-bar cache: staleness/cache-key bug (2026-09-16) | 2,780-2,823 | 3,256 | **split** | SPEC nugget (~450c, "cache key must include lookback_years") → `docs/specs/fmp-data-and-bar-cache.md` / ARCHIVE (~2,800c) → `claude-md-history-technical-signals.md` | bug-fix narrative, superseded facts, but the rule itself is worth keeping in the ground-truth cache doc |
| — Chart Stochastic: 5/3/3 EMA, ThinkOrSwim parity (2026-09-25) | 2,824-2,837 | 1,131 | **DELETE** | — | verbatim duplicate: `docs/specs/chart-indicators.md` already has a full "Full Stochastic (5, 3, 3): SMA → EMA, ThinkOrSwim parity" section covering this exact fix |
| — Chart tab reverted to zero-cache on-demand fetch (2026-09-18) | 2,838-2,868 | 2,465 | SPEC | new `docs/specs/chart-tab.md` | describes **current** Chart-tab fetch behavior (still true post-Phase 6b), not just a fix record |
| — Liquidity Zone nightly job: market-close-aware fix (2026-09-18) | 2,869-2,925 | 4,678 | **split** | SPEC nugget (~900c) → `liquidity-zones.md` / ARCHIVE (~3,800c) → `claude-md-history-technical-signals.md` | |
| — Main/Secondary watchlist rename + staleness sweep (2026-09-09) | 2,926-2,982 | 4,231 | ARCHIVE | `claude-md-history-technical-signals.md` | self-labeled: "Superseded 2026-09-11 ... Kept below as a historical record" |
| — Most-recently-breached LP level tracking (2026-09-17) | 2,983-3,073 | 7,210 | **split** | SPEC (~4,500c, the two-filter rule + storage) → `liquidity-zones.md` / ARCHIVE (~2,700c, tie-break investigation) → `claude-md-history-technical-signals.md` | |
| — Chart tab earnings/dividend markers (2026-09-20) | 3,074-3,157 | 7,481 | SPEC | new `docs/specs/chart-tab.md` | current mechanism, no existing home |
| Price-target snapshot: daily + methodology (2026-09-26) | 3,158-3,168 | 1,515 | **DELETE** | — | verbatim duplicate: `docs/specs/price-target.md:73-74` already states the identical facts (daily 02:10 job rename, `price_target_consensus` cache, `legacy_all_analysts` tag) almost word-for-word |
| **Warren RSI/ADX/WVF entry signal (2h)** | 3,169-3,439 | 23,322 | **split** | SPEC (~12,800c) → new `docs/specs/warren-signal.md` / ARCHIVE (~10,500c) → `claude-md-history-technical-signals.md` | no existing spec file for Warren at all; the "Measured, not assumed" perf-investigation and warm-up-buffer-derivation subsections are history, the state-machine/storage/cron mechanism is durable reference |
| Shared bars cache (2026-09-19) | 3,440-3,543 | 9,383 | SPEC | merge into `docs/specs/fmp-data-and-bar-cache.md` | that spec's own intro says it's "the ground-truth reference for ... the daily-bar caching mechanism," i.e. exactly this content's intended home |
| Daily prices: FMP (Phase 2) | 3,544-3,598 | 5,303 | **split** | SPEC (~3,000c) → `fmp-data-and-bar-cache.md` / ARCHIVE (~2,300c, backfill run log / parity numbers) → `claude-md-history-fmp-migration.md` | |
| Daily prices: FMP, Phase 3 (long history) | 3,599-3,637 | 3,774 | **split** | SPEC (~2,500c) → `fmp-data-and-bar-cache.md` / ARCHIVE (~1,270c) → `claude-md-history-fmp-migration.md` | |
| Intraday bars: FMP, Phase 4 | 3,638-3,671 | 3,054 | **split** | SPEC (~2,200c) → `fmp-data-and-bar-cache.md` / ARCHIVE (~850c) → `claude-md-history-fmp-migration.md` | |
| Phase 6a follow-up: corporate-events/non-US removal | 3,672-3,703 | 3,020 | **split** | SPEC (~1,500c, corporate-events upsert/retention mechanism) → new `docs/specs/corporate-events.md` or fold into `fmp-data-and-bar-cache.md` / ARCHIVE (~1,520c) → `claude-md-history-fmp-migration.md` | |
| Sector Heatmap (`/sectors`) | 3,704-3,766 | 5,745 | SPEC | merge into `docs/specs/sector-heatmap.md` (already exists, already points back here) | **also fix the window-count contradiction while merging — see §6** |
| Market Breadth (`/breadth`) | 3,767-3,901 | 12,421 | **split** | SPEC (~10,000c) → merge into `docs/specs/market-breadth.md` (already exists) / ARCHIVE (~2,420c, the "verified without a browser" test-run details) → `claude-md-history-fmp-migration.md` | |
| Delisted-ticker handling (2026-09-23) | 3,902-3,918 | 1,343 | SPEC | fold into `fmp-data-and-bar-cache.md` | short, current, cross-cutting for all bar jobs |
| Phase 6a: Massive removed | 3,919-3,965 | 4,644 | ARCHIVE | `claude-md-history-fmp-migration.md` | self-labeled removal record; current-state facts already live in "Data source"/"Data groups" (KEEP) |
| Phase 6b: Yahoo Finance removed entirely | 3,966-4,036 | 6,155 | ARCHIVE | `claude-md-history-fmp-migration.md` | self-labeled: "this section is the record of the removal" |
| Non-US cleanup (2026-09-26) | 4,037-4,064 | 2,833 | **split** | SPEC nugget (~1,200c: US-listed-only, `is_us_listed`, kept FX conversion) → `company-type-variations.md` / ARCHIVE (~1,630c, cleanup run record) → `claude-md-history-fmp-migration.md` | |
| Insider Activity — FULLY DELETED 2026-09-27 | 4,065-4,200 | 9,610 | ARCHIVE | `claude-md-history-features.md` | self-labeled: "Kept below as a historical record ... not as current instructions"; no revivable code left in the tree |
| Institutional Ownership — SHELVED 2026-09-27 | 4,201-4,298 | 8,291 | SPEC | new `docs/specs/institutional-ownership.md` | **not** deleted — code + tests live in the tree, one config flip revives it; this is a real, if-inactive, feature reference, not history |
| Workflow rules | 4,299-4,316 | 946 | KEEP | — | the four standing rules |

## 3. Proposed new `CLAUDE.md` outline

```
# CLAUDE.md — Fathom

## What this is
## Tech stack
## Running the app
## Folder layout
## Data source
## Watchlists
## Caching policy
  ### Data groups: pausing FMP (per-group toggles)
  ### Ad-hoc reproduction scripts must not touch the real database   (rule only)
## Cron job heartbeat / health monitoring                             (gotcha only)
## Company classification                                             (one-line pointer, see below)
## Workflow rules
```

KEEP items retained verbatim (see §2 for exact text/line ranges): title, What this is, Tech
stack, Running the app, Folder layout, Data source, Watchlists, Caching policy intro, Data
groups (full), the ad-hoc-repro-script *rule* (not the incident story), the cron-heartbeat
*gotcha* (not the mechanism explanation or incident stories), Workflow rules.

Exact pointer sentences to add (plain paths, not `@imports` — `@imports` still auto-load and
would defeat the whole point):

- Under Caching policy / Data groups: `For the exact FMP endpoint→group and cache-key→group
  mappings, see docs/specs/fmp-data-and-bar-cache.md.`
- Under Ad-hoc reproduction scripts rule: `For the full incident history behind this rule, see
  docs/archive/claude-md-history-features.md.`
- Under Cron job heartbeat: `For the full mechanism, exact cadence windows, and past incidents,
  see backend/OPS_RUNBOOK.md's "Cron job heartbeat / health monitoring" section and
  docs/archive/claude-md-history-features.md.`
- New short section, "Where feature/methodology detail lives": `Scoring methodology (Financials,
  Growth Rate, Debt, Profitability, Valuation, company-type variations, Speculative Growth) is in
  docs/specs/*.md — see docs/specs/overview.md for the index. Technical-analysis lenses (Trend
  structure, Liquidity Zones, Warren signal, Weinstein Stage, Sector Heatmap, Market Breadth,
  Chart tab) are in docs/specs/*.md. Completed migrations, resolved incidents, and shelved/deleted
  features are in docs/archive/claude-md-history-*.md.`
- Workflow rules already ends with a pointer sentence to `docs/design-system.md` etc. — extend
  that same sentence to also name `docs/specs/` and `docs/archive/`.

This outline is ~40 headings shorter than today's 44 top-level/sub headings, and every
methodology/feature-specific heading is gone from the auto-loaded file.

## 4. Proposed `docs/specs/` and `docs/archive/` layout

### `docs/specs/` — existing files receiving merges

| File | Current size | + merged content (est.) | Projected size |
|---|---|---|---|
| `financials.md` | 19,469c | +12,700c | ~32,200c |
| `growth-rate.md` | 8,960c | +3,400c | ~12,400c |
| `debt.md` | 13,873c | +5,500c | ~19,400c |
| `profitability.md` | 19,556c | +9,300c | ~28,900c |
| `overview.md` | 6,764c | +1,500c (Overall weighting) +2,686c (ETF exclusion) | ~11,000c |
| `valuation.md` | 21,573c | +9,950c | ~31,500c |
| `company-type-variations.md` | 7,229c | +3,500c +2,500c +1,200c | ~14,400c |
| `trend-structure-technical.md` | 10,288c | +19,200c | ~29,500c |
| `fmp-data-and-bar-cache.md` | 20,467c | +9,383c +3,000c +2,500c +2,200c +1,500c +1,343c +450c +900c | ~41,700c |
| `sector-heatmap.md` | 7,925c | +5,745c | ~13,700c |
| `market-breadth.md` | 11,366c | +10,000c | ~21,400c |
| `chart-indicators.md` | 6,162c | (no merge — CLAUDE.md's copy is deleted, not merged) | unchanged |

### `docs/specs/` — new files

| File | Content | Est. size |
|---|---|---|
| `speculative-growth.md` | Speculative Growth lens | ~3,650c |
| `liquidity-zones.md` | LZ engine, settings, cron, breach/broken-zone tracking | ~13,650c |
| `warren-signal.md` | Warren RSI/ADX/WVF state machine, storage, cron, API | ~12,800c |
| `chart-tab.md` | Zero-cache fetch behavior, earnings/dividend markers | ~9,950c |
| `institutional-ownership.md` | Shelved-but-live feature reference | ~8,290c |
| `corporate-events.md` (or fold into `fmp-data-and-bar-cache.md` — open question, see §7) | CorporateEvent upsert/retention/splits cadence | ~1,500c |

### `docs/archive/` — new, split by topic (per Step 4's "split into a few topic files if large")

| File | Content | Est. size |
|---|---|---|
| `claude-md-history-scoring.md` | Financials/Growth/Debt/Profitability/Overall-weighting investigation narratives (the "confirmed via full-universe recompute" write-ups) | ~47,000c |
| `claude-md-history-technical-signals.md` | Trend structure / Liquidity Zone / Warren investigation narratives, the staleness-window and market-close-aware bug histories, the watchlist-rename history | ~40,000c |
| `claude-md-history-fmp-migration.md` | Phase 2/3/4/6a/6b (Massive removal, Yahoo removal, non-US removal, daily-bar backfills, parity checks, cleanup run logs) | ~30,000c |
| `claude-md-history-features.md` | Insider Activity (deleted), Analysis-tab-reasoning fix, Company-classification investigation, ad-hoc-repro-script incidents, cron-heartbeat incidents | ~39,500c |

## 5. Other auto-loaded files — do they need trimming?

- **`frontend/CLAUDE.md`** (11 chars: `@AGENTS.md`) → imports `frontend/AGENTS.md` (8,380 chars).
  That file is a vendor-generated Next.js docs index (`exported SGML document`, regenerated by
  `npx @next/codemod agents-md`), not user-authored. It only loads when working under
  `frontend/`, is well under any size limit on its own, and isn't part of this restructure's
  scope — flagging it here per the task's Step 1 instruction, no action proposed.
- No `~/.claude/CLAUDE.md`, no `CLAUDE.local.md`, no `.claude/CLAUDE.md`, no `.claude/rules/`
  directory, no other subdirectory `CLAUDE.md` files exist in this repo.
- `CLAUDE.md` itself contains **zero `@path` imports** (confirmed via grep) — nothing recursive
  to follow.

## 6. Red flags

**Secrets**: none found. Targeted regex passes for key/token/secret/password patterns and common
credential shapes (`sk-...`, `AKIA...`, `ghp_...`, `xox[bp]-...`) against `CLAUDE.md`,
`frontend/CLAUDE.md`, and `frontend/AGENTS.md` returned nothing. The only credential-*adjacent*
hits are environment-variable **names** being referenced, never values: `FMP_API_KEY` (line 160)
and `MASSIVE_API_KEY` (line 3922, in a section documenting that var's own deletion). `.claude/settings.json` and `.claude/settings.local.json` contain no key/token/secret entries.

**Contradictions**:
- **Sector Heatmap window count.** `CLAUDE.md:3706-3707` says "x 7 trailing-return windows
  (1w/1m/3m/6m/9m/YTD/1y)". `docs/specs/sector-heatmap.md:4` says "× 8 trailing-return windows
  (1d/1w/1m/3m/6m/9m/YTD/1y)" and `sector-heatmap.md:92-98` explicitly documents this as a known,
  unfixed discrepancy: "The 2026-09-25 divergence investigation flagged that `CLAUDE.md`'s own
  'Sector Heatmap' section ... [is missing] an 8th (1d) window added. ... Fixing that section is
  out of scope for this session." This restructure's merge into `sector-heatmap.md` (§2) is the
  natural point to actually fix it — flagging so Phase B doesn't just copy the stale "7 windows"
  wording forward.
- No other direct contradictions found between sections (the file's own hygiene is otherwise
  good — many later sections explicitly say "SUPERSEDES" or "Superseded" when overriding an
  earlier one, e.g. lines 2585, 2666, 2928, rather than leaving both silently live).

**Duplicated sections** (beyond the DELETE-category ones already in §2's table):
- `CLAUDE.md:2824-2837` (Chart Stochastic 5/3/3 EMA) duplicates `docs/specs/chart-indicators.md`'s
  own "Full Stochastic (5, 3, 3)" section almost verbatim.
- `CLAUDE.md:3158-3168` (Price-target snapshot) duplicates `docs/specs/price-target.md:73-74`
  almost verbatim, down to the same wording ("renamed from `monthly_price_target_snapshot`
  2026-09-27", "now runs **daily 02:10**").
- `CLAUDE.md:376-445` (Cron job heartbeat mechanism) duplicates `backend/OPS_RUNBOOK.md`'s own
  "Cron job heartbeat / health monitoring" section (confirmed present at `OPS_RUNBOOK.md:475`),
  which `CLAUDE.md`'s own text already acknowledges ("documented in `backend/OPS_RUNBOOK.md`'s
  ... section ... not duplicated here" — true for the *mechanism*, but the surrounding
  incident narrative in the same CLAUDE.md section is not actually in OPS_RUNBOOK and needs to
  move to archive rather than be deleted).

**Stale / dangling references** (cited as authoritative but not present in the repo — likely
uncommitted local scratch docs from the investigations that produced them):
- `docs/chart_tab_missing_bar_investigation_2026-09-18.md` (cited at lines 2844, 2897)
- `docs/etf_heatmap_momentum_investigation_2026-09-20.md` (line 3708)
- `docs/fmp_phase2_daily_prices_plan_2026-09-24.md` (line 3548)
- `docs/fmp_phase3_long_history_non_us_investigation_2026-09-25.md` (line 3603)
- `docs/market_breadth_investigation_2026-09-21.md` (line 3773)
- `docs/price_target_daily_snapshot_implementation_2026-09-26.md` (line 3165)
- `docs/stochastic_divergence_investigation_2026-09-25.md` (line 2836)
- `docs/valuation.md` (line 2072) — this one looks like a plain wrong path; the real file is
  `docs/specs/valuation.md`.

  These don't block the restructure, but Phase B should either drop these citations when moving
  the surrounding text to archive, or note in the archive file that the cited doc no longer
  exists.

**Outdated/obsolete content, beyond what's captured in the DELETE rows above**: none found that
isn't already covered by the ARCHIVE classification (the file is generally good about
self-labeling superseded content with "Superseded"/"SUPERSEDES"/"Stale as of"/"is history"
markers — found 10+ such explicit self-labels, all correctly routed to ARCHIVE above).

## 7. Notes on non-obvious classifications

### 7.1 The "Scoring rubric notes" (446-1613) and "Valuation scoring notes" (1945-2272) SPEC/ARCHIVE split is an estimate, not a diff

These two sections total ~104,700 characters — over 31% of the whole file — and are structured as
a sequence of dated bullets, each mixing (a) a statement of current behavior/formula/constant and
(b) the investigation narrative that produced it ("Confirmed via a full-universe recompute: N
tickers changed, M verdict flips, 0 regressions... [list of tickers]"). I spot-checked overlap
with the existing spec files by grepping for constant names mentioned in these sections
(`classify_trend`, `MULTIPLE_DIPS_CEILING`, `NET_INCOME_BACKUP_THRESHOLD`,
`PASS_WITH_CAUTION_SCORE_CAP`, `MARGINS_EXEMPT_TYPES`, `NON_LENDER_TICKER_OVERRIDES`,
`CF_NORMALIZED`, `PRICE_TO_BOOK_STANDARD` all found present in the relevant spec file) — but also
found several **not** yet present in any spec file (`BASE_WEIGHTS`, `RESOLVED_CEILING`,
`PASS_SCORE_FLOOR`, `AR_EXEMPT_TYPES`). So the specs are not a strict superset of CLAUDE.md's
content here — Phase B cannot simply delete this section on the assumption specs already cover
it. My 40%-SPEC/60%-ARCHIVE split estimate reflects that most named constants/formulas already
have a home, but the exact current-value + rationale for each one still needs to be read and
merged (not just deleted), and only the "recompute proved it" validation narrative moved to
archive. This is the single largest and riskiest piece of Phase B's work — I'd budget it as its
own sub-phase with its own review, not lumped in with the smaller mechanical moves.

### 7.2 Institutional Ownership classified SPEC, not ARCHIVE, unlike Insider Activity

Both are inactive today, but Insider Activity's code was **fully deleted** (commit `6410970`) —
there's nothing left to document as "current" beyond a warning that it once existed, so ARCHIVE is
right. Institutional Ownership's code, tests, and DB schema are still in the tree; it was disabled
by a single config default flip and can be revived with no code changes. Documenting it as a SPEC
(what it does, how to turn it back on) has ongoing reference value the way any other feature's
spec does — it isn't primarily a historical record.

### 7.3 Why `corporate-events.md` is left as an open question rather than decided

The Phase 6a follow-up section's corporate-events content (upsert semantics, 4-year retention,
weekly splits cadence) doesn't clearly belong to any single existing spec file. It's plausible
either as its own small new file or as a subsection of `fmp-data-and-bar-cache.md` (which already
covers `CorporateEvent`'s role in the Chart tab's earnings/dividend markers, per that section's
own content). Left as an open question below rather than guessed.

## 8. Open questions (need your decision before Phase B)

1. **Scoring-rubric split ratio (§7.1)**: is a ~40/60 SPEC/ARCHIVE split (by my read) the right
   target, or would you rather Phase B lean more conservative (keep more detail in specs, less in
   archive) given this is the app's core methodology and gets referenced most often?
2. **`corporate-events.md`**: new file, or fold into `fmp-data-and-bar-cache.md` (§7.3)?
3. **Archive file granularity**: I proposed 4 topic files (~30-47k chars each). Would you prefer
   finer-grained files (e.g. one per dated phase/investigation) even though several would then be
   quite small, or is 4 the right level?
4. **`docs/specs/overview.md` as the catch-all for "Overall weighting" + "Screener excludes ETFs"**:
   both are short and don't have an obvious dedicated home; I routed them to `overview.md` since it
   already introduces the Overall Assessment blend and the Screener. Confirm, or would you rather
   each get its own tiny spec file for consistency with how e.g. Speculative Growth is being
   handled?
5. **Should Phase B fix the Sector Heatmap window-count contradiction (§6) as part of the merge,
   or leave it exactly as-is and file it as a separate follow-up?** I'd default to "fix it while
   touching that file anyway," but it's technically outside "restructure" scope.
6. **Dangling doc references (§6)**: drop the citations to the 7 missing investigation docs when
   moving their surrounding text to archive, or leave the citations in place as-is (pointing at
   nothing) since they're historical anyway?

## Migration ledger

| Section heading | Source lines (original) | Chars (unicode, incl. trailing newline) | Destination file(s) | Phase | Status |
|---|---|---|---|---|---|
| Speculative Growth (new classification) scoring notes | 2273-2315 | 3652 | docs/specs/speculative-growth.md (SPEC, 100%) | B2 | DONE |
| Analysis tab section-card reasoning (2026-09-05) | 1614-1720 | 6990 | docs/archive/claude-md-history-features.md (ARCHIVE, 100%) | B2 | DONE |
| Insider Activity -- SHELVED 2026-09-20, FULLY DELETED 2026-09-27 | 4065-4200 | 9610 | docs/archive/claude-md-history-features.md (ARCHIVE, 100%) | B2 | DONE |
| Phase 6a: Massive removed; FMP last-close, corporate-events and delisted-companies (2026-09-26) | 3919-3965 | 4644 | docs/archive/claude-md-history-fmp-migration.md (ARCHIVE, 100%) | B2 | DONE |
| Phase 6b: Yahoo Finance removed entirely (2026-09-26) | 3966-4036 | 6155 | docs/archive/claude-md-history-fmp-migration.md (ARCHIVE, 100%) | B2 | DONE |
| Liquidity Zone (LP) detection (Technical), main body | 2663-2779 | 9603 | docs/specs/liquidity-zones.md (SPEC) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: superseded Engine/Nearest-N/Settings bullets 2696-2709, 2719-2725, 2744-2752) | B2 | DONE |
| Liquidity Zone nightly job: market-close-aware fix (2026-09-18) | 2869-2925 | 4678 | docs/specs/liquidity-zones.md (SPEC nugget: Freshness) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE, whole section) | B2 | DONE |
| Main/Secondary watchlist rename + computed_at staleness sweep (2026-09-09) | 2926-2982 | 4231 | docs/archive/claude-md-history-technical-signals.md (ARCHIVE, 100%) | B2 | DONE |
| Most-recently-breached LP level tracking (2026-09-17) | 2983-3073 | 7210 | docs/specs/liquidity-zones.md (SPEC: Storage 3029-3034, Chart display 3043-3052, Card list 3053-3066) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: 2983-3028, 3035-3042, 3067-3073) | B2 | DONE |
| Chart tab reverted to zero-cache on-demand fetch (2026-09-18) | 2838-2868 | 2465 | docs/specs/chart-tab.md (SPEC: current fetch behavior, section 1) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE, whole section) | B2 | DONE |
| Chart tab earnings/dividend markers (2026-09-20) | 3074-3157 | 7481 | docs/specs/chart-tab.md (SPEC: section 2) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: 3074-3091 original design, 3143-3152 history + browserless verification) | B2 | DONE |
| Phase 6a follow-up: corporate-events upsert/retention/weekly splits + non-US removal (2026-09-26) | 3672-3703 | 3020 | docs/specs/corporate-events.md (SPEC: bullets 3674-3689) + docs/archive/claude-md-history-fmp-migration.md (ARCHIVE: non-US removal bullet 3690-3703) | B2 | DONE |
| Warren RSI/ADX/WVF entry signal (2h) (Technical) | 3169-3439 | 23322 | docs/specs/warren-signal.md (SPEC) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: 3196-3216, 3228-3235, 3268-3278, 3288-3293, 3310-3324, 3332-3338, 3357-3375, 3382-3386, 3393-3407, 3427-3439) | B2 | DONE |
| Institutional Ownership (ticker-page tab, 2026-09-27) -- SHELVED 2026-09-27 | 4201-4298 | 8291 | docs/specs/institutional-ownership.md (SPEC, 100%) | B2 | DONE |
| Ad-hoc reproduction scripts must not touch the real database (incident narratives; rule text also retained in CLAUDE.md) | 257-375 | 7588 | docs/archive/claude-md-history-features.md (ARCHIVE, whole section verbatim, 257-375) | B3 | DONE |
| Cron job heartbeat / health monitoring: mechanism paragraphs (intro, additive/re-raise, `GET /api/config/cron-health`) | 376-400 | 1426 | DELETED (duplicate of backend/OPS_RUNBOOK.md "### Cron job heartbeat / health monitoring" + "Known gaps" entry "Cron silent-failure blind spot") | B3 | DONE |
| Cron job heartbeat / health monitoring: `CRON_HEALTH_ENABLED` gate, FMP_ENABLED-interaction investigation, price-target guard-parity fix | 401-433 | 2324 | docs/archive/claude-md-history-features.md (ARCHIVE, verbatim, 401-433) | B3 | DONE |
| Cron job heartbeat / health monitoring: `CRON_JOB_NAMES` gotcha paragraph | 435-444 | (part of 4425 total for 376-445) | already in CLAUDE.md (KEEP, unchanged) | B3 | DONE |
| Shared FMP daily-bar cache: wrong staleness window + colliding cache key (2026-09-16) | 2780-2823 | 3256 | docs/archive/claude-md-history-technical-signals.md (ARCHIVE, whole section verbatim); rule already in docs/specs/fmp-data-and-bar-cache.md (Bug 1), plus a code-vs-history note added there | B3 | DONE |
| Chart Stochastic: 5/3/3 EMA, ThinkOrSwim parity (2026-09-25) | 2824-2837 | 1131 | DELETED (duplicate of docs/specs/chart-indicators.md; 2 missing facts added to that spec first: no-cache-invalidation-needed note, 2026-09-24 eye-check values) | B3 | DONE |
| Price-target snapshot: daily + methodology (2026-09-26) | 3158-3168 | 1515 | DELETED (duplicate of docs/specs/price-target.md; 2 missing facts added to that spec first: 32,764 backfill rows/no recency cutoff since 2021, ~8 nightly failures/SPY,TECL,PARA) | B3 | DONE |
| Shared bars cache (2026-09-19; FMP-only since Phase 6b) | 3440-3543 | 9383 | docs/specs/fmp-data-and-bar-cache.md (SPEC: 3440-3499, 3538-3543 + Screener-ordering mechanism) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: 3500-3537 flat-timer audit and 2:50->3:50 recompute fix) | B3 | DONE |
| Daily prices: FMP (Phase 2, 2026-09-24) | 3544-3598 | 5303 | docs/specs/fmp-data-and-bar-cache.md (SPEC: 3550-3580) + docs/archive/claude-md-history-fmp-migration.md (ARCHIVE: 3544-3549, 3581-3598) | B3 | DONE |
| Daily prices: FMP, Phase 3 -- long history (2026-09-25) | 3599-3637 | 3774 | docs/specs/fmp-data-and-bar-cache.md (SPEC: 3605-3637) + docs/archive/claude-md-history-fmp-migration.md (ARCHIVE: 3599-3604) | B3 | DONE |
| Intraday bars: FMP, Phase 4 (2026-09-26) | 3638-3671 | 3054 | docs/specs/fmp-data-and-bar-cache.md (SPEC, new section; 3638-3664, 3668-3671) + docs/archive/claude-md-history-fmp-migration.md (ARCHIVE: 3665-3667) | B3 | DONE |
| Sector Heatmap (`/sectors`, 2026-09-20) | 3704-3766 | 5745 | docs/specs/sector-heatmap.md (SPEC, 8-window fix; stale "Documentation drift" section removed) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: 3704-3710 original intro, 3735-3739 crontab activation, 3763-3766 verification note) | B3 | DONE |
| Market Breadth (`/breadth`, 2026-09-21) | 3767-3901 | 12421 | docs/specs/market-breadth.md (SPEC) + docs/archive/claude-md-history-fmp-migration.md (ARCHIVE: 3767-3774, 3816-3822, 3831-3835, 3858-3862, 3863-3870, 3889-3895) | B3 | DONE |
| Delisted-ticker handling (2026-09-23; detection replaced in Phase 6a) | 3902-3918 | 1343 | docs/specs/fmp-data-and-bar-cache.md (SPEC; detection rules pulled in from the already-archived Phase 6a bullet, code-verified) | B3 | DONE |
| Non-US cleanup (2026-09-26) | 4037-4064 | 2833 | docs/specs/fmp-data-and-bar-cache.md (SPEC: 4039-4056; plan said company-type-variations.md for this nugget, B3 task said fmp-data-and-bar-cache.md -- followed the task) + docs/archive/claude-md-history-fmp-migration.md (ARCHIVE: 4057-4064) | B3 | DONE |
| Company classification: non-lender ticker overrides | 1721-1802 | 5862 | docs/specs/company-type-variations.md (SPEC: mechanism, both tables, generalization caveat; new "How the type is detected" section from code) + docs/archive/claude-md-history-features.md (ARCHIVE: 1721-1752 narrative, 1787-1795 HOOD-removed note) | B4 | DONE |
| Bank classification requires genuine CET1/NPL-reporting capability (2026-09-05) | 1803-1901 | 6561 | docs/specs/company-type-variations.md (SPEC: standard, evidence rule, result, 4-ticker outcome, empty-set constant) + docs/archive/claude-md-history-features.md (ARCHIVE: 1803-1849 framing/scan/HSBC-MTB, 1878-1893 before/after table) | B4 | DONE |
| Screener excludes ETFs (2026-09-20) | 1902-1944 | 2686 | docs/specs/overview.md (SPEC, own heading; Country=US remark replaced by current no-Country-filter behavior) + docs/archive/claude-md-history-features.md (ARCHIVE: 1937-1941 Country=US bullet) | B4 | DONE |
| Valuation (Step 3) scoring notes | 1945-2272 | 24873 | docs/specs/valuation.md (SPEC: additive merge into an already-current spec) + docs/archive/claude-md-history-scoring.md (ARCHIVE, NEW FILE: whole section verbatim in 12 blocks, 1945-1951 ... 2238-2272) | B4 | DONE |
| Trend structure analysis (Technical): engine, storage/cron/API, A/D divergence, SMA position | 2316-2489 | (part of 31971 total for 2316-2662) | docs/specs/trend-structure-technical.md (SPEC) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: 2349-2357, 2358-2372, 2403-2410, 2428-2447, 2480-2489) | B4 | DONE |
| Trend structure analysis (Technical): Weinstein Stage base engine, engine swap, Chart toggle, Screener surfacing | 2490-2662 | (part of 31971 total for 2316-2662) | docs/specs/weinstein-stage.md (SPEC, new "Part 0"; deviation from plan table, which said trend-structure-technical.md) + docs/archive/claude-md-history-technical-signals.md (ARCHIVE: 2503-2525, 2549-2560, 2572-2584, 2585-2593, 2609-2613, 2625-2637, 2638-2662) | B4 | DONE |
| Scoring rubric notes: heading, Financials intro, Verdict bands (badge shading) | 446-458 | 746 | docs/specs/financials.md (SPEC: Verdict bands + badge-shading section, code-verified vs frontend/lib/tierColor.ts) + docs/archive/claude-md-history-scoring.md (ARCHIVE, verbatim) | B5a | DONE |
| Financials: Margins windowed-direction classification | 459-462 | 292 | docs/specs/financials.md (SPEC: rationale sentence in Margins classification) + docs/archive/claude-md-history-scoring.md (ARCHIVE, verbatim) | B5a | DONE |
| Financials: multi-dip trend tier split by recovery (flat 40/75 reading, superseded) | 463-468 | 416 | docs/archive/claude-md-history-scoring.md (ARCHIVE, verbatim); current behavior already in docs/specs/financials.md (trend classification steps 5-7, corrected: resolved patterns are graduated 75->65, not flat 75) | B5a | DONE |
| Financials: classify_trend age-aware, contiguous dips merge (2026-08-08) | 469-493 | 1744 | docs/specs/financials.md (SPEC: already present; no change needed) + docs/archive/claude-md-history-scoring.md (ARCHIVE: HWM case, 113/569 audit, 28-flip validation) | B5a | DONE |
| Financials: Margins sustained_decline override gated on durable reversal | 494-512 | 1352 | docs/specs/financials.md (SPEC: baseline-choice rationale, no-fall-through-to-Rule-2 note added) + docs/archive/claude-md-history-scoring.md (ARCHIVE: 128/499 audit, 16-ticker fall-through finding) | B5a | DONE |
| Financials: Rule 2 wildly_inconsistent / 2-point dip threshold known issues | 513-521 | 651 | docs/specs/financials.md (SPEC: already present; example tickers left in archive) + docs/archive/claude-md-history-scoring.md (ARCHIVE, verbatim) | B5a | DONE |
| Financials: score_step1 insufficient_data instead of fabricated Fail | 522-538 | 1253 | docs/specs/financials.md (SPEC: safe_fetch-swallow and exempt-company notes added to Insufficient data) + docs/archive/claude-md-history-scoring.md (ARCHIVE: 65/Fail repro narrative) | B5a | DONE |
| Financials: hard positivity gate (2026-08-03) + NI Operating-Income backup recency gate | 539-591 | 3753 | docs/specs/financials.md (SPEC: _classify_positive_trend scope, non-tightening rule, most_recent_real_dip_age, age-0 inclusion, threshold-equality test) + docs/archive/claude-md-history-scoring.md (ARCHIVE: SYM case, 29-ticker recompute) | B5a | DONE |
| Financials: flat_then_spike protect_terminal + Margins robust_early_direction (2026-08-13, GLW) | 592-661 | 4910 | docs/specs/financials.md (SPEC: robust_early_direction location/one-call-site scope, magnitude-gate stress-test rationale in Calibration notes) + docs/archive/claude-md-history-scoring.md (ARCHIVE: GLW trace, 18-ticker recompute) | B5a | DONE |
| Financials: declining and not_yet_positive graduated (2026-08-13) | 662-704 | 2833 | docs/specs/financials.md (SPEC: calibration facts in new Calibration notes section; mechanism already present) + docs/archive/claude-md-history-scoring.md (ARCHIVE: 141/45-hit scans, 71-ticker recompute) | B5a | DONE |
| Financials: multiple_dips (unresolved) graduated (2026-09-10) | 705-777 | 5084 | docs/specs/financials.md (SPEC: mechanism + companion fix already present; threshold-equality test and calibration added) + docs/archive/claude-md-history-scoring.md (ARCHIVE: UNH/DDOG investigation, 37-regression simulation, 47-flip recompute) | B5a | DONE |
| Financials: Bank Margins exemption, resolved-dip graduation (b), Margins-compression graduation (c) (2026-09-10) | 778-910 | 9221 | docs/specs/financials.md (SPEC: NEW resolved-dip graduation paragraph, WEIGHTS_CFO_MARGINS_EXEMPT, raw-classifier carve-out note, exemptionNote reasoning text, Bank artifact calibration) + docs/archive/claude-md-history-scoring.md (ARCHIVE: full-universe recompute narratives, WFC three-way interaction) | B5a | DONE |
| Growth Rate: methodology substitution, verdict divergence, score floor, EPS preference, target-year picker, insufficient_data, negative-magnitude graduation | 911-1035 | 8461 | docs/specs/growth-rate.md (SPEC: EPS-reversal rationale, estimate-range labeling, floor rationale, graduation calibration counts, safe_fetch note added; rest already present) + docs/archive/claude-md-history-scoring.md (ARCHIVE: FTNT case, 20-ticker recompute, verbatim) | B5a | DONE |

**B5a/B5b split point:** B5a covers original lines 446-1035 (40,716 chars, ~51% of the 79,860-char scoring-rubric range). B5b starts at **line 1036**, the paragraph beginning "Debt's original methodology calls for a CET1 ratio check for Banks" (the Debt subsection intro), and runs through line 1613 (Debt 1036-1240, Profitability 1241-1579, Overall weighting 1580-1613). B5b appends to docs/archive/claude-md-history-scoring.md and merges into docs/specs/debt.md, profitability.md and overview.md.

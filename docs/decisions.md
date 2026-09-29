# Fathom UI Redesign — Decision Log

Why the current design exists and what state the migration is in. Companion to `docs/design-system.md` (visual rules) and `docs/design-system-charts.md` (chart rules). This replaces the claude.ai chat memory that used to be the only record of this history.

## Origin

Goal: a consistent, modern, minimalist UI. Style guide first, then every page follows it. Process: a report-only Claude Code frontend audit (read-only, no changes), a design system drafted in a claude.ai chat from that audit, two directions compared on a visual canvas (A = consolidated version of the old look, B = quiet minimalist), **B chosen**, then implementation page-by-page in fresh Claude Code sessions on one long-lived branch, `ui/design-system`.

Deliberate UX kept from the old app, not touched by the redesign: in the Screener, clicking a ticker opens a new tab (same for Watchlist ticker clicks), and nav links clicked from the Screener open in a new tab, so the Screener's filters stay in place. Other pages don't need this.

## Session-by-session build log

All sessions below are commits on `ui/design-system`, not pushed to `origin` until the whole branch is reviewed.

- **Session 1 — Foundation.** Colour tokens, focus styles, contrast fixes, dead-CSS cleanup. Run and committed. (Session 1b: a build fix, also committed.)
- **Session 2 — Shared primitives**, split in two:
  - **2a:** Button, Status, Badge, Section, Input, Checkbox, Card, plus a minimal `/styleguide` route. Committed. Reviewed live in the browser — hover and keyboard behaviour checked out.
  - **2b:** Tabs, SegmentedControl, Tooltip, SideNav, PageHeader, restyled table, chart wrapper. Committed. (The restyled table was later reassigned to the tables session instead.)
- **Session 3 — Charts**, split in two:
  - **3a:** Chart tab (candlestick, `lightweight-charts`). Committed; a Safari-only chart rendering bug found afterward was fixed.
  - **3b:** `recharts`-based charts, Sector Heatmap, gauges. Committed.
  - Decision: the stock chart stays on `lightweight-charts` (no library swap).
- **Session 4 — Tables**, split in two:
  - **4a:** Table primitive, Watchlist, Momentum. Committed.
  - **4b:** Reference tables, legacy variable cleanup. Committed.
  - Decisions made here: Segmentation charts keep their cycling 5-colour series palette as built; statement tables (Financials, Ratios, Recommendation Details) get a dense 36px row option while record lists keep 44px; number formatters keep the hyphen-minus character (a true minus sign is used only in chart tooltips).
- **Session 5 — Pages**, split into five:
  - **5a:** Pills, Status, Badge — applied app-wide. Committed.
  - **5b:** Ticker page shell (Tabs, PageHeader, Section). Committed.
  - **5c:** Screener. Committed. Left the multi-select filter dropdowns deliberately unstyled — a `MultiSelect` primitive doesn't exist yet (open item, see below).
  - **5d:** Watchlist and Momentum page chrome. Committed.
  - **5e:** Breadth and Sectors pages. Committed.
  - **5f:** Reports page (unlinked, direct-URL-only route) migrated; all 10 occurrences of the `border-control` typo (see below) fixed app-wide. Committed. Decision: the Segmentation chart's "Other" slice reuses the `text-tertiary` token rather than getting a new dedicated one. At this point the app is confirmed fully on the new design system outside Settings.
- **Session 6 — Settings, last**, split in two:
  - **6a:** Merged Settings' separate raw-zinc colour system onto the shared tokens; migrated the Scheduled Jobs and FMP Data Groups tables. The sky-blue "skipped" status was retired. Committed. Found two extra items needing the same treatment along the way, folded into 6b: a 5th settings form (REIT Dividend Yield) and `FmpHealthSummaryCard`.
  - **6b (last planned session):** all 5 settings forms, `FmpHealthSummaryCard`, the 3 shared components used only by Settings (`NumberStepper`, `Select`, `InfoTooltip`), the Watchlist deletion UI, and a final whole-app sweep. **Confirmed run and complete (2026-09-29 verification)** — this line previously read "prompt written, not yet run," which was stale by the time of that check: `grep` for `zinc-` across all of `frontend/` now returns zero matches, `NumberStepper.tsx`/`Select.tsx`/`InfoTooltip.tsx` are all on named tokens, and `WatchlistDeleteButton.tsx` exists.
- **Session 7 — Unified pill family (2026-09-29).** Status and Badge rebuilt as one pill family with a compact size, every hand-rolled dot / one-off pill / inline status colour converted to the shared primitive, `/styleguide` updated. Three commits on `ui/design-system` (docs, code, styleguide), not pushed. Reverses two earlier decisions; see "Design reversals" below.

## Design reversals

### 2026-09-29 — Status becomes a pill everywhere

Two earlier decisions are reversed by the owner, for one reason: **visual consistency — the same status must not look different in different places.**

1. **Reversed: "Status (dot + word) everywhere else"** (Foundational decisions; Principle 4 in `docs/design-system.md`: "Status is a dot and a word … filled pills are for dense tables only"). Status is now a soft tinted pill (tone colour at 16% fill, tone-coloured text, no border), the same look as the Screener's pullback pills, which were the reference style. This also reverses the Direction-B line "filled pills dropped from headers, tiles and lists": the ticker header, Screener cards and Settings tables all use pills.
2. **Reversed: "Watchlist and Momentum keep the compact filled `Badge` for scores/ratings"** (the dense-table exception). There is no dense-table exception any more. `Badge` joins the same pill family and look, and Watchlist and Momentum cells (Moat, Value, Analysis score, Momentum score) render the same pill as the ticker header and Screener cards, in a **compact** size (smaller type, tighter padding, same tint) so the tables stay quiet.

Consequences recorded with the decision: one pill family with two sizes (regular, compact); no new colours (every tone reuses an existing token); the score number beside a verdict is neutral `text-primary` and the pill carries the tone; the neutral pill replaces the plain neutral dot in the jobs/health tables. Full spec: "Pills" in `docs/design-system.md`.

### 2026-09-29 (follow-up) — pill family: owner decisions on the open questions

Made by the owner after reviewing the pill work above:

1. **Index membership is neutral.** The teal `index` tone is removed from the pill tone set (and the `--fathom-index-membership` token from `globals.css`, which had no other reader). The index chip ("S&P 500 · Nasdaq") is a neutral pill, as the original design system said.
2. **`PullbackPill` and `ReversalPill` render through the shared pill.** They were the reference style and the last hand-rolled copy. No visual change is intended (a stale Reversal's text moves from `text-tertiary` to the neutral pill's `text-secondary`, the only difference). Their unused bordered "chip" variant is gone, and so is the stale comment about `TrendContinuationCard`'s `STATUS_PILL_CLASS`.
3. **The Watchlist Rating stays as coloured text**, not a pill (Buy/Hold/Sell). It would be a fourth adjacent pill in the Moat / Value / Analysis strip, and nothing else in the app shows that status as a pill. No code change.
4. **Overall Assessment ring: the number is neutral `text-primary`; the ring stroke carries the colour.** This makes the "score number is never coloured" rule true everywhere a number stands beside a status.

**Casing rule:** every pill label is sentence case ("Wide moat", "Speculative growth", "Strong pass"), applied for display only by one helper (`pillLabel()`, the extended `verdictLabel()`), never to backend strings or comparisons. This supersedes the earlier "product terms keep their own names" exception. Full spec: "Pills" in `docs/design-system.md`.

**`/styleguide`** is the complete visual reference for every pill representation (tones, sizes, Badge, direction, score + label, Pullback/Reversal states, checklist chips, the Overall Assessment ring, and in-context mock samples), for browser review before deploying.

## Known open items (re-verified against code 2026-09-29, analyst labels fixed same day — all resolved)

- **`MultiSelect` primitive — resolved, built.** `components/screener/MultiSelectDropdown.tsx` is
  a real, finished, fully-token-styled primitive (focus trap, roving keyboard nav, full ARIA),
  used by `FundamentalFilters.tsx`/`TechnicalFilters.tsx`. No longer open.
- **`border-control` typo — resolved, zero remaining occurrences.** Every instance across the
  app now correctly reads `border-border-control`/`border-border-input`. Confirmed by grepping
  the bare `control` class fragment app-wide; no unprefixed occurrence survives. No longer open.
- **Housekeeping items from the original audit — all resolved.** Dead colour variables: gone
  (including `--ring` and the old `--chart-1..5` tokens, both fully removed, not just the ones
  originally flagged). `NumberStepper`: restyled and kept, not dropped. `text-tertiary-2`: fully
  merged into `text-tertiary`, zero references. **Analyst label renames — done 2026-09-29**:
  `CurrentDistributionList.tsx`, `RatingDistributionTrendChart.tsx`, and
  `RecommendationDetailsTable.tsx` now show FMP's own Strong Buy/Buy/Hold/Sell/Strong Sell
  wording instead of the app's prior Buy/Outperform/Hold/Underperform/Sell relabel. See
  `docs/design-system.md`'s "Housekeeping items" section for the full, itemized re-verification.

## Next step

Session 6b is confirmed complete (see its own line above) and the housekeeping/open items above
are resolved except the analyst-label rename. Remaining before the branch is ready for review:
confirm build clean and all tests passing (last checked 2026-09-29: `tsc`/`eslint`/backend and
frontend test suites all clean), decide whether to do the analyst-label rename now or leave it
as a follow-up, then review the whole `ui/design-system` branch before pushing/merging.

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

- **Session 8 — Form controls and the Settings layout kit (2026-09-30).** Shared form-control primitives, a Settings layout kit and a `/styleguide` preview, with **no page migrated**. Three commits on `ui/design-system` (docs, code, styleguide), not pushed. See "Session 8: form controls" below.
- **Session 9 — Settings migration, part 1 (2026-09-30).** REIT dividend yield, Economic moat and Discount rate moved onto the session 8 form controls and Settings layout kit, one commit per section, plus the Settings nav labels in sentence case. Weinstein, Liquidity, Scheduled jobs and FMP data groups untouched. See "Session 9: Settings migration, part 1" below.
- **Session 9, part 2 — Weinstein and Liquidity (2026-09-30).** The last two form sections (and a 0-100 check on the Moat fields) moved onto the form-control kit; `NumberStepper`, `InfoTooltip` and the legacy `Select` shell removed once nothing used them. See "Session 9: Settings migration, part 2" below.

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

### 2026-09-30 — Session 8: form controls

Made by the owner, from a read-only investigation report on the current Settings, Screener and Watchlist forms. Spec: "Form controls" and "Settings layout" in `docs/design-system.md`. The primitives and the layout kit are built and reviewable in `/styleguide`; **no existing page, form or call site was changed**, and the owner reviews `/styleguide` in the browser before any migration.

1. **Form fields are boxed on form pages.** Boxed and underline fields are shown side by side in the styleguide; the Screener sidebar's choice is deferred to its own migration.
2. **Checkbox checked state is neutral** (`text-primary` fill, dark check), not `brand` blue. Same for the new Switch and the chip variant.
3. **The number field is typed only:** no native spinner, no scroll-wheel value change, no `e`. ArrowUp/ArrowDown step the value, Shift+Arrow steps by 10x. A `stepper` prop exists, defaults to off, and when on joins 32px `-`/`+` buttons to the field's edges: `[-][ 30 ][+]`.
4. **Settings layout is rows, not a grid.** Each row is `grid-cols-[1fr_auto]` inside a `max-w-2xl` body: label and hint left, control right in its size token, `py-3`, a hairline between rows.
5. **Hints are inline text under the label**, linked with `aria-describedby`. They replace the `(i)` tooltips. `InfoTooltip` is not deleted yet (the Liquidity form still uses it).
6. **Units are a suffix after the field:** `[ 30 ] weeks`. Labels drop the unit.
7. **Validation never silently clamps or corrects.** Invalid input (not a number, non-integer where an integer is required, outside min/max) shows an inline error under the field and an invalid style. `min`/`max` are optional props that mirror existing server bounds; no new bounds are invented for Moat, REIT or Discount Rate. No snapping to `step` unless a prop asks for it.
8. **Selects stay native `<select>`** in the `appearance-none` shell, restyled to the field height, border and radius, with size tokens. No Base UI, no segmented-control radiogroup mode.
9. **New Switch primitive** for settings that apply immediately: a hidden native checkbox with `role="switch"`, a 32 by 18px track, the same focus ring as Checkbox.
10. **Sentence case in the styleguide mock.** Settings titles are converted when each section is migrated, not now.
11. **Out of scope:** merging the two `SegmentedControl` implementations, and moving the Settings page to `SideNav`.
12. **Out of scope:** an unsaved-edits guard.

Size tokens, all 36px high and capped at the container's width: `short` 96px, `medium` 176px, `wide` 320px, `full` fills the container.

**Reversals and carry-overs recorded with this decision:**

- **Reversed: "boxed only for the ticker search."** The earlier rule (an `Input` doc comment and the design system's radius line) kept the boxed field for the one place that needed a visible container, with underline for everything else. Form pages are now boxed. In fact the five Settings forms already used `variant="boxed"`; the rule now matches the code. Underline stays for inline filters.
- **Superseded: "steppers restyled and kept."** The 2026-09-29 housekeeping decision kept `NumberStepper`. It stays in place until the Liquidity form migrates, then is deleted in favour of `NumberField`'s optional `stepper`, which does not clamp or snap.
- **Deferred, not reversed: the unboxed Settings SideNav.** `docs/design-system.md` says Settings navigation is the unboxed `SideNav`, but the Settings page still hand-rolls a boxed nav (a bordered `surface` panel of buttons). That page-level move is out of scope for this session (decision 11); the design-system row for `SideNav` is unchanged. The owner should confirm whether this counts as a reversal.

**Compatibility rule for the code.** Existing `Input`, `Select`, `Checkbox` and `NumberStepper` call sites render identically: the new behaviour is a new component (`NumberField`, `FormField`, `Switch`, the Settings kit) or an explicit opt-in prop (`size` and `invalid` on `Input` and `Select`, `variant` on `Checkbox`). The defaults flip at migration, per the owner's review.

### 2026-09-30 (follow-up) — Settings rows: fixed control column, left-aligned

**Corrects the earlier right-aligned row spec** (decision 4 above and the first "Settings layout" text: `grid-cols-[1fr_auto]`, control right-aligned, error right-aligned). Seen in the browser on `/styleguide`: with an `auto` column the control column was only as wide as its content, so the differing unit widths ("weeks", "%", "× average", "bars", none) staggered the boxes from row to row, hints wrapped at different points, checkboxes ended at a different edge from the number boxes, and a right-aligned error landed under the wrong spot. Now: one fixed 256px control column (`medium` 176px plus an 80px unit slot), every control left-aligned in it (checkboxes and switches included), the unit trailing the box, the error left-aligned under the box, `full` still not allowed in a row, and the row stacking below `sm`. The row is still label and hint left, control right; decision 4 (rows, not a grid of fields, `max-w-2xl` body, `py-3`, hairlines) stands. Only the kit and its `/styleguide` mocks change; no page migrated.

### 2026-09-30 — Session 9: Settings migration, part 1

The first three Settings sections are migrated onto `NumberField`, `SettingsSection`/`SettingsGroup`/`SettingsRow`/`SettingsFooter`, in separate commits so each can be reviewed and reverted alone. Owner decisions, recorded here:

- **Sections migrated:** REIT dividend yield, Economic moat, Discount rate. Weinstein and Liquidity (still on `Field`, `Input type="number"` and `NumberStepper`/`InfoTooltip`), Scheduled jobs and FMP data groups are unchanged. `NumberStepper` and `InfoTooltip` stay because Liquidity still uses them.
- **Save is disabled until something is edited** (a field's value differs from what is stored), and also while any field is invalid ("Fix the highlighted fields to save."). Status text (Saving…, Saved ✓, Save failed) sits beside the button and resets after three seconds, as before. An invalid entry never leaves a sticky "Save failed": it cannot be saved at all. (The old Moat and REIT forms set "Save failed" on a non-number and never cleared it.)
- **Browser-only bounds are dropped.** Moat's `min="0" max="100"` and REIT's `min="0"` were HTML attributes on an `<input type="number">` outside a `<form>`, so nothing ever enforced them, and the server has no bounds for these fields. The only validation is "is it a number", with an inline error. Values are never clamped or corrected.
- **Discount rate loses its Card.** Each region is a `SettingsGroup` headed "United States (US)", two rows, and its own footer; each region saves on its own.
- **Discount rate bug fixed.** Save without editing used to rewrite the stored rates: the form showed `fmtNumber(x * 100, 3)`, parsed that text, divided by 100 and sent both fields, so 0.02728 was sent back as 0.027280000000000002 and 0.036085 as 0.03608. Now the stored value is shown at full precision with float noise stripped (`Number((x * 100).toPrecision(12))`, so 0.02728 shows as 2.728), a field that was not edited is sent back as its original stored value, an edited field is converted with the same noise-stripping, and editing one field never rewrites the other.
- **Sentence case:** the three migrated section titles, and every label in the Settings nav. The titles of the sections not yet migrated (FMP Data Groups, Liquidity Zones, Weinstein Stage, and the Scheduled Jobs heading) stay in their old case for now, so the nav label and the section title differ for those until they are migrated.
- **Unchanged:** API endpoints and payloads, SWR keys and the invalidation of the `/step3` and `/summary` keys after a Discount rate or REIT save, the remount keyed on `updated_at` after a save, and the "Last updated" line. The save status now lives above that remount so "Saved ✓" can actually show; before, the keyed form that held it was replaced as soon as the fresh data arrived.

### 2026-09-30 — Session 9: Settings migration, part 2

Weinstein and Liquidity are migrated onto `NumberField`, `Select` (with a size token), the neutral `Checkbox` and the Settings kit, one commit per section, following the part 1 patterns exactly (Save disabled until a field differs from its stored value and while any field is invalid, status via `useSettingsSave`, 3-second reset, `key={updated_at}` remount, "Last updated" kept, endpoints and payloads unchanged). Decisions recorded here:

- **Moat scores get a 0 to 100 form check** ("Enter a value between 0 and 100."). This is form-level only: the backend has no bound and the API is unchanged. It reverses the part 1 rule that Moat gets no bounds (part 1 dropped the browser-only `min`/`max` hints because nothing enforced them; this enforces them). Non-numbers stay blocked.
- **Breakout volume has a floor of 0.1, stricter than the server.** The server accepts any value above 0 (`gt=0`, `le=20`); the field uses the existing client hint of 0.1 as `min` and 20 as `max`, and its error text says so ("Enter a value between 0.1 and 20."). A value in (0, 0.1) is rejected in the form though the API would accept it. This is a documented exception to "the UI mirrors the server's bounds".
- **The other Weinstein and Liquidity bounds are the server's own** (MA length 2 to 200 whole; within range 0 to 50; slope lookback 1 to 52 whole; volume average and RS smoothing 2 to 200 whole; RS benchmark 1 to 20 characters after trimming, case not enforced; swing bars 1 to 3 whole; cluster 0 to 3; max zones 1 to 10 whole; breach recency 1 to 52 whole).
- **No more silent truncation or revert.** The old Weinstein form parsed with `parseInt`, so 30.7 saved as 30; a non-integer in an integer field now shows an inline error and blocks Save. The old Liquidity `NumberStepper` clamped and snapped on blur and reverted an unparsable draft to the previous value without a word; every field now holds the raw text, an invalid entry shows an inline error and blocks Save, and nothing is changed for the user.
- **Liquidity state change.** Its form state moves from numbers (committed on blur) to text like every other form, parsed for the payload. The payload keeps its types: numbers, booleans and the select value. "Breach recency" stays in place but is disabled and dimmed unless "Only keep if breached recently" is ticked; while disabled it is neither validated nor blocking Save, and the stored value is sent unchanged.
- **A 422 shows its reason.** FastAPI returns `{"detail": [{"type", "loc": ["body", "<field>"], "msg", ...}]}` for a validation failure. The shared API client kept `detail` only when it was a string, so a 422 surfaced as a bare "failed: 422" and the form said only "Save failed". The client now formats an array `detail` into a readable string (also for any other caller that gets a 422), and `SettingsFooter` shows it after "Save failed". It resets after the same 3 seconds as every other status.
- **Checkbox and Switch without a `label` prop render no wrapping `<label>`** (their input is laid over the box), so in a Settings row the row's `<label for>` is the only accessible name. Code with a `label` prop renders as before.
- **Sentence case:** section titles "Weinstein stage" and "Liquidity zones", and the headings of Scheduled jobs and FMP data groups, now match the nav. No other change to those two sections.
- **Removed once unused:** `NumberStepper`, `InfoTooltip` (and its tooltip-position helper if nothing else used it) and the legacy `Select` shell, after a grep showed no remaining caller. The brand `Checkbox` variant stays because the Screener filters use it.

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

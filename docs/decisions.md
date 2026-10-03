# Fathom UI Redesign — Decision Log

Why the current design exists and what state the migration is in. Companion to `docs/design-system.md` (visual rules) and `docs/design-system-charts.md` (chart rules). This replaces the claude.ai chat memory that used to be the only record of this history.

## Origin

Goal: a consistent, modern, minimalist UI. Style guide first, then every page follows it. Process: a report-only Claude Code frontend audit (read-only, no changes), a design system drafted in a claude.ai chat from that audit, two directions compared on a visual canvas (A = consolidated version of the old look, B = quiet minimalist), **B chosen**, then implementation page-by-page in fresh Claude Code sessions on one long-lived branch, `ui/design-system`.

Deliberate UX kept from the old app, not touched by the redesign: in the Screener, clicking a ticker opens a new tab (same for Watchlist ticker clicks), and top-nav links (the logo and Screener included) open in a new tab, so the page you're on, such as the Screener with its filters, stays in place. The one exception (2026-10-01): on Momentum, Sectors, Breadth (and `/breadth/<sector>`) and Settings, every top-nav item and the logo navigate in the same tab. Ticker search always opens a new tab.

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
- **Session 9, part 3 — FMP settings on the kit (2026-09-30).** The FMP status card moved into FMP data groups; the immediate-apply FMP controls became `Switch` and native `Select`; error messages now persist; REIT and Discount rate show the server's reason. See "Session 9: Settings migration, part 3" below.

- **Session 10 — Screener migration: plan and primitives (2026-09-30).** The form-control primitives and a `/styleguide` sidebar mock for the Screener migration, with **no Screener page change** beyond a `T` suffix in market-cap input. Five commits (docs, helpers and primitives, `RangeField`, a `RangeField` re-sync fix found by the mock, styleguide), not pushed. See "Session 10: Screener migration, plan and primitives" below.
- **Session 10, part 2 — Screener sidebar migration, session 1 of 2 (2026-09-30).** The Screener filter sidebar moved onto the form-control kit with boxed fields (the owner's choice), in five commits (docs, range filters, sidebar shell, chips and multi-selects and the Watchlist select and counts, cleanup and styleguide), local only, not pushed. See "Session 10, part 2: Screener sidebar migration" below.
- **Session 10, part 3 — Screener results controls, session 2 of 2 (2026-09-30).** The Sort row, Pagination, the saved-views bar, `RecomputeButton`'s styling and the multi-select trigger's accessible name moved onto the form-control kit, in five commits (docs, sort and outline buttons, pagination and multi-select name, saved-views bar, styleguide and cleanup). One guard added: a view name cannot contain "/". See the entry below.
- **Session 11 — Watchlist page and shared buttons (2026-09-30).** The Watchlist page controls (name editor, delete button, the table's remove buttons) and the shared `RefreshButton` and `ExportMenu` moved onto the outline, destructive and icon Button forms and the boxed `Input`, in four commits (docs; characterization tests and the Watchlist page; the shared buttons; styleguide and cleanup). `AddToWatchlistButton` and the ticker page remain. See the entry below.
- **Session 12 — Ticker page controls, part A (2026-10-01).** `AddToWatchlistButton`, `BankCapitalMetricsForm` and the Economic moat tab's Cancel button moved onto the kit, in three commits (docs, `AddToWatchlistButton`, the Bank form and the Moat button). See the entry below.
- **Session 13 — Ticker page controls, part B (2026-10-01).** `ManualCalculationPanel` (the Valuation tab's Custom valuation column) moved onto the kit: the method select, the formatted rows, the action buttons and the sliders' accessibility, in three commits (docs; characterization tests, the select and the rows; the buttons and sliders), local, not pushed. See the entry below.
- **Session 14 — Ticker page and shell controls, part C1 (2026-10-01).** The top-nav ticker search, the chart and price-target toggles, the merge of the two `SegmentedControl` implementations, the slider keyboard focus rule and a non-blocking parse warning in the Custom valuation rows, in four commits (docs; search and toggles; the merge; the slider rule and the warning), local, not pushed. See the entry below.
- **Session 15 — Ticker page and shell controls, part C2, cleanup sweep (2026-10-01).** The leftovers from sessions 12 to 14: two icon buttons' keyboard ring, the emoji and text glyphs, sentence-case strings, the multi-select trigger's name, the 32px primary `sm` button, the Bank, Moat and Zoom buttons, a focus return and an ArrowUp fix, and the stale docs and comments, in four commits (docs; accessibility and icons; sentence case and the multi-select name; buttons and cleanups), local, not pushed. See the entry below.
- **Session 16 — Ticker page and shell controls, part C3 (2026-10-01).** Two browser-found bugs (the Speculative growth tooltips overflowing their box, the expanded Analysis cards not lining up with their paragraph) and the neutral-selection and accessibility leftovers: five navigation places off brand blue, two tab strips onto `Tabs`, an accessible name for the SEC check icon, and the two Screener dropdown triggers onto the kit. Four commits on local `main` (docs, the two bug fixes, items 1 to 3, the triggers); see the entry below.

- **ETFs page and the "Stocks" rename (2026-10-02).** Step 5 of the ETFs screener. The top nav is Stocks, ETFs, Watchlist, Momentum, Sectors, Breadth, Settings; "Screener" is now "Stocks" (heading and tab title "Stocks Screener"). Routes, API paths, file, component and SWR-key names are unchanged, and `/` still redirects to `/screener`. The new `/etfs` page is the Stocks Screener's shell over `GET /api/etf-screener`, with ETF twins only where a component is bound to the stock row or filter state. Spec: "Frontend" in `docs/specs/etf-screener.md`.

## Design reversals

### 2026-09-29 — Status becomes a pill everywhere

Two earlier decisions are reversed by the owner, for one reason: **visual consistency — the same status must not look different in different places.**

1. **Reversed: "Status (dot + word) everywhere else"** (Foundational decisions; Principle 4 in `docs/design-system.md`: "Status is a dot and a word … filled pills are for dense tables only"). Status is now a soft tinted pill (tone colour at 16% fill, tone-coloured text, no border), the same look as the Screener's Weinstein stage pill, now the reference style (it was the Pullback/Reversal pills until the trend-structure feature was removed 2026-10-01). This also reverses the Direction-B line "filled pills dropped from headers, tiles and lists": the ticker header, Screener cards and Settings tables all use pills.
2. **Reversed: "Watchlist and Momentum keep the compact filled `Badge` for scores/ratings"** (the dense-table exception). There is no dense-table exception any more. `Badge` joins the same pill family and look, and Watchlist and Momentum cells (Moat, Value, Analysis score, Momentum score) render the same pill as the ticker header and Screener cards, in a **compact** size (smaller type, tighter padding, same tint) so the tables stay quiet.

Consequences recorded with the decision: one pill family with two sizes (regular, compact); no new colours (every tone reuses an existing token); the score number beside a verdict is neutral `text-primary` and the pill carries the tone; the neutral pill replaces the plain neutral dot in the jobs/health tables. Full spec: "Pills" in `docs/design-system.md`.

### 2026-09-29 (follow-up) — pill family: owner decisions on the open questions

Made by the owner after reviewing the pill work above:

1. **Index membership is neutral.** The teal `index` tone is removed from the pill tone set (and the `--fathom-index-membership` token from `globals.css`, which had no other reader). The index chip ("S&P 500 · Nasdaq") is a neutral pill, as the original design system said.
2. **`PullbackPill` and `ReversalPill` render through the shared pill** (both since deleted with the trend-structure feature; the Weinstein stage pill is the reference style now). They were the reference style and the last hand-rolled copy. No visual change is intended (a stale Reversal's text moves from `text-tertiary` to the neutral pill's `text-secondary`, the only difference). Their unused bordered "chip" variant is gone, and so is the stale comment about `TrendContinuationCard`'s `STATUS_PILL_CLASS`.
3. **The Watchlist Rating stays as coloured text**, not a pill (Buy/Hold/Sell). It would be a fourth adjacent pill in the Moat / Value / Analysis strip, and nothing else in the app shows that status as a pill. No code change.
4. **Overall Assessment ring: the number is neutral `text-primary`; the ring stroke carries the colour.** This makes the "score number is never coloured" rule true everywhere a number stands beside a status.

**Casing rule:** every pill label is sentence case ("Wide moat", "Speculative growth", "Strong pass"), applied for display only by one helper (`pillLabel()`, the extended `verdictLabel()`), never to backend strings or comparisons. This supersedes the earlier "product terms keep their own names" exception. Full spec: "Pills" in `docs/design-system.md`.

**`/styleguide`** is the complete visual reference for every pill representation (tones, sizes, Badge, direction, score + label, checklist chips, the Overall Assessment ring, and in-context mock samples), for browser review before deploying.

### 2026-09-30 — Session 8: form controls

Made by the owner, from a read-only investigation report on the current Settings, Screener and Watchlist forms. Spec: "Form controls" and "Settings layout" in `docs/design-system.md`. The primitives and the layout kit are built and reviewable in `/styleguide`; **no existing page, form or call site was changed**, and the owner reviews `/styleguide` in the browser before any migration.

1. **Form fields are boxed on form pages.** Boxed and underline fields are shown side by side in the styleguide; the Screener sidebar's choice is deferred to its own migration. *(Resolved 2026-09-30, session 10 part 2: the owner chose boxed; the underline variants are deleted.)*
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

- **Reversed: "boxed only for the ticker search."** The earlier rule (an `Input` doc comment and the design system's radius line) kept the boxed field for the one place that needed a visible container, with underline for everything else. Form pages are now boxed. In fact the five Settings forms already used `variant="boxed"`; the rule now matches the code. Underline stays for inline filters. *(Reversed 2026-09-30, session 10 part 2: the Screener sidebar, the only inline-filter user, is boxed too and the underline variants are deleted.)*
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
- **Removed once unused** (a grep first showed no caller left): `NumberStepper`, `InfoTooltip`, `lib/tooltipPosition.ts` (only `InfoTooltip` used it) and its test, and the un-tokened `Select` shell (`Select` now requires a `size`). The styleguide's "Settings controls" demo of the old stepper and select went with them, since the "Form controls" section shows their replacements. The brand `Checkbox` variant stays because the Screener filters use it. *(Deleted 2026-09-30, session 10 part 2, once the sidebar moved to the neutral variant.)*

### 2026-09-30 — Session 9: Settings migration, part 3

- **The FMP status card moves into FMP data groups, below the table.** `FmpHealthSummaryCard` (the "My FMP plan" select, the "FMP master switch" with its On / Off badge, the "FMP rejected the API key" line, and its own error line) leaves Scheduled jobs, which keeps only its jobs table, and sits inside the FMP data groups section under the per-group table. Moved on its own first, with no control changes, so it can be reviewed and reverted alone. The card and the table already share one SWR key (`/config/data-groups`, and every plan, master and group write puts the fresh response into it), so neither depends on the other's component state and moving the card changes no fetching.
- **Immediate-apply controls use the kit.** The master checkbox and each per-row enable checkbox become `Switch`; the plan select and each per-row required-tier select become the native `Select` with a size token. The section has no Save button and the apply-immediately behaviour, busy handling, endpoints, payloads and SWR keys are unchanged. The Switch is driven by the fetched data, so cancelling the "turn off" confirmation, or a failed request, leaves it showing the real state. The FMP data groups table stays a table.
- **Error messages persist.** In the Settings forms a failed save's message (including a 422's reason) now stays until the user's next edit or next Save attempt; only "Saved ✓" resets after three seconds. This refines the part 1 rule ("a three-second reset"), which made a server reason vanish before it could be read.
- **REIT dividend yield and Discount rate show the server's reason** beside "Save failed", as Moat, Weinstein and Liquidity already did.
- **Sentence case** for the labels in these two sections.

### 2026-09-30 — Session 10: Screener migration, plan and primitives

Plan and primitives for moving the Screener sidebar onto the form-control kit. **Only the primitives and a `/styleguide` mock are built; `app/screener` and `components/screener` are untouched**, and the owner reviews the mock in the browser before any Screener page change. The one live change is that market-cap input accepts a `T` suffix. Spec: "Screener filter sidebar primitives (session 10)" in `docs/design-system.md`.

**Currency finding (read-only investigation, 2026-09-30).** The Screener needs no currency handling. Every `TickerScore` row quotes in USD (585 of 585 screenable rows; none NULL), so Quote and Mkt cap are USD and a "USD" label is always true. The 14 US-listed ADRs that report in another currency (ASML, BABA, CCEP, CCJ, CNI, EVVTY, FER, MFC, NVO, PDD, RY, SINGY, TME, TSM) are stored correctly: price and market cap are USD, the five scores and Growth % are unitless, and P/E is computed by FMP on one currency basis. The FX conversion in Valuation stays. The non-US cleanup (Country filter, HK and France discount rates) was already done on 2026-09-26.

**Owner decisions.**

1. **Sidebar width stays `w-64` (256px)**, card content 222px. Not widened.
2. **Units go in the label row**, right-aligned in `text-tertiary`, not after the boxes: Quote and Mkt cap "USD", P/E "x", Growth "%", score fields none.
3. **Boxed versus underline is decided by the owner by eye from the mock.** Both are built: `NumberField` gets an additive `variant` (boxed default, underline) backed by `Input`'s existing variants. **Resolved: the owner chose boxed** (session 10 part 2); the underline variants of `NumberField` and `Input` are deleted with the migration's cleanup commit.
4. **Compact `FormField`, sidebar only:** label `text-xs` `text-secondary`, 2px gap to the control, no hint line (one optional single-line hint for market cap only), unit right-aligned in the label row.
5. **`T` added to the market-cap suffixes** (M, B, T). `5T` is 5,000,000,000,000. The live parser `parseMarketCapInput` changes by adding `T` only; the new lenient parser in `lib/numberInput.ts` (accepts `12.`, `.5`, `2 m`) is used by `NumberField` and `RangeField`, and the old one is deleted at migration (done in session 10 part 2). The mock's caption saying the live sidebar still rejects `12.` went with it.
6. **Live-filter rule for a Min/Max pair (option B):** valid text commits immediately, including `12.` and `.5`; an incomplete prefix (`-`, `.`, `-.`) holds the previous committed value with no error while focused and becomes invalid on blur (emitting `null` on that blur); any other invalid text (letters, `1x`, `5e`) makes that side inactive at once (emits `null`) and shows an inline error. Never clamp, swap or correct a value. No bounds except the existing market-cap minimum of 0.
7. **Filter state stays numeric.** `ScreenerFilterState` and saved-view compatibility do not change; typed text lives only in UI drafts.
8. **A reversed range** (min greater than max) is applied literally, so nothing matches, as today. One pair-level message under both boxes: "Min is higher than max, so no ticker can match." The Max box alone is marked invalid.
9. **External changes re-sync the drafts by object identity.** `useDraftNumber` remembers the exact `{ min, max }` object it emitted; a different object from outside (Reset, Load saved view, remount), including an equal-valued `EMPTY_RANGE`, rewrites the boxes even when one holds invalid text such as `1x`; the same object never overwrites typing. Parents pass the emitted object back unchanged.
10. **Applied indicator:** orange stays as label text colour only. A neutral applied-count `Badge` for section headers (mock only). Chips show applied through their checked fill, not orange. The Watchlist label is orange only while the watchlist filter is actually in effect.
11. **`formatMarketCapInput`** picks the shortest exact form (`1.5e9` reads `1.5B`, `2.5e12` reads `2.5T`): a candidate is accepted only if parsing it returns exactly the same number, otherwise a smaller suffix, otherwise plain digits.
12. **New additive `outline` Button variant** replaces the repeated "ghost plus `border-border-input hover:border-brand`" hack. Existing uses are not migrated yet.

**Built (additive and opt-in):** `NumberField` `optional`, `suffixes`, `keyboardStep`, `variant`, `hideError`; `FormField` `density="compact"` (and `applied`); `useDraftNumber` and `RangeField`; `Button` `outline`; `countActiveFilters` and `formatMarketCapInput`. Existing call sites render exactly as before.

**Deferred or decided for the migration itself:**

- **`AddToWatchlistButton` is deferred to the ticker-page session.** The Screener page keeps it as it is.
- **Reset will also reset the sort** (field and direction), not just the filters, the universe and the watchlist. Decided here, done at migration.
- **The sidebar will stay mounted on a universe switch**, so draft text and open sections are not lost. Decided here, done at migration.

### 2026-09-30 — Screener data: delisted exclusion and trailing P/E

Backend-only data changes to what the Screener (and the ticker header/Summary) show. **No frontend file changes** — the Screener page, sidebar and cards are untouched. Written up from the 2026-09-30 investigations (delisted tickers; P/E basis). Spec: "Screener excludes delisted tickers" and "P/E basis" in `docs/specs/overview.md`.

**Decisions and reasons**

1. **Delisted tickers never appear in any Screener universe.** `GET /api/screener` and `GET /api/screener/meta` add `TickerScore.delisted_at IS NULL` in every branch (`all`, `sp500`, `dow`, `nasdaq`; the page's Watchlist scope is applied client-side over the `all` response, so it inherits the exclusion). *Reason:* the five flagged tickers (TWTR, WBA, EA, AVB, EQR) carry stale prices and stale scores; they only showed under "All", but a stale row in a screen is misleading. Filtered on the server, so the frontend needs no change; the meta count uses the same condition so "X of Y" stays honest.
2. **`delisted_at` is not exposed to the frontend and the schema does not change.** Nothing is un-flagged. *Reason:* the flag is an internal job input (bar jobs, Momentum); AVB and EQR are correctly flagged (they merged into Vivmark Residential, ticker VMRK, trading from 2026-08-18), so there is nothing to correct.
3. **Nightly fundamentals fetch and score recompute are unchanged for delisted tickers.** *Reason:* out of scope for this change; the cost is reported separately (see the session report) so it can be decided on its own.
4. **P/E becomes trailing:** current price ÷ FMP TTM EPS (`netIncomePerShareTTM` from the cached `ratios/ttm` row), stored in the same `TickerScore.pe_ratio` column (no `pe_basis` column, no migration). *Reason:* the previous value was FMP's annual `priceToEarningsRatio` — fiscal-year-end price over fiscal-year EPS, a median 273 days old and a median 17% (90th percentile 65%) away from a trailing figure — and the header showed it beside a TTM PEG, a mixed basis.
5. **Price = `TickerLastClose` (nightly), falling back to the quote price** when a ticker has no `TickerLastClose` row (e.g. HUT). *Reason:* the cached quote row refreshes on a 7-day window; the nightly close is at most one session old. No other price handling changes (the Quote and Mkt cap columns still come from the quote row).
6. **NULL when TTM EPS is zero, negative or missing.** *Reason:* a negative multiple is not a P/E; storing it made loss-makers pass a max-only P/E filter (`≤ 20` matched INTC's −615) while a NULL is excluded by any active range (`inRange`).
7. **ADRs use FMP's own `priceToEarningsRatioTTM`,** stored NULL if that value is zero or negative. An ADR is detected by `reported_currency != quote_currency` with both non-null (not a hardcoded list). *Reason:* price (USD) over EPS (reporting currency) needs FX conversion and, for some ADRs, an ADR ratio; FMP's TTM P/E is already currency-consistent. If either currency is missing the standard formula is used.
8. **The Ratios tab is unchanged.** It keeps showing FMP's annual P/E history plus FMP's TTM column, so its P/E can differ from the header's by design.
9. **Saved views are unaffected** (all 3 saved filters have P/E min and max null).

**Docs corrections in the same change:** `docs/specs/fmp-data-and-bar-cache.md` claimed the five delisted flags were "verified against the live endpoint"; they were actually set by the 2026-09-24 staleness heuristic (a manual `stale_data_health_check` run), not by the `/delisted-companies` sync, and the endpoint check is not reproducible from cached data. **No `docs/specs/ratios.md` exists** (the Ratios tab is undocumented in the specs); a short one is warranted — the Ratios tab's field table, its annual-vs-TTM columns, and now the deliberate difference from the header/Screener P/E — but it is not created here.

**Backfill:** the new basis reaches `TickerScore` on the next nightly recompute (3:25) or an owner-run `uv run python -m pipeline.recompute_ticker_scores` (cache-only, **writes the live DB**).

### 2026-09-30 — Session 10, part 2: Screener sidebar migration (session 1 of 2)

The Screener filter sidebar moves onto the session 8 to 10 primitives. Made by the owner; this entry records what was decided and what was delivered. Spec: "Screener filter sidebar (session 10)" in `docs/design-system.md`. Five commits on local `main`, not pushed: docs; range filters; sidebar shell; chips, multi-selects, the Watchlist select, counts and sentence case; cleanup and styleguide.

**Decisions.**

1. **Boxed fields.** The owner compared the boxed and underline sidebars in the `/styleguide` mock and chose boxed. This **reverses** the rule recorded at session 8 and again in "Reversed: boxed only for the ticker search" above ("underline stays for inline filters"), and it settles session 8 decision 1's deferral. Underline `Input` and `NumberField` variants are deleted once grep shows no user.
2. **Scope: the sidebar only.** In: the Watchlist, Fundamental and Technical sections (the ten Min/Max pairs, the multi-selects, the two chips, the Watchlist scope select and the section headers) and the page-level Reset and loading behaviour they depend on. Out, and unchanged: the sort select and direction button, pagination, the saved-views bar's internals (its trigger, popover, list and naming row), `AddToWatchlistButton` (deferred to the ticker-page session), `RecomputeButton`, `UniverseSelector`, `ScreenerCard`, the backend and every non-Screener page. The Reset button lives in the saved-views bar, and only its handler in the page changes. A second Screener session takes the out-of-scope pieces that belong to the Screener.
3. **The sidebar stays `w-64`** (222px of content). Units go in the label row (Quote and Mkt cap "USD", P/E "x", Growth "%"; none on the score fields or Beta). Mkt cap has the hint "Type 500M or 2B."
4. **Range commit rule** is the one already built in `RangeField` (session 10, decision 6), unchanged.
5. **Applied indicator.** Orange stays as label text colour only. Each section header gets a neutral applied-count badge (no badge at zero), and chips show applied through their checked fill. The Watchlist scope label is orange only while the watchlist filter is in effect.
6. **Chips** (Speculative growth, BB + RSI entry) are `Checkbox` `variant="chip"` at full width with the inner check box kept. **`MultiSelectDropdown`** option checkboxes become the bare neutral `Checkbox`; its keyboard behaviour, focus handling and ARIA structure are not changed, and the docs no longer call it "full ARIA".
7. **Watchlist scope select** is a compact `FormField` with a full-size `Select`, the helper sentence as its hint, disabled and dimmed (label and hint together) when the universe is not All. Its label is "Limit results to", to avoid a second "Watchlist" under the section title.
8. **Reset also resets the sort**, and **the sidebar stays mounted on a universe switch** (decided in the plan entry above, done here).
9. **Sentence case, display only:** filter, chip and range labels and the sidebar's option labels. Sort labels and "Add to Watchlist" wait for a later session. Filter values, option keys, saved views and everything sent to or stored by the backend are unchanged.

**Live-behaviour changes delivered** (the only ones authorised):

- The `T` (trillion) suffix in Mkt cap (already live from the plan commits).
- The sidebar accepts `12.`, `.5`, lowercase and spaced suffixes such as `2 m`.
- Partial input: `-`, `.` and `-.` hold the previous value with no error while focused and become invalid (that side inactive) on blur; other invalid text (`1x`, `5e`, letters) makes that side inactive at once with an inline error.
- A reversed range shows one message under the pair ("Min is higher than max, so no ticker can match.") and marks only the Max box invalid; it still applies literally.
- Reset also resets the sort to the page's default field and direction.
- The sidebar stays mounted on a universe switch, so collapse state, the active saved-view name, a half-typed view name and range drafts survive.
- Mkt cap boxes show "1B"-style text after a collapse and reopen or a saved-view load.
- The lost-collapse-state bug on a universe switch is fixed (the same change as the sidebar staying mounted).

**Deleted with the migration, each after a grep showed no remaining user:** `RangeInput`, `MarketCapSideInput` and the strict `parseMarketCapInput` (commit 2); the `brand` `Checkbox` variant (neutral is now the default, `chip` is kept), the old `Field` component with its orange `applied` prop, the underline variants of `Input` and `NumberField` and `RangeField`'s `variant` prop, `Input`'s `inputVariants`, the styleguide's underline sidebar, underline preset column, "Brand" checkbox column and underline `Input` demos, and the "live sidebar still uses the old parser" caption (commit 5). The styleguide's Boxed-versus-underline comparison became a boxed-only reference.

**Known consequences, not regressions.** A collapsed section unmounts its content (Base UI's default), so a half-typed value is dropped on collapse, and invalid text (which the numeric filter state cannot hold) is gone after reopen; the numeric filter values are kept.

### 2026-09-30 — Session 10, part 3: Screener results controls (session 2 of 2)

The Screener controls left over from the sidebar migration move onto the kit. Made by the owner; this entry records what was decided and delivered. Spec: "Screener results controls (session 10, part 2)" in `docs/design-system.md`. Five commits on local `main`, not pushed: docs; characterization tests, sort and the outline buttons; pagination and the multi-select trigger name; the saved-views bar; styleguide and cleanup.

**Scope.** In: the results header (sort field and direction), `Pagination`, the saved-views bar (trigger, popover and list, the naming step, the overwrite confirm, Reset), `RecomputeButton`'s styling only, and the multi-select trigger's accessible name and caret. Out and unchanged: `AddToWatchlistButton` (**stays for the ticker-page session**; it is shared with the ticker header), `UniverseSelector`, `ScreenerCard`, the sidebar filters and `RangeField`, the backend and every non-Screener page.

**Decisions.**

1. **Sort field** is a `Select` with a real "Sort by" label; option labels are sentence case, display only (values, the `SortField` type and stored or sent data unchanged). The size token is `wide`: `medium` clips the longest label.
2. **Sort direction** stays one toggle button, `outline`, 36px like the select, with a Phosphor arrow plus "Asc" or "Desc" and an accessible name stating the direction and the action.
3. **Outline Button** replaces the "ghost plus `border-border-input hover:border-brand`" override in the Screener: Sort direction, Save current view, Reset and `RecomputeButton` (styling only).
4. **Pagination:** the current page is neutral selected with `aria-current="page"`, never brand blue; Previous and Next are Phosphor caret icons with accessible names. The page window, the disabled states and `PAGE_SIZE` are unchanged.
5. **Multi-select trigger:** accessible name "<label>: <summary>", a decorative `CaretDown`; its keyboard behaviour, option markup and focus handling are not touched.
6. **Saved-views bar:** Escape closes the popover and returns focus to the trigger; rows are real buttons with a separate named delete button; the active marker is neutral and exposed with `aria-current`; the naming step is a labelled boxed `Input` with Save and Cancel on their own row; the overwrite confirm wraps; sentence case throughout; the horizontal layout is deleted. No maximum name length (the backend has none).
7. **Names with "/" (verified, not assumed).** Saved, listed, loaded and deleted through the real routes on an in-memory database (the backend test client, then a real uvicorn process on a temporary in-memory database to confirm the test client's behaviour), sending each name the way the frontend does (`encodeURIComponent`): "a b", "a?b", "a#b" and "100%" all work, as do "+", a backslash, ";", "&", "a%2Fb" typed literally, and accented letters. **"a/b" is broken:** `PUT` and `DELETE` answer 404 because the server decodes `%2F` to "/" before routing, so such a view can be neither saved nor deleted. The naming input therefore rejects "/" with an inline message (text is never stripped or altered) and a test covers it; the backend is unchanged. Not verified: the Next.js `/api` rewrite in front of the backend (the brief limited verification to the backend test client).

**Live-behaviour changes authorised:** the visible "Sort by" label and sentence-case sort options; the direction button's icons and accessible name (and the loss of its `title` tooltip); neutral current page and icon Previous and Next; the multi-select trigger's accessible name and caret icon; keyboard-operable saved-view rows, Escape closing the popover and the neutral active marker; the naming step's layout and label; the overwrite row wrapping; the outline button styling; and the "/" guard.

**Delivered, and what differs from the brief's assumptions.**

- **Sort row** is a new `SortControls` component (it owns the sort options), rendered by the page. The Select is `wide` (320px): the longest label, "Warren signal recency", is about 146px at 14px Public Sans and a `medium` select has 130px of text room. The direction `Button` is `outline` at the default size, which is 36px (`size="sm"` is 32px for `outline`). The field's `id` comes from `useId` so two Sort rows can coexist (the styleguide has two).
- **Saved-views bar rows are real buttons** (a load button and a separate delete button per row), not `role="option"` rows, so the popover is a labelled `group` and the trigger a disclosure button (`aria-expanded`, `aria-controls`). While a delete is in flight the button uses `aria-disabled`, not `disabled`, so it keeps focus; after a delete focus moves to the next row, else the previous one, else the trigger.
- **The bar is 256px on the page, not 222px.** It sits in the sidebar outside the filter cards; 222px is only the card content width. It was built for 222px and fits both.
- **`SavedFiltersBar` is split** into the data-wired wrapper and `SavedFiltersBarView` (saved list, save and delete passed in, plus `default*` props for initial state) so the styleguide can render the real UI without touching the backend. The page and its tests use the wrapper unchanged.
- **Naming input:** the `View name` placeholder was replaced by the visible label (a label plus an identical placeholder is redundant), and the old `title` on the delete and direction buttons by accessible names that are also their tooltips.
- **Multi-select name versus visible text:** with several selected the name is "Sector: 3 selected" while the visible text is "Sector (3)"; the brief fixed the name and forbade changing the text, so they differ there.
- **Styleguide:** the "Screener sidebar (mock)" had its own hand-built Sort select, "↓ Desc" glyph button, "▾" text glyph and naming row (plan-time prototypes that contradicted the live page and the new rules); they are replaced by the real saved-views bar, and the mock has no Sort row (the live sidebar never had one).

**Deferred.** `AddToWatchlistButton` (ticker-page session). Other uses of the hand-written outline override outside the Screener (Watchlist, ticker page, Step 3 and Step 5 forms) migrate with their own pages.

### 2026-09-30 — Nightly cron chain reordered: technical first, fundamentals later

The daily chain now runs 2:00-3:30 AM UTC in this order: last close (2:00) → trend + Weinstein (2:05) →
Liquidity Zone (2:15) → BB+RSI (2:20) → Warren (2:25) → Sector ETF (2:35) → Market Breadth (2:40) →
corporate events (2:45) → FMP fundamentals (2:55) → analyst price-target (3:10) → score recompute (3:25) →
SQLite backup (3:30); monthly momentum (1st–5th) moved 3:05 → 2:50. Previously fundamentals and price-target
ran first (2:00/2:10) and the technical jobs at 3:10-3:40. Technical data is the higher priority, and nothing
technical depends on fundamentals. Hard constraints kept: trend fills the bar cache before LP/Sector/Breadth,
BB+RSI before Warren, recompute after the technical jobs and before the backup. Corporate events was not in the
requested order; placed after the technical jobs, before fundamentals. Order pinned by
`backend/tests/test_cron_wiring.py::test_nightly_chain_runs_in_the_agreed_order`. Known exposure: a cold-cache
fundamentals run (up to ~65 min) can overlap price-target; recompute and backup are cache-only and still run on time.

### 2026-10-01 — Technical nightly jobs moved to 12:00-12:40 AM UTC

Last close 2:00 → 12:00, trend + Weinstein 2:05 → 12:05, Liquidity Zone 2:15 → 12:15, BB+RSI 2:20 → 12:20,
Warren 2:25 → 12:25, Sector ETF 2:35 → 12:35, Market Breadth 2:40 → 12:40. Order and every hard constraint from
the 2026-09-30 entry above are unchanged; corporate events (2:45) onward did not move. Side effect: the Sunday
index-list refreshes (1:00-1:10) now ran after the technical jobs instead of before, so a constituent change was
picked up by the next night's technical run (one-day lag, Sundays only). **Superseded 2026-10-02 (next entry): the
refreshes now run at 12:00-12:10 AM, before the 1:00 AM chain, so the lag no longer exists.**

### 2026-10-02 — Tracked universe: a viewed-only ticker expires 30 days after its last view

**Supersedes** the 2026-08-06 "index + ever-viewed + watchlisted" decision, under which a ticker opened once stayed in
every nightly job forever (595 tickers on 2026-10-02: 518 index members, 13 watchlist-only, 64 viewed-only). Investigation:
`docs/tracked-universe-expiry-investigation-2026-10-02.md`; spec: `docs/specs/tracked-universe.md`. **Rule (owner):** in the
nightly universe only if (a) S&P 500 / Nasdaq-100 / Dow member, (b) on any watchlist, (c) in the system set (the 11 sector
ETFs plus SPY), or (d) viewed in the last 30 days; viewing re-adds it; nothing is deleted. **Added by the owner the same day:**
(e) a Moat rating, custom valuation or bank-capital entry never expires (Monthly Momentum would otherwise silently lose 29
of its 403 rows), and a delisted flag removes a ticker from every job at once.
**Mechanism:** one helper `data/tracked_universe.py::load_tracked_universe` read by every nightly and weekly job (the old
wide set stays as `load_all_known_tickers` for the non-US purge, the delisted sync, the search fallback and the backfills);
`TickerView(ticker, last_viewed_at)` written by `GET /summary` after it succeeds, at most once per ticker per day;
`init_db()` seeds it once for every existing ticker with the migration time (30 days of grace, idempotent). **User-facing
effects:** the Screener's default `all` universe hides expired rows (`ScreenerMeta.hidden_inactive`, shown in the page
subtitle; saved views just show fewer rows); the header score chip recomputes a row older than 36 h on view; the ETF
Overview fetches daily bars on view when the cache is empty or behind (about one call, on demand only). **Delisted
flag:** it is no longer permanent: the weekly sync clears it when the whole delisted list was read, the ticker is off it, and a
live `/profile` says `isActivelyTrading: true`. **Unchanged on purpose:** `prune_cache` (an expired ticker's cache rows go about
210 days after its last view; its score row stays), every cron time, Liquidity Zone/BB+RSI/Warren (monitored watchlists
only). **Effect (projected from the live DB):** universe 595 -> 590 on the first run (the 5 delisted leave at once) -> 563 on
day 31 (20 stocks and 7 ETFs expire); about 3 FMP calls per dropped ticker per night. **Open:** a future ETF momentum
universe must be added to `ETF_SEED_TICKERS` (`SYSTEM_TICKERS` was retired by the 2026-10-03 ETF cutover entry below).

### 2026-10-02 — Cron reschedule: Sunday block first, technical chain 1:00-1:40, fundamentals 2:00

All UTC (the box is UTC). Weekly index-list refreshes 1:00/1:05/1:10 → **12:00/12:05/12:10 AM Sunday** and the Sunday
maintenance jobs (prune_cache, rotate_logs, audit_fixture_contamination, stale_data_health_check, purge_invalid_tickers)
1:15-1:35 → **12:15-12:35 AM**. The daily technical jobs moved one hour later, minute offsets kept: last close 1:00,
trend + Weinstein 1:05, Liquidity Zone 1:15, BB+RSI 1:20, Warren 1:25, Sector heatmap 1:35, Market Breadth 1:40.
Fundamentals 2:55 → **2:00**. Unchanged: momentum 2:50 (1st-5th), price-target 3:10, score recompute 3:25, backup 3:30.
**Why:** the 2026-10-01 move to 12:00-12:40 had pushed the Sunday refreshes after the chain (constituent changes a night
late); the Sunday block now runs first again, and the chain starts with a clean hour. Fundamentals at 2:00 keeps it away
from price-target: a 64.5-minute run (the worst seen, 2026-09-15) ends ~3:04, 5.5 minutes before 3:10 and 20 minutes before
the 3:25 recompute (the 44.6-minute 2026-10-01 run ended ~2:45). **Measured margins:** Sunday block ends by ~12:33 (the
slowest, stale_data_health_check, max 2.6 min) against a 1:00 start; the chain ends by ~1:45 in the worst case (Warren's
9-minute theoretical), so 1:45-2:00 is clear. **Overlaps:** momentum (2:50, days 1-5, 4 calls, ~10 s) overlaps fundamentals
only on a run longer than 50 minutes, negligibly. **Corporate events** stays disabled (2026-10-01 entry); its planned
re-enable slot is **1:50 AM** so it ends before fundamentals starts and never overlaps it (its 406-527 requests/min is over
Starter's 300/min). Pinned by `test_cron_wiring.py` (order, Sunday block before the chain, fundamentals + 65 min <=
price-target) and `JOB_METADATA` labels/`sort_minutes`. Transition: applied 2026-10-02 after the night's run, so no job ran
twice or was skipped; the first run on the new schedule is 2026-10-03 1:00 AM (daily) and Sunday 2026-10-04 12:00 AM (weekly).

### 2026-10-02 — Honest nightly job status: no_data vs failed, one shared failure threshold, messages on the five silent jobs

Findings in `docs/nightly-failures-and-schedule-ui-2026-10-02.md`. **The problem:** the price-target job read "Success" with
"8 failed" (16 on 2026-10-02), but every one of those was an HTTP 200 with an empty body (ETFs and thinly covered stocks have no
analyst targets), and the page only turned red when every ticker failed, so a real regression would have been invisible
against a standing "8 failed". Five jobs also showed no message at all. **Decided:** (1) the price-target job skips known ETFs
and funds (the `nightly_fundamentals_fetch` filter) and classifies the rest written / no_data / failed, message "N written, M no
analyst data, K skipped (ETF), F failed", 24-hour cache unchanged; (2) one shared helper,
`core.cron_health.check_failure_threshold`, marks a run failed (the existing red state) at failed/attempted >= **5%** or when
everything fails, with the rate rule only from **25 attempted** so one stray error never flips a run (1/25 = 4%; two do);
no_data and skip counts are message-only; (3) fundamentals, BB+RSI, Warren, score recompute and backup_db set a short message
(counts or sizes), and the first four feed their per-ticker failures to the same helper; (4) the Scheduled Jobs Time cell
wraps (`whitespace-normal`, the precedent of the Description and Message cells) so "1st–5th, 2:50 AM" no longer spills 19px
into the Status column. **Rejected:** a new "partial/warning" health value (touches the API type, the pill map, the tests and
the design system's Status table); counting no_data in the threshold; widening the Time column (takes room from Message and
stays fragile); dropping PARA or any ticker (a separate expiry task covers strays). **Known limit:** fundamentals only counts
exceptions that escape a ticker's refresh; per-statement FMP errors swallowed inside `get_stepN_data` are not visible to it.
Cron times unchanged.

### 2026-10-01 — nightly_corporate_events disabled pending investigation

The job's crontab line is commented out (`backend/crontab.txt`, and the installed crontab via `crontab crontab.txt`;
the pre-change crontab is saved as `backend/crontab.backup-2026-10-01.txt`). **Reason:** it makes about 1,165 FMP
calls per run (2 per ticker, `/earnings` + `/dividends`, about 1,770 on the weekly splits night) at 406 to 527
requests per minute (concurrency-bound, 10 per second at peak), over the Starter tier's 300 per minute; the owner is
investigating why and will decide separately how to bring it back. Nothing else moved (the reschedule is paused).
**Mechanism chosen:** comment out the cron line, plus one entry in `core/cron_health.py::DISABLED_CRON_JOBS` so the
Scheduled Jobs page shows the job as the neutral "Skipped" pill with "Disabled since 2026-10-01: ..." instead of
"Overdue" after 36 hours; `test_cron_wiring.py` requires a job in that dict to be absent from `crontab.txt` and every
other job to be present, so the two cannot get out of step. **Rejected:** switching the `corporate_events` data group
off in Settings (documented, and the job then records a real `skipped` run, but the state lives in the DB, not in git or
the crontab, and the process would still start every night); deleting the job from `CRON_JOB_NAMES`/`JOB_METADATA` (hides
it from the page and makes re-enabling a four-place edit); a new "Disabled" health value (touches the API type, the
frontend pill map and `/styleguide`). **What degrades:** the Chart tab's E/D markers (the cache's only reader) keep
serving the cached rows; only the newest ones go missing (see `docs/specs/corporate-events.md`, "Disabled"). Code, cache
and data are untouched. **Re-enable:** uncomment the line, delete the `DISABLED_CRON_JOBS` entry, `crontab crontab.txt`
from `backend/`, check `crontab -l`. The "corporate events after the technical jobs and before fundamentals" test is
skipped while the job is disabled and is live again on re-enable.

### 2026-09-30 — Session 11: Watchlist page and shared buttons

The Watchlist page controls and the two buttons shared with other pages move onto the session 8 to 10 primitives. Made by the owner; this entry records what was decided and what was delivered. Spec: "Watchlist page and shared buttons (session 11)" in `docs/design-system.md`. Four commits on local `main`, not pushed: docs; characterization tests and the Watchlist page; `RefreshButton` and `ExportMenu`; styleguide and cleanup.

**Scope.** In: `WatchlistNameEditor`, `WatchlistDeleteButton`, the buttons in `WatchlistTable` (remove, confirm, cancel), `ExportMenu` and `RefreshButton`. Out and unchanged: `AddToWatchlistButton` (**stays for the ticker-page session**; shared with the ticker header), the ticker-page components (`ManualCalculationPanel`, `BankCapitalMetricsForm`, `EconomicMoatTab`, the chart and price-target toggles), `TickerSearch`, the Screener, Settings, Momentum, the backend, and table cell content.

**Decisions (the owner's; not re-decided).**

1. Every "ghost plus border" hack or hand-written bordered button in scope becomes `Button variant="outline"`; the size follows the neighbours (36px beside inputs, `sm` 32px in dense rows).
2. Text glyphs become Phosphor icons; icon-only buttons have an accessible name and keep their tooltip; decorative icons are `aria-hidden`.
3. `WatchlistDeleteButton` keeps every behaviour and takes the destructive `danger` Button.
4. `WatchlistNameEditor` uses the kit `Input` with no class overrides, the accessible name "Watchlist name", no `focus:outline-none`, `maxLength` mirroring the backend, and shows server rejections inline.
5. `ExportMenu` gets an outline trigger with a `CaretDown`, `aria-haspopup` and `aria-expanded`; Escape and outside click close it (only what was missing is added).
6. `RefreshButton` is styling and icon only.
7. Sentence case, display only, for every string in the touched components.

**Decision made while building (recorded, not in the brief).** `Button` gained two square icon sizes, `icon` (36px) and `icon-sm` (28px, 32px as an outline). The alternative was an `px-0` and width override repeated on five buttons.

**Live-behaviour changes authorised:** the outline button styling and icons; accessible names; the rename input showing server messages inline and mirroring the backend limit; `ExportMenu` Escape and focus return if missing; sentence-case strings. Nothing else.

**Delivered, and where the brief and the code differed.** The code was ground truth:

- `WatchlistDeleteButton` never used `window.confirm`; its confirm is an inline state (idle, asking, deleting, error). Kept exactly.
- The rename input already showed the server's message (`errorDetail`, with the duplicate-name 409 as "already exists"), already had `maxLength` 100, Enter to save and Escape to cancel, and an `aria-label` of "Watchlist name". Delivered: the kit `Input`, the shared `WATCHLIST_NAME_MAX_LENGTH` (`lib/watchlistName.ts`; the backend `WatchlistName` is 1 to 100 characters after stripping), the invalid style and a linked `role="alert"` message.
- `ExportMenu` already closed on Escape (from the trigger and from an item) with focus returned, and on an outside click; it never had arrow-key navigation. Nothing to add; tests pin it.
- `RefreshButton` has a fourth state, "Refreshed ✓"; the glyph became a `Check` icon.
- The trash and pencil triggers were unbordered icon buttons; they became `ghost` icon buttons (the trash turns `danger` after a failed delete, so the error cue is kept).
- Four components gained optional styleguide seams (a swappable request and a starting state) so the mock cannot reach the backend; the real pages pass none.

**Deferred.** `AddToWatchlistButton` and the rest of the ticker page (the remaining hand-written outline overrides are all in ticker-page files) migrate in the ticker-page session, and `AddToWatchlistButton` should adopt the shared watchlist-name length constant then.

*Update 2026-10-01: completed by sessions 12 to 15 (`AddToWatchlistButton` and the shared constant in session 12; the rest of the ticker page in sessions 12 to 15). The text above is the record of what was deferred, not what is left.*

### 2026-10-01 — Session 12: ticker page controls, part A

Stage 2 of 4 of the ticker page. `AddToWatchlistButton`, `BankCapitalMetricsForm` and the Economic moat tab's Cancel button move onto the session 8 to 11 primitives. Made by the owner; this entry records what was decided before the build. Spec: "Ticker page controls, part A (session 12)" in `docs/design-system.md`. Three commits on local `main`, not pushed: docs; `AddToWatchlistButton` (characterization tests and the migration); `BankCapitalMetricsForm` and the Moat button (the same).

**Scope.** In: the three components above. Out and unchanged: `ManualCalculationPanel`, `TickerSearch`, the chart and price-target toggle buttons, both `SegmentedControl`s, the Screener files (only verified, since `AddToWatchlistButton` renders in its results header), `TickerHeader` beyond verifying its layout, Settings, the Watchlist page, the backend and `components/ui` itself.

**Decisions (the owner's; not re-decided).**

1. **`AddToWatchlistButton` trigger** is `Button variant="primary"` at 32px, the height of today's hand-rolled brand button and of the outline `RefreshButton` beside it in the ticker header and the Screener results-header buttons. Computed heights are checked in both places. (The brief called this `size="sm"`; in the code primary at `sm` is 28px, only `outline` at `sm` is 32px, so the build adds `h-8` on the button. See the session report.)
2. **Every other bordered hand-written button in the popover** becomes `outline` (secondary) or `primary` (the single confirming submit), at the size the popover fits; its width and structure stay. Text glyphs become Phosphor icons ("Added ✓" is a `Check` plus "Added"); icon-only buttons get an `aria-label`.
3. **New-watchlist input** is the kit `Input` (no class overrides, no `focus:outline-none`) named "New watchlist name", with `maxLength` from `WATCHLIST_NAME_MAX_LENGTH`. This **adds** a limit: the backend `WatchlistName` allows 1 to 100 characters after trimming, and the old input had none. Trimming and the empty-name rule are unchanged; a server rejection shows inline, linked to the input, with the shared `errorDetail` message.
4. **Popover behaviour is unchanged** (which lists show, toggling membership, create-and-add, loading and error states, closing after success). Escape closes it and returns focus to the trigger, and an outside click closes it; each is added only if missing.
5. **`BankCapitalMetricsForm`:** the two native `type="number"` inputs become `NumberField` (typed only, no stepper, "%" unit, optional) and the two text inputs become `Input` in a `FormField`, each with a visible sentence-case label and an inline error; the uppercase wide-tracking label style goes; nothing is silently clamped or corrected. Bounds mirror only what the backend enforces (nothing: both ratios are plain optional floats) and unenforced browser hints are dropped. The hand-rolled container becomes the kit `Card`; its secondary button becomes `outline`; every `focus:outline-none` goes. Save logic, payload, endpoint and cache invalidation stay identical (numbers stay numbers). A non-numeric entry blocks Save with an inline error and never leaves a sticky failure; a server rejection shows its message inline.
6. **Economic moat tab:** only its hand-written bordered Cancel button becomes `outline`, plus sentence case for that button's strings and its immediate label. Its `SegmentedControl`, card structure and everything else are untouched (the `SegmentedControl` merge is a later session).
7. **Sentence case, display only,** for every string in the touched components. Identifiers, stored values and what is sent to the backend are unchanged.

**Live-behaviour changes authorised:** button and input styling and icons; accessible names; the new-watchlist length limit and its inline server error; popover Escape and focus return if missing; the Bank form's native spinners and scroll-wheel changes gone, typed validation with inline errors and sentence-case labels; sentence-case strings. Nothing else.

**What remains after this session.** `ManualCalculationPanel` (the last hand-written ghost-plus-border button and `focus:outline-none` inputs among the ticker-page files), the confirm buttons in the Bank and Moat save panels (warn-toned, hand-written), the Moat tab's uppercase headings, both `SegmentedControl` implementations (to be merged), `TickerSearch` and the chart and price-target toggles.

*Update 2026-10-01: completed by sessions 13 to 15 (`ManualCalculationPanel` in session 13; the segmented-control merge, `TickerSearch` and the toggles in session 14; the Confirm buttons and the Moat headings in session 15).*

### 2026-10-01 — Session 13: ticker page controls, part B

Stage 3 of 4 of the ticker page. `ManualCalculationPanel` (`components/step3/ManualCalculationPanel.tsx`, the right-hand "Custom valuation" card on the Valuation tab; the left card is `Step3Card`'s read-only Model Valuation) moves onto the session 8 to 12 primitives. Made by the owner; this entry records what was decided before the build, and "Delivered" below it records what the code does. Spec: "Ticker page controls, part B (session 13)" in `docs/design-system.md`. Three commits on local `main`, not pushed: docs; characterization tests plus the method select, the formatted rows and the two `focus:outline-none` controls; the action buttons, the slider accessibility and the remaining sentence-case strings.

**Scope.** In: `ManualCalculationPanel` only. Out and unchanged: its calculation logic, formulas, defaults, number parsing and formatting results, the endpoints it calls and their payloads, `Step3Card` and every other component, `components/ui` and `lib` (the primitives are used as they are; a control a primitive cannot serve stays unmigrated and is listed), `TickerSearch`, the chart and price-target toggles, both `SegmentedControl`s, the Screener, Settings, Watchlist, `app/styleguide`, the global CSS and the backend.

**Decisions (the owner's; not re-decided).**

1. **Method select** is the kit native `Select` with a size token that fits the longest option label, a real visible label in sentence case, and no `focus:outline-none`. The option values, their order and what changing the method does to the rest of the panel are identical.
2. **Formatted text rows** become `NumberField` (typed only, no stepper, a unit suffix, `optional` where empty is valid) only if the row's current parse and format behaviour can be preserved exactly. Otherwise the row keeps a text control, the kit `Input` inside the `FormField` wiring, with its parse and format code unchanged, a visible label, an inline error for text that does not parse, and no silent clamping or correction. No bounds are invented: only a bound the code or the backend already enforces is mirrored, and browser-only `min`/`max` hints that nothing enforced are dropped (each reported). A row that cannot be converted without changing behaviour is left as it is and listed with the reason. What is sent to the backend and the calculation result never change.
3. **Range sliders** keep the `.range-slider` styling and behaviour. Added: an accessible name, `aria-valuetext` where the displayed value differs from the raw number, a visible keyboard focus ring (no `outline-none`), and the native arrow-key behaviour left alone. They are not replaced and the global CSS is not edited.
4. **The hand-built bordered buttons** become `Button`: `outline` for secondary actions, `primary` only for the single confirming action, at the size that matches the neighbouring controls. Text glyphs become Phosphor icons (`aria-hidden`), with an accessible name on any icon-only button.
5. **The `outline-none` controls** lose it and use the kit `Input` or `NumberField`.
6. **Sentence case, display only,** for every label, button, heading, tooltip and placeholder in the panel. Identifiers, stored values and everything sent to the backend are unchanged.
7. **Layout and spacing stay** unless a primitive forces a small change. Below `lg` the panel behaves as today. Nothing sets `focus:outline-none`, and every control has an accessible name.

**Live-behaviour changes authorised:** kit styling, labels, units and icons; accessible names and `aria-valuetext`; inline errors for text that does not parse; native browser `min`/`max` hints and spinners removed where present; sentence-case strings. Nothing else, and in particular no calculation input parses to a different number than it does today.

**Delivered, and where the brief and the code differed.** The code was ground truth:

- **Six hand-built bordered buttons, not three.** Save, Revert to auto and the delete confirmation's Cancel were the plain "ghost plus border" ones. Activate, Delete and Confirm delete were tone-tinted (positive and negative), a different hand-written pattern. All six moved to `Button`, because leaving three at their old 26px beside three 32px buttons in the same bar would have made a row of mixed heights. Save is the one `primary`; Revert to auto and Cancel are `outline`; Activate and Delete are `outline` with their tone kept as colour classes (the session 11 precedent); Confirm delete is `danger`. None was an icon or a glyph, so none gained an icon.
- **One `outline-none` text input and one select**, not two inputs: the formatted row's box and the method select. Both are gone.
- **The sliders have no paired text box.** Each is one native range input with a label and a readout; there is nothing to sync. Their values are strings of percentage points, sent divided by 100.
- **No row became `NumberField`.** A row shows formatted text ("$48,253.00", "+35.0%") while idle and the raw number while focused, which `NumberField` cannot do, and it parses with `parseFloat`, which accepts text `NumberField` rejects ("12abc", "1e3", "+4"). Every one of the ten rows (four for each cash-flow method, three for price to book, three for price to sales growth) stays a text `Input` with its parse and format code unchanged.
- **Inline error semantics.** The new "Enter a number." line appears only for non-empty text the existing parse reads as nothing at all (it was silently sent as `null`), and never blocks Save or the calculation. Two older behaviours are deliberately **not** changed and are listed for the owner: text that `parseFloat` cuts short is still read as its leading number ("12abc" is 12, "1,234" is 1, "1e3" is 1000, with no warning), and Save still saves an unreadable row as `null`.
- **The slider focus ring** was removed by the global `.range-slider:focus { outline: none }`, which is in the components layer. Utility classes on the input restore it (the utilities layer sorts after it), so no global CSS changed.
- **The method select** is `wide`. It fits the nine built-in labels but not always the saved "<method> · custom" entry (see the design-system section for the numbers), and with the visible label the title row now wraps under the title below a window of about 1200px, where the old compact select wrapped only below about 910px. Left as built; a narrower token would clip most labels.
- **`errorMessage`** now calls the shared `errorDetail` from `lib/api/client` (the same "after ' - '" rule, the action's own fallback otherwise); behaviour is identical.
- **The left Model Valuation column** (`Step3Card`, not in scope) still has Title Case labels ("Growth Yr 1-5", "Total Debt", "Discount/Premium"), so the two columns now differ in case, and a comment there still describes the title row's "h-8 method select". Both wait for that component's own session.
- **Tests.** `ManualCalculationPanel.test.tsx` is new (the panel had none): 98 tests, written and green against the unmodified panel before any control changed. Selectors match labels case-insensitively, so the migration needed no selector update; the one string that changed with the sentence-case commit is the Revert button's text.

**What remains after this session.** The confirm buttons in the Bank and Moat save panels (warn-toned, hand-written), the Moat tab's uppercase headings, both `SegmentedControl` implementations (to be merged), `TickerSearch` and the chart and price-target toggles. Nothing in the panel is left unmigrated (the sliders keep their custom styling by decision); the unresolved items are the two `parseFloat` behaviours listed above.

*Update 2026-10-01: completed by sessions 14 and 15 (the Confirm buttons, the segmented-control merge, `TickerSearch` and the toggles; the `parseFloat` prefix reading now shows a warning, session 14). The "h-8 method select" and Title Case notes about `Step3Card` were cleared in session 15.*

### 2026-10-01 — Session 14: ticker page and shell controls, part C1

Stage 4a of 5. The four behaviour-bearing items left after session 13: `TickerSearch`, the chart and price-target toggles, the `SegmentedControl` merge, and the slider focus rule plus the manual-calculation parse warning. Made by the owner; this entry records what was decided before the build. Spec: "Ticker page controls, part C1 (session 14)" in `docs/design-system.md`. Four commits on local `main`, not pushed: docs; `TickerSearch` and the toggles (characterization tests and the migration); the merge; the slider rule and the warning.

**Scope.** In: `components/nav/TickerSearch.tsx`, the toggle buttons in `ChartTab` and `PriceTargetTrendChart`, both `SegmentedControl` implementations and their call sites, the `.range-slider:focus` rule in `app/globals.css`, and the parse code in `ManualCalculationPanel`. Out and unchanged: the search logic, ranking, debounce, API calls and navigation; chart data and series; the Screener, Settings and Watchlist; the Screener "Add to Watchlist" label, `Step3Card` labels, the remaining glyph icons and the Bank and Moat Confirm buttons (all C2, the next session); the backend; `app/styleguide`.

**Decisions (the owner's; not re-decided).**

1. **`TickerSearch`** input is the kit `Input` (boxed, no class overrides, no `outline-none`), with every combobox attribute and handler as it was, an accessible name ("Search ticker") and its width kept. The height is the kit's 36px unless that would change the nav height. The results panel's markup and behaviour are unchanged apart from any `outline-none`, and the active option keeps a visible indicator. Nothing about results, order, debounce, fetches or navigation changes.
2. **Chart and price-target toggles** are classified with "Choosing the right control". A choose-one set (the chart range) is a `SegmentedControl`. An independent on/off overlay is a `Switch` with a visible sentence-case label if it fits the toolbar without changing its height; if not, an `outline` `sm` `Button` with `aria-pressed` and a neutral selected state (`surface-2` fill, `text-primary`), never brand blue. Behaviour, defaults and persisted state are identical.
3. **One `SegmentedControl`**: `components/ui/segmented-control` (neutral selection, principles 2 and 3). Every call site of `components/shared/SegmentedControl` moves to it, keeping option values, labels, `onChange` meaning and layout; the kit control is extended only additively and only if a call site needs it. The shared one and its tests are deleted after a grep shows no importer. Labels at the migrated call sites are sentence case, display only. The selected state at those call sites changes from brand blue to neutral.
4. **Slider focus rule.** The global `.range-slider:focus { outline: none }` becomes a rule that removes the outline only when `:focus-visible` does not match, so a keyboard focus shows the global 2px `brand` ring and a mouse focus shows nothing. No other slider styling changes. The session 13 utility-class workaround on the Custom valuation sliders is removed only if the ring is still there through the global rule alone.
5. **Parse warning** (non-blocking, `warn` tone). When a Custom valuation row's trimmed text is non-empty, `parseFloat` reads a number, but `Number(text)` is `NaN` (a prefix was read: "12abc" is 12, "1,234" is 1), the row shows a polite inline line linked to its input with `aria-describedby`: "Read as 12. Check the text.", or "Read as 1. Remove the comma." when the text contains a comma. None for fully numeric text ("1e3", "+4"), for empty text, or for "-", "." and "-." while the box is focused. The existing "Enter a number." error stays for text that reads as nothing and takes precedence. The warning never blocks Save or the calculation and never changes what is parsed, sent or calculated: the session 13 golden scenarios still pass unchanged.

**Live-behaviour changes authorised:** the kit input and focus ring on the ticker search; toggle and segmented-control styling and semantics as classified above; the brand-blue selected state replaced by neutral at the migrated segmented-control call sites; the keyboard slider focus ring; the new parse warning; sentence-case labels at touched call sites. Nothing else.

**Delivered, and where the brief and the code differed.** The code was ground truth:

- **No `aria-activedescendant` existed** on the search box (the options have no ids), so there was none to keep; none was added. The highlighted option is shown with `aria-selected` and a `surface-2` fill, and focus stays in the input.
- **The search box is 36px, not matched to the nav links.** The nav is a fixed `h-12` (48px) and the kit `Input` is 36px (the old one was 32px; the links are 33px), so the nav height cannot change and the kit height was kept rather than a one-off size. The width moved to the wrapper (the kit has no 160px or 224px token).
- **ArrowUp from "nothing highlighted"** lands on the second-to-last result (the index starts at -1), an old quirk pinned by a test and left alone. *Fixed in session 15: it now goes to the last result.*
- **Re-clicking the selected chart range** used to reset the zoom (the old buttons called the handler whatever the state); the kit control ignores a re-click, so it no longer does. Every other segmented call site was unaffected, because their handlers were no-ops for the same value.
- **The ten chart overlays are `outline` `sm` buttons, not switches**, because a row of labelled switches always wraps (see the design-system section); the toggles row is 32px high where the old text buttons were 25px. The Zoom in and Zoom out buttons were not toggles and were left as they were. *Moved onto `Button` in session 15.*
- **The parse warning follows the brief's rule exactly** (`parseFloat` reads a number but `Number()` does not), so text `Number` accepts but `parseFloat` reads differently ("0x10" is read as 0) shows no warning.
- **The sliders' session 13 utility classes were removed**: the global rule alone gives the keyboard ring.
- **Tests.** `TickerSearch`, `ChartTab`, `FinancialsTab` and `SentimentOverTimeCard` had none and gained characterization tests written green against the old code; `EconomicMoatTab` gained three. Selector updates: the moat segments are matched by their sentence-case names, the price-target overlay is found as a `switch`, and the segmented call sites check `aria-pressed`.

**What remains after this session (C2).** The Screener "Add to Watchlist" label, `Step3Card`'s Title Case labels, the remaining text-glyph icons, and the warn-toned Confirm buttons in the Bank and Moat save panels. The exact file and line lists are in the session report.

*Update 2026-10-01: completed by session 15.*

### 2026-10-01 — Session 15: ticker page and shell controls, part C2, cleanup sweep

Stage 4b of 5. The leftovers from sessions 12 to 14. Made by the owner; this entry records what was decided before the build and "Delivered" records what the code does. Spec: "Ticker page controls, part C2 (session 15)" in `docs/design-system.md`. Four commits on local `main`, not pushed: docs; accessibility and icons; sentence case and the multi-select name; buttons and cleanups.

**Scope.** In: the two Speculative growth icon buttons; every emoji and text-glyph control found by grep; `Step3Card`'s labels, the Screener "Add to watchlist" label and the Economic moat tab's headings; `MultiSelectDropdown`'s trigger name; the `Button` `primary` `sm` size; the Bank and Moat Confirm buttons and the Chart tab's Zoom buttons; `AddToWatchlistButton`'s focus after Cancel; the ticker search's ArrowUp; and stale comments and docs. Out and unchanged: search logic, ranking and fetching; chart data; calculation logic; the backend; `app/styleguide`; the status labels "Saved ✓" and "Recomputed ✓" (they stay as status text); the pills' "▲ ▼", the "⚠" text glyph in table and metric cells and the chart-label arrows (content, not controls); the chart range's re-click behaviour (left as it is).

**Decisions (the owner's; not re-decided).**

1. Both icon buttons lose `focus:outline-none`, so the global 2px `brand` `:focus-visible` ring shows; nothing else about them changes.
2. Each warning emoji becomes the Phosphor `Warning` icon (`aria-hidden`, in the existing tone class) with the text, layout and any accessible name kept.
3. "Hide details −" and "Hide reasoning −" become text plus `CaretUp` (expanded) and `CaretDown` (collapsed); the heatmap "↓ ↑", "Browse by sector →" and "Live →" become `ArrowDown`, `ArrowUp` and `ArrowRight`. Behaviour, links and sorting do not change; a glyph that is content rather than a control is left and reported.
4. Sentence case, display only: `Step3Card`'s labels (consistent with the Custom valuation panel), the Screener's "Add to watchlist" and the Moat tab's headings (the uppercase tracking removed). No identifier, stored value or payload changes.
5. The multi-select trigger's visible text must be contained in its accessible name in all three states (WCAG label-in-name), by the smallest change; the 21 keyboard tests stay.
6. `primary` at `sm` is 32px by a compound variant, and `AddToWatchlistButton`'s `h-8` goes. If any usage would shift layout, the compound variant is not used and a new explicitly named size is added instead.
7. The Bank and Moat Confirm buttons become `Button` (`primary` for the confirming action, the warn tone kept where it says the action overwrites), sized to match their neighbours; Zoom in and Zoom out become `outline` `sm` buttons (icons if icon-only, text if they have visible text). Behaviour, disabled states and payloads are unchanged.
8. Small fixes: the stale comment in `lib/watchlistName.ts`; focus returns to the "New watchlist" row button after Cancel in the naming step (with a test); ArrowUp with nothing highlighted goes to the last result (with a test, replacing the test that pinned the old behaviour).
9. Stale docs: Housekeeping item 5, the "what remains" notes in the Session 11, 12 and 13 entries (dated notes, not rewritten history), the comment in `UniverseSelector.test.tsx`, and the `Step3Card` comment about an "h-8 method select".

**Live-behaviour changes authorised:** the keyboard ring on two icon buttons; icons replacing glyphs and emoji; sentence-case labels at the listed places; the multi-select trigger's name; the 32px `primary` `sm`; the Bank, Moat and Zoom buttons on `Button`; focus return after Cancel; the ArrowUp fix; corrected comments and docs. Nothing else.

**Final state.** After this session no source file hand-writes a ghost-plus-border button except the two Screener dropdown triggers (see the session report for the final sweep, which lists every remaining hit and whether it is deliberate).

### 2026-10-01 — Session 16: ticker page and shell controls, part C3

Stage 4c of 5. Two bugs the owner saw in the browser, then the leftovers of session 15's final sweep. Made by the owner; this entry records the scope and the decisions, the two root causes, and "Delivered". Spec: "Ticker page controls, part C3 (session 16)" in `docs/design-system.md`. Four commits on local `main`, not pushed: docs; the two bug fixes; neutral selection, tabs and accessible names; the two Screener triggers.

**Scope.** In: the two Speculative growth tooltips and any other `role="tooltip"`; the expanded Analysis cards and every card with the same Show or Hide pattern; brand blue as a selected or current state in `TopNav`, `BreadthSectorTabs`, the `FinancialsTab` statement strip, the `ScheduledJobsSection` group strip and `SectorHeatmapGrid`'s active column; moving the two strips onto `Tabs` where it fits; `SecCellCheckButton` and any other icon-only button with a title and no `aria-label`; the `SavedFiltersBar` and `MultiSelectDropdown` triggers. Out and unchanged: the heading casing and uppercase caption sweep (dropped), search logic, chart data, calculation logic, the backend, `app/styleguide`, the status labels "Saved ✓" and "Recomputed ✓", the two `window.confirm` calls in Settings FMP, pill and cell glyphs, and every control or label not listed.

**Root causes.**

1. **Tooltip overflow.** `TickerHeader.tsx` puts the Speculative growth pill and its two icon buttons in one `inline-flex whitespace-nowrap` group "so they never split" (added by `c4beedc`, the pill-family session, 2026-09-29). The tooltip bubbles (`SpeculativeGrowthInfoIcon` and `SpeculativeGrowthFakeGrowthWarning`, from `2a37bc3` and `555606a`, `w-64` and `absolute`) are descendants of that group and never set `white-space`, so they inherited `nowrap`: the bubble stayed 256px wide and its text ran on as one line past its right edge. Session 15 (`d8f1f9a`) only removed `focus:outline-none` from the two buttons and did not cause it.
2. **Details misalignment.** `AnalysisSectionCard` rendered the row (score column `w-52`, gap 1rem, text column) inside the `CollapsibleTrigger` button and the reasoning list outside it as a sibling, indented by a hard-coded `pl-[10.4rem]` (80% of the score column, "roughly under the title"). The text column starts at 13rem + 1rem = 14rem, so the list started 3.6rem to its left. It dates from the Analysis-tab restyle (`2c77c52`); the C2 glyph-to-icon change (`d8f1f9a`) touched only the toggle's label and caused nothing. `ChecklistCard` has no side column and was already aligned.

**Decisions (the owner's; not re-decided).**

1. Every hand-built tooltip bubble sets `whitespace-normal`, has a width bound that never passes the viewport, keeps its padding and tone, sits above the tabs row, and is not clipped by an `overflow-hidden` ancestor. CSS classes only; no positioning library.
2. Expanded content goes inside the same text column as the title and paragraph, list-outside with padding, the toggle stays top right, and the collapsed state looks as it did.
3. A current or selected navigation item is neutral (a `surface-2` fill or an underline, with `text-primary`) with `aria-current="page"` on current links, never colour alone; brand blue stays for real actions and links.
4. The two hand-rolled strips move to `Tabs` if it expresses their behaviour without changing it.
5. An icon-only button has an accessible name; the `title` stays.
6. The Saved views trigger is an outline `Button` with a `CaretDown`; the multi-select trigger is the kit's boxed look; hover never turns the border brand blue.

**Delivered.**

- **Tooltips.** Both bubbles are `whitespace-normal`, `w-64` capped at `min(18rem, 100vw - 2rem)`, `z-30`, with the same padding, border and tone. From `md` they stay centred under the icon. Below `md` the icon wrapper is `static` and the header's pill row is `relative`, so the bubble starts at the row's left edge and is at most `min(20rem, 100%)` wide, which keeps it inside the screen (at about 375px the centred bubble can pass the right edge when the icon wraps near it; computed, not measured). No other `role="tooltip"` exists.
- **Details alignment.** `AnalysisSectionCard` is now `[score column] [text column]`, with the toggle in the text column's header row and the list below the paragraph in the same column: its left edge equals the paragraph's, in both states. The list is `pl-5` list-outside (the marker hangs in the padding, the text is indented one step). The card stays clickable anywhere in its header through the toggle's stretched `::after`; the list is `relative` above it. `ChecklistCard` was already aligned and is pinned by a test. There is no narrow-width stacking breakpoint in the code to follow.
- **Neutral selection.** `TopNav` and `BreadthSectorTabs`: `surface-2` fill, `text-primary`, `aria-current="page"` (the Breadth tabs keep `role="tab"` and `aria-selected`; their hover is text only so it never reads as selected; the Ticker Analysis indicator is a non-link span that carries `aria-current` on a ticker page). `SectorHeatmapGrid`: the active column header is `text-primary` (arrow and `aria-sort` as before). The design-system table said TopNav's current item is "underlined"; it is now the fill, which has no layout effect in the fixed 48px nav.
- **Tabs.** Both strips are `Tabs`: Financials "Financial statement", Scheduled jobs "Job cadence" (counts through the `count` figure). `Tabs` gained one optional `aria-label` prop. The labels stay as they were ("Income Statement" and so on: the casing sweep is dropped).
- **Names.** `SecCellCheckButton`: "Check SEC EDGAR figure for income taxes paid, period ending 2025-09-27" (or "interest paid"); `title` kept; icon `aria-hidden`.
- **Triggers.** Saved views: `Button variant="outline" size="sm"` (32px, as before) with `gap-1.5` and `hover:border-border-input`. Multi-select: `FIELD_BOX_CLASS` at full width, 36px (it was 32px and content-wide, so each of the nine triggers in the sidebar is 4px taller), `text-sm`. Neither trigger's border turns brand on hover: the multi-select is a field with no hover border, and the Saved views trigger is the one outline `Button` that overrides the documented "outline turns brand on hover" (the owner asked that neither trigger does), so it now differs from the Save current view and Reset buttons beside it.

**Live-behaviour changes authorised:** tooltip wrapping and bounds; details alignment; neutral selected states at the five places; `Tabs` where it fits; accessible names; the two trigger restyles. Nothing else.

**Final state.** No source file selects or marks a current item with brand blue, hand-writes a ghost-plus-border button, sets `outline-none`, or has an icon-only button without an `aria-label`. The remaining `brand` uses and glyphs, each with why, are listed in the "What is left after session 16" bullets in `docs/design-system.md`.

### 2026-10-01 — ETF page (Task B)

Built from `docs/etf-page-investigation-2026-10-01.md`; full behaviour in `docs/specs/etf-page.md`. Decisions worth keeping:

- **One endpoint, no holdings.** `/etf/info` only (it already carries the sector weights), behind one data group `etf_info`.
  Cached in `FundamentalsCache`, 1-day TTL, no table, no cron job. The investigation's holdings table and second endpoint were dropped by the owner.
- **Variant, not a route.** The ticker page branches on `is_etf`; the stock page is untouched. Header and tabs are ETF-specific
  (Overview/Technical/Chart); no scoring, Moat, valuation or earnings surface. Moat is refused for ETFs in the API and excluded from momentum.
- **Design.** Hairline sections and `DefinitionRow`s, 15px semibold section titles, 13px tertiary captions, sector bars in the single series colour, a
  quiet disabled "On watchlist <name>" state instead of a second primary button. `/styleguide` deliberately not updated.
- **One watchlist click.** The ETF button adds straight to the list named "ETF" (not the stock popover); the frontend learns
  which lists are monitored from the backend (`WatchlistOut.monitored`) rather than matching names.
- **Search label is local knowledge only** (FMP search has no type; a per-result profile call would add every searched ticker to the tracked universe).

### 2026-10-02 — ETF page extras and removal of wasted FMP calls

Behaviour in `docs/specs/etf-page.md`. Decisions worth keeping:

- **Trading data is computed from what is already cached, not from FMP's `price_change`.** Performance is a split-adjusted price return
  from the cached daily bars (the Sector Heatmap basis), so it is never up to 7 days old; if bars are missing the row is omitted rather
  than falling back to the stale row. Distribution yield is the profile's trailing-12-month `lastDividend` over the current price,
  labelled TTM (it is not the last payment, and not an SEC yield). Beta is shown for equity funds only. Profile `marketCap` is never
  shown: it contradicts the `/etf/info` AUM, which stays the only size figure. Any zero/null row is omitted; no rows, no block.
- **An ETF/fund short-circuits `get_summary`.** The profile is fetched first, and for a fund every stock-only fetch (and Step 2/3) is
  skipped: 18 -> 4 FMP calls on a first open, no empty cache rows. The stock path is untouched.
- **ETF rows on the Watchlists page make no `/grades-consensus` call** and show a dash in Rating. This is the only Watchlist change here;
  the ETF-specific column set is a separate task.
- **`etf_info` is seeded at Starter**, matching the owner's recorded tier. The seed never rewrites an existing row.

### 2026-10-02 — History protection: a shorter FMP answer never shortens cached history

Built from `docs/fmp-starter-downgrade-impact-2026-10-02.md` (section 3 and change-list item 1). Behaviour and the full table of cache
writes are in `docs/specs/fmp-data-and-bar-cache.md` ("History protection"). Decisions worth keeping:

- **One merge rule at the one write path**, not per caller: `core/history_merge.py` + `core/cache.py::_write_cache_row`. An allow-list
  (`HISTORY_KEYS`) decides which keys merge; every cached statement type must be on the history or the snapshot list (a test enforces it).
  `earnings/latest` stays a plain overwrite on purpose: its scheduled-date rows would go stale in a merge.
- **Merge, newest wins, capped at `max(len(cached), len(new))`.** Never shorter, but not unbounded either: a full answer still gives
  exactly the new response, so readers that pad/trim to 10 years or 12 quarters see no difference.
- **An empty or error body keeps the cached rows but still stamps `fetched_at`.** Not stamping would make a plan that answers `[]` for
  everything re-fetch about 7,000 calls a night; stamping is what the old code did for an empty body.
- **Return the merged rows from the cache call**, so the request that triggered the refresh and every later read agree.
- **A clamp is informational, not a failure.** Counted per ticker, shown as `N history-clamped` (and `M empty-body kept`) in the
  nightly fundamentals message; it never enters `check_failure_threshold`.
- **Bars were not safe by construction** (a 20+-bar answer replaced the cache). The replace path now keeps older bars only when the
  answer is shorter than both the cache and the request and its overlap agrees; a restatement (split) still replaces, because splicing two
  price bases is worse than a shorter series. Ordinary window-moving trims are untouched.
- **Refresh button no longer deletes history rows**: it marks them stale (`fetched_at = 1970-01-01`) so the refetch merges. Deviation from
  the old "cold start" wording, taken because the button was a one-click path to the same loss; `prune_cache` skips marked rows.
- **Left unchanged, recorded as remaining exposure:** the 180-day `prune_cache` age delete (untouched tickers rebuild at the depth the plan
  serves) and a restated-and-clamped bar history (replaced, logged). `/styleguide` not touched.

### 2026-10-02 — A 402 restricts one request variant, not the data group

Built from `docs/fmp-starter-downgrade-impact-2026-10-02.md` item 2; behaviour in `docs/specs/fmp-data-and-bar-cache.md`
("Request variants"). Decisions worth keeping:

- **Only `fundamentals` is a variant group (`VARIANT_GROUPS`).** It is the group where one parameter (`period=quarter`) can be refused
  while the same endpoint serves another, and where the group-level canary demonstrably flaps (the probe asks annual). The other groups keep the
  group-level canary because their restriction also drives the cache gate and the nightly jobs' `skipped` status; changing that is a separate
  decision. They are listed with a flap-risk rating in the spec.
- **Variant = endpoint + `period` + `limit`.** `limit` is in the key because the downgrade report left open that Starter may refuse a limit
  rather than clamp it; including it costs one extra 2-call discovery per distinct value and avoids blocking requests that work.
- **A restricted variant raises, it does not return `[]`.** An empty return would be written to the cache (and stamp it fresh). The typed
  error is an `httpx.HTTPError` subclass, so every existing `safe_fetch` site already reads it as "no data"; `core.cache` serves the stale
  cached quarterly rows instead, and writes nothing. Deviation from the literal "return a result": same effect for callers, no empty row.
- **Only the variant's own replay clears it.** This is what ends the weekly flap. A manual Re-test (Settings) and `clear-variant` (API/CLI) exist
  for the owner; Re-test sits in the group row where the note is, no new panel.
- **The nightly count is informational** (`N variant-unavailable`) and is kept out of `check_failure_threshold`; the `failed` count is untouched.
- **Scoring was not touched.** Step 5 reads `insufficient_data` for Standard/REIT tickers and the Overall Assessment goes empty when quarterly
  data is refused; the table in the spec records every caller's behaviour for the later annual-fallback task.

### 2026-10-02 — Chart tab 2H·90D range

Owner decisions, built in four commits (engines, endpoint, frontend, docs); behaviour in `docs/specs/chart-tab.md` section 3.

- **Available for every ticker**, monitored or not; the three availability flags mean "bars exist" on this range. Warren, BB+RSI and LP are computed on demand and stored nowhere.
- **Bars:** the shared bars cache for a ticker that already has `60m` rows, otherwise a live fetch of 9 parallel 90-day windows that **writes nothing** (a viewed-only ticker must not grow the cache). Intraday group off means cached bars only; none means unavailable. No in-memory cache (warm ~100 ms, cold 1.4-2.1 s).
- **Candle time = window start** (09:30/11:30/13:30/15:30), naive-ET strings; the frontend encodes ET wall-clock as UTC seconds, so DST cannot shift anything. The legend shows the full window.
- **The forming candle is dropped** from display and every computation (clock and last-bar checks), so no arrow ever repaints.
- **BB+RSI markers are one per firing candle** (no first-per-day dedup); the stored events mix first- and last-of-day, so matching them was not possible anyway.
- **Warren replays from `today-729d` (the nightly window), then slices to 90 days.** Its own indicator series feed the panes (no second calculation); thresholds come from the engine constants.
- **LP uses the current shared settings live, with `breach_recency_bars` hardcoded to 20 candles for 2h**, over the full series, then filtered to the 90-day window (cap, then filter).
- **Per-range toggles:** only BB+RSI, Warren, LP Support, LP Resistance; the rest hidden and forced off without touching saved values (the Stage precedent). Default range stays D·6M.
- **Panes:** Warren RSI, ADX with ±DI, WVF replace RSI/Stochastic at the same 580/100 stretch factors; existing tokens only (see `docs/design-system-charts.md`).
- **The nightly Warren job and the old 2h builder are untouched.** The vectorised builder is bit-identical on all 108 cached tickers; switching the nightly job to it (about 100 s down to about 10 s) is a separate, unmade decision.

## Known open items (re-verified against code 2026-09-29, analyst labels fixed same day — all resolved)

- **`MultiSelect` primitive — resolved, built.** `components/screener/MultiSelectDropdown.tsx` is
  a real, finished, fully-token-styled primitive (focus trap, roving keyboard nav, and a
  partial ARIA structure: `aria-haspopup`/`aria-expanded` on the trigger, `role="listbox"` on the
  panel and `role="option"` labels around native checkboxes; not "full ARIA", see
  `docs/design-system.md`), used by `FundamentalFilters.tsx`/`TechnicalFilters.tsx`. No longer open.
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

### 2026-10-03 — ETF cutover: ETFs leave the stock-side jobs
Step 7 of the ETFs screener. **Decision (owner):** `load_tracked_universe` is the stock side of `partition_known_tickers`, so no
ETF is in the stock universe (live: 600 -> 581 tickers, exactly the 19 ETFs); the nightly ETF job (1:45 AM) owns everything the
stock jobs gave an ETF: it writes `TrendAnalysis` from the one Weinstein computation shared with the `EtfScreenerRow` fields, and
`TickerLastClose` through the stock-side helper, plus the weekly (Sunday UTC) full bar resync for its own bars. `SYSTEM_TICKERS` is
retired (no other consumer; `ETF_SEED_TICKERS` has the same members). **Unchanged on purpose:** every cron time, the Watchlist and
ticker pages (they read the same tables), existing ETF `TickerScore` rows (left in place, frozen; the Stocks Screener already hides
them and `/api/screener?universe=all` no longer serves them). **Audit:** no prune/cleanup keys on the stock universe (age, empty
profile, non-US exchange, or the ETF universe), pinned by `tests/test_etf_rows_survive_maintenance.py`. **Side effects:** the 11
sector ETFs' bars are now filled by the Sector Heatmap job (1:35) instead of arriving warm from the 1:05 job (11 calls, still one batch).
Detail: `docs/specs/etf-screener.md`, "Cutover".

### 2026-10-03 — Opt-in universe and the wipe: decisions (step 1 built, nothing active)
Investigation: `docs/universe-add-wipe-investigation-2026-10-03.md`; spec: `docs/specs/tracked-universe.md`, "Planned: opt-in universe and wipe".
**Decisions (owner):**
- **Opt-in universe.** A ticker the user opens but does not Add is "browsed": not in the screeners, not in the nightly jobs. Clicking Add makes it "added". The
  Add and Remove buttons come in later steps. Stocks and ETFs alike. This replaces the 2026-10-02 rule "viewing an expired ticker re-adds it".
- **Implicitly in the universe, never wiped, no Remove button; each protection is independent and sufficient on its own:** a member of any index in
  `IndexConstituent` (live names: `sp500`, `nasdaq`, `dow`); on any watchlist, while it is; a seed ETF (`ETF_SEED_TICKERS`) plus `WEINSTEIN_BENCHMARK_TICKER`
  plus the live `WeinsteinSettings.rs_benchmark`; manual data (`TickerMoat`, `TickerCustomValuation` incl. inactive rows, `TickerBankCapitalMetrics`,
  `GrowthCatalystNote`).
- **Added tickers never expire by the 30-day rule.** They leave only through the Remove button, so an added ticker is protected from the wipe.
- **The wipe rule.** A ticker is wiped when its last touch (`TickerView.last_viewed_at`) is more than 30 days old AND it has no protection AND it is not added
  (exactly 30 days idle is not due). Delisted tickers follow the same rule; delisted plus any protection stays.
- **Adoption.** A ticker with stored data but NO `TickerView` row and no protection (a stock that left an index, an orphan) is never wiped blind: the wipe job
  stamps `last_viewed_at = now` ("adopts" it, logged) and it becomes eligible 30 days after that.
- **Wipe order per ticker:** derived tables first, caches next, `TickerView` last, one `BEGIN IMMEDIATE` transaction per ticker (the journal mode is not WAL), the
  decision re-checked inside it. FundamentalsCache `forex_rate` rows (keys look like tickers: EURUSD, ...) are never touched.
- **Not registered anywhere:** no crontab line, no `CRON_JOB_NAMES`/`_EXPECTED_CADENCE_HOURS`/`JOB_METADATA` entry, no heartbeat, until the cron reschedule is done.
**Built in step 1 (no schema change, no live write):** `data/ticker_data_registry.py` (every per-ticker table classified WIPE / PROTECTING / KEEP, the deletion order,
the schema guard), `data/tracked_universe.py::classify_wipe_candidates` (raw protection sets, takes the added set as a parameter, default empty), the
`GrowthCatalystNote` addition to `load_manual_data_tickers`, and `pipeline/wipe_untouched_tickers.py`: dry run by default (read-only connection, writes nothing),
`--apply` locked behind `FATHOM_ALLOW_WIPE_APPLY=1`. **Still to come:** step 2 (the `added_at`/`added_source` columns, the real added loader, the grandfathering of
the 25 viewed-only tickers BEFORE the classification flips `viewed` to `added`), the API and buttons, removal of `hidden_inactive`, the docs sweep for "hidden, not
deleted"/"viewing re-adds", the first `--apply` after a backup and disk check, and (after the reschedule) the cron registration.

### 2026-10-03 — Opt-in universe, step 2: the added state and the grandfather backfill; the flip waits for the Add button
**Built:** nullable `TickerView.added_at` / `added_source` (`user` | `grandfathered`), `load_added_tickers` (the wipe job's protection now reads it), and
`pipeline/grandfather_universe.py` (dry run by default; marks the tickers whose only reason today is `viewed` as added, `grandfathered`). **Decision (owner):
the classification flip (`viewed` becomes `added`, new `browsed` reason) is deferred until the Add button and its endpoints exist (step 3).** Reason: the flip
makes "viewed" stop admitting a ticker, so without an Add button there would be no way to add a new ticker and the universe would freeze; grandfathering first
means nothing in a screener today drops out when it ships. Until then `_classify`, every universe, the screeners and the nightly jobs ignore the two columns
(pinned by a test), and `ScreenerMeta.hidden_inactive` keeps its current meaning. `--apply` on the wipe job stays locked; nothing is registered in cron.
**Live run (2026-10-03):** pre-write snapshot `backend/backups/pre_universe_step2_20261003.db.gz` (outside the pruner), columns added by the `uvicorn --reload`
`init_db`, then the grandfather backfill; see the step-2 report for the verification.

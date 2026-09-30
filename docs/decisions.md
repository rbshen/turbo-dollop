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
- **Session 9, part 3 — FMP settings on the kit (2026-09-30).** The FMP status card moved into FMP data groups; the immediate-apply FMP controls became `Switch` and native `Select`; error messages now persist; REIT and Discount rate show the server's reason. See "Session 9: Settings migration, part 3" below.

- **Session 10 — Screener migration: plan and primitives (2026-09-30).** The form-control primitives and a `/styleguide` sidebar mock for the Screener migration, with **no Screener page change** beyond a `T` suffix in market-cap input. Five commits (docs, helpers and primitives, `RangeField`, a `RangeField` re-sync fix found by the mock, styleguide), not pushed. See "Session 10: Screener migration, plan and primitives" below.

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
- **Removed once unused** (a grep first showed no caller left): `NumberStepper`, `InfoTooltip`, `lib/tooltipPosition.ts` (only `InfoTooltip` used it) and its test, and the un-tokened `Select` shell (`Select` now requires a `size`). The styleguide's "Settings controls" demo of the old stepper and select went with them, since the "Form controls" section shows their replacements. The brand `Checkbox` variant stays because the Screener filters use it.

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
3. **Boxed versus underline is decided by the owner by eye from the mock.** Both are built: `NumberField` gets an additive `variant` (boxed default, underline) backed by `Input`'s existing variants. **Pending the owner's review.** The variant that loses is deleted at migration, not now.
4. **Compact `FormField`, sidebar only:** label `text-xs` `text-secondary`, 2px gap to the control, no hint line (one optional single-line hint for market cap only), unit right-aligned in the label row.
5. **`T` added to the market-cap suffixes** (M, B, T). `5T` is 5,000,000,000,000. The live parser `parseMarketCapInput` changes by adding `T` only; the new lenient parser in `lib/numberInput.ts` (accepts `12.`, `.5`, `2 m`) is used by `NumberField` and `RangeField`, and the old one is deleted at migration. The mock carries a caption saying the live sidebar still rejects `12.` until then.
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

**Backfill:** the new basis reaches `TickerScore` on the next nightly recompute (3:50) or an owner-run `uv run python -m pipeline.recompute_ticker_scores` (cache-only, **writes the live DB**).

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

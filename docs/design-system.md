# Fathom Design System

A calm, data-first interface for fundamental investing.

> This is the living style guide for Fathom's frontend. It was drafted in a claude.ai chat working from a read-only audit of the codebase, decided against a two-way A/B comparison ("Direction B, quiet minimalist"), and implemented page-by-page on the `ui/design-system` branch (sessions 1 through 8). Token names and values are authored in `frontend/app/globals.css` — this document explains what they mean and when to use them, it is not a second source of truth for the values themselves. Chart-specific rules live in `docs/design-system-charts.md`. The build history and open items are in `docs/decisions.md`.

## Principles

1. **Whitespace and hairlines before boxes.** Content sits on the page. Groups are separated by a 1px `border-subtle` rule and space, not by filled, bordered cards.
2. **Blue means act.** `brand` is the primary button, links and keyboard focus. It is never used for selection or status.
3. **Selection is neutral.** The current nav item, tab, segment or side-nav item is shown with `text-primary`, plus an underline or a `surface-2` fill. The same goes for a checked Checkbox, an on Switch and a checked chip: `text-primary` fill with a dark check or thumb, never `brand` blue (see "Form controls" below). The built `Checkbox` still paints checked in `brand` until it is migrated; the neutral style is opt-in in code and becomes the only style at migration.
4. **Status is a pill.** A soft tinted fill with coloured text and no border, in one of two sizes (regular, compact). The same status looks the same everywhere: ticker header, Screener cards, Watchlist, Momentum, Settings. There is no dot-and-word Status and no separate dense-table style. See "Pills" below.
5. **Words, not colour alone.** The label always says the state. Where direction is implied (+3.66%), a ▲ or ▼ sits inside the pill before the label.
6. **Quiet type.** Larger, lighter titles; sentence-case labels; no uppercase, no wide tracking. Numbers stay mono.
7. **Same job, same component.**

## Content fundamentals

- **Sentence case everywhere**, including section titles and field labels. Nothing is uppercase.
- **Tickers** are mono, with the company name in `text-secondary`.
- **Numbers** are mono and tabular, right-aligned in tables, with an explicit sign on changes (+1.26%, −7.49%), units after the value (−52 days), and "—" when missing.
- **Verdicts** are one pill ("Strong pass") beside a neutral score. Every pill label is sentence case ("Strong pass", "Wide moat", "Speculative growth", "Pass with caution"). This is display-only: the one helper `pillLabel()` in `lib/tierColor.ts` re-cases a label at the moment it is drawn, while backend strings ("Strong Pass") and every comparison (`verdict === "Pass with caution"`) keep running on the raw value. The rule is per segment of a label split on " · ": the first word keeps its capital, later Title-case words drop to lower case ("Growth Rate · 25% · 92" reads "Growth rate · 25% · 92"), and acronyms, numbers and proper nouns are left alone ("5Y vs SPY", "S&P 500", "Stage 2 · Advance"). A label that has no lower-case form (a single word such as "Fairvalued", or a fixed name like "Nasdaq") is used as written.
- **Disclaimers** ("Informational only") are `caption` in `text-tertiary`.
- **Tone:** plain and factual.

## Visual foundations

- **Surfaces:** mostly `page`. `surface` appears only as a hover fill and in the rare Card or popover; `surface-2` marks a selected segment or side-nav item and a hovered popover row.
- **Text:** `text-primary` for headings and figures, `text-body` for running text, `text-secondary` for secondary, `text-tertiary` for captions and labels.
- **Type:** Public Sans (text), Sora (page and ticker titles, logotype), IBM Plex Mono (numbers and tickers), snapped to the app's scale: 13 / 15 / 17 / 19 / 21 / 26 / 32 / 39 / 52px. Titles use weight 500. Page title 26, ticker title 32, price 39, score 26, body 15, captions 13, pill label 13 (regular) or 11 (compact).
- **Spacing:** the 4px scale. Page top padding 48, header-to-content 32, section padding 24 top and 8 bottom, tile gap 40 by 12.
- **Radius:** `radius-md` (8px) for buttons, segments, side-nav items, boxed fields (the ticker search and every form field) and native selects; `radius-lg` (10px) only for the rare Card. Underline inputs (inline filter fields only) have no radius.
- **Layout:** `PageContainer` (1280px, 32px gutter) wraps every page, and every page starts with the same `PageHeader`.
- **Icons:** Phosphor, regular weight, 16px, `currentColor`. No emoji.
- **Focus:** a 2px `brand` outline on keyboard focus only (`:focus-visible`). Hover and focus never leave a lasting highlight.

## Choosing the right control

| The job | Use |
| --- | --- |
| Move between pages | TopNav (one item current, underlined) |
| Move between areas of Settings | SideNav |
| Switch between views of one ticker | Tabs (neutral underline) |
| Change a data option on the same view | SegmentedControl (fixed 2–6 options only — use Tabs instead for an unbounded set, e.g. the Watchlist switcher) |
| Do something | Button: one `primary` per region, `ghost` for everything else. `outline` (ghost with a hairline border that turns `brand` on hover) is for a secondary action that has to read as a button inside a dense panel, such as the Screener's Sort direction and Saved views actions |
| Enter a typed value (a number, or short text) on a form page | `NumberField` for numbers, boxed `Input` for text, each in a `FormField` or a Settings row |
| Choose one of a few options on a form page | Native `Select` (in its themed shell), at `short` or `medium` size. Not a SegmentedControl: that is for switching a view, not for a saved setting |
| An on/off setting that is saved with a Save button | `Checkbox` (neutral checked state) |
| An on/off setting that applies the moment it is flipped | `Switch` (never use one on a form that has a Save button) |
| Show a classification or state | Status (pill) |
| Show a short label or value in a table cell (a score, a rating, a kind) | Badge (the same pill, with a `missing` state) |
| Group related content | Section (hairline and title) |
| One repeated item in a grid | Tile (hairline on top) |
| List many records with numbers | DataTable |
| Label and value pairs | Definition rows |
| Tell the user about system state | Banner |
| An object that must read as a box | Card (rare) |

## Form controls

The controls for typing, choosing and toggling a value on a form page. Built 2026-09-30 (session 8) and shown in `/styleguide`. All five Settings forms (REIT dividend yield, Economic moat, Discount rate, Weinstein, Liquidity) use them as of session 9. The Screener sidebar and the Watchlist name editor still render through the older `Input` and `Checkbox` defaults and are migrated one at a time, each in its own change. The primitives the Screener sidebar needs (session 10) are built and shown in `/styleguide` under "Screener sidebar (mock)"; the page itself is unchanged until the owner has reviewed the mock. The new behaviour is opt-in in code (a new component, or an explicit prop) wherever an old call site still exists, so nothing there changes how it renders; `Select` has no old form left and always takes a `size`.

| Control | Component | Job |
| --- | --- | --- |
| Number | `NumberField` (`components/ui/number-field.tsx`) | A typed number with optional integer, min, max, step, unit |
| Text | `Input` with `variant="boxed"` and a `size` token | A short piece of text (a ticker, a benchmark symbol) |
| Choice | `Select` with a `size` token | One of a few options, a native `<select>` |
| On/off with Save | `Checkbox` with `variant="neutral"` or `"chip"` | Saved when the form is |
| On/off now | `Switch` (`components/ui/switch.tsx`) | Applied immediately, no Save |
| Anatomy | `FormField` (`components/ui/form-field.tsx`) | Label, hint, control, unit, error, wired together |

**Boxed on form pages.** A form field is a box: `radius-md`, 1px `border-control`, `page` fill, 36px high. This reverses the earlier "boxed for the ticker search only" rule. Underline fields stay for inline filters in dense strips. The Screener sidebar's own choice between boxed and underline is **pending the owner's review of the `/styleguide` mock**, which shows both built from the real primitives; `NumberField` has a `variant` prop for it (below), and whichever loses is deleted at migration.

**Size tokens.** Every control is 36px high and never wider than its container (`max-w-full`). Width is a token, chosen by what the value looks like, never by the layout around it.

| Token | Width | Use for |
| --- | --- | --- |
| `short` | 96px | A number of up to about six characters: a length in weeks, a percentage, a multiple |
| `medium` | 176px | A native select, a ticker or symbol, a longer number |
| `wide` | 320px | Free text that can run long (rare) |
| `full` | fills the container | A stacked form or a search box. Not for a Settings row, whose control sits in an `auto` column |

**States.**

| State | Look |
| --- | --- |
| Default and filled | `border-control`, `text-primary`, mono and tabular for numbers |
| Focused | The global 2px `brand` outline on `:focus-visible`. Nothing sets `focus:outline-none`, and a control never draws its own focus border |
| Invalid | `border-negative` on the box, plus the error text under the field (below). Colour is never the only signal: the message says what is wrong |
| Disabled | 45% opacity, `not-allowed` cursor, and its label and hint dim with it (the Liquidity breach-recency row) |

**Anatomy.** From top to bottom: the **label**, a real `<label for>` in `text-sm` `text-primary` and sentence case, with **the unit dropped** ("MA length", not "MA length (weeks)"); the **hint**, one plain-English sentence in `caption` `text-tertiary` directly under the label; the **field**, followed on the same line by its **unit** as a suffix in `text-secondary` (`[ 30 ] weeks`); and the **error** in `text-negative` under the field. The hint and the error are linked to the control with `aria-describedby` (and the unit too, for a number), and the error has `role="alert"` so it is announced when it appears. `FormField` does the wiring, so a control inside it needs no manual ids beyond its own `id`. Hints replaced the `(i)` `InfoTooltip`, which has been deleted: help that a user has to hover for is help most never read, and a touch device cannot hover at all.

**Validation.** A value is never silently clamped, rounded, snapped or corrected. If it is not a number, is not a whole number where one is required, or is outside `min`/`max`, the field shows the invalid style and an inline error and the form's Save is disabled until it is fixed. `min` and `max` are optional props that mirror the bounds the server already enforces (for example Weinstein's MA length 2 to 200); a setting with no server bound gets none in the UI either. Two deliberate, recorded exceptions are form-level only: the Economic moat scores check 0 to 100 (the backend has no bound), and Weinstein's breakout volume has a floor of 0.1 where the server accepts anything above 0. A value is never snapped to `step` unless a prop asks for it.

**Number fields are typed only.** `NumberField` is a text input with `inputMode="decimal"`, not a native `type="number"`: no browser spinner, no scroll-wheel value change, no `e` (exponent) character. ArrowUp and ArrowDown step the value by `step`, and Shift with either arrow steps by ten times `step`. Stepping only acts on a valid value and stops at `min` and `max`. A `stepper` prop, off by default, adds joined `-` and `+` buttons at the field's edges, `[-][ 30 ][+]`, 32px wide each; use it only where a value is nudged far more often than it is typed. It replaced `NumberStepper`, which has been deleted.

**Native select rule.** A choice is a native `<select>` in the themed `appearance-none` shell with an overlaid caret, restyled to the same 36px height, border and radius as a boxed field and sized by the same tokens. No custom listbox, and no segmented-control mode for a form setting: a native select gives keyboard, touch and screen-reader behaviour for free.

**Checked state is neutral.** A checked Checkbox is `text-primary` fill with a dark check; an on Switch is a `text-primary` track with a dark thumb (32 by 18px, a hidden native `<input type="checkbox" role="switch">`). The `chip` Checkbox variant is the Screener's toggle chip done properly: a `radius-md` 32px chip with a 1px `border-input`, `text-secondary`, and a `surface-2` fill with `text-primary` when checked (a chip is not a Pill; see "Not a Status" under Pills below).

### Screener filter sidebar primitives (session 10)

Additive and opt-in: every existing call site renders exactly as before, and nothing in `app/screener` or `components/screener` uses these yet. They are shown in `/styleguide` under "Screener sidebar (mock)".

**`NumberField` additions.** All default to today's behaviour, so the Settings forms are unchanged.

| Prop | Default | What it does |
| --- | --- | --- |
| `optional` | off | An empty field is valid and its check reports a `null` value, instead of "Enter a number." |
| `suffixes` | none | A map such as `{ M: 1e6, B: 1e9, T: 1e12 }`. Text like `500M`, `2B`, `1.5T` or `2 m` (case-insensitive, optional space) parses to base units. Anything else with letters is invalid (`1x`, `5e`, `1BX`). Without `suffixes`, letters are invalid as always |
| `keyboardStep` | on | `false` disables ArrowUp and ArrowDown stepping (a market-cap box has no sensible step) |
| `variant` | `boxed` | `boxed` or `underline`, backed by `Input`'s existing variants. One of the two is deleted at migration |
| `hideError` | off | The field draws no error line of its own, so a composite can show one line under a pair. It still sets `aria-invalid` and accepts an `aria-describedby` |

`aria-describedby` and every other attribute still pass through. A number is never clamped, rounded or corrected, with or without a suffix.

**Compact `FormField`.** `density="compact"` is for the filter sidebar only: the label is `text-xs` `text-secondary`, the gap to the control is 2px, there is no hint line (one optional single-line hint is allowed, for market cap only), and a `unit` renders **in the label row, right-aligned in `text-tertiary`**, not after the box. An `applied` prop turns the label text `filter-active` orange. The default density is unchanged: `text-sm` label, hint under it, unit after the box.

**`RangeField`** (`components/ui/range-field.tsx`). One labelled Min/Max pair for a numeric range. Props: the numeric `{ min, max }` value, `onChange` with the same shape, `label`, `unit`, `size` (`short`), optional `suffixes` (market cap) and `variant`. It is `role="group"` labelled by its label; the boxes are named "Minimum" and "Maximum" and have the placeholders "Min" and "Max". Typed text lives in a per-side draft (`useDraftNumber`, `lib/hooks/useDraftNumber.ts`); the filter state stays numeric, so `ScreenerFilterState` and saved views do not change.

The commit rule for a Min/Max pair (live filtering, nothing waits for Apply or blur):

1. **Valid text commits immediately**, including `12.` and `.5`.
2. **An incomplete prefix** (`-`, `.`, `-.`) **holds the previous committed value** with no error while the box is focused. On blur it becomes invalid: that side emits `null` and the error shows.
3. **Any other invalid text** (letters, `1x`, `5e`) makes that side inactive at once (it emits `null`) and shows an inline error.
4. **Never clamp, swap or correct.** The only bound is a market cap of at least 0.
5. **A reversed range** (min higher than max) is applied literally, so nothing matches, exactly as today. One message sits under both boxes, "Min is higher than max, so no ticker can match.", and only the Max box is marked invalid.
6. **One error line** under the pair, never one per box. A text error wins over the reversed-range message.
7. **External changes re-sync the boxes.** The hook remembers the exact `{ min, max }` object it last emitted. A different object from outside (Reset, loading a saved view, a remount) rewrites the drafts, even when its numbers equal the current ones, so stale invalid text such as `1x` is cleared. The same object handed back never rewrites what the user is typing. Parents must therefore pass the emitted object back unchanged.
8. A market-cap box shows the shortest exact form on mount or re-sync (`1e9` reads `1B`, `2.5e12` reads `2.5T`, `1234567` stays plain digits).

**The 256px filter sidebar.** The Screener sidebar stays `w-64` (256px): with the card's 1px borders and `p-4`, its content is **222px** wide. It is not widened. A range pair is two `short` (96px) boxes with a dash between them and fits without overflow. **Units sit in the label row**, right-aligned in `text-tertiary`: Quote and Market cap "USD" (every current ticker is USD-quoted, so the label is always true), P/E "x", Growth "%", the score fields none. A label is `text-xs` sentence case (Overall, Financials, Growth rate, Profitability, Debt, Quote, P/E, Growth, Mkt cap, Beta).

**Applied state.** A filter label turns `filter-active` orange while it holds a value, the one documented colour exception; it is the only thing that turns orange. A chip shows applied through its checked fill (`surface-2`, `text-primary`), not orange. The Watchlist label is orange only while the watchlist filter is actually in effect: a selected watchlist that is dimmed because the universe is not "All" is not applied. A section header may carry a neutral applied-count `Badge` (for example "3"), computed by the pure `countActiveFilters(filters, watchlistActive)` in `lib/screenerFilters.ts`: applied ranges, non-empty multi-selects, checked chips and an in-effect watchlist. The badge exists in the mock only until migration.

**Market-cap suffixes** are M, B and T (`5T` is 5,000,000,000,000). The live sidebar's own parser (`parseMarketCapInput`) gains the `T` suffix and nothing else; the new lenient parser is in `lib/numberInput.ts` and the old one is deleted at migration.

## Settings layout

Every Settings section is built from four components in `components/settings/SettingsLayout.tsx` (built 2026-09-30, shown in `/styleguide`, used by all five form sections of the Settings page; Scheduled jobs and FMP data groups are not built from it, see "Immediate-apply sections" below):

- **Section title.** `SettingsSection`: a `Section` (hairline and title), sentence case. The existing Title Case titles ("Economic Moat Point Values", "REIT Dividend Yield Threshold") are converted when a section is migrated, not before.
- **Intro.** One short paragraph under the title, capped at `max-w-xl`. It says what the section controls and when a change takes effect, in plain English. It never cites a doc, a section number or a file name.
- **Sub-heading.** `SettingsGroup title="..."`, used only when a section has **more than four settings**. A section of four or fewer is one untitled group. (Weinstein has eight and is split into "Stage" and "Breakout and relative strength".)
- **Rows.** `SettingsRow`, inside a body capped at `max-w-2xl`. **Rows, not a grid of fields:** each row is a two-column grid, the label and its hint in the flexible left column and the control in a **fixed-width control column** on the right, `py-3`, a 1px `border-subtle` hairline between rows.
  - **Control column.** One width for the whole kit, **256px (16rem)**: the widest field allowed in a row, `medium` (176px), plus an **80px unit slot**. It is set in one place (`SETTINGS_CONTROL_COLUMN_CLASS` in `SettingsLayout.tsx`) and never depends on a row's content, so the column, and the left column beside it, is the same width in every row of every section.
  - **Left-aligned controls.** Every control sits on the column's left edge, so all boxes in a section share one left edge. The unit follows the box directly (an 8px gap) and trails into the unit slot; a row with no unit leaves the slot empty. The unit slot is what makes the unit widths ("weeks", "%", "× average", "bars") irrelevant to alignment: a short unit no longer pulls the box left or right.
  - **Checkboxes and switches** sit on the same left edge as the number boxes (their 16px box or 32px track starts where a field's border starts), not at the right edge. In a row they have no label of their own: the row's `<label for>` is their only accessible name. A `Checkbox` or `Switch` given no `label` prop renders no wrapping `<label>` at all (its input is laid over the box), so there is never a second, empty label on the same input.
  - **Sizes in a row.** `short` and `medium` only. `full` is not allowed in a row. `wide` (320px) is wider than the column and is capped to it, so use `medium` for long text.
  - **Error.** On a second line under the control, left-aligned to the box edge (the same left edge as the box, in the control column, wrapping inside it).
  - **Label and hint** take the remaining width, so a hint wraps at the same place in every row.
  - **Conditional rows.** A row that depends on another (breach recency, only relevant when "only keep if breached recently" is ticked) stays in place and is disabled, dimmed, rather than hidden, so the layout never jumps, and keeps the same alignment.
  - **Narrow widths.** Below the `sm` breakpoint the row stacks: label and hint above, the control below, left-aligned, and the error under it. Nothing overflows horizontally.
- **Footer.** `SettingsFooter`, at the bottom of the section: the `primary` Save button, then a status message (`aria-live="polite"`: "Saving…", "Saved ✓", "Save failed" (followed by the server's own reason when it gave one), or "Fix the highlighted fields to save." while a field is invalid), then "Last updated ..." in `caption` `text-tertiary`. This is the position and order the forms use today; only the status text has moved out of the button label so the button does not change width while saving. **Save is disabled until something differs from the stored values** (the footer's `unchanged` prop), as well as while a field is invalid and while a save is in flight; a success ("Saved ✓") resets to empty three seconds after the save finishes, but a failure ("Save failed", with the server's reason) **stays until the next edit or the next Save attempt**, so a reason is never gone before it can be read. An invalid entry never produces "Save failed": it blocks Save instead.

**Immediate-apply sections.** Scheduled jobs and FMP data groups have no Save button and are not built from rows. Their controls apply the moment they are changed, so they are `Switch` (on/off) and native `Select` (a choice, at `medium` unless a shorter token clearly fits its options), never a `Checkbox`. FMP data groups is a table (a `Switch` and a tier `Select` in each row's cells) with the FMP status card below it: the "My FMP plan" `Select` and the "FMP master switch" `Switch`, the FMP key problem, and the section's own error line. Each control is named by its visible label or row, is disabled while a request is in flight, and is driven by the fetched data, not by local state: a cancelled confirmation, or a failed request, leaves the control showing the real current state, and a failure shows the server's message inline near the control.

A section that saves several independent panels (Discount Rate has one per region) repeats a titled group with its own rows and footer per panel; the panel is a `SettingsGroup`, not a boxed Card.

## Pills

One family, two components, two sizes. `Status` (a labelled state, with an optional ▲/▼ direction glyph) and `Badge` (a short value or label, with a `missing` state) render the same pill; `Verdict` is `Status` for a verdict word. They never differ in look, only in what they are for. Nothing in the app hand-rolls a pill, a dot or an inline status colour — a new status goes through these. That includes the Screener's `PullbackPill` and `ReversalPill`, which were the reference style and now render through `Status` themselves (2026-09-29), and the Technical tab's `ChecklistCard` status chip.

**Anatomy.** `radius-md` (8px). Fill is the tone colour at 16% opacity, text is the tone colour at full strength, and there is no border. This is the look of the Screener's pullback pills ("Pullback recovered", "Pullback pending", "Trend invalidated"), which are the reference style. No new colours: every tone reuses an existing token.

| Size | Type | Padding | Height | Where |
| --- | --- | --- | --- | --- |
| Regular | 13px, weight 600 | 4px / 8px | 25px | Ticker header, Screener cards, tabs, Settings tables, anywhere a pill is a first-class read |
| Compact | 11px, weight 500 | 2px / 6px | 20px | Dense tables only (Watchlist, Momentum). Same tint as regular, so the colour signal is not weakened; only the type and padding are quieter |

The choice of size is the only difference between a Watchlist Moat cell and the ticker header's Moat pill.

**Tones.** Tier logic stays in `lib/tierColor.ts`; this guide defines the colours.

| Tone | Token | Label / where it shows up |
| --- | --- | --- |
| `strong` | `positive-strong` | Strong pass (score above 90), Wide moat, Undervalued, 5Y vs SPY outperform |
| `positive` | `positive` (muted green) | Pass (score 75 to 90), Narrow moat, Fairvalued, Stage 2 (Advance), Pullback recovered |
| `warn` | `warn` | Needs review: the amber borderline read. In the app the 70 to 74 score band carries the backend's own verdict word "Pass" in this tone; "Needs review" is the tone's name and its styleguide label. Also Stage 3 (Top), Pullback pending |
| `caution` | `caution` | Pass with caution (checked before score tiers) |
| `negative` | `negative` | Fail, No moat, Overvalued, Stage 4 (Decline), Trend invalidated |
| `speculative` | `chart-purple` | Speculative growth only |
| `neutral` | `surface-2` fill, `text-secondary` | No read to colour: Not scored, N/A, Stage 1 (Base), index membership (S&P 500, Nasdaq, Dow 30), company kind (Badge), Skipped and Unknown in the jobs tables, a stale Reversal, and any value with no Pass/Fail meaning |

`Badge` and `Status` share this tone set. "Pass with caution" is `caution` everywhere, Watchlist included.

**Score and label.** A score number standing beside a pill is never coloured: it is `text-primary`, mono, tabular, and the pill carries the tone. (A number written inside a pill's own label — the Watchlist Analysis cell, the Overall Assessment breakdown chips — takes that pill's tone, because the pill is the value.) Inline (an Analysis section header) the number sits to the left of the pill with an 8px gap, vertically centred: `74 [Pass with caution]`. Stacked (a Screener card header, where the number is large) the number sits above the pill, both right-aligned. A Watchlist Analysis cell is one column wide, so its compact pill holds the score itself (toned by the verdict, with a ⚠ appended for Pass with caution, whose tooltip names the steps) rather than a number plus a label. A score without a computed value is a neutral pill or a `missing` Badge ("—"), never a bare dash. The Overall Assessment's circular score badge is a gauge, not a pill, but follows the same rule: its number is neutral `text-primary` and the ring stroke carries the tone (full-strength tone colour, no fill). Beside it sits the headline verdict pill.

**Wrapping.** Pills never break internally (`nowrap`). A row of pills is a `flex-wrap` container with an 8px gap in both directions, so a row wraps whole pills onto the next line at narrow widths and stays left-aligned. An info or warning icon that belongs to a pill (Speculative growth, Stage pending) is wrapped with it so the two never split across lines. The ticker header's status row (Assessment, Moat, Valuation, Speculative growth, 5Y vs SPY, Stage) is about six pills wide and follows this rule.

**Not a pill: the Watchlist Rating.** The analyst consensus in the Watchlist's Rating column (Buy / Hold / Sell) stays as tone-coloured text, not a pill. It is the one deliberate exception (2026-09-29): it sits directly after the Moat, Value and Analysis pills, and a fourth adjacent pill would make that strip busy for no consistency gain, since no other view shows the rating as a pill.

**Not a Status.** A dot is still right for a chart legend key (see `docs/design-system-charts.md`) and a timeline marker, because they name a series or a point in time, not a state. A pill is not used for a filter chip or a button.

## Foundational decisions (settled, built)

- **Direction B** ("quiet minimalist") over a consolidated version of the old look.
- **Tables:** hover only on rows that open something; whole-row click opens the ticker in a new tab; Screener cards unchanged; Watchlist and Momentum use the compact size of the same pill family as everywhere else (2026-09-29 reversal — they previously kept a separate filled `Badge`; see `docs/decisions.md`).
- **Fonts:** Public Sans, Sora, IBM Plex Mono — no change needed from what the app already had.
- **New tabs:** ticker links in the Screener, Momentum and Watchlist, and nav links from the Screener, open in a new tab so Screener filters stay put. Two tabs each showing an active item is expected behaviour, not a bug.
- **By choosing B:** dark `on-brand` text on the primary button; underline inputs with `border-control` (now for inline filter fields only; form fields are boxed, see "Form controls" and the 2026-09-30 entry in `docs/decisions.md`); ▲/▼ glyph on the 5Y vs SPY status; orange stays reserved for the applied-filter label. (Also originally: "filled pills dropped from headers, tiles and lists", with `Status` as a dot and a word. Reversed 2026-09-29: status is now a pill everywhere — see "Pills" above and `docs/decisions.md`.)
- **Segmentation chart "Other" slice:** reuses the `text-tertiary` token rather than a new dedicated token.
- **Settings' "skipped" status:** the old sky-blue treatment was retired during the Settings migration (session 6a).

## Housekeeping items (verified against code 2026-09-29, analyst labels fixed same day — all 6 resolved)

These were recommended during the original audit; each was re-checked directly against the
current `frontend/` source rather than assumed, and every remaining occurrence was counted, not
sampled.

1. **Single colour system — done.** `grep` for `--card`, `--popover`, `--primary`, `--secondary`,
   `--accent`, `--destructive`, `--input`, any `-foreground` pair, and all eight `--sidebar-*`
   across `app/globals.css` returns zero matches — fully deleted. `components/ui/chart.tsx`'s
   tooltip chrome is re-pointed onto named Fathom tokens (`border-border-card`, `bg-surface`,
   `stroke-border-subtle`, `fill-surface-2`), not the generic shadcn ones. `--ring` is also fully
   gone (not merely "kept until the outline rule is gone" as this section used to say) —
   `*:focus-visible` now sets its own explicit 2px `brand` outline directly, with no `--ring`
   variable anywhere in `globals.css` or any component. The old `--chart-1..5` tokens this
   section said to "leave alone" no longer exist either — `grep` finds zero definitions and zero
   consumers; every former `chart-1..5` reader (`MarketBreadthCharts.tsx`,
   `PriceTargetTrendChart.tsx`, the shelved `InstitutionalOwnershipTab.tsx`) now reads
   `--color-series-1..5` instead (see `docs/design-system-charts.md`'s own series-token rules).
2. **Steppers — restyled and kept, then superseded and deleted (2026-09-30).**
   `components/ui/NumberStepper.tsx` was kept in the 2026-09-29 verification (brought onto the
   shared token set rather than dropped). Session 8 added `NumberField` with an opt-in `stepper`
   prop, which is typed-only, never clamps or snaps, and shows an inline error; session 9 moved
   the last user of `NumberStepper` (the Liquidity form) onto it and deleted the component.
3. **Analyst labels — done.** `CurrentDistributionList.tsx`, `RatingDistributionTrendChart.tsx`,
   and `RecommendationDetailsTable.tsx` now display FMP's own Strong Buy/Buy/Hold/Sell/Strong
   Sell wording (was the app's own relabeled Buy/Outperform/Hold/Underperform/Sell). Only the
   display `label` changed — the internal `key`s (`buy`/`outperform`/`hold`/`underperform`/
   `sell`) and the backend's `RecommendationDetailsColumn`/`RatingHistoryPoint` field names are
   unchanged, since those still map 1:1 to FMP's own `strongBuy`/`buy`/`hold`/`sell`/`strongSell`
   fields.
4. **`text-tertiary-2` — done.** Zero references anywhere in `frontend/` (`.tsx`/`.ts`/`.css`) —
   fully merged into `text-tertiary` as originally recommended.
5. **`border-control` typo — done, zero remaining occurrences.** Every class in the codebase now
   reads `border-border-control`/`border-border-input` (the correct, prefixed form) — confirmed
   by grepping for the bare `control` class fragment app-wide and finding only correctly-prefixed
   hits (`TickerSearch.tsx`, `NumberStepper.tsx`, `Select.tsx`, `AddToWatchlistButton.tsx`,
   `ManualCalculationPanel.tsx` ×2, `BankCapitalMetricsForm.tsx` ×4, `SavedFiltersBar.tsx`,
   `checkbox.tsx`, `input.tsx` ×2, `WatchlistFilters.tsx`, `app/screener/page.tsx`) plus
   unrelated component/comment hits (`SegmentedControl`, code comments) — no bare, unprefixed
   `control` class survives anywhere.

## `MultiSelect` primitive — built, not a placeholder

Resolved the same day as the items above: `components/screener/MultiSelectDropdown.tsx` is a
real, finished primitive — checkbox-listbox popover with a focus trap, roving arrow-key/Home/End
navigation between options, Escape-to-close, a "Clear" action, and full ARIA
(`role="listbox"`/`aria-multiselectable`/`aria-selected`) — built entirely on named tokens
(`border-input`, `surface`, `surface-2`, `brand`, `text-secondary`/`text-tertiary`). Used by
`FundamentalFilters.tsx` and `TechnicalFilters.tsx` for every Screener multi-select filter. The
5c-era "left deliberately unstyled" state (see `docs/decisions.md`) is fully superseded.

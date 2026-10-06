# Fathom Design System

A calm, data-first interface for fundamental investing.

> This is the living style guide for Fathom's frontend. It was drafted in a claude.ai chat working from a read-only audit of the codebase, decided against a two-way A/B comparison ("Direction B, quiet minimalist"), and implemented page-by-page on the `ui/design-system` branch (sessions 1 through 16). Token names and values are authored in `frontend/app/globals.css` — this document explains what they mean and when to use them, it is not a second source of truth for the values themselves. Chart-specific rules live in `docs/design-system-charts.md`. The build history and open items are in `docs/decisions.md`.

## Principles

1. **Whitespace and hairlines before boxes.** Content sits on the page. Groups are separated by a 1px `border-subtle` rule and space, not by filled, bordered cards.
2. **Blue means act.** `brand` is the primary button, links and keyboard focus. It is never used for selection or status.
3. **Selection is neutral.** The current nav item, tab, segment or side-nav item is shown with `text-primary`, plus an underline or a `surface-2` fill. The same goes for a checked Checkbox, an on Switch and a checked chip: `text-primary` fill with a dark check or thumb, never `brand` blue (see "Form controls" below). Neutral is the only checked style: the Settings forms (session 9) and the Screener sidebar (session 10) both use it, and the old `brand` `Checkbox` variant was deleted with the Screener migration (`variant` is now `neutral`, the default, or `chip`).
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
- **Radius:** `radius-md` (8px) for buttons, segments, side-nav items, boxed fields (the ticker search and every form field) and native selects; `radius-lg` (10px) only for the rare Card. There is no underline field: the Screener sidebar was the last place that used one, it is boxed too (session 10), and the underline variants of `Input` and `NumberField` were deleted with that migration.
- **Layout:** `PageContainer` (1280px, 32px gutter) wraps every page, and every page starts with the same `PageHeader`.
- **Icons:** Phosphor, regular weight, 16px, `currentColor`. No emoji.
- **Focus:** a 2px `brand` outline on keyboard focus only (`:focus-visible`). Hover and focus never leave a lasting highlight.

## Choosing the right control

| The job | Use |
| --- | --- |
| Move between pages | TopNav (one item current: `surface-2` fill, `text-primary`, `aria-current="page"`) |
| Move between areas of Settings | SideNav |
| Switch between views of one ticker, or between a few groups of one table (the Financials statement, the Scheduled jobs cadence) | Tabs (neutral underline), with an `aria-label` where the page has more than one tab list |
| Change a data option on the same view | SegmentedControl, the one implementation in `components/ui/segmented-control` with a neutral selected state (fixed 2–6 options only — use Tabs instead for an unbounded set, e.g. the Watchlist switcher) |
| Show or hide an overlay on a chart, independently of the others | `Switch` with a visible sentence-case label where the row has room; where it does not (a row of ten), an `outline` `sm` `Button` with `aria-pressed` and a neutral selected state. Never a segmented control (the options are not exclusive) and never brand blue (see "Ticker page controls, part C1") |
| Do something | Button: one `primary` per region, `ghost` for everything else. `outline` (ghost with a hairline border that turns `brand` on hover) is for a secondary action that has to read as a button inside a dense panel. The Screener uses it for Sort direction, Save current view, Reset and Recompute all scores (session 10, part 2); nothing in the Screener hand-writes the "ghost plus `border-border-input hover:border-brand`" override any more. The Watchlist page and the two shared buttons follow in session 11 (see "Watchlist page and shared buttons" below); an icon-only button is a `Button` with an `icon` size and an `aria-label` |
| Sort a list by a field and a direction | A `Select` labelled "Sort by" for the field plus one `outline` toggle `Button` (an arrow icon, "Asc" or "Desc") for the direction. Not a segmented control, and not a column header (see "Screener results controls") |
| Adjust a percentage by dragging (the Custom valuation growth and discount-rate sliders) | The native `.range-slider` range input, with a real `<label for>`, `aria-valuetext` carrying the displayed value ("+14.6%"), and the global keyboard focus ring. Not a custom slider |
| Enter a typed value (a number, or short text) on a form page | `NumberField` for numbers, `Input` for text, each in a `FormField` or a Settings row |
| Choose one of a few options on a form page | Native `Select` (in its themed shell), at `short` or `medium` size. Not a SegmentedControl: that is for switching a view, not for a saved setting |
| Filter a number to a range (a Min/Max pair) | `RangeField`: one label, a unit in the label row, two `short` boxed boxes. Never two separate fields |
| Filter by any of many options (Sector, Moat, Weinstein stage) | `MultiSelectDropdown`: a trigger that opens a checkbox popover. Not a native `<select multiple>`, and not a row of chips |
| Turn a yes/no filter on in a dense sidebar | `Checkbox` `variant="chip"` at full width; the checked fill is the applied signal |
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

The controls for typing, choosing and toggling a value on a form page. Built 2026-09-30 (session 8) and shown in `/styleguide`. All five Settings forms (REIT dividend yield, Economic moat, Discount rate, Weinstein, Liquidity) use them as of session 9, and the Screener sidebar's fields (the Watchlist scope select, every Min/Max range, the multi-selects' checkboxes and the two chips) use them as of session 10. The Screener's results controls (the sort select and direction button, the saved-views bar and its naming row, pagination, the multi-select trigger's name) follow in session 10, part 2; see "Screener results controls" below. The Watchlist name editor moved onto the kit in session 11, and `AddToWatchlistButton` and `BankCapitalMetricsForm` in session 12 (see "Ticker page controls, part A"), and the Custom valuation panel's select, rows and buttons in session 13 (see "Ticker page controls, part B"). `Select` always takes a `size`. The `/styleguide` "Screener sidebar (mock)" section stays as the reference for the sidebar, and "Screener results controls (mock)" for the controls around the results.

| Control | Component | Job |
| --- | --- | --- |
| Number | `NumberField` (`components/ui/number-field.tsx`) | A typed number with optional integer, min, max, step, unit |
| Text | `Input` with a `size` token (always boxed) | A short piece of text (a ticker, a benchmark symbol) |
| Choice | `Select` with a `size` token | One of a few options, a native `<select>` |
| On/off with Save | `Checkbox` (neutral; `variant="chip"` for a filter chip) | Saved when the form is |
| On/off now | `Switch` (`components/ui/switch.tsx`) | Applied immediately, no Save |
| Anatomy | `FormField` (`components/ui/form-field.tsx`) | Label, hint, control, unit, error, wired together |

**Boxed on form pages.** A form field is a box: `radius-md`, 1px `border-control`, `page` fill, 36px high. This reverses the earlier "boxed for the ticker search only" rule. The Screener sidebar is boxed as well: the owner chose boxed over underline (session 10) after comparing both, built from the real primitives, in the `/styleguide` mock. That reverses the earlier "underline stays for inline filters" rule and settles the deferral in session 8's first decision. The underline variants of `Input` and `NumberField`, the old `Field` label wrapper with its orange `applied` prop, and `RangeInput` were deleted with the migration; `FormField` (compact density, `applied`) replaces them.

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

### Screener filter sidebar (session 10)

The primitives below were built additive and opt-in (Settings renders exactly as before) and the Screener sidebar now uses them. The `/styleguide` "Screener sidebar (mock)" section is the visual reference.

**`NumberField` additions.** All default to today's behaviour, so the Settings forms are unchanged.

| Prop | Default | What it does |
| --- | --- | --- |
| `optional` | off | An empty field is valid and its check reports a `null` value, instead of "Enter a number." |
| `suffixes` | none | A map such as `{ M: 1e6, B: 1e9, T: 1e12 }`. Text like `500M`, `2B`, `1.5T` or `2 m` (case-insensitive, optional space) parses to base units. Anything else with letters is invalid (`1x`, `5e`, `1BX`). Without `suffixes`, letters are invalid as always |
| `keyboardStep` | on | `false` disables ArrowUp and ArrowDown stepping (a market-cap box has no sensible step) |
| `hideError` | off | The field draws no error line of its own, so a composite can show one line under a pair. It still sets `aria-invalid` and accepts an `aria-describedby` |

`aria-describedby` and every other attribute still pass through. A number is never clamped, rounded or corrected, with or without a suffix.

**Compact `FormField`.** `density="compact"` is for the filter sidebar only: the label is `text-xs` `text-secondary`, the gap to the control is 2px, there is no hint line by default (an optional hint sits under the field: Mkt cap's "Type 500M or 2B." and the Watchlist scope sentence, which wraps in the 222px column), and a `unit` renders **in the label row, right-aligned in `text-tertiary`**, not after the box. An `applied` prop turns the label text `filter-active` orange. The default density is unchanged: `text-sm` label, hint under it, unit after the box.

**`RangeField`** (`components/ui/range-field.tsx`). One labelled Min/Max pair for a numeric range. Props: the numeric `{ min, max }` value, `onChange` with the same shape, `label`, `unit`, `size` (`short`), optional `suffixes` (market cap) and `min` (market cap: 0), and an optional single hint. It is `role="group"` labelled by its label; the boxes are named "Minimum" and "Maximum" and have the placeholders "Min" and "Max". Typed text lives in a per-side draft (`useDraftNumber`, `lib/hooks/useDraftNumber.ts`); the filter state stays numeric, so `ScreenerFilterState` and saved views do not change.

The commit rule for a Min/Max pair (live filtering, nothing waits for Apply or blur):

1. **Valid text commits immediately**, including `12.` and `.5`.
2. **An incomplete prefix** (`-`, `.`, `-.`) **holds the previous committed value** with no error while the box is focused. On blur it becomes invalid: that side emits `null` and the error shows.
3. **Any other invalid text** (letters, `1x`, `5e`) makes that side inactive at once (it emits `null`) and shows an inline error.
4. **Never clamp, swap or correct.** The only bound is a market cap of at least 0.
5. **A reversed range** (min higher than max) is applied literally, so nothing matches, exactly as today. One message sits under both boxes, "Min is higher than max, so no ticker can match.", and only the Max box is marked invalid.
6. **One error line** under the pair, never one per box. A text error wins over the reversed-range message.
7. **External changes re-sync the boxes.** The hook remembers the exact `{ min, max }` object it last emitted (none until the first emit, so a reset to the very object the field mounted with also counts as external). A different object from outside (Reset, loading a saved view, a remount) rewrites the drafts, even when its numbers equal the current ones, so stale invalid text such as `1x` is cleared. The same object handed back never rewrites what the user is typing. Parents must therefore pass the emitted object back unchanged.
8. A market-cap box shows the shortest exact form on mount or re-sync (`1e9` reads `1B`, `2.5e12` reads `2.5T`, `1234567` stays plain digits).

**The 256px filter sidebar.** The Screener sidebar stays `w-64` (256px): with the card's 1px borders and `p-4`, its content is **222px** wide. It is not widened. A range pair is two `short` (96px) boxes with a dash between them and fits without overflow. **Units sit in the label row**, right-aligned in `text-tertiary`: Quote and Mkt cap "USD" (every current ticker is USD-quoted, so the label is always true), P/E "x", Growth "%"; the score fields (Overall, Financials, Growth rate, Profitability, Debt) and Beta have none. A label is `text-xs` sentence case (Overall, Financials, Growth rate, Profitability, Debt, Quote, P/E, Growth, Mkt cap, Beta). Mkt cap carries the one-line hint "Type 500M or 2B." Below `lg` the sidebar still stacks above the results. Chip and multi-select labels are sentence case too ("Speculative growth", "Weinstein stage", "Wide moat", "Blue up"); this is display only, and the filter values, option keys and saved views are unchanged.

**Applied state.** A filter label turns `filter-active` orange while it holds a value, the one documented colour exception; orange is label *text* colour only, on a range or select label (`FormField` `applied`) and on a multi-select trigger's text. A chip shows applied through its checked fill (`surface-2`, `text-primary`), not orange. The Watchlist scope label is orange only while the watchlist filter is actually in effect (the universe is All and a watchlist is selected): a selected watchlist that is dimmed because the universe is not "All" is not applied. Each section header (Watchlist, Fundamental, Technical) carries a neutral applied-count `Badge` (compact, neutral tone, for example "3"), computed from `countActiveFilters(filters, watchlistActive)` in `lib/screenerFilters.ts` over that section's filters: applied ranges, non-empty multi-selects, checked chips and an in-effect watchlist. A section with nothing applied shows no badge (a "0" would be noise on every header), and the badge stays visible while the section is collapsed, which is what it is for.

**The Watchlist scope field.** The section is titled "Watchlist", so its field is labelled "Limit results to" (a second "Watchlist" would read as a duplicate). It is a `FormField` (compact) with a full-size `Select`; the one helper sentence is the hint, and the whole field (label, box and hint) is disabled and dimmed while the universe is not All.

**Market-cap suffixes** are M, B and T (`5T` is 5,000,000,000,000), case-insensitive with an optional space (`2 m`). There is one parser, `checkNumber(..., { suffixes })` in `lib/numberInput.ts`, used by `NumberField` and `RangeField`; the sidebar's old strict `parseMarketCapInput` is deleted.

**Sidebar shell.** The sidebar stays mounted when the universe changes: the results area shows the loading (and the error) state, and the header, the Sort row and the sidebar stay in place, so collapse state, the active saved-view name, a half-typed view name and range drafts survive a universe switch. The Sector and Company type options come from the loaded rows, so the last known lists are kept while a new universe loads and the multi-selects never empty out. Reset returns the filters, the universe, the watchlist, the sort (the page's default field and direction) and the active view name to their defaults.

### Screener results controls (session 10, part 2)

The controls around the results: the Sort row, Pagination, the saved-views bar and the multi-select trigger's name. They use the same kit as the sidebar. The `/styleguide` "Screener results controls (mock)" section renders the real components with mock data (Sort row, Pagination at the first, a middle and the last page, the saved-views popover with its list and an active view, the naming step at 222 and 256px and with a "/" error, the overwrite confirm, a multi-select trigger with none, one and several selected, and a table of the computed sizes). The components are `SortControls` (`components/screener/SortControls.tsx`, which owns the sort options), `Pagination`, `SavedFiltersBar` and `MultiSelectDropdown`. `SavedFiltersBar` is a thin wrapper that supplies the SWR list and the real save and delete calls to `SavedFiltersBarView`; the styleguide renders the view over an in-memory list (`MockSavedViewsBar`), so nothing in the mock can reach the backend. The "Screener sidebar (mock)" now shows the same real bar, in place of its earlier hand-built Sort select, glyph buttons and naming row.

**Sort row.** A real `<label for>` "Sort by" (`text-xs` `text-secondary`) tied to a native boxed `Select` of size `wide` (320px, capped to its container), then the direction toggle. `medium` (176px) clips: the longest label, "Warren signal recency", is about 146px wide at 14px Public Sans (computed from the font's advance widths), and a medium select leaves 130px for text after its padding and caret. The row wraps below `lg` rather than overflowing. Option labels are sentence case, **display only**: "Overall score", "Financials score", "Growth rate score", "Profitability score", "Debt score", "Quote", "Market cap", "P/E", "Beta", "Growth rate", "Warren signal recency", "Weinstein: stage since". The option values, the `SortField` type and everything stored in a saved view or sent to the backend are unchanged. Changing the field or the direction returns to page 1.

**Sort direction** stays one toggle button (not a segmented control), `Button` `variant="outline"` at the default size, which is 36px like the `Select` beside it (`size="sm"` is 32px for the outline variant, so it is not used here). It shows a Phosphor `ArrowUp` or `ArrowDown` (decorative) and the visible word "Asc" or "Desc". Its accessible name states the current direction and the action: "Sort direction: descending. Switch to ascending." (and the mirror). The old `title` tooltip and the "↑ Asc" / "↓ Desc" text glyphs are gone.

**Pagination.** The current page is the neutral selected treatment the segmented control uses (`surface-2` fill, `text-primary`), never `brand` blue, plus `aria-current="page"`. Previous and Next are a Phosphor `CaretLeft` or `CaretRight` (decorative) with the words "Prev" and "Next" and the accessible names "Previous page" and "Next page". The page window (the first and last page always, the current page plus or minus two, "…" for a gap), the disabled first and last states and the 18-row page size are unchanged.

**Multi-select trigger name.** The trigger's accessible name is "<label>: <summary>": "Sector: none selected", "Sector: Technology" (exactly one), "Sector: 3 selected". The visible text is unchanged (the label with none, the option's name with one, "Sector (3)" with several), so with several selected the name does not repeat the visible "(3)" verbatim; that is the one place the name and the visible text differ. The caret is a decorative Phosphor `CaretDown` (`aria-hidden`), like `Select`'s. `aria-haspopup="listbox"` and `aria-expanded` stay on the trigger. The keyboard behaviour, option markup and focus handling are not changed by this rule.

**Saved-views bar.** One vertical bar (the sidebar's; the horizontal layout and its `layout` prop are deleted), every string in sentence case ("Saved views", "Save current view", "Reset").

- *Trigger and popover.* The trigger is a disclosure button (`aria-expanded`, `aria-controls`) showing "Saved views (n)" or the active view's name, with a decorative `CaretDown`. Escape closes the popover and returns focus to the trigger; an outside click still closes it.
- *Rows.* The popover is a labelled group, not a listbox. Each view is a row of two real buttons: a load button (the view's name, full row width) and a separate delete button whose accessible name includes the view name (`Delete view "Growth screen"`). Enter or Space on the load button loads the view and closes the popover, returning focus to the trigger. Deleting moves focus to the next row (the previous row, or the trigger when none is left) so focus is never dropped.
- *Active marker.* Neutral: a `text-primary` check, `surface-2` fill and a heavier weight, plus `aria-current="true"` on the load button, so it is not colour alone. The brand-blue check is gone.
- *Naming step.* A compact `FormField` labelled "View name" with a boxed full-width `Input` on its own row, then Save and Cancel (`outline` `Button`s) on the row below. Enter saves, Escape cancels. The validation is unchanged: an empty or whitespace-only name cannot be saved and the name is trimmed before saving; there is no maximum length (the backend has none). The one new rule is that a name cannot contain "/" (see below). The bar sits at the sidebar's 256px, outside the filter cards, so the naming step is 256px wide on the page and 222px wherever it is placed inside a card; it is designed for 222px and nothing overflows at either (computed, not measured: the Input is `w-full`, the Save and Cancel row is at most about 162px with the widest label "Save failed").
- *Overwrite confirm.* The message on its own line (about 405px on one line, so it wraps to two at 222px; a long unbroken name breaks), then "Overwrite" and "Cancel" on the row below (about 155px), in the same 222px.
- *Names with "/".* Verified 2026-09-30 against the real routes (see `docs/decisions.md`): a view named with "/" cannot be saved or deleted (`PUT` and `DELETE /api/screener/filters/{name}` answer 404, because the client sends the name as one path segment and the server decodes `%2F` back to "/" before routing). Spaces, "?", "#", "%", "+", a backslash, ";", "&" and non-ASCII names all save, list, load and delete correctly. So the naming input rejects "/" with an inline message and never alters the typed text; the backend is unchanged.

**Outline Button.** Sort direction, Save current view, Reset, the naming step's and overwrite row's buttons and Recompute all scores are `Button variant="outline"`. Recompute's logic is unchanged (styling only). The Watchlist page and the shared `RefreshButton` and `ExportMenu` joined them in session 11 (next section). The ticker page followed in session 12 (`AddToWatchlistButton`, `BankCapitalMetricsForm`, the Moat tab's Cancel) and session 13 (`ManualCalculationPanel`); no ticker-page action button hand-writes the override any more. Inside the Screener the only hand-written `border-border-input hover:border-brand` left are the two dropdown triggers (`MultiSelectDropdown`, and the saved-views trigger), which are not action buttons, and the card hover on `ScreenerCard`.

### Watchlist page and shared buttons (session 11)

The Watchlist page's controls and the two buttons shared with other pages moved onto the kit. The `/styleguide` "Watchlist and shared buttons (mock)" section renders the real components with mock data (rename idle, editing, invalid and two server errors, plus one at a phone's 311px content width; delete idle, asking and failed; `ExportMenu` closed, open and disabled; `RefreshButton` idle, loading, refreshed and failed). To draw those states without touching the backend, `WatchlistNameEditor`, `WatchlistDeleteButton`, `ExportMenu` and `RefreshButton` each take optional styleguide seams (a swappable request, `rename`, `remove` or `request`, and a starting state, `defaultEditing`, `defaultValue`, `defaultError`, `defaultStatus` or `defaultOpen`); the real pages pass none of them and behave exactly as before. Table cell content (the Moat, Value and Analysis pills, Rating as coloured text) is not touched.

**Outline and size.** A hand-written bordered button becomes `Button variant="outline"`. The size follows the neighbours: the default 36px where the button sits beside an input or select (the rename row: Save and Cancel), and `size="sm"` (32px) in a dense toolbar or table row with other 32px controls (`ExportMenu` and `RefreshButton`, which sit in rows beside 32px buttons, and the Watchlist table's remove, confirm and cancel buttons, inside rows that are already at least 36px tall because of the mini charts). The tone of a special state is kept with a colour class on the outline button, not a new variant (the remove button's negative error state and its `warn` confirm).

**Icon-only buttons.** `Button` has two square icon sizes: `icon` (36px) and `icon-sm` (28px, and 32px as an `outline`, like `sm`). An icon-only button always has an `aria-label` (and keeps any `title` it already had as its tooltip); the Phosphor icon inside is 16px and `aria-hidden`. A text glyph ("▾", "−", "✓", an arrow or "×") is never used as an icon: use the Phosphor equivalent (`CaretDown`, `Minus`, `Check`, `X`).

**Watchlist name editor.** The kit `Input` with no class overrides (36px, boxed, the `wide` token) and the accessible name "Watchlist name"; Save and Cancel are 36px `outline` buttons on the same row, which wraps below the input when the screen is narrow. Enter saves and Escape cancels (both already worked). The length limit mirrors the backend: `WatchlistName` in `backend/core/schemas.py` strips whitespace, then requires 1 to 100 characters, so `maxLength` is 100 (the constant is shared in `lib/watchlistName.ts`; `AddToWatchlistButton` adopted it in session 12). A rejection from the server is shown inline, using the server's own message (`errorDetail`), with the duplicate-name 409 as a short "already exists" line.

**Delete watchlist.** The state machine is unchanged: idle, an inline "Delete "name"?" question with Confirm and Cancel (there is no `window.confirm`), deleting, error. The trash trigger is a ghost icon button that turns negative on hover and stays negative in its error state; Confirm is the `danger` Button, the destructive variant shown in the Buttons section of `/styleguide`; Cancel is `outline`.

**`ExportMenu`.** The trigger is an `outline` `sm` Button, "Export list" with a decorative `CaretDown`, `aria-haspopup="menu"` and `aria-expanded`. Escape closes the menu and returns focus to the trigger (from the trigger or from an item), and a click outside closes it; both were already there and are pinned by tests. The items and what each export writes are unchanged. There is no arrow-key navigation (there never was; items are reached with Tab).

**`RefreshButton`.** An `outline` `sm` Button. Its four states (idle "Refresh data", loading "Refreshing…" and disabled, "Refreshed" with a `Check` icon, "Refresh failed") and its request are unchanged; the "✓" glyph became the icon (so its accessible name in the refreshed state is "Refreshed", without the glyph). It is rendered only by the ticker header, beside `AddToWatchlistButton`, which is also 32px high.

**`UniverseControl`.** The ticker header's Add / Remove for the opt-in universe (stock and ETF headers share the one flow; spec: `docs/specs/tracked-universe.md`, "Frontend"). Deliberately quieter than the primary `AddToWatchlistButton` it sits beside: Add to Universe is an `outline` `sm` Button with a decorative `Plus`; Remove from Universe is a `ghost` `sm` Button in `text-tertiary` that turns `negative` on hover, with the inline two-step confirm (negative "Remove from Universe?" text, a `danger` Confirm and an `outline` Cancel, no modal), the same idiom as `WatchlistDeleteButton`. It renders only one button or nothing: there is no "In universe" label (the index chip already shows membership; the long label broke the header). **Header action layout:** row 1 never wraps (`flex items-start justify-between`, no `flex-wrap`); the title block is `min-w-0 flex-1` and is what wraps or shrinks; the actions are a `shrink-0` right column holding the cluster (`flex-nowrap`, `whitespace-nowrap`, 8px gap) with the universe button first, then Add to watchlist, then Refresh. A one-line note or error sits in that column **under** the cluster, right-aligned (`role="status"` in `text-tertiary`, `role="alert"` in `negative`), so the buttons never move when one appears. No new tokens. The `/styleguide` "Watchlist and shared buttons (mock)" section draws the states with mock requests (`UniverseControlView`).

**Watchlist table remove buttons.** Remove (`Minus`), confirm (`Check`, `warn` tone) and cancel (`X`) are `outline` `icon-sm` buttons, 32px squares inside the 44px rows, with their existing accessible names and titles. The remove button keeps its negative hover and error tone; the "−" glyph is gone.

**What is left after session 11.** Superseded by sessions 12 and 13, below: no ticker-page file hand-writes a "ghost plus `border-border-input hover:border-brand`" button or a `focus:outline-none` input any more. Elsewhere the only hand-written `hover:border-brand` are the two Screener dropdown triggers and the `ScreenerCard` hover. Text-glyph affordances still in the code: the "Saved ✓" status (the Settings footer and the saved-views bar) and the "Recomputed ✓" button label, "Hide details −" and "Hide reasoning −", the sector heatmap's "↓ ↑" and "Browse by sector →"; the table's " ⚠" and the pills' "▲ ▼" are cell and pill content and stay.

### Ticker page controls, part A (session 12)

`AddToWatchlistButton`, `BankCapitalMetricsForm` and the Economic moat tab's Cancel button moved onto the kit. The decisions are in `docs/decisions.md` ("Session 12"); this section is what the code now does.

**`AddToWatchlistButton`.** The trigger is `Button variant="primary"` at `size="sm"`. (Session 12 gave it an `h-8` class because primary at `sm` was then 28px; since session 15 the kit's primary `sm` is 32px itself, so the class is gone.) 32px is what the ticker header's `RefreshButton` and the Screener results-header buttons beside it are. The default label has a `Plus` icon (decorative) and the word "Watchlist"; a custom label (the Screener's "Add to watchlist") is text only. Inside the popover every button is a `Button`: the per-row Add, Remove, Okay and Cancel are `outline` at `sm`, "Create and add" is the one `primary`, and "New watchlist" is a ghost row button with a `Plus` icon. "Added" uses a `Check` icon, not a "✓" glyph, and the warn-toned "Okay" in the confirm questions is an `outline` button with the warn colour kept as a class (the remove button keeps its negative hover the same way). The naming step is a kit `Input` named "New watchlist name" with `maxLength` 100 (`WATCHLIST_NAME_MAX_LENGTH`) and an inline `role="alert"` message linked to it; Escape in the input cancels the step, and Escape anywhere else in the open popover closes it and returns focus to the trigger.

**`BankCapitalMetricsForm`.** A kit `Card`. CET1 and NPL are `NumberField`s (optional, unit "%", `medium`) and their "as of" boxes are `Input`s, each in a `FormField` with a visible sentence-case label. There are no bounds because the backend has none (`TickerBankCapitalMetricsIn` is four optional values). Text that is not a number marks the field invalid with an inline error and disables Confirm; an error never survives the edit that fixes it. A rejection from the server is shown with its own message.

**Economic moat tab.** Only the Cancel button is `outline`; the rest of the tab is as it was.

### Ticker page controls, part B (session 13)

`ManualCalculationPanel`, the Valuation tab's right-hand "Custom valuation" card, moved onto the kit. The decisions are in `docs/decisions.md` ("Session 13"); this section is what the code now does. Its calculation, its payloads and its number parsing and formatting are untouched.

**Method select.** A native kit `Select` with the real `<label for>` "Method" (`text-xs` `text-secondary`) to its left in the card's title row, id `manual-method`. Size token `wide` (320px, capped to the container): its text room is about 274px, which fits the nine built-in labels (the longest, "Discounted free cash flow (normalized)", is about 264px, estimated at 6.95px a character) but not always the saved entry ("<method> · custom", up to about 327px), which clips when the select is closed (the open list shows it whole). Label and select sit on one line only when the card's content is at least about 505px wide (a window of about 1200px or more); below that the group wraps under the title, and below about 365px the label wraps above the select. The option values and their order are unchanged; the labels are sentence case, display only (`METHOD_LABELS` in `Step3Card` is not edited, the panel re-cases each label as it draws it). The saved entry reads "<method> · custom". The row keeps its 32px height (the Model Valuation card's title row is `min-h-8` and the two columns align row for row), so the 36px select carries a `-my-0.5` margin rather than growing the row.

**Formatted rows.** Every row is the kit `Input` (right-aligned, mono, `full` width in the value cell) wired as a `FormField` control: a real `<label for>` in the label cell, the "(in millions)" note as its linked hint, and an inline `role="alert"` error under the box for text that is not a number. None became `NumberField`: a row shows formatted text ("$48,253.00", "+35.0%") while idle and the raw number while focused, and parses with `parseFloat` (so "12abc" reads 12, "1e3" reads 1000 and "+4" reads 4), none of which `NumberField` can do (it holds the raw text only and rejects those). The parse, the format and what is sent are exactly as before; the error appears only for non-empty text the existing parse reads as nothing at all, which is the text the old code silently sent as `null`. Nothing blocks Save or the calculation, and nothing is clamped or corrected. There are no min or max: the backend has none for these fields and the panel never had any.

**Sliders.** The `.range-slider` styling and the live recalculation on every tick are unchanged. Each slider has its label as a real `<label for>`, its note linked with `aria-describedby`, an `aria-valuetext` equal to the readout beside it ("+14.6%"), and a visible keyboard focus ring (the global `.range-slider:focus { outline: none }` removed it; session 13 restored the ring with utility classes on the input because the global CSS was not edited, and session 14 fixed the global rule instead, see "Ticker page controls, part C1"). Arrow, Home, End and Page keys are the browser's own.

**Action buttons.** All six are `Button`. In the status bar they are `size="sm"`, 32px (the same height as the outline `RefreshButton` and `ExportMenu` in a dense row): Save is the one `primary` (with `h-8` until session 15, when the kit's primary `sm` became 32px itself; as `AddToWatchlistButton`), Revert to auto is `outline`, and Activate and Delete are `outline` with their positive and negative tone kept as colour classes (the session 11 precedent). In the delete confirmation, Confirm delete is `danger` and Cancel is `outline`, both at the default 36px. No button in the panel was an icon or a glyph, so none gained an icon.

### Ticker page controls, part C1 (session 14)

The top-nav ticker search, the chart and price-target toggles, the segmented-control merge, the slider focus rule and a parse warning on the Custom valuation rows. The decisions are in `docs/decisions.md` ("Session 14"); this section is what the code now does.

**Ticker search.** The input is the kit `Input` with no class overrides (boxed, 36px, `text-sm`), named "Search ticker" (`aria-label`; there is no visible label), with the placeholder "Search ticker…" and the combobox attributes it always had: `role="combobox"`, `aria-expanded`, `aria-autocomplete="list"` and `aria-controls` pointing at the results listbox. There never was an `aria-activedescendant` (the options carry no ids): the highlighted option is shown with a `surface-2` fill and `aria-selected`, and focus stays in the input. The width (160px, 224px from `sm`) is set on the wrapper, and the input is `size="full"`. The nav is a fixed 48px (`h-12`) with `items-center`, so the 36px input (the old one was 32px) does not change the nav height; its links are 33px (a 21px line and 6px of padding each side). Arrow keys wrap, Enter opens the highlighted (or first) result in a new tab and Escape closes; Home, End and Tab have no handler. The results panel is unchanged and had no `outline-none`; an option reached with Tab shows the global keyboard ring.

**Chart controls.** The four range buttons are a choose-one set: the kit `SegmentedControl` (`aria-label` "Chart range"; the labels "D · 6M", "D · 1Y", "D · 2Y" and "W · 4Y" are unchanged). The ten overlay toggles (eleven on the weekly range, which adds Stage) are independent on/off, so by the table they would be `Switch`es, but a labelled switch is about 100px wide and the row of ten plus the zoom buttons is about 1,330px against a 1,216px content width, so it always wraps and the toolbar would grow. They are `outline` `sm` `Button`s with `aria-pressed` instead (the row is about 1,040px and fits on one line at desktop widths, as it did before); on is a `surface-2` fill with `text-primary`, off is the outline button's own `text-secondary`. Their labels, order, defaults (all on, Stage off) and the saved state in `localStorage` are unchanged. The Zoom in and Zoom out buttons are not toggles; they kept their hand-written style until session 15, when they became `outline` `sm` `Button`s (see part C2).

**Price-target overlay.** "Overlay stock price" is a single independent overlay in a row of its own, so it is a `Switch` with its visible label. The row keeps its old 25px height with `min-h`, so the chart below does not move.

**One segmented control.** `components/ui/segmented-control` is the only implementation; `components/shared/SegmentedControl` and its call-site props (`onChange`, a generic value) are gone. It renders a `role="group"` of `aria-pressed` toggles with a roving tab stop (only the selected segment is a tab stop; the arrow keys move between segments, a Base UI ToggleGroup behaviour) and does not let the selected segment be deselected. An optional `aria-label` names the group. The selected segment is `surface-2` with `text-primary`: the old shared control's brand-blue fill is gone everywhere. Call sites: the Financials Annual and Quarterly switch, the Economic moat rating (No moat, Narrow moat, Wide moat; the pending pick still previews before Confirm), the Sentiment details switch (Summary, vs 2M · 6M · 1Y ago), plus the chart range above. The Momentum period and the Universe selector already used it. A segment is 28px high (the shared one was 32px) and text is `text-sm`; the labels are sentence case, display only.

**Slider focus.** `.range-slider:focus { outline: none }` is now `.range-slider:focus:not(:focus-visible) { outline: none }`: a keyboard focus gets the global 2px `brand` ring (`*:focus-visible`) and a mouse press leaves no ring. Nothing else about the slider's styling changed. The session 13 utility classes on the Custom valuation sliders are gone, since the global rule alone gives the ring. The only `.range-slider` users are those four sliders.

**Parse warning.** In a Custom valuation row, text that `parseFloat` reads only a prefix of shows a polite line in the same slot as the "Enter a number." error, in `warn`: "Read as 12. Check the text." for "12abc", and "Read as 1. Remove the comma." for "1,234". It is linked to the box with `aria-describedby` and never blocks Save, the calculation or the value sent (still 12 and 1). Fully numeric text ("1e3", "+4"), empty text and the start of a number ("-", ".", "-." while the box has focus) show nothing. "Enter a number." wins when the text reads as nothing. The number in the line is plain text. Text that `Number` accepts but `parseFloat` reads differently ("0x10" is read as 0) is not warned about.

**What is left after session 14 (C2), counted by grep at the end of the session.**

- **"Ghost plus border" hand-written buttons:** the two Screener dropdown triggers (`SavedFiltersBar` and `MultiSelectDropdown`, each `h-8 border border-border-input hover:border-brand`). `ScreenerCard`'s `hover:border-brand` is a card hover, not a button. Hand-written buttons of another pattern: the warn-toned Confirm buttons in the Bank and Moat save panels, and the Chart tab's Zoom in and Zoom out buttons (borderless, `text-tertiary`).
- **`outline-none`:** only `focus:outline-none` on the two info-icon buttons, `SpeculativeGrowthInfoIcon` and `SpeculativeGrowthFakeGrowthWarning`, which changes only the icon's colour on keyboard focus and so shows no ring. Everything else that matches is a comment saying a control has none.
- **Text-glyph icons:** the "Saved ✓" status (`SettingsLayout`, `SavedFiltersBar`), the "Recomputed ✓" label (`RecomputeButton`), "Hide details −" (`ChecklistCard`) and "Hide reasoning −" (`AnalysisSectionCard`), the sector heatmap's "↓ ↑" (`SectorHeatmapGrid`), "Browse by sector →" (the Breadth page), and the "⚠" in the Watchlist table and `MetricsGrid`. The "⚠️" emoji in `OutlierWarningNote` and `OverallAssessmentCard` break the no-emoji rule. The pills' "▲ ▼" (`status.tsx`) and the arrows inside chart labels ("Live →", "Price data starts →") are content and stay.
- **Also still to do:** the Screener "Add to Watchlist" label and `Step3Card`'s Title Case labels.

(Both lists above were closed by sessions 15 and 16: the two Screener triggers moved onto the kit in session 16, see part C3.)

### Ticker page controls, part C2 (session 15)

The cleanup sweep after part C1: keyboard focus on two icon buttons, icons in place of emoji and text glyphs, sentence-case strings, the multi-select trigger's name, the 32px primary `sm` button and the last hand-written buttons. The decisions are in `docs/decisions.md` ("Session 15"); this section is what the code now does.

**Focus ring on the two info icons.** `SpeculativeGrowthInfoIcon` and `SpeculativeGrowthFakeGrowthWarning` no longer set `focus:outline-none`, so the global 2px `brand` `:focus-visible` ring shows on a keyboard focus (they still open their tooltip on focus, hover and tap, as before).

**Icons, not glyphs or emoji.** The "⚠️" emoji in `OutlierWarningNote` and `OverallAssessmentCard` are the Phosphor `Warning` icon (`aria-hidden`, drawn in the note's own tone class); the sentence next to it is unchanged. "Show details +" and "Hide details −" (`ChecklistCard`) and "Show reasoning +" and "Hide reasoning −" (`AnalysisSectionCard`) are the text with a Phosphor `CaretDown` when collapsed and `CaretUp` when expanded; the "+" and "−" characters are gone, and `aria-expanded` and the toggle behaviour are as they were. The sector heatmap's sort direction and the "Browse by sector" link use `ArrowDown`, `ArrowUp` and `ArrowRight` beside the text. A glyph that is content, not a control, stays: the pills' "▲ ▼", the "⚠" text in table and metric cells, the status labels "Saved ✓" and "Recomputed ✓", and the arrows inside chart labels ("Live →" and "Price data starts →", which are SVG text on a chart).

**Sentence case.** `Step3Card`'s Model Valuation labels and title read in sentence case, the same way the Custom valuation panel beside them does ("Growth yr 1-5", "Total debt", "Discount/premium"); the Screener button reads "Add to watchlist" (as the ticker header's does); the Economic moat tab's headings are sentence case without the uppercase tracking. Display only: no identifier, stored value or payload changed.

**Multi-select trigger.** The visible text is unchanged ("Sector", the one chosen option's name, or "Sector (3)"), and the accessible name now contains the visible text in every state: "Sector: none selected", "Sector: Technology", and "Sector (3): 3 selected" (it was "Sector: 3 selected", which did not contain "Sector (3)"). The visible text was not changed to the name's wording because the longest trigger label would not fit the 222px column ("BB + RSI entry (2h): 3 selected" is about 240px).

**Button.** `primary` at `sm` is 32px (`h-8`, a compound variant, like `outline` at `sm`), so the explicit `h-8` on the ticker header's Add to watchlist button and on the Custom valuation Save button is gone. The Bank and Moat save panels' Confirm buttons are `Button variant="primary"` with the `warn` fill kept (the action overwrites a score), 36px like the Cancel beside them. The Chart tab's Zoom in and Zoom out have visible words, so they are `outline` `sm` text buttons (32px, like the overlay toggles beside them), with no icon.

**Small fixes.** Focus returns to the "New watchlist" row button when the naming step is cancelled; ArrowUp in the ticker search with nothing highlighted goes to the last result.


### Ticker page controls, part C3 (session 16)

Two bugs found in the browser (the Speculative growth tooltips and the expanded Analysis cards), and the neutral-selection and accessibility leftovers of the C2 sweep. The decisions are in `docs/decisions.md` ("Session 16"); this section is what the code now does.

**Tooltip wrapping rule.** A hand-built tooltip bubble (`role="tooltip"`) always sets its own `whitespace-normal`, because it usually sits inside a nowrap parent (a pill, a pill group) and `white-space` is inherited. It has a bounded width that never passes the viewport (`w-64` capped at `min(18rem, 100vw - 2rem)`), keeps its padding, sits at `z-30`, and is never inside an `overflow-hidden` ancestor. Position: from `md` it is centred under its icon; below `md` the icon's wrapper is `static`, so the bubble anchors to the nearest `relative` ancestor (the ticker header's pill row) and starts at that row's left edge, which keeps it on screen wherever the pill wrapped to. The two bubbles are `SpeculativeGrowthInfoIcon` and `SpeculativeGrowthFakeGrowthWarning`; no other `role="tooltip"` exists. (The "ⓘ" and "⚠" spans in `MetricsGrid` and `RecommendationDetailsTable` use the native `title` attribute, not a bubble.)

**Details alignment rule.** Expanded "Show reasoning" or "Show details" content sits in the same column as the text it expands, so its left edge is the paragraph's left edge in both states. `AnalysisSectionCard` is `[score column, w-52] [text column]`: the text column holds the title, blurb, methodology, notes, the toggle (top right of the column) and the expanded list, so toggling only grows the column downward. The list is list-outside with `pl-5`: markers hang in that padding, bullet text is indented one step (1.25rem) from the paragraph. The whole card is still clickable: the toggle button's `::after` is stretched over the `relative` Collapsible root, and the list is `relative` so it paints above that overlay (clicks on the list do not toggle). `ChecklistCard` is a single stack with no side column, so its details were already flush with its title and paragraph; a test pins that. `CollapsibleFilterSection` is a section header with full-width content and no side column, so it is not this pattern. The cards have no breakpoint at which the score column stacks above the text (there is none in the code); at very narrow widths the fixed 208px score column leaves the text column little room, which is older than this session and not changed.

**Neutral selected treatment for navigation.** A current or selected navigation item is neutral and never brand blue, with `aria-current="page"` on a current link (and `aria-selected` where it is a tab). The treatment per place: TopNav (the current page and the Ticker Analysis indicator) is a `surface-2` fill with `text-primary`; the Breadth sector tabs the same, with a text-only hover so a hover never looks selected; the sector heatmap's active column header is `text-primary` (with the arrow and `aria-sort`); the Financials statement strip and the Scheduled jobs cadence strip are the shared `Tabs` primitive (neutral underline). Brand blue stays for real actions and links.

**Strips on Tabs.** The Financials statement strip and the Scheduled jobs cadence strip are `Tabs`, each with an `aria-label` ("Financial statement", "Job cadence"). `Tabs` gained one optional prop, `aria-label`, for this (absent by default, no default changed). Behaviour: the selection state is still local `useState`; the cadence counts show through `Tabs`' own `count` figure (so "Daily (2)" reads "Daily 2" in the mono figure style); keyboard is the standard tab model (one tab stop, arrow keys move between tabs, Enter or Space selects) instead of one tab stop per button.

**Accessible names.** `SecCellCheckButton` (the SEC EDGAR check icon on two Cash Flow rows) is named "Check SEC EDGAR figure for <field>, period ending <date>" and keeps its `title`; its icon is `aria-hidden`. No other icon-only button with a title and no `aria-label` exists.

**The two Screener dropdown triggers.** The Saved views trigger is `Button variant="outline" size="sm"` (32px, `text-xs`, like Save current view and Reset beside it) with the `CaretDown` icon, `gap-1.5` to keep its width, and a neutral border on hover (`hover:border-border-input`: it opens a list, it is not an action; the other outline buttons still turn `brand`). The multi-select trigger is the kit's boxed field: `FIELD_BOX_CLASS` (36px, `radius-md`, 1px `border-control`, `page` fill) at the column's full width, label left and `CaretDown` right as in `Select`, `text-sm`, with no hover border. Its text is `text-secondary` with nothing chosen and the filter-active tone once something is. Behaviour, focus handling, ARIA names and keyboard handling are unchanged.

**What is left after session 16, counted by grep at the end of the session** (source only, not tests, not `app/styleguide`):

- **`brand` on a selected or current state:** none. Remaining `brand` uses are actions, links, focus rings and one data bar: `Button` primary and the outline hover, the `Checkbox` and `Switch` focus rings, `MomentumBanner`, the `TickerNotFound` link button, the `SecCellCheckButton` icon's hover, `ScreenerCard`'s card hover, the Breadth page's link, and (until it was deleted with the trend-structure feature) `ReversalCard`'s freshness bar.
- **`outline-none`:** none (two comments only).
- **Hand-written bordered buttons:** none. The tone-coloured hover overrides on `Button variant="outline"` (warn and negative in `AddToWatchlistButton`, `WatchlistTable`, `SavedFiltersBar`'s overwrite and the Custom valuation Confirm buttons) are deliberate tone changes.
- **Icon-only buttons without an `aria-label`:** none.
- **Text glyphs in controls:** none in a button. Content glyphs remain: the pills' "▲ ▼", "⚠" and "ⓘ" in table and metric cells (title-only spans, mouse only), "Saved ✓" and "Recomputed ✓", "↳" sub-bullets and the arrows inside chart labels.

### Data-quality markers (2026-10-06)

Warnings that a number on a raw-display tab may be built from a bad row (spec: `docs/specs/statement-data-quality.md`, "Display markers"). They annotate; no value is hidden or replaced, and no new token is introduced. **Column marker:** the Phosphor `Info` icon (13px, bold, decorative inside a `role="img"` span whose `aria-label` is the sentence) in the `warn` tone, before the column's header text in `FinancialsStatementTable`, with a native `title` carrying the sentence and the evidence (the same `title` idiom as the Income Taxes Paid and Interest Paid icons). **Box:** `PartialBalanceSheetNote` is the `OutlierWarningNote` box (`rounded-md border border-warn/40 bg-warn/10 p-3`, Phosphor `Warning`, an `sr-only` "Warning:" prefix) with the sentence in `text-sm text-warn` and the evidence line in `text-xs text-warn/80`; a separate component so the existing note and `/styleguide` are untouched. **Muted line:** `NotLandedLine`, `text-xs text-text-tertiary`. **Inline note:** `FmpRatiosNote`, `text-xs text-warn`, on the Ratios tab and in the Step 4 card's notes. All wording lives in `lib/dataQuality.ts` (sentence case, no new terms); the backend sends facts only.

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

**Score weighting (2026-10-06).** The one section with many numeric rows saved by one action, between "Discount rate by country" and "Economic moat" (`components/settings/ScoreWeightingForm.tsx`). Five `SettingsGroup`s ("Overall weights", "Financials", "Growth Rate", "Profitability", "Debt"), each of `NumberSettingRow`s with `integer`, `min` and `max` taken from the endpoint's `bounds` (never constants). Each group ends with a **sum caption** (`text-xs`, tertiary, `negative` when wrong): "Sum 69 of 69" or "Sum 71, needs 69"; Save stays disabled until every set adds up. The Overall group's fifth row is the locked "Economic moat 31%" (a disabled, read-only `NumberField`, hint says why). `SettingsFooter` gained a `secondary` slot, rendered right after Save, used for the outline "Reset to defaults" button. Save and Reset each open the same warn-toned confirmation panel the Economic moat tab uses (one `primary` Confirm in the warn fill, an outline Cancel) because they change every ticker's score. While a recompute runs the section shows "Recomputing scores, N of M" (`RecomputeStatusLine`, polled every 1.5 s), disables every control and Save/Reset; a failed run shows its reason in `negative`, and the saved weights stay displayed. No sliders: whole-number inputs only.

**Immediate-apply sections.** Scheduled jobs and FMP data groups have no Save button and are not built from rows. Their controls apply the moment they are changed, so they are `Switch` (on/off) and native `Select` (a choice, at `medium` unless a shorter token clearly fits its options), never a `Checkbox`. FMP data groups is a table (a `Switch` and a tier `Select` in each row's cells) with the FMP status card below it: the "My FMP plan" `Select` and the "FMP master switch" `Switch`, the FMP key problem, and the section's own error line. Each control is named by its visible label or row, is disabled while a request is in flight, and is driven by the fetched data, not by local state: a cancelled confirmation, or a failed request, leaves the control showing the real current state, and a failure shows the server's message inline near the control. The Scheduled jobs table is `table-fixed` with a 112px (`w-28`) Time column: every body cell that can hold a long string wraps (`whitespace-normal`: Description, Time, Message), because a `TableCell` is `whitespace-nowrap` by default and a fixed-layout cell does not grow (the monthly label "1st–5th, 2:50 AM", 16 mono characters at `text-xs`, is about 115px against a 96px content box and wraps to two lines; Daily and Weekly labels, at most 11 characters, stay on one).

A section that saves several independent panels (Discount Rate has one per region) repeats a titled group with its own rows and footer per panel; the panel is a `SettingsGroup`, not a boxed Card.

## Pills

One family, two components, two sizes. `Status` (a labelled state, with an optional ▲/▼ direction glyph) and `Badge` (a short value or label, with a `missing` state) render the same pill; `Verdict` is `Status` for a verdict word. They never differ in look, only in what they are for. Nothing in the app hand-rolls a pill, a dot or an inline status colour — a new status goes through these. That includes the Screener's `PullbackPill` and `ReversalPill`, which were the reference style and now render through `Status` themselves (2026-09-29), and the Technical tab's `ChecklistCard` status chip.

**Anatomy.** `radius-md` (8px). Fill is the tone colour at 16% opacity, text is the tone colour at full strength, and there is no border. This is the look of the Weinstein stage pill ("Stage 2 · Advance" and so on; the Screener card shows the same wording as the ticker header), which is the reference style (it was originally set by the Pullback/Reversal pills, since removed with the trend-structure feature). No new colours: every tone reuses an existing token.

| Size | Type | Padding | Height | Where |
| --- | --- | --- | --- | --- |
| Regular | 13px, weight 600 | 4px / 8px | 25px | Ticker header, Screener cards, tabs, Settings tables, anywhere a pill is a first-class read |
| Compact | 11px, weight 500 | 2px / 6px | 20px | Dense tables only (Watchlist, Momentum). Same tint as regular, so the colour signal is not weakened; only the type and padding are quieter |

The choice of size is the only difference between a Watchlist Moat cell and the ticker header's Moat pill.

**Tones.** Tier logic stays in `lib/tierColor.ts`; this guide defines the colours.

| Tone | Token | Label / where it shows up |
| --- | --- | --- |
| `strong` | `positive-strong` | Strong pass (score above 90), Wide moat, Undervalued, 5Y vs SPY outperform |
| `positive` | `positive` (muted green) | Pass (score 75 to 90), Narrow moat, Fairvalued, Stage 2 (Advance) |
| `warn` | `warn` | Needs review: the amber borderline read. In the app the 70 to 74 score band carries the backend's own verdict word "Pass" in this tone; "Needs review" is the tone's name and its styleguide label. Also Stage 3 (Top) |
| `caution` | `caution` | Pass with caution (checked before score tiers) |
| `negative` | `negative` | Fail, No moat, Overvalued, Stage 4 (Decline), Trend invalidated |
| `speculative` | `chart-purple` | Speculative growth only |
| `neutral` | `surface-2` fill, `text-secondary` | No read to colour: Not scored, N/A, Stage 1 (Base), index membership (S&P 500, Nasdaq, Dow 30), company kind (Badge), Skipped and Unknown in the jobs tables, a stale Reversal, and any value with no Pass/Fail meaning |

`Badge` and `Status` share this tone set. "Pass with caution" is `caution` everywhere, Watchlist included.

**Review status (2026-10-06).** The four Review statuses reuse existing tones, no new token (`lib/reviewStatus.ts`): "Review (structural)" is `caution` (the deeper amber, the stronger read); "Review (unclear)", "Review (by design)" and "Data uncertain" are `warn`. Never `negative`: a Review is not a Fail. It appears as the ticker header's Assessment chip (the label replaces the verdict word; the native `title` carries the Overall score, the gated step, the evidence and the conviction, and the chip shows no number of its own), as a block on the Analysis card (a `Warning` icon, `text-caution` or `text-warn`, one bullet per gated step), and, since phase 2, as `components/shared/ReviewMarkers.tsx`: a compact `Status` pill under the score and verdict badge on the Screener card (right-aligned in the card header, only when the row has a status), and an icon-only marker (phosphor `Flag`, 12px, `text-caution` or `text-warn`, the label as `sr-only` text, the same tooltip as `title`) after the score pill in the Watchlist Analysis cell and left of the neutral score badge in the Momentum Score cell. The score pill or badge beside it is never changed. The ETF tables keep drawing no status. The Screener sidebar's "Review status" is an ordinary `MultiSelectDropdown` (orange label when active, like Moat). No new tone or token.

**Score and label.** A score number standing beside a pill is never coloured: it is `text-primary`, mono, tabular, and the pill carries the tone. (A number written inside a pill's own label — the Watchlist Analysis cell, the Overall Assessment breakdown chips — takes that pill's tone, because the pill is the value.) Inline (an Analysis section header) the number sits to the left of the pill with an 8px gap, vertically centred: `74 [Pass with caution]`. Stacked (a Screener card header, where the number is large) the number sits above the pill, both right-aligned. A Watchlist Analysis cell is one column wide, so its compact pill holds the score itself (toned by the verdict, with a ⚠ appended for Pass with caution, whose tooltip names the steps) rather than a number plus a label. A score without a computed value is a neutral pill or a `missing` Badge ("—"), never a bare dash. The Overall Assessment's circular score badge is a gauge, not a pill, but follows the same rule: its number is neutral `text-primary` and the ring stroke carries the tone (full-strength tone colour, no fill). Beside it sits the headline verdict pill.

**Wrapping.** Pills never break internally (`nowrap`). A row of pills is a `flex-wrap` container with an 8px gap in both directions, so a row wraps whole pills onto the next line at narrow widths and stays left-aligned. An info or warning icon that belongs to a pill (Speculative growth, Stage pending) is wrapped with it so the two never split across lines. The ticker header's status row (Assessment, Moat, Valuation, Speculative growth, 5Y vs SPY, Stage) is about six pills wide and follows this rule.

**Not a pill: the Watchlist Rating.** The analyst consensus in the Watchlist's Rating column (Buy / Hold / Sell) stays as tone-coloured text, not a pill. It is the one deliberate exception (2026-09-29): it sits directly after the Moat, Value and Analysis pills, and a fourth adjacent pill would make that strip busy for no consistency gain, since no other view shows the rating as a pill.

**Not a Status.** A dot is still right for a chart legend key (see `docs/design-system-charts.md`) and a timeline marker, because they name a series or a point in time, not a state. A pill is not used for a filter chip or a button.

## Foundational decisions (settled, built)

- **Direction B** ("quiet minimalist") over a consolidated version of the old look.
- **Tables:** hover only on rows that open something; whole-row click opens the ticker in a new tab; Screener cards unchanged; Watchlist and Momentum use the compact size of the same pill family as everywhere else (2026-09-29 reversal — they previously kept a separate filled `Badge`; see `docs/decisions.md`).
- **Fonts:** Public Sans, Sora, IBM Plex Mono — no change needed from what the app already had.
- **New tabs:** ticker links in the Stocks Screener, ETFs, Momentum and Watchlist, and every top-nav link and the logo, open in a new tab so the current page (e.g. Screener filters) stays put. The top nav reads Stocks, ETFs, Watchlist, Momentum, Sectors, Breadth, Settings (2026-10-02: "Screener" became "Stocks"; the route stays `/screener`, and the `/etfs` page is the ETF twin of it, see `docs/specs/etf-screener.md`, "Frontend"). Exception: on Momentum, Sectors, Breadth (incl. sub-routes) and Settings the nav links and logo navigate in the same tab. Ticker search always opens a new tab. Two tabs each showing an active item is expected behaviour, not a bug.
- **By choosing B:** dark `on-brand` text on the primary button; underline inputs with `border-control` (retired in session 10: every form and filter field is now boxed, see "Form controls" and the 2026-09-30 entries in `docs/decisions.md`); ▲/▼ glyph on the 5Y vs SPY status; orange stays reserved for the applied-filter label. (Also originally: "filled pills dropped from headers, tiles and lists", with `Status` as a dot and a word. Reversed 2026-09-29: status is now a pill everywhere — see "Pills" above and `docs/decisions.md`.)
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
   hits plus unrelated component/comment hits — no bare, unprefixed `control` class survives
   anywhere. **Updated 2026-10-01 (session 15):** the hits listed at the time have since moved
   onto the form-control kit, so the correctly-prefixed class now lives in only a few places: the
   shared box in `lib/formControl.ts` (every `Input`, `NumberField` and `Select`), the stepper
   buttons in `number-field.tsx`, the `Checkbox` and `Switch` boxes, and the styleguide. Gone since
   (each by its own session): `TickerSearch.tsx` (the kit `Input`, session 14), `BankCapitalMetricsForm.tsx`
   (`NumberField` and `Input`, session 12), `AddToWatchlistButton.tsx` (session 12), `SavedFiltersBar.tsx`
   and `app/screener/page.tsx` (session 10, part 2), `WatchlistFilters.tsx`, `NumberStepper.tsx` and
   `RangeInput.tsx` (session 10 and earlier; the last two are deleted).

## `MultiSelect` primitive — built, not a placeholder

Resolved the same day as the items above: `components/screener/MultiSelectDropdown.tsx` is a
real, finished primitive — checkbox-listbox popover with a focus trap, roving arrow-key/Home/End
navigation between options, Escape-to-close, a "Clear" action, and this ARIA: the trigger button has
`aria-haspopup="listbox"` and `aria-expanded`, the panel is `role="listbox"` with
`aria-multiselectable="true"` and `aria-label`, and each option is a `<label role="option"
aria-selected>` wrapping a native checkbox. That is **not** "full ARIA": there is no
`aria-controls`, and no `aria-activedescendant` (focus roves across the real checkboxes instead), the
options contain interactive checkboxes (not the canonical listbox pattern), the Clear button is a
child of the listbox, and (until session 10, part 2) the trigger's accessible name was its visible summary text (the label with
none or several chosen, but just the option's name with exactly one, plus the ▾ glyph). Session 10, part 2 gave it
the explicit name "<label>: <summary>" and a decorative `CaretDown` (see "Screener results controls"). None of it has been checked with
a screen reader. Session 10 swapped the option checkboxes for the bare neutral `Checkbox` without
changing any of this. The popover is built entirely on named tokens
(`border-input`, `surface`, `surface-2`,
`text-secondary`/`text-tertiary`); the trigger itself is the kit's boxed field since session 16
(no hover border). Used by
`FundamentalFilters.tsx` and `TechnicalFilters.tsx` for every Screener multi-select filter. The
5c-era "left deliberately unstyled" state (see `docs/decisions.md`) is fully superseded.

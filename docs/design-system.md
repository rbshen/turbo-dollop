# Fathom Design System

A calm, data-first interface for fundamental investing.

> This is the living style guide for Fathom's frontend. It was drafted in a claude.ai chat working from a read-only audit of the codebase, decided against a two-way A/B comparison ("Direction B, quiet minimalist"), and implemented page-by-page on the `ui/design-system` branch (sessions 1 through 6b). Token names and values are authored in `frontend/app/globals.css` — this document explains what they mean and when to use them, it is not a second source of truth for the values themselves. Chart-specific rules live in `docs/design-system-charts.md`. The build history and open items are in `docs/decisions.md`.

## Principles

1. **Whitespace and hairlines before boxes.** Content sits on the page. Groups are separated by a 1px `border-subtle` rule and space, not by filled, bordered cards.
2. **Blue means act.** `brand` is the primary button, links and keyboard focus. It is never used for selection or status.
3. **Selection is neutral.** The current nav item, tab, segment or side-nav item is shown with `text-primary`, plus an underline or a `surface-2` fill.
4. **Status is a dot and a word.** A 6px dot in the tone colour, then the label in body text. Filled pills are for dense tables only (Watchlist, Momentum).
5. **Words, not colour alone.** Where direction is implied (5Y vs SPY), a ▲ or ▼ replaces the dot.
6. **Quiet type.** Larger, lighter titles; sentence-case labels; no uppercase, no wide tracking. Numbers stay mono.
7. **Same job, same component.**

## Content fundamentals

- **Sentence case everywhere**, including section titles and field labels. Nothing is uppercase.
- **Tickers** are mono, with the company name in `text-secondary`.
- **Numbers** are mono and tabular, right-aligned in tables, with an explicit sign on changes (+1.26%, −7.49%), units after the value (−52 days), and "—" when missing.
- **Verdicts** are one coloured word ("Strong Pass") beside a neutral score.
- **Disclaimers** ("Informational only") are `caption` in `text-tertiary`.
- **Tone:** plain and factual.

## Visual foundations

- **Surfaces:** mostly `page`. `surface` appears only as a hover fill and in the rare Card or popover; `surface-2` marks a selected segment or side-nav item and a hovered popover row.
- **Text:** `text-primary` for headings and figures, `text-body` for running text and status words, `text-secondary` for secondary, `text-tertiary` for captions and labels.
- **Type:** Public Sans (text), Sora (page and ticker titles, logotype), IBM Plex Mono (numbers and tickers), snapped to the app's scale: 13 / 15 / 17 / 19 / 21 / 26 / 32 / 39 / 52px. Titles use weight 500. Page title 26, ticker title 32, price 39, score 26, body and status 15, captions 13.
- **Spacing:** the 4px scale. Page top padding 48, header-to-content 32, section padding 24 top and 8 bottom, tile gap 40 by 12.
- **Radius:** `radius-md` (8px) for buttons, segments, side-nav items and the boxed search; `radius-lg` (10px) only for the rare Card. Underline inputs have no radius.
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
| Do something | Button: one `primary` per region, `ghost` for everything else |
| Show a classification or state | Status (dot and word) |
| Group related content | Section (hairline and title) |
| One repeated item in a grid | Tile (hairline on top) |
| List many records with numbers | DataTable |
| Label and value pairs | Definition rows |
| Tell the user about system state | Banner |
| An object that must read as a box | Card (rare) |

## Status vocabulary

Tier logic stays in `lib/tierColor.ts`; this guide defines the colours.

| Meaning | Dot colour | Where it shows up |
| --- | --- | --- |
| Strong | `positive-strong` | Strong Pass (score above 90), Wide Moat |
| Positive | `positive` (muted green) | Pass (score 75 to 90), Narrow Moat |
| Borderline | `warn` | Score 70 to 74, Pullback pending |
| Pass with caution | `caution` | The "Pass with caution" verdict (checked before score tiers) |
| Negative | `negative` | Fail, No Moat, Trend invalidated, Overvalued |
| Speculative | `chart-purple` | Speculative Growth only |
| Neutral | none (plain `text-secondary`) | Stage labels, index membership, kind and sector |

The score number stays `text-primary`; only the verdict word takes the tone colour. Moat tiers live in `MoatPill.tsx` and valuation in `FairValuePill.tsx`, both behind one shared map.

## Foundational decisions (settled, built)

- **Direction B** ("quiet minimalist") over a consolidated version of the old look.
- **Tables:** hover only on rows that open something; whole-row click opens the ticker in a new tab; Screener cards unchanged; Watchlist and Momentum keep the compact filled `Badge` for scores/ratings, `Status` (dot + word) everywhere else.
- **Fonts:** Public Sans, Sora, IBM Plex Mono — no change needed from what the app already had.
- **New tabs:** ticker links in the Screener, Momentum and Watchlist, and nav links from the Screener, open in a new tab so Screener filters stay put. Two tabs each showing an active item is expected behaviour, not a bug.
- **By choosing B:** dark `on-brand` text on the primary button; underline inputs with `border-control`; ▲/▼ glyph on the 5Y vs SPY status; orange stays reserved for the applied-filter label; filled pills dropped from headers, tiles and lists.
- **Segmentation chart "Other" slice:** reuses the `text-tertiary` token rather than a new dedicated token.
- **Settings' "skipped" status:** the old sky-blue treatment was retired during the Settings migration (session 6a).

## Housekeeping items (verified against code 2026-09-29 — all 6 resolved)

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
2. **Steppers — restyled and kept, not dropped.** `components/ui/NumberStepper.tsx` still exists
   as a real shared component, used by `LiquidityZoneSettingsForm.tsx` and shown in
   `/styleguide` — the original "drop it" recommendation was not carried out; it was brought
   onto the shared token set instead.
3. **Analyst labels — not shipped, still open.** `CurrentDistributionList.tsx` and
   `RatingDistributionTrendChart.tsx` both explicitly keep the app's own
   Buy/Outperform/Hold/Underperform/Sell labels ("this app's own established labels," per their
   own code comments), not FMP's raw Strong Buy/Buy/Hold/Sell/Strong Sell. Still a small,
   separate fix if wanted — nobody has done it.
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

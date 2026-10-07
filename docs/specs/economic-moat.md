# Economic Moat

Economic Moat is the simplest input in Fathom, and the only one that isn't computed from
financial data at all: it's a rating **you set yourself**, based on your own judgment of whether
the company has a durable competitive advantage — something that protects its profits from
competitors over the long run (a strong brand, network effects, high switching costs, patents,
scale advantages, and similar).

## The three ratings

You choose one of three states from the Economic Moat tab:

- **No Moat** — no meaningful, durable competitive advantage protecting this business from
  competitors.
- **Narrow Moat** — some real advantage exists, but it isn't strong or broad enough to reliably
  fend off competition indefinitely.
- **Wide Moat** — a strong, durable advantage expected to hold up for a decade or more.

There's no built-in checklist or scoring rubric behind these — Fathom doesn't attempt to compute
a moat rating from financial data, and doesn't offer any automated suggestion for which one to
pick. It's entirely your own qualitative assessment of the business.

## Why it matters this much

Economic Moat is a **multiplier on the Overall score**, not a component of the blend (redesign of 2026-10-07; docs/decisions.md).
The four automated checks combine into a Fundamentals score; the Overall Assessment is that Fundamentals score times the Moat multiplier:

| Rating | Multiplier |
|---|---|
| Wide Moat | 1.0 (fixed) |
| Narrow Moat | 0.85 by default; selectable: 0.80, 0.82, 0.85, 0.87, 0.90 |
| No Moat, or not rated | 0.70 (fixed) |

This is a deliberate design choice: a durable competitive advantage is treated as at least as important to a company's long-term
investment case as any one quarter's worth of financial performance, so it acts on the whole result. A Wide Moat leaves the Fundamentals
score as it is, a Narrow Moat takes 15% off by default, and a missing or No Moat takes 30% off. For example, Fundamentals 83.8 x Narrow 0.85 =
71 (the Analysis card shows this arithmetic in a collapsible "Show calculation" section).

**Not rated is not neutral.** A ticker with no rating is **scored as No moat** (multiplier 0.70) and the Analysis card and the ticker
header say so: "Moat not rated, scored as No moat". There is no separate "Moat not rated" verdict any more (retired 2026-10-07, replacing the 2026-10-05
rule that kept the steps-only score and only blocked a Pass): an unrated ticker's verdict is read from its score, which reads Fail in practice
(only four perfect check scores of 100 reach exactly 70). Rate the ticker to lift it.

## It doesn't persist automatically until you confirm it

Changing the selector shows you a live preview of the new rating, but nothing is saved until you
explicitly confirm the change — since doing so changes how Overall Assessment is scored for that
ticker. You'll see a prompt asking you to confirm before it takes effect.

---

## Technical reference

Unlike every other component of the Overall Assessment, Moat is not computed from any financial data at all — it's a manually-set,
user-asserted classification, and its effect is a fixed multiplier per state.

### Multipliers

| Rating | Multiplier | Where it lives |
|---|---|---|
| Wide Moat | 1.0 | constant, `scoring/overall.py::WIDE_MOAT_MULTIPLIER` |
| Narrow Moat | 0.85 default | the one saved setting, `MoatScoreConfig.narrow_moat_multiplier`; allowed values `NARROW_MOAT_MULTIPLIER_OPTIONS` (0.80, 0.82, 0.85, 0.87, 0.90) |
| No Moat / not rated | 0.70 | constant, `scoring/overall.py::NO_MOAT_MULTIPLIER` |

The setting is edited in Settings > Economic moat: Wide and No moat / not rated are shown read-only, Narrow is a select of the five allowed values
(`GET/PUT /api/config/moat`; the server validates the value against the allowed set and returns 422 otherwise; the request carries only the
Narrow value, so the fixed multipliers cannot be changed). It repurposes the old per-tier points config row (the three points columns were
dropped, `core/db.py::_OBSOLETE_COLUMNS`; the old "No Moat points are capped at 1" rule no longer exists: the multiplier model has no such
loophole, see below). **Saving the Narrow multiplier** advances `weights_version`, starts the same background recompute as a weights change (one
run at a time, 409 while another is running) and shows in the Screener's "N scores are still on the previous weights" note until the
job has re-scored the rows.

### How it enters the Overall Assessment

Overall = round(Fundamentals score x multiplier), the Fundamentals score being the unrounded weighted average of the four checks (see [Overview](overview.md)).
The ticker's stored row keeps the Fundamentals score (`TickerScore.steps_score`, unrounded) and the multiplier applied
(`TickerScore.moat_multiplier`) beside `overall_score`. Moat has no row in the Analysis card's breakdown any more; the arithmetic block shows the
multiplication instead.

A missing/incomplete four-check blend is never rescued by a present Moat rating — if the four checks can't produce a confident Fundamentals
score, the whole Overall Assessment stays incomplete (no score, no verdict, no "not rated" note); Moat is not a substitute for missing
step data. A check that is "not supported" (Banks without CET1, Insurance for Debt) is excluded from the Fundamentals score and the others
reweighted; the multiplier then applies to that reweighted score.

### Why a No moat ticker cannot pass in practice

0.70 x 100 = 70. A No moat or unrated ticker therefore reaches the Pass line (70) only when all four checks score a perfect 100, which no
ticker does (in the 2026-10-07 investigation the best Fundamentals score among No moat tickers was 91, giving 64, and every unrated ticker was at 69 or below). Unlike the old
points model, there is no points setting to raise: the 0.70 is fixed so that this holds by construction.

### Unset vs. explicit "No Moat"

"Not set" (no rating chosen yet) and "No Moat" now score **identically** (multiplier 0.70, same Overall, same verdict). The only difference is the note: an
unset ticker shows "Moat not rated, scored as No moat" on the Analysis card and the header chip (`overall.py::MOAT_NOT_RATED_NOTE`, mirrored in
`overallScore.ts`), so it is visible that the 30% reduction comes from a missing rating, not a judgement. `PUT /api/tickers/{t}/moat` recomputes the stored row
(cache only), so rating the ticker takes effect immediately; there is no "clear Moat" endpoint.

### Saving

Selecting a rating shows a live preview immediately, but nothing is persisted until the user
explicitly confirms — since doing so changes how Overall Assessment is scored for that ticker.

## ETFs

An Economic Moat is a company judgement, so it cannot be set on an ETF or fund: `PUT /api/tickers/{t}/moat` answers 400 for a ticker the app knows is an ETF/fund, the ETF page has no Moat tab or pill, and the monthly momentum snapshot excludes `TickerScore.is_etf` rows (see `docs/specs/etf-page.md`).

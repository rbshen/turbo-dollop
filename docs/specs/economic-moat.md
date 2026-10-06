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

Once you set a rating for a ticker, it's folded into the Overall Assessment at a 31% weight —
the single largest weight of any component, larger than any one of the four automated financial
checks on its own (see [Overview](overview.md) for the full weighting). This is a deliberate
design choice: a durable competitive advantage is treated as at least as important to a
company's long-term investment case as any one quarter's worth of financial performance.

Until you set a rating, the Overall **score** is simply the blend of the four automated checks on
their own — leaving Moat unrated doesn't drag the number down. But Moat is non-negotiable for a
Pass, so an unrated ticker whose blend would read Pass, Pass with caution or Strong Pass shows the
verdict **Moat not rated** instead until you rate it (a would-be Fail stays Fail). It's only once
you actively select **No Moat** that it becomes a real, negative input pulling the blended score
down; the unrated state and "No Moat" are not the same thing. See [Overview](overview.md), "What
happens if Economic Moat isn't set".

## It doesn't persist automatically until you confirm it

Changing the selector shows you a live preview of the new rating, but nothing is saved until you
explicitly confirm the change — since doing so changes how Overall Assessment is scored for that
ticker. You'll see a prompt asking you to confirm before it takes effect.

---

## Technical reference

Unlike every other component of the Overall Assessment, Moat is not computed from any financial
data at all — it's a manually-set, user-asserted classification with a fixed point value per
state.

### Point values

| Rating | Default points |
|---|---|
| No Moat | 0 |
| Narrow Moat | 65 |
| Wide Moat | 100 |

These point values are not hardcoded constants — they live in a single configuration row,
editable via the Settings page. The values above are only the seeded defaults on first read;
once the config row exists, it (not these numbers) is the source of truth. There is no scoring
rubric or checklist behind the rating itself — the user picks one of the three states directly,
and the app assigns it whatever point value the current config row holds for that state.

**No Moat points are capped at 1 (2026-10-06).** `PUT /api/config/moat` rejects a No Moat value above 1 (or below 0) and one that
is not lower than both the Narrow and the Wide value. Reason: with Moat fixed at 31%, the four checks add at most 69 (a convex
blend of scores of at most 100), so `round(0.69 x 100 + 0.31 x No Moat points)` stays at 69, a Fail, for any No Moat value up to
about 1.6; 31% is the smallest whole-number Moat weight for which that holds. Above about 1.6 points a perfect steps score could
reach 70, so the cap is 1.

### Weight in Overall Assessment

Once a ticker has any of the three real Moat states set, Moat occupies **31%** of the Overall
Assessment, with the four automated checks (Financials, Growth Rate, Profitability, Debt)
combined occupying the remaining **69%**.

```
score = round(0.69 × steps_score + 0.31 × moat_points)
```

This is applied as a **second stage** on top of the four-check blend, not folded into one flat
weight table alongside the four checks' own weights — the arithmetic does not reduce to the same
result under a flat renormalization once a check is also exempt or missing, so the two-stage
formula above is not a simplification, it's the actual computation.

### Unset vs. explicit "No Moat"

"Not set" (no rating chosen yet) is a distinct third state from "No Moat," and the two behave
differently:

- **Not set** (the default for every ticker until a user picks a rating): Overall Assessment
  uses the pure four-check blend on its own (`steps_score` above, with `display_scale = 1.0`),
  reweighted to sum to 100% — Moat is simply absent from the picture, not treated as a zero or a
  penalty. The verdict, though, can never be a Pass: a would-be Pass-family verdict reads **Moat
  not rated** (`moat_not_rated`) until the ticker is rated; `PUT /api/tickers/{t}/moat` recomputes
  the stored row (cache only), so rating it flips the verdict immediately.
- **No Moat** (an explicit user selection): scores its full 0 points at the full 31% weight — a
  real, negative input that actively pulls the blended score down, and (combined with the
  four-check blend) can cap the overall score below the Pass threshold regardless of how well the
  four automated checks score. This is intended: unlike every other component of Overall
  Assessment, Moat has no averaging-based protection against a single weak input, since it's the
  one deliberately user-asserted signal in the whole blend.

A missing/incomplete four-check blend is never rescued by a present Moat rating — if the four
checks can't produce a confident blended score, the whole Overall Assessment stays incomplete
regardless of what Moat is set to.

### Saving

Selecting a rating shows a live preview immediately, but nothing is persisted until the user
explicitly confirms — since doing so changes how Overall Assessment is scored for that ticker.

## ETFs

An Economic Moat is a company judgement, so it cannot be set on an ETF or fund: `PUT /api/tickers/{t}/moat` answers 400 for a ticker the app knows is an ETF/fund, the ETF page has no Moat tab or pill, and the monthly momentum snapshot excludes `TickerScore.is_etf` rows (see `docs/specs/etf-page.md`).

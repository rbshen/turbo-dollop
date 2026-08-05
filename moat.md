# Economic Moat

Technical reference for the Economic Moat rating (the "Economic Moat" tab).
Unlike every other component of the Overall Assessment, Moat is not
computed from any financial data at all — it's a manually-set,
user-asserted classification with a fixed point value per state.

## The three ratings

| Rating | Default points |
|---|---|
| No Moat | 0 |
| Narrow Moat | 65 |
| Wide Moat | 100 |

These point values are not hardcoded constants — they live in a
single configuration row, editable via the Settings page. The values
above are only the seeded defaults on first read; once the config row
exists, it (not these numbers) is the source of truth. There is no
scoring rubric or checklist behind the rating itself — the user picks one
of the three states directly, and the app assigns it whatever point value
the current config row holds for that state.

## Weight in Overall Assessment

Once a ticker has any of the three real Moat states set, Moat occupies
**31%** of the Overall Assessment, with the four automated checks
(Financials, Growth Rate, Profitability, Debt) combined occupying the
remaining **69%** — the single largest weight of any component, larger
than any one of the four automated checks on its own.

```
score = round(0.69 × steps_score + 0.31 × moat_points)
```

This is applied as a **second stage** on top of the four-check blend, not
folded into one flat weight table alongside the four checks' own weights
— the arithmetic does not reduce to the same result under a flat
renormalization once a check is also exempt or missing, so the two-stage
formula above is not a simplification, it's the actual computation.

## Unset vs. explicit "No Moat"

"Not set" (no rating chosen yet) is a distinct third state from "No
Moat," and the two behave differently:

- **Not set** (the default for every ticker until a user picks a rating):
  Overall Assessment uses the pure four-check blend on its own (`steps_score`
  above, with `display_scale = 1.0`), reweighted to sum to 100% — Moat is
  simply absent from the picture, not treated as a zero or a penalty.
- **No Moat** (an explicit user selection): scores its full 0 points at
  the full 31% weight — a real, negative input that actively pulls the
  blended score down, and (combined with the four-check blend) can cap the
  overall score below the Pass threshold regardless of how well the four
  automated checks score. This is intended: unlike every other component
  of Overall Assessment, Moat has no averaging-based protection against a
  single weak input, since it's the one deliberately user-asserted signal
  in the whole blend.

A missing/incomplete four-check blend is never rescued by a present Moat
rating — if the four checks can't produce a confident blended score (see
the Overview reference for when that happens), the whole Overall
Assessment stays incomplete regardless of what Moat is set to.

## Saving

Selecting a rating shows a live preview immediately, but nothing is
persisted until the user explicitly confirms — since doing so changes how
Overall Assessment is scored for that ticker.

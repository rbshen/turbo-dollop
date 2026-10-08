# Glossary: verdict labels

Every automated check in Fathom (Financials, Growth Rate, Profitability, Debt, and the Overall
Assessment they roll up into) reports a verdict using a shared set of labels. This page explains
what each one means in plain terms; the individual check pages link back here rather than
re-explaining it each time.

## Fail ("May not pass")

Fathom stores this verdict as `Fail` but **displays it as "May not pass"** on every surface (2026-10-08), in a slate blue (not red, unlike "No moat" or "Overvalued"); the rest of this page and the check pages use the stored word Fail.

The check found a genuine, meaningful weakness — not just "not the best," but falling short of
what the check considers a healthy result. Most checks treat certain conditions as an automatic
Fail regardless of how strong everything else looks (for example, Profitability's negative average ROE or ROIC) — the idea
being that a single serious red flag shouldn't get averaged away by strength elsewhere. Debt for
ordinary companies has no automatic fail since 2026-10-07, and neither do Banks and REITs since 2026-10-08: a breach scores near zero (0 for a Bank or REIT limit) and the
weights, which put the most weight on Debt/EBITDA, keep it below 70. Debt shows that result as
"May not pass" like every other check; see [Debt](debt.md).

Growth Rate has no automatic fail since 2026-10-08: its verdict follows its score (Fail below 70),
and a negative projected growth rate cannot score 70, so a company analysts expect to shrink still
reads Fail. See [Growth Rate](growth-rate.md).

## Pass

The check came back solidly healthy overall. This is the normal, expected result for a
fundamentally sound company — it doesn't mean "perfect," just "meets the bar."

## Strong Pass

The check came back excellent across the board — a step up from a normal Pass, reserved for
results that are strong not just on average but consistently so. Financials and Profitability need at
least 8 data points to reach it; a shorter history is held at a plain Pass (score 90).

## Pass with caution

Two different things carry the stored key `Pass with caution`, and since 2026-10-08 they are **drawn with two different labels**, so that each
label means one thing: the word "Pass with caution" is the **Overall** verdict only, and the Debt check's own state reads **"Pass, ratio in
breach"** (display only; the stored value, API value and amber tone are unchanged).

**On a check (currently only Debt) — displayed "Pass, ratio in breach".** A real breach of a safety threshold did occur, but either Fathom found enough offsetting
evidence (such as a debt-reduction trend, strong free cash flow relative to debt, or comfortable interest coverage) to excuse it, or
nothing excused it and the other ratios still carried the blend to 70 or more (the card names the breached ratio). Read this as "passed,
but only barely, and with a real caveat attached" — not as equivalent to a clean Pass. See [Debt](debt.md) for the details.

**On the Overall verdict (since 2026-10-08).** The Overall reads "Pass with caution" instead of Pass or Strong Pass when its score is 70
or more **and** either (a) the Debt check is "Pass, ratio in breach" (its stored `Pass with caution`), or (b) at least one of Financials, Growth Rate, Profitability or
Debt is below the pass line ("May not pass", a score under 70): the other checks carried the average, but one check did not pass. Both
reasons can apply at once. A check that is not applied to the company (not supported, such as Debt for an Insurance company) is ignored,
the Economic Moat plays no part, and an Overall under 70 stays "May not pass". The Overall score itself never changes. The Analysis card
and the Watchlist tooltip name the cause in plain words ("because Debt passed with a ratio in breach" / "because Financials may not pass (under 70)").

## Insufficient data

The figures this check needed simply weren't available for this company — this is a data gap,
not a judgment that the company is weak. Fathom deliberately does not fabricate a Fail out of
missing data; instead, the check (and, if it's one of the four checks feeding Overall
Assessment, the whole Overall Assessment) reports as incomplete rather than scored.

## Not supported

The check doesn't currently have a reliable way to evaluate this company at all — not because
data happens to be missing this one time, but because of a structural gap (for example, Fathom's
data provider doesn't publish the figure banks are normally judged on for capital adequacy, so a
Bank ticker shows "not supported" for Debt until that figure is entered manually, or
permanently for the small number of Bank-classified tickers that turn out not to be genuine
deposit-taking lenders). This is different from "insufficient data": it reflects a known
limitation of what can currently be computed for this company type, not a one-off missing
figure that might show up on the next data refresh.

## Overall Assessment's own rules

Overall Assessment is the **Fundamentals score** (the weighted blend of the four automated checks, default weights Financials 30, Debt 30, Growth
Rate 20, Profitability 20) times a **Moat multiplier** (Wide 1.0, Narrow 0.85 by default, No moat or not rated 0.70). It uses these same
verdict labels, read from the Overall score (the weights each check carries are adjustable: see [Overview](overview.md), "Adjustable
weights"; Step 4's hard fail still reads Fail on its own check):

- If any of the four automated checks comes back **insufficient data** (or hits an internal
  error), Overall Assessment doesn't attempt a partial average — the whole Overall Assessment is
  marked incomplete instead. A check that comes back **not supported** is treated differently:
  it's simply excluded from the blend, with the remaining checks reweighted to fill the gap — it
  does not block the rest of Overall Assessment from being computed.
- If any one check reports **Pass, ratio in breach** (Debt's stored `Pass with caution`), that flag carries up into Overall Assessment's
  own displayed verdict even if the blended number would otherwise read as a plain Pass or
  Strong Pass — a real caveat on one check isn't allowed to disappear once it's folded into the
  bigger picture. So does a check that is **below the pass line** ("May not pass") beside an Overall of 70 or more
  (2026-10-08): a strong average isn't allowed to hide a check that did not pass.
- A ticker with **no Moat rated** is **scored as No moat** (multiplier 0.70): its verdict is read from its score like any other (in
  practice Fail), and the Analysis card and header say "Moat not rated, scored as No moat". There is no separate "Moat not rated" verdict
  any more (retired 2026-10-07).

See [Overview](overview.md) for how Overall Assessment is built.

## Fundamentals score (formerly Steps score)

The weighted blend of the four automated checks (Financials, Growth Rate, Profitability, Debt), kept unrounded and shown to one decimal. The
Economic Moat multiplier then scales it to give the Overall score (Overall = round(Fundamentals score x Moat multiplier)). Renamed from "Steps
score" on 2026-10-07 in all user-facing text and docs; the code identifiers (`steps_score`, `stepsScore`) keep the old name. The individual
"Step 1" to "Step 5" labels are unchanged.

# Glossary: P/E

## P/E (trailing)

The P/E shown on the Screener, Watchlist and ticker header is **trailing**: the latest official
close divided by trailing-twelve-month earnings per share. It is blank ("—") when trailing EPS is
zero, negative or unavailable — a loss-making company has no meaningful P/E. For a US-listed
company that reports in a different currency (an ADR), FMP's own trailing P/E is used instead. The
Ratios tab's P/E rows are FMP's own annual and TTM figures and can differ. See
[Overview](overview.md), "P/E basis".

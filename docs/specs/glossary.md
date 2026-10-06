# Glossary: verdict labels

Every automated check in Fathom (Financials, Growth Rate, Profitability, Debt, and the Overall
Assessment they roll up into) reports a verdict using a shared set of labels. This page explains
what each one means in plain terms; the individual check pages link back here rather than
re-explaining it each time.

## Fail

The check found a genuine, meaningful weakness — not just "not the best," but falling short of
what the check considers a healthy result. Most checks treat certain conditions as an automatic
Fail regardless of how strong everything else looks (for example, Debt fails outright if any one
ratio breaches a clearly unsafe level, even if the other ratios look fine) — the idea being that
a single serious red flag shouldn't get averaged away by strength elsewhere.

Growth Rate is a deliberate exception: it only fails when analysts project the company will
actually shrink. See [Growth Rate](growth-rate.md) for why.

## Pass

The check came back solidly healthy overall. This is the normal, expected result for a
fundamentally sound company — it doesn't mean "perfect," just "meets the bar."

## Strong Pass

The check came back excellent across the board — a step up from a normal Pass, reserved for
results that are strong not just on average but consistently so. Financials and Profitability need at
least 8 data points to reach it; a shorter history is held at a plain Pass (score 90).

## Pass with caution

Currently used only by the **Debt** check. This means a real breach of a safety threshold did
occur, but Fathom found enough offsetting evidence (such as a debt-reduction trend, strong free
cash flow relative to debt, or comfortable interest coverage) to avoid treating it as an outright
Fail. Read this as "passed, but only barely, and with a real caveat attached" — not as
equivalent to a clean Pass. See [Debt](debt.md) for the details.

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

Overall Assessment uses these same labels, with two additions worth knowing:

- If any of the four automated checks comes back **insufficient data** (or hits an internal
  error), Overall Assessment doesn't attempt a partial average — the whole Overall Assessment is
  marked incomplete instead. A check that comes back **not supported** is treated differently:
  it's simply excluded from the blend, with the remaining checks reweighted to fill the gap — it
  does not block the rest of Overall Assessment from being computed.
- If any one check reports **Pass with caution**, that flag carries up into Overall Assessment's
  own displayed verdict even if the blended number would otherwise read as a plain Pass or
  Strong Pass — a real caveat on one check isn't allowed to disappear once it's folded into the
  bigger picture.

- If **Economic Moat** hasn't been rated and the blend would read Pass, Pass with caution or Strong
  Pass, the Overall verdict is **Moat not rated** — not a Pass and not a Fail. The score is
  unchanged; rate the moat to get a real verdict.

See [Overview](overview.md) for how Overall Assessment is built.

## Review status

Not a verdict. A flag stored beside a Pass, Pass with caution or Strong Pass Overall verdict when Financials or
Debt failed with a score below 50; the Overall number and verdict stay as computed.

- **Review (structural)** — the debt servicing ratio is at or above 60%. Informational, not a Fail.
- **Review (by design)** — every failing Debt ratio is a long-standing feature of the business (a Current
  Ratio below 1.0 for years, or a Debt/EBITDA that has stayed in a narrow band with strong interest coverage).
- **Review (unclear)** — a gated step the rules cannot explain (every gated Financials step reads this way).
- **Data uncertain** — a data-quality problem on the statements (a placeholder or scale-broken cash flow, a
  partial balance sheet, or a quarter that has not landed) touches the gated step, so its reading is not
  trusted yet; the tooltip says what it would read if the data is confirmed.
- **Conviction** — high, medium or low, from Growth Rate and Profitability: high when both are Pass or better,
  low when both fail, otherwise medium.

Where it shows: the ticker header chip and Analysis card, a pill on the Screener card (and a "Review status"
filter in the Fundamental sidebar), and an icon marker in the Watchlist Analysis column and the Momentum Score
cell. The tooltip carries the reason in every place. See [Overview](overview.md), "Review status".

# Glossary: P/E

## P/E (trailing)

The P/E shown on the Screener, Watchlist and ticker header is **trailing**: the latest official
close divided by trailing-twelve-month earnings per share. It is blank ("—") when trailing EPS is
zero, negative or unavailable — a loss-making company has no meaningful P/E. For a US-listed
company that reports in a different currency (an ADR), FMP's own trailing P/E is used instead. The
Ratios tab's P/E rows are FMP's own annual and TTM figures and can differ. See
[Overview](overview.md), "P/E basis".

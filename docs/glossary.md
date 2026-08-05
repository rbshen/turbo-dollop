# Glossary: verdict labels

Every automated check in Fathom (Financials, Growth Rate, Profitability,
Debt, and the Overall Assessment they roll up into) reports a verdict
using a shared set of labels. This page explains what each one means in
plain terms; the individual check pages link back here rather than
re-explaining it each time.

## Fail

The check found a genuine, meaningful weakness — not just "not the best,"
but falling short of what the check considers a healthy result. Most
checks treat certain conditions as an automatic Fail regardless of how
strong everything else looks (for example, Debt fails outright if any one
ratio breaches a clearly unsafe level, even if the other ratios look
fine) — the idea being that a single serious red flag shouldn't get
averaged away by strength elsewhere.

Growth Rate is a deliberate exception: it only fails when analysts project
the company will actually shrink. See [Growth Rate](growth-rate.md) for
why.

## Pass

The check came back solidly healthy overall. This is the normal, expected
result for a fundamentally sound company — it doesn't mean "perfect," just
"meets the bar."

## Strong Pass

The check came back excellent across the board — a step up from a normal
Pass, reserved for results that are strong not just on average but
consistently so.

## Pass with caution

Currently used only by the **Debt** check. This means a real breach of a
safety threshold did occur, but Fathom found enough offsetting evidence
(such as a debt-reduction trend, strong free cash flow relative to debt,
or comfortable interest coverage) to avoid treating it as an outright
Fail. Read this as "passed, but only barely, and with a real caveat
attached" — not as equivalent to a clean Pass. See [Debt](debt.md) for
the details.

## Insufficient data

The figures this check needed simply weren't available for this company —
this is a data gap, not a judgment that the company is weak. Fathom
deliberately does not fabricate a Fail out of missing data; instead, the
check (and, if it's one of the four checks feeding Overall Assessment, the
whole Overall Assessment) reports as incomplete rather than scored.

## Not supported

The check doesn't currently have a reliable way to evaluate this company
at all — not because data happens to be missing this one time, but because
of a structural gap (for example, Fathom's data provider doesn't publish
the figure banks are normally judged on for capital adequacy, so a Bank
ticker shows "not supported" for Debt until that figure is entered
manually). This is different from "insufficient data": it reflects a known
limitation of what can currently be computed for this company type, not a
one-off missing figure that might show up on the next data refresh.

## Overall Assessment's own rules

Overall Assessment uses these same labels, with two additions worth
knowing:

- If any of the four automated checks comes back **insufficient data**
  (or hits an internal error), Overall Assessment doesn't attempt a
  partial average — the whole Overall Assessment is marked incomplete
  instead. A check that comes back **not supported** is treated
  differently: it's simply excluded from the blend, with the remaining
  checks reweighted to fill the gap — it does not block the rest of
  Overall Assessment from being computed.
- If any one check reports **Pass with caution**, that flag carries up
  into Overall Assessment's own displayed verdict even if the blended
  number would otherwise read as a plain Pass or Strong Pass — a real
  caveat on one check isn't allowed to disappear once it's folded into the
  bigger picture.

See [Overview](overview.md) for how Overall Assessment is built.

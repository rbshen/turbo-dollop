# Debt

The Debt card is a conservative check on whether a company's debt load is
safe — it's built to behave like a bankruptcy-risk filter rather than a
typical continuous score. For most companies ("Standard" — see
[Company type variations](company-type-variations.md)), it looks at three
things:

- **Current Ratio** — can the company cover its short-term (within one
  year) obligations with its short-term assets? A low ratio suggests a
  real near-term liquidity risk.
- **Debt / EBITDA** — how large the company's total debt is relative to
  its annual earnings (before interest, tax, depreciation, and
  amortization). A high ratio means debt is large relative to what the
  business actually earns.
- **Debt Servicing Ratio** — how much of the company's earnings are
  consumed just by servicing (paying interest and principal on) its debt.
  A high burden here means less room to absorb a downturn.

## A real breach usually fails the whole card

Unlike Fathom's other checks, Debt isn't a plain weighted average. If any
one of these ratios breaches a clearly unsafe level, the whole card fails,
even if the other two ratios look fine — averaging a genuine debt problem
away against healthy ratios elsewhere would defeat the point of a
bankruptcy-risk filter. The numeric score still displays for context, but
the verdict itself reads Fail regardless.

## Borderline breaches get a second look

Not every breach is treated the same. A ratio that's only moderately over
its safe threshold (rather than severely over it) gets a closer,
second look before Fathom settles on a Fail — checking things like
whether the company's debt burden has been improving over time, whether
free cash flow comfortably covers total debt, and whether earnings
comfortably cover interest payments. If enough of that supporting evidence
looks favorable, the result downgrades from a hard Fail to **Pass with
caution** rather than a clean Pass — it acknowledges a real breach
occurred while recognizing the underlying evidence doesn't point to
genuine distress. A severe breach — well beyond the borderline zone —
never gets this second look and always fails outright.

Separately, for the Current Ratio specifically, some companies collect
cash from customers before delivering the product or service (an airline
selling advance tickets, a business collecting an annual subscription
upfront). That cash is booked as a liability ("deferred revenue") even
though it isn't really money the company owes anyone — it just hasn't
been earned yet. Fathom checks for this and can rescue an apparently weak
Current Ratio when a low ratio turns out to be explained by this pattern
rather than genuine liquidity risk.

## Banks, Insurance companies, and REITs are judged differently

The three ratios above assume a typical operating company's balance
sheet. That doesn't hold for financial companies or real-estate companies,
so each is judged on different, more appropriate criteria:

- **Banks** are judged on **capital adequacy** — specifically a CET1
  (Common Equity Tier 1) ratio, a standard regulatory measure of a bank's
  capital cushion — combined with a **Non-Performing Loan (NPL) ratio**,
  which measures how much of the bank's loan book is at risk of default.
  FMP (Fathom's data provider) doesn't publish CET1 data, so this figure
  must be entered manually before a Bank ticker gets a real Debt verdict;
  until then, it displays as **not supported** rather than a fabricated
  score. NPL is computed automatically where the underlying data is
  available, and can also be manually overridden.

  <details>
  <summary>Current CET1 bands (subject to change)</summary>

  | CET1 ratio | Read as |
  |---|---|
  | Below 10% | Fail |
  | 10% – 12% | Acceptable |
  | 12% – 14% | Good |
  | 14% and above | Excellent |

  </details>

- **Insurance companies** aren't judged on these ratios at all — their
  balance sheets are dominated by loss reserves and unearned premiums,
  which don't map cleanly onto a short-term liquidity or leverage read the
  way a typical company's does, and there's currently no reliable
  substitute capital-adequacy signal available for insurers from Fathom's
  data provider. Insurance tickers show as **not supported** for Debt.
- **REITs and Property Developers** are judged on a **Gearing ratio**
  instead — total debt relative to total assets — which better reflects
  how a real-estate-heavy balance sheet is normally evaluated.

## What the verdict means

- **Fail** — a hard breach occurred (or, for Banks/REITs, the relevant
  ratio is genuinely weak).
- **Pass with caution** — a real breach occurred but was resolved by a
  legitimate offsetting factor (deferred revenue, or a borderline breach
  with strong supporting evidence). Treat this as "barely passing," not as
  equivalent to a clean Pass.
- **Pass** — no ratio breached its safe threshold.
- **Strong Pass** — every ratio is comfortably within safe territory.
- **Not supported** — this company type doesn't have a reliable way to
  compute this check with the data currently available (Insurance always;
  Banks until a CET1 value is entered).

See the [Glossary](glossary.md) for how every verdict label is defined.
